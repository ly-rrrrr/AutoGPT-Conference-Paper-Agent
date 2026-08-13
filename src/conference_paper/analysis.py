import asyncio
import html
import logging
import re
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any, Literal, Protocol
from xml.etree import ElementTree

from backend.blocks._base import (
    Block,
    BlockCategory,
    BlockOutput,
    BlockSchemaInput,
    BlockSchemaOutput,
)
from backend.blocks.conference_paper.models import (
    AnalysisMode,
    AnalysisResult,
    AnalysisStatus,
    PaperAnalysis,
    PaperQARecord,
    PaperTask,
)
from backend.blocks.conference_paper.checkpoints import (
    DEFAULT_OUTPUT_ROOT,
    JsonlCheckpoint,
)
from backend.blocks.conference_paper.results import write_analysis_report
from backend.blocks.llm import (
    AICredentials,
    AIStructuredResponseGeneratorBlock,
    AITextGeneratorBlock,
    LlmModel,
)
from backend.blocks.mcp.client import MCPClient
from backend.data.model import (
    APIKeyCredentials,
    CredentialsField,
    CredentialsMetaInput,
    OAuth2Credentials,
    SchemaField,
)
from backend.integrations.providers import ProviderName

logger = logging.getLogger(__name__)

ALPHAXIV_MCP_URL = "https://api.alphaxiv.org/mcp/v1"
ALPHAXIV_TOOL_NAME = "answer_pdf_queries"
ALPHAXIV_REPORT_TOOL_NAME = "get_paper_content"
MISSING_MCP_CREDENTIALS_ERROR = "ANALYSIS_SKIPPED_NO_MCP_CREDENTIALS"
MISSING_LLM_CREDENTIALS_ERROR = "ANALYSIS_SKIPPED_NO_LLM_CREDENTIALS"
MAX_ANALYSIS_CONCURRENCY = 3
MAX_ERROR_DETAIL_LENGTH = 500
ANALYSIS_BATCH_SIZE = 50
MAX_INLINE_ANALYSIS_RESULTS = 100
DEFAULT_ANALYSIS_REQUEST_INTERVAL_SECONDS = 4.0
DEFAULT_MAX_NEW_ANALYSES_PER_RUN = 400
AUTHORIZATION_CIRCUIT_OPEN_ERROR = "ANALYSIS_DEFERRED_AUTHORIZATION_CIRCUIT_OPEN"
RUN_LIMIT_DEFERRED_ERROR = "ANALYSIS_DEFERRED_RUN_LIMIT"
PAPER_ANALYSIS_FORMAT = {
    "paper_key": "The exact paper_key supplied in the request.",
    "research_problem": "Research problem, with [page N] citations.",
    "main_contributions": "Main contributions, each with [page N] citations.",
    "method_summary": "Method summary, with [page N] citations.",
    "datasets": "Datasets supported by the source, with [page N] citations.",
    "key_results": "Key results, each with [page N] citations.",
    "limitations": "Limitations, each with [page N] citations.",
    "code_urls": "Code URLs explicitly present in the source.",
    "answer_by_question": (
        "One non-empty answer for every requested question. Use the exact question "
        "text as each JSON key and include [page N] citations in every answer."
    ),
    "source_references": "Unique source page references such as page 1.",
    "warnings": "Unsupported or incomplete information warnings.",
    "raw_answer": (
        "A human-readable combined question-and-answer response. Never include raw "
        "XML or the full paper text."
    ),
}

AlphaXivCredentials = CredentialsMetaInput[Literal[ProviderName.MCP], Literal["oauth2"]]


class PaperSourceReader(Protocol):
    async def read(self, paper_url: str, queries: list[str]) -> str: ...


class StructuredAnalysisGenerator(Protocol):
    async def generate(self, paper: PaperTask, source_xml: str) -> PaperAnalysis: ...


class PaperAnalyzer(Protocol):
    async def analyze(
        self, paper: PaperTask, questions: list[str]
    ) -> AnalysisResult: ...


class PaperReportReader(Protocol):
    async def read(self, paper_url: str) -> str: ...


class PaperQuestionAnswerReader(Protocol):
    async def read(self, paper_url: str, questions: list[str]) -> str: ...


class CompleteQuestionAnswerGenerator(Protocol):
    async def generate(
        self,
        paper: PaperTask,
        report: str,
        questions: list[str],
    ) -> str: ...


