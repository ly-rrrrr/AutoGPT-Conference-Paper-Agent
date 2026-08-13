import asyncio
import logging
from xml.etree import ElementTree
from pathlib import Path

import pytest

import backend.blocks.conference_paper.analysis as analysis_module
from backend.blocks.conference_paper.analysis import (
    ALPHAXIV_MCP_URL,
    ALPHAXIV_REPORT_TOOL_NAME,
    ALPHAXIV_TOOL_NAME,
    AlphaXivMCPSourceReader,
    MISSING_MCP_CREDENTIALS_ERROR,
    PAPER_ANALYSIS_FORMAT,
    AnalyzeConferencePapersBlock,
    ConfiguredPaperAnalyzer,
    MCPRawQuestionAnswerAnalyzer,
    MCPReportPaperAnalyzer,
    ReportQuestionAnswerAnalyzer,
    analyze_many,
    build_alphaxiv_arguments,
    build_alphaxiv_report_arguments,
    build_analysis_prompt,
    build_complete_qa_analysis,
    build_complete_qa_prompt,
    build_report_evidence_xml,
    build_mcp_report_analysis,
    build_mcp_raw_qa_analysis,
    extract_paper_xml,
    extract_text_content,
    has_complete_question_answers,
    validate_question_answers,
)
from backend.blocks.conference_paper.models import (
    AnalysisResult,
    AnalysisStatus,
    PaperAnalysis,
    PaperTask,
)
from backend.blocks.mcp.client import MCPCallResult

FIXTURE_PATH = (
    Path(__file__).resolve().parents[5]
    / "projects"
    / "conference-paper-research-agent"
    / "fixtures"
    / "alphaxiv"
    / "answer-pdf-queries.xml"
)
QUESTIONS = [
    "What problem does the paper solve?",
    "What are the main experimental results?",
]


@pytest.fixture(scope="session", autouse=True)
def graph_cleanup() -> None:
    return None


def paper_task(arxiv_id: str = "2503.21761") -> PaperTask:
    return PaperTask(
        paper_key=f"arxiv:{arxiv_id}",
        conference="CVPR",
        year=2025,
        title=f"Contract Paper {arxiv_id}",
        authors=["Ada Lovelace"],
        detail_url=f"https://openaccess.thecvf.com/content/CVPR2025/paper/{arxiv_id}",
        pdf_url=f"https://openaccess.thecvf.com/content/CVPR2025/papers/{arxiv_id}.pdf",
        arxiv_url=f"https://arxiv.org/abs/{arxiv_id}",
        arxiv_id=arxiv_id,
        questions=QUESTIONS,
        conference_day="2025-06-13",
    )


def successful_result(paper: PaperTask) -> AnalysisResult:
    return AnalysisResult(
        paper_key=paper.paper_key,
        status=AnalysisStatus.SUCCESS,
        analysis=PaperAnalysis(
            paper_key=paper.paper_key,
            research_problem="A source-grounded problem statement [page 1].",
            method_summary="A source-grounded method summary [page 1].",
            source_references=["page 1"],
            answer_by_question={
                QUESTIONS[0]: "It solves the target problem [page 1].",
                QUESTIONS[1]: "It reports the target results [page 1].",
            },
        ),
    )


def contract_xml() -> str:
    return FIXTURE_PATH.read_text(encoding="utf-8")


def test_official_contract_uses_paper_and_batches_queries() -> None:
    task = paper_task()

    arguments = build_alphaxiv_arguments(task.arxiv_url, task.questions)

    assert ALPHAXIV_MCP_URL == "https://api.alphaxiv.org/mcp/v1"
    assert ALPHAXIV_TOOL_NAME == "answer_pdf_queries"
    assert arguments == {"paper": task.arxiv_url, "queries": QUESTIONS}


def test_official_report_contract_uses_get_paper_content() -> None:
    task = paper_task()

    arguments = build_alphaxiv_report_arguments(task.arxiv_url)

    assert ALPHAXIV_REPORT_TOOL_NAME == "get_paper_content"
    assert arguments == {"url": task.arxiv_url}


def test_extract_paper_xml_accepts_documented_page_envelope() -> None:
    source_xml = extract_paper_xml([{"type": "text", "text": contract_xml()}])

    assert '<paper id="2503.21761">' in source_xml
    assert '<page num="1">' in source_xml
    assert '<page num="9">' in source_xml


