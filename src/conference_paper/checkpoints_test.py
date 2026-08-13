from pathlib import Path

import pytest

from backend.blocks.conference_paper.checkpoints import JsonlCheckpoint
from backend.blocks.conference_paper.models import (
    AnalysisResult,
    AnalysisStatus,
)


@pytest.fixture(scope="session", autouse=True)
def graph_cleanup() -> None:
    return None


@pytest.mark.asyncio
async def test_checkpoint_appends_and_reloads_latest_paper_result(
    tmp_path: Path,
) -> None:
    checkpoint = JsonlCheckpoint(
        "cvpr-2026-full",
        "analysis-checkpoint.jsonl",
        AnalysisResult,
        lambda result: result.paper_key,
        output_root=tmp_path,
    )
    failed = AnalysisResult(
        paper_key="arxiv:2601.00001",
        status=AnalysisStatus.FAILED,
        error_code="PAPER_ANALYSIS_FAILED",
    )
    success = AnalysisResult(
        paper_key="arxiv:2601.00001",
        status=AnalysisStatus.SUCCESS,
        analysis={
            "paper_key": "arxiv:2601.00001",
            "research_problem": "Problem",
            "method_summary": "Complete answer",
            "raw_answer": "Complete answer",
        },
        analysis_mode="mcp_qa_raw",
        questions=["What is new?"],
    )

    await checkpoint.append(failed)
    await checkpoint.append(success)

    loaded = checkpoint.load()
    assert loaded[success.paper_key] == success
    assert len(checkpoint.path.read_text().splitlines()) == 2