class ConfiguredPaperAnalyzer:
    def __init__(
        self,
        source_reader: PaperSourceReader,
        structured_generator: StructuredAnalysisGenerator,
    ):
        self._source_reader = source_reader
        self._structured_generator = structured_generator

    async def analyze(self, paper: PaperTask, questions: list[str]) -> AnalysisResult:
        source_xml = await self._source_reader.read(paper.arxiv_url, questions)
        analysis = await self._structured_generator.generate(paper, source_xml)
        analysis = validate_question_answers(paper, questions, analysis)
        return AnalysisResult(
            paper_key=paper.paper_key,
            status=AnalysisStatus.SUCCESS,
            analysis=analysis,
        )


class AlphaXivMCPSourceReader:
    def __init__(self, access_token: str):
        self._access_token = access_token

    async def read(self, paper_url: str, queries: list[str]) -> str:
        client = MCPClient(ALPHAXIV_MCP_URL, auth_token=self._access_token)
        try:
            await client.initialize()
            result = await client.call_tool(
                ALPHAXIV_TOOL_NAME,
                build_alphaxiv_arguments(paper_url, queries),
            )
            if not result.is_error:
                try:
                    return extract_paper_xml(result.content)
                except ValueError:
                    logger.warning(
                        "alphaXiv answer_pdf_queries returned no usable XML for %s; "
                        "falling back to get_paper_content (%s)",
                        paper_url,
                        describe_mcp_content(result.content),
                    )

            fallback = await client.call_tool(
                ALPHAXIV_REPORT_TOOL_NAME,
                build_alphaxiv_report_arguments(paper_url),
            )
            if fallback.is_error:
                raise ValueError("ALPHAXIV_EVIDENCE_UNAVAILABLE")
            report = extract_text_content(fallback.content)
            return build_report_evidence_xml(paper_url, report)
        finally:
            await client.close()


class AlphaXivMCPReportReader:
    def __init__(self, access_token: str):
        self._access_token = access_token

    async def read(self, paper_url: str) -> str:
        client = MCPClient(ALPHAXIV_MCP_URL, auth_token=self._access_token)
        try:
            await client.initialize()
            result = await client.call_tool(
                ALPHAXIV_REPORT_TOOL_NAME,
                build_alphaxiv_report_arguments(paper_url),
            )
            if result.is_error:
                raise ValueError("ALPHAXIV_MCP_ERROR")
            return extract_text_content(result.content)
        finally:
            await client.close()


class AlphaXivMCPQuestionAnswerReader:
    def __init__(self, access_token: str):
        self._access_token = access_token

    async def read(self, paper_url: str, questions: list[str]) -> str:
        client = MCPClient(ALPHAXIV_MCP_URL, auth_token=self._access_token)
        try:
            await client.initialize()
            result = await client.call_tool(
                ALPHAXIV_TOOL_NAME,
                build_alphaxiv_arguments(paper_url, questions),
            )
            if result.is_error:
                raise ValueError("ALPHAXIV_MCP_ERROR")
            return extract_text_content(result.content)
        finally:
            await client.close()


class MCPReportPaperAnalyzer:
    def __init__(self, report_reader: PaperReportReader):
        self._report_reader = report_reader

    async def analyze(self, paper: PaperTask, questions: list[str]) -> AnalysisResult:
        report = await self._report_reader.read(paper.arxiv_url)
        return AnalysisResult(
            paper_key=paper.paper_key,
            status=AnalysisStatus.SUCCESS,
            analysis=build_mcp_report_analysis(paper, report),
        )


class ReportQuestionAnswerAnalyzer:
    def __init__(
        self,
        report_reader: PaperReportReader,
        answer_generator: CompleteQuestionAnswerGenerator,
    ):
        self._report_reader = report_reader
        self._answer_generator = answer_generator

    async def analyze(self, paper: PaperTask, questions: list[str]) -> AnalysisResult:
        report = await self._report_reader.read(paper.arxiv_url)
        answer = await self._answer_generator.generate(paper, report, questions)
        return AnalysisResult(
            paper_key=paper.paper_key,
            status=AnalysisStatus.SUCCESS,
            analysis=build_complete_qa_analysis(paper, answer),
        )