@pytest.mark.parametrize(
    "wrapped",
    [
        "Here is the evidence:\n```xml\n<paper id=\"x\"><page num=\"1\">A</page></paper>\n```",
        "{\"result\":\"<paper id='x'><page num='1'>A</page></paper>\"}",
        "&lt;paper id=&quot;x&quot;&gt;&lt;page num=&quot;1&quot;&gt;A&lt;/page&gt;&lt;/paper&gt;",
    ],
)
def test_extract_paper_xml_accepts_wrapped_and_escaped_xml(wrapped: str) -> None:
    source_xml = extract_paper_xml([{"type": "text", "text": wrapped}])

    assert source_xml.startswith("<paper")
    assert source_xml.endswith("</paper>")


def test_report_fallback_builds_safe_page_evidence() -> None:
    evidence = build_report_evidence_xml(
        "https://arxiv.org/abs/2506.05398",
        "Method compares a <baseline> & reports improvements.",
    )
    root = ElementTree.fromstring(evidence)

    assert root.attrib["id"] == "2506.05398"
    assert root.attrib["source"] == "alphaxiv_report_fallback"
    assert root.find("page").text == (
        "Method compares a <baseline> & reports improvements."
    )


@pytest.mark.asyncio
async def test_source_reader_falls_back_when_query_response_has_no_xml(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    class FakeMCPClient:
        def __init__(self, server_url: str, auth_token: str):
            assert server_url == ALPHAXIV_MCP_URL
            assert auth_token == "secret"

        async def initialize(self) -> None:
            return None

        async def call_tool(self, tool_name: str, arguments: dict):
            calls.append(tool_name)
            if tool_name == ALPHAXIV_TOOL_NAME:
                return MCPCallResult(
                    content=[{"type": "text", "text": "Paper is still indexing"}]
                )
            return MCPCallResult(
                content=[{"type": "text", "text": "Fallback report evidence"}]
            )

        async def close(self) -> None:
            return None

    monkeypatch.setattr(analysis_module, "MCPClient", FakeMCPClient)

    evidence = await AlphaXivMCPSourceReader("secret").read(
        "https://arxiv.org/abs/2506.05398",
        QUESTIONS,
    )

    assert calls == [ALPHAXIV_TOOL_NAME, ALPHAXIV_REPORT_TOOL_NAME]
    assert "Fallback report evidence" in evidence
    assert 'source="alphaxiv_report_fallback"' in evidence


def test_extract_text_content_joins_mcp_text_blocks() -> None:
    report = extract_text_content(
        [
            {"type": "text", "text": "Research overview"},
            {"type": "image", "data": "ignored"},
            {"type": "text", "text": "Method and results"},
        ]
    )

    assert report == "Research overview\n\nMethod and results"


def test_mcp_report_builds_usable_analysis_without_external_llm() -> None:
    task = paper_task()
    report = (
        "This paper studies reliable visual reasoning.\n\n"
        "The method uses a constrained decoder. "
        "Code: https://github.com/example/research-agent"
    )

    analysis = build_mcp_report_analysis(task, report)

    assert analysis.paper_key == task.paper_key
    assert analysis.research_problem == "This paper studies reliable visual reasoning."
    assert analysis.method_summary == report
    assert analysis.code_urls == ["https://github.com/example/research-agent"]
    assert analysis.warnings and "MCP_REPORT_MODE" in analysis.warnings[0]


@pytest.mark.parametrize(
    "content",
    [
        [],
        [{"type": "image", "data": "ignored"}],
        [{"type": "text", "text": "not XML"}],
        [{"type": "text", "text": "<result />"}],
        [{"type": "text", "text": '<paper id="x"><page>missing num</page></paper>'}],
    ],
)
def test_extract_paper_xml_rejects_non_contract_content(content: list[dict]) -> None:
    with pytest.raises(ValueError, match="INVALID_ALPHAXIV_RESPONSE"):
        extract_paper_xml(content)


def test_prompt_and_expected_format_enforce_grounded_model_boundary() -> None:
    task = paper_task()
    source_xml = contract_xml()

    prompt = build_analysis_prompt(task, source_xml)

    assert set(PAPER_ANALYSIS_FORMAT) == set(PaperAnalysis.model_fields)
    assert task.paper_key in prompt
    assert source_xml in prompt
    assert "page num" in prompt
    assert "source_references" in prompt
    assert "warnings" in prompt
    assert "unsupported" in prompt.casefold()
    assert "exact question text" in prompt
    assert "never copy the XML" in prompt


def test_question_answer_validation_rejects_missing_answer() -> None:
    task = paper_task()
    incomplete = PaperAnalysis(
        paper_key=task.paper_key,
        research_problem="Problem [page 1].",
        method_summary="Method [page 1].",
        answer_by_question={QUESTIONS[0]: "Answered [page 1]."},
    )

    with pytest.raises(ValueError, match="INCOMPLETE_QUESTION_ANSWERS"):
        validate_question_answers(task, task.questions, incomplete)


def test_question_answer_validation_replaces_raw_xml_with_complete_qa() -> None:
    task = paper_task()
    analysis = successful_result(task).analysis
    assert analysis is not None
    analysis.raw_answer = contract_xml()

    validated = validate_question_answers(task, task.questions, analysis)
    result = successful_result(task).model_copy(update={"analysis": validated})

    assert "<paper" not in (validated.raw_answer or "")
    assert "Question: What problem does the paper solve?" in validated.raw_answer
    assert has_complete_question_answers(result, task)


class SourceReaderRecorder:
    def __init__(self) -> None:
        self.calls: list[tuple[str, list[str]]] = []

    async def read(self, paper_url: str, queries: list[str]) -> str:
        self.calls.append((paper_url, list(queries)))
        return contract_xml()


class StructuredGeneratorRecorder:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    async def generate(self, paper: PaperTask, source_xml: str) -> PaperAnalysis:
        self.calls.append((paper.paper_key, source_xml))
        result = successful_result(paper).analysis
        assert result is not None
        return result


class ReportReaderRecorder:
    def __init__(self) -> None:
        self.calls: list[str] = []

    async def read(self, paper_url: str) -> str:
        self.calls.append(paper_url)
        return "AI-generated alphaXiv report"


class QuestionAnswerReaderRecorder:
    def __init__(self) -> None:
        self.calls: list[tuple[str, list[str]]] = []

    async def read(self, paper_url: str, questions: list[str]) -> str:
        self.calls.append((paper_url, list(questions)))
        return "Question 1: answer one.\n\nQuestion 2: answer two."


class CompleteQuestionAnswerGeneratorRecorder:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, list[str]]] = []

    async def generate(
        self,
        paper: PaperTask,
        report: str,
        questions: list[str],
    ) -> str:
        self.calls.append((paper.paper_key, report, list(questions)))
        return "# Question 1\nComplete answer one.\n\n# Question 2\nComplete answer two."


