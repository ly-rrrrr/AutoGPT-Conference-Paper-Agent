import asyncio
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

from pydantic import AwareDatetime

from backend.blocks._base import (
    Block,
    BlockCategory,
    BlockOutput,
    BlockSchemaInput,
    BlockSchemaOutput,
)
from backend.blocks.conference_paper.models import (
    AnalysisResult,
    AnalysisStatus,
    ConferenceRunInput,
    ContractModel,
    DiscoveryResult,
    LikesResult,
    PaperResult,
    PaperQARecord,
    PaperStatus,
    PaperTask,
    ResultStatus,
    RunCounts,
    RunManifest,
    RunStatus,
    SelectionResult,
)
from backend.blocks.conference_paper.checkpoints import (
    DEFAULT_OUTPUT_ROOT,
    JsonlCheckpoint,
    RUN_ID_PATTERN,
)
from backend.data.model import SchemaField

MAX_INLINE_PAPER_RESULTS = 100


def write_analysis_report(
    run_id: str,
    paper: PaperTask,
    analysis_result: AnalysisResult,
    output_root: Path = DEFAULT_OUTPUT_ROOT,
) -> Path:
    if RUN_ID_PATTERN.fullmatch(run_id) is None:
        raise ValueError("INVALID_RUN_ID")
    run_directory = output_root.resolve() / run_id
    if run_directory.parent != output_root.resolve():
        raise ValueError("INVALID_RUN_ID")
    report_path = (
        run_directory / "reports" / f"{paper.arxiv_id.replace('/', '__')}.md"
    )
    _atomic_write(report_path, _render_analysis_report(paper, analysis_result))
    return report_path


class RunWriter:
    def __init__(self, run_id: str, output_root: Path = DEFAULT_OUTPUT_ROOT):
        if RUN_ID_PATTERN.fullmatch(run_id) is None:
            raise ValueError("INVALID_RUN_ID")
        self.run_id = run_id
        self.run_directory = output_root.resolve() / run_id
        if self.run_directory.parent != output_root.resolve():
            raise ValueError("INVALID_RUN_ID")
        self._lock = asyncio.Lock()

    async def write_result(self, result: PaperResult) -> bool:
        return await self.write_results([result]) == 1

    async def write_results(self, new_results: list[PaperResult]) -> int:
        async with self._lock:
            try:
                existing = self.load_results()
                completed_keys = {
                    item.paper.paper_key
                    for item in existing
                    if item.status is PaperStatus.COMPLETED
                }
                accepted = [
                    result
                    for result in new_results
                    if result.paper.paper_key not in completed_keys
                ]
                if not accepted:
                    return 0
                updated = existing
                for result in accepted:
                    updated = _replace_result(updated, result)
                self._write_result_files(updated)
                return len(accepted)
            except Exception as error:
                if str(error) == "RESULT_PERSIST_FAILED":
                    raise
                raise RuntimeError("RESULT_PERSIST_FAILED") from error

    def load_results(self) -> list[PaperResult]:
        path = self.run_directory / "paper-results.jsonl"
        if not path.exists():
            return []
        return [
            PaperResult.model_validate_json(line)
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]

    def aggregate(self, manifest: RunManifest) -> RunManifest:
        try:
            if manifest.run_id != self.run_id:
                raise ValueError("RUN_ID_MISMATCH")
            results = self.load_results()
            saved = _finalize_manifest(manifest, results)
            _atomic_write(
                self.run_directory / "manifest.json",
                saved.model_dump_json(indent=2) + "\n",
            )
            _atomic_write(
                self.run_directory / "conference-summary.md",
                _render_summary(saved, results),
            )
            return saved
        except Exception as error:
            if str(error) == "RESULT_PERSIST_FAILED":
                raise
            raise RuntimeError("RESULT_PERSIST_FAILED") from error

    def _write_result_files(self, results: list[PaperResult]) -> None:
        self.run_directory.mkdir(parents=True, exist_ok=True)
        reports = self.run_directory / "reports"
        reports.mkdir(exist_ok=True)
        _write_jsonl(self.run_directory / "papers.jsonl", [r.paper for r in results])
        _write_jsonl(
            self.run_directory / "likes-results.jsonl", [r.likes for r in results]
        )
        _write_jsonl(self.run_directory / "paper-results.jsonl", results)
        _write_jsonl(
            self.run_directory / "qa-results.jsonl",
            [PaperQARecord.from_result(result) for result in results],
        )
        for result in results:
            filename = result.paper.arxiv_id.replace("/", "__") + ".md"
            _atomic_write(reports / filename, _render_paper(result))