class MCPRawQuestionAnswerAnalyzer:
    def __init__(self, reader: PaperQuestionAnswerReader):
        self._reader = reader

    async def analyze(self, paper: PaperTask, questions: list[str]) -> AnalysisResult:
        answer = await self._reader.read(paper.arxiv_url, questions)
        return AnalysisResult(
            paper_key=paper.paper_key,
            status=AnalysisStatus.SUCCESS,
            analysis=build_mcp_raw_qa_analysis(paper, answer),
            analysis_mode="mcp_qa_raw",
            questions=list(questions),
        )


class AutoGPTStructuredAnalysisGenerator:
    def __init__(
        self,
        credentials: AICredentials,
        resolved_credentials: APIKeyCredentials,
        model: LlmModel,
    ):
        self._credentials = credentials
        self._resolved_credentials = resolved_credentials
        self._model = model

    async def generate(self, paper: PaperTask, source_xml: str) -> PaperAnalysis:
        block = AIStructuredResponseGeneratorBlock()
        input_data = AIStructuredResponseGeneratorBlock.Input(
            prompt=build_analysis_prompt(paper, source_xml),
            expected_format=PAPER_ANALYSIS_FORMAT,
            force_json_output=True,
            model=self._model,
            credentials=self._credentials,
        )
        response = await block.run_once(
            input_data,
            "response",
            credentials=self._resolved_credentials,
        )
        if not isinstance(response, dict):
            raise ValueError("INVALID_STRUCTURED_ANALYSIS")
        analysis = PaperAnalysis.model_validate(response)
        if analysis.paper_key != paper.paper_key:
            raise ValueError("ANALYSIS_IDENTITY_MISMATCH")
        return analysis


class AutoGPTCompleteQuestionAnswerGenerator:
    def __init__(
        self,
        credentials: AICredentials,
        resolved_credentials: APIKeyCredentials,
        model: LlmModel,
        request_interval_seconds: float = DEFAULT_ANALYSIS_REQUEST_INTERVAL_SECONDS,
    ):
        self._credentials = credentials
        self._resolved_credentials = resolved_credentials
        self._model = model
        self._request_interval_seconds = request_interval_seconds
        self._request_lock = asyncio.Lock()
        self._next_request_at = 0.0

    async def _wait_for_request_slot(self) -> None:
        if self._request_interval_seconds <= 0:
            return
        async with self._request_lock:
            loop = asyncio.get_running_loop()
            delay = self._next_request_at - loop.time()
            if delay > 0:
                await asyncio.sleep(delay)
            self._next_request_at = loop.time() + self._request_interval_seconds

    async def generate(
        self,
        paper: PaperTask,
        report: str,
        questions: list[str],
    ) -> str:
        await self._wait_for_request_slot()
        block = AITextGeneratorBlock()
        response = await block.run_once(
            AITextGeneratorBlock.Input(
                prompt=build_complete_qa_prompt(paper, report, questions),
                model=self._model,
                credentials=self._credentials,
                retry=1,
            ),
            "response",
            credentials=self._resolved_credentials,
        )
        if not isinstance(response, str) or not response.strip():
            raise ValueError("EMPTY_QUESTION_ANSWER")
        if "<paper" in response.casefold() or "</paper>" in response.casefold():
            raise ValueError("RAW_PAPER_RETURNED_AS_ANSWER")
        return response.strip()