@pytest.mark.asyncio
async def test_local_orchestration_batches_all_questions_in_one_reader_call() -> None:
    task = paper_task()
    reader = SourceReaderRecorder()
    generator = StructuredGeneratorRecorder()
    analyzer = ConfiguredPaperAnalyzer(reader, generator)

    result = await analyzer.analyze(task, task.questions)

    assert reader.calls == [(task.arxiv_url, QUESTIONS)]
    assert generator.calls == [(task.paper_key, contract_xml())]
    assert result.status is AnalysisStatus.SUCCESS


@pytest.mark.asyncio
async def test_mcp_report_analyzer_succeeds_without_llm() -> None:
    task = paper_task()
    reader = ReportReaderRecorder()
    analyzer = MCPReportPaperAnalyzer(reader)

    result = await analyzer.analyze(task, task.questions)

    assert reader.calls == [task.arxiv_url]
    assert result.status is AnalysisStatus.SUCCESS
    assert result.analysis is not None
    assert result.analysis.method_summary == "AI-generated alphaXiv report"


@pytest.mark.asyncio
async def test_default_report_qa_uses_one_report_and_one_complete_answer() -> None:
    task = paper_task()
    reader = ReportReaderRecorder()
    generator = CompleteQuestionAnswerGeneratorRecorder()
    analyzer = ReportQuestionAnswerAnalyzer(reader, generator)

    result = await analyzer.analyze(task, task.questions)

    assert reader.calls == [task.arxiv_url]
    assert generator.calls == [
        (task.paper_key, "AI-generated alphaXiv report", QUESTIONS)
    ]
    assert result.analysis is not None
    assert result.analysis.raw_answer == (
        "# Question 1\nComplete answer one.\n\n# Question 2\nComplete answer two."
    )
    assert result.analysis.answer_by_question == {}


def test_complete_qa_prompt_requests_plain_markdown_without_schema() -> None:
    task = paper_task()

    prompt = build_complete_qa_prompt(task, "General report", QUESTIONS)
    analysis = build_complete_qa_analysis(task, "Complete Markdown answer")

    assert all(question in prompt for question in QUESTIONS)
    assert "readable Markdown only" in prompt
    assert "Do not return JSON, XML" in prompt
    assert analysis.raw_answer == "Complete Markdown answer"
    assert analysis.answer_by_question == {}