class PersistPaperResultsBlock(Block):
    class Input(BlockSchemaInput):
        run_id: str = SchemaField(description="Safe local run identifier")
        selection: SelectionResult = SchemaField(description="Selected papers")
        analyses: list[AnalysisResult] = SchemaField(description="Analysis branch")
        likes_results: list[LikesResult] = SchemaField(description="Likes branch")

    class Output(BlockSchemaOutput):
        paper_results: list[PaperResult] = SchemaField(
            description="Joined results reloaded from disk"
        )

    def __init__(self, output_root: Path = DEFAULT_OUTPUT_ROOT):
        self._output_root = output_root
        super().__init__(
            id="b3e8a1c6-4d72-4f95-8b30-6a1e9c5d2f47",
            description="Joins and atomically persists per-paper research results.",
            categories={BlockCategory.DATA},
            input_schema=PersistPaperResultsBlock.Input,
            output_schema=PersistPaperResultsBlock.Output,
        )

    async def run(self, input_data: Input, **kwargs) -> BlockOutput:
        analyses = input_data.analyses
        if not analyses and input_data.selection.paper_tasks:
            analyses = list(
                JsonlCheckpoint(
                    input_data.run_id,
                    "analysis-checkpoint.jsonl",
                    AnalysisResult,
                    lambda result: result.paper_key,
                    self._output_root,
                ).load().values()
            )
        likes_results = input_data.likes_results
        if not likes_results and input_data.selection.paper_tasks:
            likes_results = list(
                JsonlCheckpoint(
                    input_data.run_id,
                    "likes-checkpoint.jsonl",
                    LikesResult,
                    lambda result: result.paper_key,
                    self._output_root,
                ).load().values()
            )
        results = join_results(
            input_data.selection.paper_tasks,
            analyses,
            likes_results,
        )
        writer = RunWriter(input_data.run_id, self._output_root)
        await writer.write_results(results)
        if len(input_data.selection.paper_tasks) > MAX_INLINE_PAPER_RESULTS:
            yield "paper_results", []
            return
        saved = {item.paper.paper_key: item for item in writer.load_results()}
        yield "paper_results", [
            saved[paper.paper_key] for paper in input_data.selection.paper_tasks
        ]


class AggregatePaperReportBlock(Block):
    class Input(BlockSchemaInput):
        run_id: str = SchemaField(description="Safe local run identifier")
        run_input: ConferenceRunInput = SchemaField(description="Original run input")
        discovery: DiscoveryResult = SchemaField(description="Discovery outcome")
        selection: SelectionResult = SchemaField(description="Selection outcome")
        paper_results: list[PaperResult] = SchemaField(
            description="Persisted-result dependency; disk remains authoritative"
        )
        discovered_page_count: int = SchemaField(default=0, ge=0)
        started_at: AwareDatetime | None = SchemaField(default=None)

    class Output(BlockSchemaOutput):
        manifest: RunManifest = SchemaField(description="Final run manifest")
        manifest_path: str = SchemaField(description="Persisted manifest path")
        summary_path: str = SchemaField(description="Persisted summary path")

    def __init__(self, output_root: Path = DEFAULT_OUTPUT_ROOT):
        self._output_root = output_root
        super().__init__(
            id="d7c1b4e8-9a25-4f60-8e13-3b6d2a9c5f74",
            description="Aggregates persisted paper results into run reports.",
            categories={BlockCategory.DATA},
            input_schema=AggregatePaperReportBlock.Input,
            output_schema=AggregatePaperReportBlock.Output,
        )

    async def run(self, input_data: Input, **kwargs) -> BlockOutput:
        now = datetime.now(UTC)
        manifest = RunManifest(
            run_id=input_data.run_id,
            status=RunStatus.RUNNING,
            input=input_data.run_input,
            started_at=input_data.started_at or now,
            discovered_page_count=input_data.discovered_page_count,
            counts=_initial_counts(input_data.discovery, input_data.selection),
            warnings=_run_warnings(input_data.discovery, input_data.selection),
        )
        writer = RunWriter(input_data.run_id, self._output_root)
        yield "manifest", writer.aggregate(manifest)
        yield "manifest_path", str(writer.run_directory / "manifest.json")
        yield "summary_path", str(writer.run_directory / "conference-summary.md")