class AnalyzeConferencePapersBlock(Block):
    execution_timeout_seconds = None

    class Input(BlockSchemaInput):
        run_id: str = SchemaField(
            default="conference-paper-run",
            description="Conference run identifier used for resume checkpoints",
            min_length=1,
        )
        paper_tasks: list[PaperTask] = SchemaField(
            description="Selected conference papers"
        )
        analysis_concurrency: int = SchemaField(
            default=1,
            ge=1,
            le=3,
            description="Maximum concurrent paper analyses",
        )
        analysis_request_interval_seconds: float = SchemaField(
            default=DEFAULT_ANALYSIS_REQUEST_INTERVAL_SECONDS,
            ge=0,
            le=300,
            description="Minimum interval between LLM request starts",
            advanced=True,
        )
        max_new_analyses_per_run: int = SchemaField(
            default=DEFAULT_MAX_NEW_ANALYSES_PER_RUN,
            ge=0,
            le=10_000,
            description="Maximum uncached papers analyzed per run; 0 means unlimited",
            advanced=True,
        )
        authorization_circuit_breaker: bool = SchemaField(
            default=True,
            description="Stop starting new analyses after an authorization failure",
            advanced=True,
        )
        model: LlmModel = SchemaField(
            default=LlmModel.GPT5_6_LUNA,
            description="Language model used to produce the complete Q&A response",
            advanced=True,
        )
        analysis_mode: AnalysisMode = SchemaField(
            default="structured_llm",
            description=(
                "Use the alphaXiv general report plus one strong LLM call per paper, "
                "or save the general report without answering custom questions"
            ),
            advanced=True,
        )
        alphaxiv_credentials: AlphaXivCredentials = CredentialsField(
            discriminator_values={ALPHAXIV_MCP_URL},
            description="Optional OAuth credentials for alphaXiv deep analysis",
            default={},
        )
        llm_credentials: AICredentials = CredentialsField(
            description="Optional API key used when alphaXiv analysis is enabled",
            discriminator="model",
            discriminator_mapping={
                model.value: model.metadata.provider for model in LlmModel
            },
            default={},
        )

    class Output(BlockSchemaOutput):
        analyses: list[AnalysisResult] = SchemaField(
            description="Per-paper analysis results in input order"
        )

    def __init__(self, output_root: Path = DEFAULT_OUTPUT_ROOT):
        self._output_root = output_root
        super().__init__(
            id="c1d4e7a9-2b58-4f63-8c90-5e7a1d3b6f42",
            description="Answers paper questions from an alphaXiv general report.",
            categories={BlockCategory.AI},
            input_schema=AnalyzeConferencePapersBlock.Input,
            output_schema=AnalyzeConferencePapersBlock.Output,
        )

    async def run(
        self,
        input_data: Input,
        *,
        alphaxiv_credentials: OAuth2Credentials | None = None,
        llm_credentials: APIKeyCredentials | None = None,
        **kwargs,
    ) -> BlockOutput:
        if alphaxiv_credentials is None:
            yield (
                "analyses",
                [
                    AnalysisResult(
                        paper_key=paper.paper_key,
                        status=AnalysisStatus.FAILED,
                        error_code=MISSING_MCP_CREDENTIALS_ERROR,
                    )
                    for paper in input_data.paper_tasks
                ],
            )
            return

        checkpoint = JsonlCheckpoint(
            input_data.run_id,
            "analysis-checkpoint.jsonl",
            AnalysisResult,
            lambda result: result.paper_key,
            self._output_root,
        )
        qa_checkpoint = JsonlCheckpoint(
            input_data.run_id,
            "qa-results.jsonl",
            PaperQARecord,
            lambda result: result.paper_key,
            self._output_root,
        )
        cached = checkpoint.load()
        completed = {
            paper.paper_key: cached[paper.paper_key]
            for paper in input_data.paper_tasks
            if paper.paper_key in cached
            and cached[paper.paper_key].status is AnalysisStatus.SUCCESS
            and cached[paper.paper_key].analysis_mode == input_data.analysis_mode
            and cached[paper.paper_key].questions == paper.questions
            and (
                input_data.analysis_mode == "mcp_report"
                or has_complete_question_answers(cached[paper.paper_key], paper)
            )
        }
        remaining = [
            paper
            for paper in input_data.paper_tasks
            if paper.paper_key not in completed
        ]
        access_token = alphaxiv_credentials.access_token.get_secret_value()
        if input_data.analysis_mode == "mcp_report":
            analyzer: PaperAnalyzer = MCPReportPaperAnalyzer(
                AlphaXivMCPReportReader(access_token)
            )
        else:
            if llm_credentials is None:
                failures = {
                    paper.paper_key: AnalysisResult(
                        paper_key=paper.paper_key,
                        status=AnalysisStatus.FAILED,
                        error_code=MISSING_LLM_CREDENTIALS_ERROR,
                        analysis_mode=input_data.analysis_mode,
                        questions=list(paper.questions),
                    )
                    for paper in remaining
                }
                by_key = {**completed, **failures}
                yield (
                    "analyses",
                    [by_key[paper.paper_key] for paper in input_data.paper_tasks],
                )
                return
            analyzer = ReportQuestionAnswerAnalyzer(
                AlphaXivMCPReportReader(access_token),
                AutoGPTCompleteQuestionAnswerGenerator(
                    input_data.llm_credentials,
                    llm_credentials,
                    input_data.model,
                    input_data.analysis_request_interval_seconds,
                ),
            )
        scheduled = remaining
        deferred_by_run_limit: list[PaperTask] = []
        if input_data.max_new_analyses_per_run > 0:
            scheduled = remaining[: input_data.max_new_analyses_per_run]
            deferred_by_run_limit = remaining[input_data.max_new_analyses_per_run :]
        compact_output = len(input_data.paper_tasks) > MAX_INLINE_ANALYSIS_RESULTS
        papers_by_key = {paper.paper_key: paper for paper in input_data.paper_tasks}

        async def persist_analysis(result: AnalysisResult) -> None:
            await checkpoint.append(result)
            paper = papers_by_key[result.paper_key]
            await qa_checkpoint.append(PaperQARecord.from_analysis(paper, result))
            await asyncio.to_thread(
                write_analysis_report,
                input_data.run_id,
                paper,
                result,
                self._output_root,
            )

        fresh = await analyze_many(
            scheduled,
            analyzer,
            input_data.analysis_concurrency,
            input_data.analysis_mode,
            persist_analysis,
            retain_results=not compact_output,
            authorization_circuit_breaker=input_data.authorization_circuit_breaker,
        )
        if compact_output:
            yield "analyses", []
            return
        by_key = {**completed, **{result.paper_key: result for result in fresh}}
        by_key.update(
            {
                paper.paper_key: deferred_analysis_result(
                    paper,
                    input_data.analysis_mode,
                    RUN_LIMIT_DEFERRED_ERROR,
                )
                for paper in deferred_by_run_limit
            }
        )
        yield "analyses", [by_key[paper.paper_key] for paper in input_data.paper_tasks]