@pytest.mark.asyncio
async def test_mcp_raw_qa_batches_questions_and_preserves_complete_answer() -> None:
    task = paper_task()
    reader = QuestionAnswerReaderRecorder()
    analyzer = MCPRawQuestionAnswerAnalyzer(reader)

    result = await analyzer.analyze(task, task.questions)

    assert reader.calls == [(task.arxiv_url, QUESTIONS)]
    assert result.status is AnalysisStatus.SUCCESS
    assert result.questions == QUESTIONS
    assert result.analysis_mode == "mcp_qa_raw"
    assert result.analysis is not None
    assert result.analysis.raw_answer == (
        "Question 1: answer one.\n\nQuestion 2: answer two."
    )


def test_build_mcp_raw_qa_analysis_keeps_answer_verbatim() -> None:
    task = paper_task()
    answer = "Complete alphaXiv answer with [page 1]."

    analysis = build_mcp_raw_qa_analysis(task, answer)

    assert analysis.raw_answer == answer
    assert analysis.method_summary == answer


class ConcurrencyRecorder:
    def __init__(self, failing_id: str | None = None) -> None:
        self.active = 0
        self.maximum_active = 0
        self.failing_id = failing_id

    async def analyze(self, paper: PaperTask, questions: list[str]) -> AnalysisResult:
        assert questions == paper.questions
        self.active += 1
        self.maximum_active = max(self.maximum_active, self.active)
        await asyncio.sleep(0.01)
        self.active -= 1
        if paper.arxiv_id == self.failing_id:
            raise RuntimeError("controlled local orchestration failure")
        return successful_result(paper)


@pytest.mark.asyncio
async def test_local_orchestration_caps_analysis_concurrency_at_three() -> None:
    papers = [paper_task(f"2503.{index:05d}") for index in range(8)]
    recorder = ConcurrencyRecorder()

    results = await analyze_many(papers, recorder, concurrency=20)

    assert recorder.maximum_active == 3
    assert [result.paper_key for result in results] == [
        paper.paper_key for paper in papers
    ]


@pytest.mark.asyncio
async def test_local_orchestration_isolates_one_paper_failure() -> None:
    papers = [paper_task("2503.00001"), paper_task("2503.00002")]
    recorder = ConcurrencyRecorder(failing_id="2503.00001")

    results = await analyze_many(papers, recorder, concurrency=3)

    assert [result.status for result in results] == [
        AnalysisStatus.FAILED,
        AnalysisStatus.SUCCESS,
    ]
    assert results[0].error_code == "PAPER_ANALYSIS_FAILED"
    assert (
        results[0].error_detail
        == "RuntimeError: controlled local orchestration failure"
    )
    assert results[0].analysis is None


@pytest.mark.asyncio
async def test_local_orchestration_logs_the_original_paper_failure(caplog) -> None:
    task = paper_task("2503.00001")
    recorder = ConcurrencyRecorder(failing_id=task.arxiv_id)

    with caplog.at_level(
        logging.ERROR,
        logger="backend.blocks.conference_paper.analysis",
    ):
        await analyze_many([task], recorder, concurrency=1)

    assert "controlled local orchestration failure" in caplog.text
    assert f"paper_key={task.paper_key}" in caplog.text
    assert f"arxiv_id={task.arxiv_id}" in caplog.text


def test_block_declares_separate_mcp_and_llm_credentials() -> None:
    block = AnalyzeConferencePapersBlock()
    credential_fields = block.input_schema.get_credentials_fields()
    credential_fields_info = block.input_schema.get_credentials_fields_info()

    assert block.id == "c1d4e7a9-2b58-4f63-8c90-5e7a1d3b6f42"
    assert set(credential_fields) == {
        "alphaxiv_credentials",
        "llm_credentials",
    }
    assert credential_fields_info["alphaxiv_credentials"].discriminator_values == {
        ALPHAXIV_MCP_URL
    }
    assert "alphaxiv_credentials" not in block.input_schema.jsonschema().get(
        "required", []
    )
    assert "llm_credentials" not in block.input_schema.jsonschema().get("required", [])
    input_data = block.Input(paper_tasks=[])
    assert input_data.analysis_mode == "structured_llm"
    assert input_data.model.value == "gpt-5.6-luna"


@pytest.mark.asyncio
async def test_block_skips_analysis_without_mcp_credentials() -> None:
    task = paper_task()
    block = AnalyzeConferencePapersBlock()
    input_data = block.Input(paper_tasks=[task])

    outputs = [
        item
        async for item in block.run(
            input_data,
            alphaxiv_credentials=None,
            llm_credentials=None,
        )
    ]

    assert outputs == [
        (
            "analyses",
            [
                AnalysisResult(
                    paper_key=task.paper_key,
                    status=AnalysisStatus.FAILED,
                    error_code=MISSING_MCP_CREDENTIALS_ERROR,
                )
            ],
        )
    ]