def join_results(
    papers: list[PaperTask],
    analyses: list[AnalysisResult],
    likes_results: list[LikesResult],
) -> list[PaperResult]:
    paper_keys = [paper.paper_key for paper in papers]
    if len(set(paper_keys)) != len(paper_keys):
        raise ValueError("PAPER_RESULT_MISMATCH")
    analyses_by_key = _unique_analyses(analyses)
    likes_by_key = _unique_likes(likes_results)
    allowed = set(paper_keys)
    if set(analyses_by_key) - allowed:
        raise ValueError("ANALYSIS_RESULT_MISMATCH")
    if set(likes_by_key) - allowed:
        raise ValueError("LIKES_RESULT_MISMATCH")

    joined = []
    for paper in papers:
        analysis = analyses_by_key.get(paper.paper_key) or _missing_analysis(paper)
        likes = likes_by_key.get(paper.paper_key) or _missing_likes(paper)
        if likes.arxiv_id != paper.arxiv_id:
            raise ValueError("LIKES_RESULT_MISMATCH")
        joined.append(PaperResult.from_parts(paper, likes, analysis))
    return joined


def _unique_analyses(results: list[AnalysisResult]) -> dict[str, AnalysisResult]:
    mapped = {result.paper_key: result for result in results}
    if len(mapped) != len(results):
        raise ValueError("ANALYSIS_RESULT_MISMATCH")
    return mapped


def _unique_likes(results: list[LikesResult]) -> dict[str, LikesResult]:
    mapped = {result.paper_key: result for result in results}
    if len(mapped) != len(results):
        raise ValueError("LIKES_RESULT_MISMATCH")
    return mapped


def _missing_analysis(paper: PaperTask) -> AnalysisResult:
    return AnalysisResult(
        paper_key=paper.paper_key,
        status=AnalysisStatus.FAILED,
        error_code="MISSING_ANALYSIS_RESULT",
    )


def _missing_likes(paper: PaperTask) -> LikesResult:
    return LikesResult(
        paper_key=paper.paper_key,
        arxiv_id=paper.arxiv_id,
        status=ResultStatus.FAILED,
        error_code="MISSING_LIKES_RESULT",
    )


def _replace_result(results: list[PaperResult], new: PaperResult) -> list[PaperResult]:
    return (
        [
            new if item.paper.paper_key == new.paper.paper_key else item
            for item in results
        ]
        if any(item.paper.paper_key == new.paper.paper_key for item in results)
        else [*results, new]
    )


def _write_jsonl(path: Path, models: Sequence[ContractModel]) -> None:
    lines = [model.model_dump_json() for model in models]
    _atomic_write(path, "\n".join(lines) + ("\n" if lines else ""))


def _atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(content, encoding="utf-8")
    temporary.replace(path)


def _render_paper(result: PaperResult) -> str:
    likes = result.likes.likes if result.likes.likes is not None else "FAILED"
    warnings = ", ".join(result.warnings) or "None"
    answers = _render_question_answers(result)
    questions = "\n".join(
        f"{index}. {question}"
        for index, question in enumerate(result.paper.questions, start=1)
    )
    return (
        f"# {result.paper.title}\n\n"
        f"- arXiv: {result.paper.arxiv_id}\n"
        f"- Status: {result.status}\n"
        f"- Likes: {likes}\n"
        f"- Warnings: {warnings}\n\n"
        f"## Questions\n\n{questions}\n\n"
        f"## Answers\n\n{answers}\n"
    )