async def analyze_many(
    papers: list[PaperTask],
    analyzer: PaperAnalyzer,
    concurrency: int = MAX_ANALYSIS_CONCURRENCY,
    analysis_mode: AnalysisMode | None = None,
    on_result: Callable[[AnalysisResult], Awaitable[None]] | None = None,
    retain_results: bool = True,
    authorization_circuit_breaker: bool = True,
) -> list[AnalysisResult]:
    semaphore = asyncio.Semaphore(min(max(concurrency, 1), MAX_ANALYSIS_CONCURRENCY))
    authorization_circuit_open = asyncio.Event()

    async def guarded(paper: PaperTask) -> AnalysisResult:
        if authorization_circuit_open.is_set():
            return deferred_analysis_result(
                paper,
                analysis_mode,
                AUTHORIZATION_CIRCUIT_OPEN_ERROR,
            )
        async with semaphore:
            if authorization_circuit_open.is_set():
                return deferred_analysis_result(
                    paper,
                    analysis_mode,
                    AUTHORIZATION_CIRCUIT_OPEN_ERROR,
                )
            try:
                result = await analyzer.analyze(paper, paper.questions)
            except Exception as error:
                logger.exception(
                    "Conference paper analysis failed for paper_key=%s arxiv_id=%s",
                    paper.paper_key,
                    paper.arxiv_id,
                )
                result = AnalysisResult(
                    paper_key=paper.paper_key,
                    status=AnalysisStatus.FAILED,
                    error_code="PAPER_ANALYSIS_FAILED",
                    error_detail=build_analysis_error_detail(error),
                )
                if authorization_circuit_breaker and is_authorization_error(error):
                    authorization_circuit_open.set()
            result = result.model_copy(
                update={
                    "analysis_mode": result.analysis_mode or analysis_mode,
                    "questions": result.questions or list(paper.questions),
                }
            )
            if on_result is not None:
                await on_result(result)
            return result

    retained: list[AnalysisResult] = []
    for start in range(0, len(papers), ANALYSIS_BATCH_SIZE):
        batch = papers[start : start + ANALYSIS_BATCH_SIZE]
        completed = list(await asyncio.gather(*(guarded(paper) for paper in batch)))
        if retain_results:
            retained.extend(completed)
    return retained


def deferred_analysis_result(
    paper: PaperTask,
    analysis_mode: AnalysisMode | None,
    error_code: str,
) -> AnalysisResult:
    return AnalysisResult(
        paper_key=paper.paper_key,
        status=AnalysisStatus.FAILED,
        error_code=error_code,
        analysis_mode=analysis_mode,
        questions=list(paper.questions),
    )


