import asyncio
from datetime import UTC, datetime
from pathlib import Path

import pytest

from backend.blocks.conference_paper.models import (
    AnalysisResult,
    AnalysisStatus,
    ConferenceRunInput,
    DiscoveryCounts,
    DiscoveryResult,
    LikesResult,
    PaperAnalysis,
    PaperResult,
    PaperSeed,
    PaperStatus,
    PaperTask,
    ResultStatus,
    RunCounts,
    RunManifest,
    RunStatus,
    SelectionResult,
)
from backend.blocks.conference_paper.results import (
    AggregatePaperReportBlock,
    PersistPaperResultsBlock,
    RunWriter,
    join_results,
    write_analysis_report,
)


@pytest.fixture(scope="session", autouse=True)
def graph_cleanup() -> None:
    return None


def test_join_preserves_order_and_marks_missing_branch() -> None:
    papers = [_paper("2503.00002"), _paper("2503.00001")]

    results = join_results(
        papers,
        [_analysis_result(papers[0])],
        [_likes_result(papers[0], 8), _likes_result(papers[1], 3)],
    )

    assert [result.paper.paper_key for result in results] == [
        "arxiv:2503.00002",
        "arxiv:2503.00001",
    ]
    assert results[0].status is PaperStatus.COMPLETED
    assert results[1].status is PaperStatus.PARTIAL
    assert "MISSING_ANALYSIS_RESULT" in results[1].warnings


@pytest.mark.parametrize("branch", ["unknown", "duplicate", "identity"])
def test_join_rejects_invalid_branch_results(branch: str) -> None:
    paper = _paper("2503.00001")
    analyses = [_analysis_result(paper)]
    likes = [_likes_result(paper, 3)]
    if branch == "unknown":
        analyses = [_analysis_result(_paper("2503.99999"))]
    elif branch == "duplicate":
        likes = [likes[0], likes[0]]
    else:
        likes = [
            LikesResult(
                paper_key=paper.paper_key,
                arxiv_id="2503.99999",
                likes=3,
                raw_text="3 Likes",
                status=ResultStatus.SUCCESS,
            )
        ]

    with pytest.raises(ValueError, match="RESULT_MISMATCH"):
        join_results([paper], analyses, likes)


@pytest.mark.asyncio
async def test_writer_uses_real_files_and_serializes_concurrent_writes(
    tmp_path: Path,
) -> None:
    writer = RunWriter("run-01", output_root=tmp_path)
    results = [
        _paper_result(_paper(f"2503.0000{index}"), likes=index) for index in range(1, 6)
    ]

    await asyncio.gather(*(writer.write_result(result) for result in results))

    run_dir = tmp_path / "run-01"
    assert len(writer.load_results()) == 5
    assert len((run_dir / "papers.jsonl").read_text().splitlines()) == 5
    assert len((run_dir / "likes-results.jsonl").read_text().splitlines()) == 5
    assert len((run_dir / "paper-results.jsonl").read_text().splitlines()) == 5
    assert len((run_dir / "qa-results.jsonl").read_text().splitlines()) == 5
    assert len(list((run_dir / "reports").glob("*.md"))) == 5
    assert not list(run_dir.rglob("*.tmp"))


@pytest.mark.asyncio
async def test_writer_does_not_overwrite_completed_result(tmp_path: Path) -> None:
    writer = RunWriter("resume", output_root=tmp_path)
    paper = _paper("2503.00001")
    await writer.write_result(_paper_result(paper, likes=83))
    await writer.write_result(_paper_result(paper, likes=84))

    reloaded = RunWriter("resume", output_root=tmp_path).load_results()

    assert len(reloaded) == 1
    assert reloaded[0].likes.likes == 83


