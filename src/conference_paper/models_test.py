from copy import deepcopy

import pytest
from pydantic import ValidationError

from backend.blocks.conference_paper.models import (
    AnalysisResult,
    AnalysisStatus,
    ConferenceRunInput,
    LikesResult,
    PaperAnalysis,
    PaperResult,
    PaperSeed,
    PaperStatus,
    PaperTask,
)


@pytest.fixture(scope="session", autouse=True)
def graph_cleanup() -> None:
    return None


def valid_task() -> dict:
    return {
        "paper_key": "arxiv:2503.00001",
        "conference": "CVPR",
        "year": 2025,
        "title": "A Contract Test Paper",
        "authors": ["Ada Lovelace"],
        "detail_url": "https://example.test/paper",
        "pdf_url": "https://example.test/paper.pdf",
        "arxiv_url": "https://arxiv.org/abs/2503.00001",
        "arxiv_id": "2503.00001",
        "questions": ["What problem does the paper solve?"],
        "conference_day": "Day 1",
    }


def successful_analysis(paper_key: str = "arxiv:2503.00001") -> AnalysisResult:
    return AnalysisResult(
        paper_key=paper_key,
        status=AnalysisStatus.SUCCESS,
        analysis=PaperAnalysis(
            paper_key=paper_key,
            research_problem="Problem",
            main_contributions=["Contribution"],
            method_summary="Method",
            source_references=["page 1"],
        ),
    )


def successful_likes(
    paper_key: str = "arxiv:2503.00001",
    arxiv_id: str = "2503.00001",
) -> LikesResult:
    return LikesResult(
        paper_key=paper_key,
        arxiv_id=arxiv_id,
        likes=1_080,
        raw_text="1,080 Likes",
        status="SUCCESS",
    )


def failed_analysis(paper_key: str = "arxiv:2503.00001") -> AnalysisResult:
    return AnalysisResult(
        paper_key=paper_key,
        status="FAILED",
        error_code="ANALYSIS_FAILED",
    )


def failed_likes() -> LikesResult:
    return LikesResult(
        paper_key="arxiv:2503.00001",
        arxiv_id="2503.00001",
        status="FAILED",
        error_code="LIKES_ELEMENT_NOT_FOUND",
    )


@pytest.mark.parametrize(
    "overrides",
    [
        {"topics": ["  "]},
        {"paper_questions": []},
        {"paper_questions": [f"Question {index}" for index in range(11)]},
        {"max_papers": -1},
        {"max_papers": 10_001},
        {"analysis_concurrency": 0},
        {"analysis_concurrency": 4},
    ],
)
def test_run_input_rejects_invalid_boundaries(overrides: dict):
    payload = {
        "topics": ["vision"],
        "paper_questions": ["Question"],
        **overrides,
    }
    with pytest.raises(ValidationError):
        ConferenceRunInput.model_validate(payload)


def test_run_input_strips_topics_and_questions():
    result = ConferenceRunInput(
        topics=["  vision  "],
        paper_questions=["  What changed?  "],
    )

    assert result.topics == ["vision"]
    assert result.paper_questions == ["What changed?"]


def test_run_input_supports_cvpr_2026_full_selection():
    result = ConferenceRunInput(
        year=2026,
        topics=[],
        max_papers=0,
        paper_questions=["What changed?"],
    )

    assert result.year == 2026
    assert result.topics == []
    assert result.max_papers == 0


def test_paper_seed_strips_required_strings_and_authors():
    payload = valid_task()
    seed = PaperSeed.model_validate(
        {
            key: value
            for key, value in payload.items()
            if key not in {"paper_key", "arxiv_id", "questions"}
        }
        | {"title": "  Paper  ", "authors": ["  Ada  "]}
    )

    assert seed.title == "Paper"
    assert seed.authors == ["Ada"]


def test_paper_key_must_match_arxiv_id():
    payload = valid_task()
    payload["paper_key"] = "arxiv:2503.99999"

    with pytest.raises(ValidationError, match="paper_key"):
        PaperTask.model_validate(payload)


@pytest.mark.parametrize(
    ("raw_text", "likes"),
    [("0 Likes", 0), ("1 Like", 1), ("1,080 Likes", 1_080)],
)
def test_likes_success_accepts_full_control_text(raw_text: str, likes: int):
    result = LikesResult(
        paper_key="arxiv:2503.00001",
        arxiv_id="2503.00001",
        likes=likes,
        raw_text=raw_text,
        status="SUCCESS",
    )

    assert result.likes == likes