def is_authorization_error(error: Exception) -> bool:
    message = str(error).casefold()
    return (
        "http 401" in message
        or "invalid authorization" in message
        or "unauthorized" in message
    )


def build_analysis_error_detail(error: Exception) -> str:
    message = str(error).strip() or "No error message"
    sanitized = re.sub(
        r"(?i)\b(authorization|bearer|access[_-]?token|token)\b"
        r"(\s*[:=]\s*|\s+)[^\s,;]+",
        r"\1=<redacted>",
        message,
    )
    return f"{type(error).__name__}: {sanitized}"[:MAX_ERROR_DETAIL_LENGTH]


def build_alphaxiv_arguments(paper_url: str, queries: list[str]) -> dict[str, Any]:
    return {"paper": paper_url, "queries": list(queries)}


def build_alphaxiv_report_arguments(paper_url: str) -> dict[str, Any]:
    return {"url": paper_url}


def extract_text_content(content: list[dict[str, Any]]) -> str:
    report = "\n\n".join(
        item.get("text", "").strip()
        for item in content
        if item.get("type") == "text" and item.get("text", "").strip()
    )
    if not report:
        raise ValueError("INVALID_ALPHAXIV_RESPONSE")
    return report


def build_mcp_report_analysis(paper: PaperTask, report: str) -> PaperAnalysis:
    normalized_report = report.strip()
    if not normalized_report:
        raise ValueError("INVALID_ALPHAXIV_RESPONSE")
    first_paragraph = next(
        (
            paragraph.strip()
            for paragraph in normalized_report.split("\n\n")
            if paragraph.strip()
        ),
        normalized_report,
    )
    return PaperAnalysis(
        paper_key=paper.paper_key,
        research_problem=first_paragraph,
        method_summary=normalized_report,
        code_urls=_extract_github_urls(normalized_report),
        warnings=[
            "MCP_REPORT_MODE: alphaXiv AI report used directly; custom questions "
            "were not separately synthesized by an external LLM."
        ],
    )


def build_mcp_raw_qa_analysis(paper: PaperTask, answer: str) -> PaperAnalysis:
    normalized_answer = answer.strip()
    if not normalized_answer:
        raise ValueError("INVALID_ALPHAXIV_RESPONSE")
    first_paragraph = next(
        (
            paragraph.strip()
            for paragraph in normalized_answer.split("\n\n")
            if paragraph.strip()
        ),
        normalized_answer,
    )
    return PaperAnalysis(
        paper_key=paper.paper_key,
        research_problem=first_paragraph,
        method_summary=normalized_answer,
        raw_answer=normalized_answer,
        code_urls=_extract_github_urls(normalized_answer),
        warnings=[
            "MCP_QA_RAW_MODE: questions and the complete alphaXiv answer are "
            "preserved without a second LLM call."
        ],
    )


def build_complete_qa_analysis(paper: PaperTask, answer: str) -> PaperAnalysis:
    normalized_answer = answer.strip()
    if not normalized_answer:
        raise ValueError("EMPTY_QUESTION_ANSWER")
    return PaperAnalysis(
        paper_key=paper.paper_key,
        research_problem=normalized_answer,
        method_summary=normalized_answer,
        raw_answer=normalized_answer,
    )


def build_complete_qa_prompt(
    paper: PaperTask,
    report: str,
    questions: list[str],
) -> str:
    numbered_questions = "\n".join(
        f"{index}. {question}" for index, question in enumerate(questions, start=1)
    )
    return f"""You are reading the alphaXiv general report for this paper:
Title: {paper.title}
arXiv: {paper.arxiv_id}

Answer every question below in order. Preserve each complete question as a heading,
then write its complete answer. Use only information supported by the report. If the
report does not contain enough information, state that clearly instead of inventing
facts. Return readable Markdown only. Do not return JSON, XML, the report itself, or
any additional schema fields.

Questions:
{numbered_questions}

alphaXiv general report:
{report}
"""


def extract_paper_xml(content: list[dict[str, Any]]) -> str:
    text_items = [
        item.get("text", "") for item in content if item.get("type") == "text"
    ]
    for text in text_items:
        candidate = _find_paper_xml(text)
        if candidate is None:
            continue
        try:
            root = ElementTree.fromstring(candidate)
        except ElementTree.ParseError:
            if _has_lenient_paper_envelope(candidate):
                return candidate
            continue
        if _is_valid_paper_xml(root):
            return candidate
    raise ValueError("INVALID_ALPHAXIV_RESPONSE")