@pytest.mark.asyncio
async def test_writer_persists_full_batch_with_one_file_rewrite(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    writer = RunWriter("batch", output_root=tmp_path)
    results = [
        _paper_result(_paper(f"2503.{index:05d}"), likes=index) for index in range(20)
    ]
    calls = 0
    original = writer._write_result_files

    def record_write(items: list[PaperResult]) -> None:
        nonlocal calls
        calls += 1
        original(items)

    monkeypatch.setattr(writer, "_write_result_files", record_write)

    written = await writer.write_results(results)

    assert written == 20
    assert calls == 1
    assert len(writer.load_results()) == 20


@pytest.mark.asyncio
async def test_writer_reports_real_file_failure_with_stable_code(
    tmp_path: Path,
) -> None:
    blocked_root = tmp_path / "not-a-directory"
    blocked_root.write_text("file")
    writer = RunWriter("run", output_root=blocked_root)

    with pytest.raises(RuntimeError, match="RESULT_PERSIST_FAILED"):
        await writer.write_result(_paper_result(_paper("2503.00001"), 1))


def test_writer_sanitizes_slash_in_arxiv_report_name(tmp_path: Path) -> None:
    writer = RunWriter("legacy", output_root=tmp_path)
    asyncio.run(writer.write_result(_paper_result(_paper("hep-th/9901001"), 1)))

    assert (tmp_path / "legacy" / "reports" / "hep-th__9901001.md").is_file()


def test_paper_report_preserves_questions_and_complete_answer(tmp_path: Path) -> None:
    writer = RunWriter("qa", output_root=tmp_path)
    paper = _paper("2503.00001")
    result = _paper_result(paper, 7)
    assert result.analysis is not None
    result.analysis.raw_answer = "<paper>must not be persisted as the answer</paper>"
    result.analysis.answer_by_question = {"What is new?": "The complete answer."}

    asyncio.run(writer.write_result(result))

    report = (tmp_path / "qa" / "reports" / "2503.00001.md").read_text()
    qa_record = (tmp_path / "qa" / "qa-results.jsonl").read_text()
    assert "## Questions" in report
    assert "What is new?" in report
    assert "## Answers" in report
    assert "### 1. What is new?" in report
    assert "The complete answer." in report
    assert 'Question: What is new?\\nAnswer: The complete answer.' in qa_record
    assert "<paper>" not in report
    assert "<paper>" not in qa_record


def test_analysis_report_is_available_before_likes_finish(tmp_path: Path) -> None:
    paper = _paper("2503.00001")

    report_path = write_analysis_report(
        "live-run", paper, _analysis_result(paper), tmp_path
    )

    report = report_path.read_text(encoding="utf-8")
    assert report_path == tmp_path / "live-run" / "reports" / "2503.00001.md"
    assert "Status: ANALYSIS_COMPLETED" in report
    assert "Likes: Pending" in report
    assert "What is new?" in report
    assert "A method [page 2]" in report


@pytest.mark.parametrize(
    "run_id", ["../escape", "C:\\escape", "/escape", "a/b", "a\\b"]
)
def test_writer_rejects_unsafe_run_id(tmp_path: Path, run_id: str) -> None:
    with pytest.raises(ValueError, match="INVALID_RUN_ID"):
        RunWriter(run_id, output_root=tmp_path)


@pytest.mark.asyncio
async def test_aggregate_rereads_disk_and_writes_manifest_and_summary(
    tmp_path: Path,
) -> None:
    writer = RunWriter("aggregate", output_root=tmp_path)
    complete = _paper_result(_paper("2503.00001"), 11)
    partial = PaperResult.from_parts(
        _paper("2503.00002"),
        _likes_result(_paper("2503.00002"), 4),
        AnalysisResult(
            paper_key="arxiv:2503.00002",
            status=AnalysisStatus.FAILED,
            error_code="PAPER_ANALYSIS_FAILED",
        ),
    )
    await writer.write_result(complete)
    await writer.write_result(partial)
    manifest = _manifest("aggregate")

    saved = writer.aggregate(manifest)

    reloaded = RunManifest.model_validate_json(
        (tmp_path / "aggregate" / "manifest.json").read_text()
    )
    summary = (tmp_path / "aggregate" / "conference-summary.md").read_text()
    assert saved == reloaded
    assert reloaded.status is RunStatus.PARTIAL
    assert reloaded.counts.completed == 1
    assert reloaded.counts.partial == 1
    assert reloaded.counts.likes_success == 2
    assert "2503.00001" in summary and "11" in summary
    assert "2503.00002" in summary and "4" in summary
    assert (
        "observed_at"
        not in (tmp_path / "aggregate" / "likes-results.jsonl").read_text()
    )


def test_block_ids_are_stable() -> None:
    assert PersistPaperResultsBlock().id == "b3e8a1c6-4d72-4f95-8b30-6a1e9c5d2f47"
    assert AggregatePaperReportBlock().id == "d7c1b4e8-9a25-4f60-8e13-3b6d2a9c5f74"
    assert {"run_id", "selection", "analyses", "likes_results"} <= set(
        PersistPaperResultsBlock.Input.model_fields
    )
    assert {
        "run_id",
        "run_input",
        "discovery",
        "selection",
        "paper_results",
    } <= set(AggregatePaperReportBlock.Input.model_fields)


@pytest.mark.asyncio
async def test_blocks_join_persist_and_aggregate_through_real_files(
    tmp_path: Path,
) -> None:
    paper = _paper("2503.00001")
    selection = SelectionResult(
        paper_tasks=[paper],
        skipped_no_arxiv_link=2,
        skipped_topic_mismatch=1,
    )
    persist = PersistPaperResultsBlock(output_root=tmp_path)
    persist_input = persist.Input(
        run_id="block-run",
        selection=selection,
        analyses=[_analysis_result(paper)],
        likes_results=[_likes_result(paper, 9)],
    )
    persisted = [item async for item in persist.run(persist_input)]

    aggregate = AggregatePaperReportBlock(output_root=tmp_path)
    aggregate_input = aggregate.Input(
        run_id="block-run",
        run_input=_manifest("block-run").input,
        discovery=DiscoveryResult(
            status=RunStatus.COMPLETED,
            papers=[
                PaperSeed.model_validate(
                    paper.model_dump(exclude={"paper_key", "arxiv_id", "questions"})
                )
            ],
            counts=DiscoveryCounts(
                raw_count=4,
                unique_count=4,
                duplicate_count=0,
                failed_page_count=0,
            ),
        ),
        selection=selection,
        paper_results=persisted[0][1],
        discovered_page_count=3,
    )
    aggregated = [item async for item in aggregate.run(aggregate_input)]

    assert persisted[0][0] == "paper_results"
    assert aggregated[0][0] == "manifest"
    assert aggregated[0][1].status is RunStatus.COMPLETED
    output = dict(aggregated)
    assert Path(output["manifest_path"]).is_file()
    assert Path(output["summary_path"]).is_file()


def _paper(arxiv_id: str) -> PaperTask:
    return PaperTask(
        conference="CVPR",
        year=2025,
        title=f"Paper {arxiv_id}",
        authors=["A. Author"],
        detail_url=f"https://openaccess.thecvf.com/{arxiv_id.replace('/', '-')}",
        pdf_url=f"https://openaccess.thecvf.com/{arxiv_id.replace('/', '-')}.pdf",
        arxiv_url=f"https://arxiv.org/abs/{arxiv_id}",
        arxiv_id=arxiv_id,
        paper_key=f"arxiv:{arxiv_id}",
        conference_day="2025-06-13",
        questions=["What is new?"],
    )


def _analysis_result(paper: PaperTask) -> AnalysisResult:
    return AnalysisResult(
        paper_key=paper.paper_key,
        status=AnalysisStatus.SUCCESS,
        analysis=PaperAnalysis(
            paper_key=paper.paper_key,
            research_problem="A problem [page 1]",
            main_contributions=["A contribution [page 1]"],
            method_summary="A method [page 2]",
            key_results=["A result [page 3]"],
            source_references=["page 1", "page 2", "page 3"],
        ),
    )


def _likes_result(paper: PaperTask, likes: int) -> LikesResult:
    return LikesResult(
        paper_key=paper.paper_key,
        arxiv_id=paper.arxiv_id,
        likes=likes,
        raw_text=f"{likes} Likes",
        status=ResultStatus.SUCCESS,
    )


def _paper_result(paper: PaperTask, likes: int) -> PaperResult:
    return PaperResult.from_parts(
        paper,
        _likes_result(paper, likes),
        _analysis_result(paper),
    )


def _manifest(run_id: str) -> RunManifest:
    return RunManifest(
        run_id=run_id,
        status=RunStatus.RUNNING,
        input=ConferenceRunInput(
            topics=["vision"],
            paper_questions=["What is new?"],
        ),
        started_at=datetime(2026, 7, 19, tzinfo=UTC),
        discovered_page_count=3,
        counts=RunCounts(
            discovered=10,
            skipped=8,
            selected=2,
            likes_success=0,
            likes_failed=0,
            analysis_success=0,
            analysis_failed=0,
            completed=0,
            partial=0,
            failed=0,
        ),
    )