def _render_analysis_report(
    paper: PaperTask, analysis_result: AnalysisResult
) -> str:
    questions = "\n".join(
        f"{index}. {question}"
        for index, question in enumerate(paper.questions, start=1)
    )
    if analysis_result.analysis is None:
        answers = "Unavailable"
        warnings = analysis_result.error_code or "PAPER_ANALYSIS_FAILED"
        status = "ANALYSIS_FAILED"
    else:
        partial_result = PaperResult.from_parts(
            paper,
            LikesResult(
                paper_key=paper.paper_key,
                arxiv_id=paper.arxiv_id,
                status=ResultStatus.FAILED,
                error_code="LIKES_PENDING",
            ),
            analysis_result,
        )
        answers = _render_question_answers(partial_result)
        warnings = "Likes collection pending"
        status = "ANALYSIS_COMPLETED"
    return (
        f"# {paper.title}\n\n"
        f"- arXiv: {paper.arxiv_id}\n"
        f"- Status: {status}\n"
        f"- Likes: Pending\n"
        f"- Warnings: {warnings}\n\n"
        f"## Questions\n\n{questions}\n\n"
        f"## Answers\n\n{answers}\n"
    )


def _render_question_answers(result: PaperResult) -> str:
    if result.analysis is None:
        return "Unavailable"
    if result.analysis.answer_by_question:
        sections = []
        for index, question in enumerate(result.paper.questions, start=1):
            answer = result.analysis.answer_by_question.get(question)
            if answer:
                sections.append(f"### {index}. {question}\n\n{answer}")
        if sections:
            return "\n\n".join(sections)
    return result.analysis.raw_answer or result.analysis.method_summary


def _initial_counts(
    discovery: DiscoveryResult, selection: SelectionResult
) -> RunCounts:
    skipped = (
        selection.skipped_no_arxiv_link
        + selection.skipped_topic_mismatch
        + len(selection.rejected)
    )
    return RunCounts(
        discovered=discovery.counts.unique_count,
        skipped=skipped,
        selected=len(selection.paper_tasks),
        likes_success=0,
        likes_failed=0,
        analysis_success=0,
        analysis_failed=0,
        completed=0,
        partial=0,
        failed=0,
    )


def _run_warnings(discovery: DiscoveryResult, selection: SelectionResult) -> list[str]:
    return [failure.error_code for failure in discovery.page_failures] + [
        rejected.error_code for rejected in selection.rejected
    ]


def _finalize_manifest(
    manifest: RunManifest, results: list[PaperResult]
) -> RunManifest:
    counts = manifest.counts.model_copy(
        update={
            "selected": len(results),
            "likes_success": sum(
                r.likes.status is ResultStatus.SUCCESS for r in results
            ),
            "likes_failed": sum(r.likes.status is ResultStatus.FAILED for r in results),
            "analysis_success": sum(r.analysis is not None for r in results),
            "analysis_failed": sum(r.analysis is None for r in results),
            "completed": sum(r.status is PaperStatus.COMPLETED for r in results),
            "partial": sum(r.status is PaperStatus.PARTIAL for r in results),
            "failed": sum(r.status is PaperStatus.FAILED for r in results),
        }
    )
    status = _run_status(results)
    return RunManifest.model_validate(
        {
            **manifest.model_dump(),
            "status": status,
            "finished_at": datetime.now(UTC),
            "counts": counts,
        }
    )


def _run_status(results: list[PaperResult]) -> RunStatus:
    if results and all(r.status is PaperStatus.COMPLETED for r in results):
        return RunStatus.COMPLETED
    if not results or all(r.status is PaperStatus.FAILED for r in results):
        return RunStatus.FAILED
    return RunStatus.PARTIAL


def _render_summary(manifest: RunManifest, results: list[PaperResult]) -> str:
    rows = [
        f"| {r.paper.arxiv_id} | {r.status} | {r.likes.likes if r.likes.likes is not None else 'FAILED'} |"
        for r in results
    ]
    return (
        f"# {manifest.input.conference} {manifest.input.year} Research Summary\n\n"
        f"Run status: {manifest.status}\n\n"
        f"Selected: {manifest.counts.selected}; Completed: {manifest.counts.completed}; "
        f"Partial: {manifest.counts.partial}; Failed: {manifest.counts.failed}.\n\n"
        "| arXiv ID | Status | Likes |\n|---|---|---:|\n" + "\n".join(rows) + "\n"
    )