def build_report_evidence_xml(paper_url: str, report: str) -> str:
    normalized_report = report.strip()
    if not normalized_report:
        raise ValueError("INVALID_ALPHAXIV_RESPONSE")
    paper_id_match = re.search(r"(?:abs/|pdf/)?([^/]+?)(?:\.pdf)?$", paper_url)
    paper_id = paper_id_match.group(1) if paper_id_match else paper_url
    return (
        f'<paper id="{html.escape(paper_id, quote=True)}" '
        'source="alphaxiv_report_fallback">'
        f'<page num="1">{html.escape(normalized_report)}</page>'
        "</paper>"
    )


def describe_mcp_content(content: list[dict[str, Any]]) -> str:
    text_lengths = [
        len(item.get("text", "")) for item in content if item.get("type") == "text"
    ]
    content_types = [str(item.get("type", "unknown")) for item in content]
    return f"types={content_types}, text_lengths={text_lengths}"


def _find_paper_xml(text: str) -> str | None:
    normalized = text.lstrip("\ufeff").strip()
    for candidate_text in (normalized, html.unescape(normalized)):
        start = candidate_text.find("<paper")
        end = candidate_text.rfind("</paper>")
        if start >= 0 and end >= start:
            return candidate_text[start : end + len("</paper>")].strip()
    return None


def _has_lenient_paper_envelope(candidate: str) -> bool:
    paper_open = re.search(r"<paper\b[^>]*\bid\s*=\s*(['\"])[^'\"]+\1", candidate)
    page_open = re.search(r"<page\b[^>]*\bnum\s*=\s*(['\"])[^'\"]+\1", candidate)
    return bool(paper_open and page_open and candidate.rstrip().endswith("</paper>"))


def build_analysis_prompt(paper: PaperTask, source_xml: str) -> str:
    questions = "\n".join(f"- {question}" for question in paper.questions)
    return f"""Analyze the paper using only the alphaXiv XML evidence below.
Return paper_key exactly as {paper.paper_key}.
Make exactly one model response for this paper. Populate every expected field.
answer_by_question MUST contain one non-empty entry for every requested question,
using the exact question text below as its JSON key. raw_answer MUST be a concise,
human-readable compilation of those questions and answers; never copy the XML or
the complete paper into raw_answer.
Every factual claim must cite the supporting XML page as [page N], using page num.
List cited pages in source_references. Put unsupported information in warnings;
when evidence is insufficient, say so explicitly in that question's answer rather
than omitting it. Do not infer or invent unsupported facts.

Questions:
{questions}

alphaXiv XML source:
{source_xml}
"""


def validate_question_answers(
    paper: PaperTask,
    questions: list[str],
    analysis: PaperAnalysis,
) -> PaperAnalysis:
    answers_by_trimmed_question = {
        question.strip(): answer.strip()
        for question, answer in analysis.answer_by_question.items()
        if question.strip() and answer.strip()
    }
    normalized_answers: dict[str, str] = {}
    for question in questions:
        answer = answers_by_trimmed_question.get(question.strip())
        if not answer:
            raise ValueError(f"INCOMPLETE_QUESTION_ANSWERS: {question}")
        normalized_answers[question] = answer
    return analysis.model_copy(
        update={
            "answer_by_question": normalized_answers,
            "raw_answer": render_question_answers(normalized_answers),
        }
    )


def has_complete_question_answers(
    result: AnalysisResult,
    paper: PaperTask,
) -> bool:
    if result.analysis is None:
        return False
    raw_answer = (result.analysis.raw_answer or "").strip()
    return bool(raw_answer) and "<paper" not in raw_answer.casefold()


def render_question_answers(answers: dict[str, str]) -> str:
    return "\n\n".join(
        f"Question: {question}\nAnswer: {answer}"
        for question, answer in answers.items()
    )


def _is_valid_paper_xml(root: ElementTree.Element) -> bool:
    if root.tag != "paper" or not root.attrib.get("id", "").strip():
        return False
    pages = root.findall("page")
    return bool(pages) and all(page.attrib.get("num", "").strip() for page in pages)


def _extract_github_urls(text: str) -> list[str]:
    return list(
        dict.fromkeys(
            re.findall(r"https://github\.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", text)
        )
    )