@pytest.mark.parametrize(
    "payload",
    [
        {"likes": 1_080, "raw_text": "1080", "error_code": None},
        {"likes": 12, "raw_text": "11 Likes", "error_code": None},
        {"likes": 12, "raw_text": "12 Likes", "error_code": "STALE_ERROR"},
    ],
)
def test_likes_success_rejects_invalid_payload(payload: dict):
    with pytest.raises(ValidationError):
        LikesResult(
            paper_key="arxiv:2503.00001",
            arxiv_id="2503.00001",
            status="SUCCESS",
            **payload,
        )


@pytest.mark.parametrize(
    "payload",
    [
        {"likes": 10, "raw_text": None, "error_code": "FAILED"},
        {"likes": None, "raw_text": "10 Likes", "error_code": "FAILED"},
        {"likes": None, "raw_text": None, "error_code": None},
    ],
)
def test_likes_failure_requires_null_values_and_error(payload: dict):
    with pytest.raises(ValidationError):
        LikesResult(
            paper_key="arxiv:2503.00001",
            arxiv_id="2503.00001",
            status="FAILED",
            **payload,
        )


def test_likes_result_forbids_observed_at():
    with pytest.raises(ValidationError, match="observed_at"):
        LikesResult(
            paper_key="arxiv:2503.00001",
            arxiv_id="2503.00001",
            likes=83,
            raw_text="83 Likes",
            status="SUCCESS",
            observed_at="2025-01-01T00:00:00Z",
        )


@pytest.mark.parametrize(
    "payload",
    [
        {
            "status": "SUCCESS",
            "analysis": PaperAnalysis(
                paper_key="arxiv:2503.99999",
                research_problem="Problem",
                method_summary="Method",
            ),
            "error_code": None,
        },
        {"status": "SUCCESS", "analysis": None, "error_code": None},
        {
            "status": "SUCCESS",
            "analysis": successful_analysis().analysis,
            "error_code": "OLD",
        },
        {
            "status": "FAILED",
            "analysis": successful_analysis().analysis,
            "error_code": "FAILED",
        },
        {"status": "FAILED", "analysis": None, "error_code": None},
    ],
)
def test_analysis_result_enforces_status_payload(payload: dict):
    with pytest.raises(ValidationError):
        AnalysisResult(paper_key="arxiv:2503.00001", **payload)


@pytest.mark.parametrize(
    ("likes", "analysis", "expected_status"),
    [
        (successful_likes(), successful_analysis(), PaperStatus.COMPLETED),
        (successful_likes(), failed_analysis(), PaperStatus.PARTIAL),
        (failed_likes(), successful_analysis(), PaperStatus.PARTIAL),
        (failed_likes(), failed_analysis(), PaperStatus.FAILED),
    ],
)
def test_paper_result_uses_three_state_outcome(
    likes: LikesResult,
    analysis: AnalysisResult,
    expected_status: PaperStatus,
):
    task = PaperTask.model_validate(valid_task())

    result = PaperResult.from_parts(task, likes, analysis)

    assert result.status is expected_status
    assert result.analysis is analysis.analysis


@pytest.mark.parametrize(
    ("likes", "analysis"),
    [
        (successful_likes(paper_key="arxiv:2503.99999"), successful_analysis()),
        (successful_likes(arxiv_id="2503.99999"), successful_analysis()),
        (successful_likes(), successful_analysis("arxiv:2503.99999")),
        (successful_likes(), failed_analysis("arxiv:2503.99999")),
    ],
)
def test_paper_result_rejects_branch_identity_mismatch(
    likes: LikesResult,
    analysis: AnalysisResult,
):
    task = PaperTask.model_validate(valid_task())

    with pytest.raises(ValueError):
        PaperResult.from_parts(task, likes, analysis)


def test_analysis_failure_does_not_create_placeholder():
    task = PaperTask.model_validate(valid_task())

    result = PaperResult.from_parts(task, successful_likes(), failed_analysis())

    assert result.analysis is None


def test_models_do_not_share_mutable_defaults():
    payload = valid_task()
    first_task = PaperTask.model_validate(payload)
    second_task = PaperTask.model_validate(deepcopy(payload))
    first_task.authors.append("Grace Hopper")

    first_analysis = PaperAnalysis(
        paper_key=first_task.paper_key,
        research_problem="Problem",
        method_summary="Method",
    )
    second_analysis = PaperAnalysis(
        paper_key=second_task.paper_key,
        research_problem="Problem",
        method_summary="Method",
    )
    first_analysis.warnings.append("warning")

    assert second_task.authors == ["Ada Lovelace"]
    assert second_analysis.warnings == []
