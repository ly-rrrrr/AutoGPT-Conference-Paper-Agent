from pathlib import Path

import pytest
from pydantic import ValidationError

from backend.blocks.conference_paper.cvf import merge_day_results, parse_day_page
from backend.blocks.conference_paper.models import DiscoveryResult
from backend.blocks.conference_paper.selection import (
    SelectConferencePapersBlock,
    normalize_title,
    select_papers,
)

FIXTURE_DIR = (
    Path(__file__).parents[5]
    / "projects"
    / "conference-paper-research-agent"
    / "fixtures"
    / "cvf"
)
DAY_ONE_URL = "https://openaccess.thecvf.com/CVPR2025?day=2025-06-13"


@pytest.fixture(scope="session", autouse=True)
def graph_cleanup() -> None:
    return None


@pytest.fixture
def discovery() -> DiscoveryResult:
    html = (FIXTURE_DIR / "day-1.html").read_text(encoding="utf-8")
    return merge_day_results([parse_day_page(html, DAY_ONE_URL, "Day 1")])


def test_selects_real_uni4d_paper_and_preserves_questions(
    discovery: DiscoveryResult,
):
    questions = [
        "What problem does the paper solve?",
        "What are the main contributions?",
    ]

    result = select_papers(discovery, ["4D"], questions, 20)

    assert len(result.paper_tasks) == 1
    task = result.paper_tasks[0]
    seed = next(paper for paper in discovery.papers if paper.title.startswith("Uni4D:"))
    assert task.paper_key == "arxiv:2503.21761"
    assert task.arxiv_id == "2503.21761"
    assert task.questions == questions
    assert task.title == seed.title
    assert task.authors == seed.authors
    assert task.detail_url == seed.detail_url
    assert task.pdf_url == seed.pdf_url
    assert task.conference_day == seed.conference_day


def test_counts_real_paper_without_arxiv_before_topic_filter(
    discovery: DiscoveryResult,
):
    result = select_papers(
        discovery,
        ["Towards Source-Free Machine Unlearning"],
        ["What problem does the paper solve?"],
        20,
    )

    assert result.paper_tasks == []
    assert result.skipped_no_arxiv_link == 1
    assert result.skipped_topic_mismatch == 1


def test_normalizes_case_and_whitespace_and_is_stable_at_limit(
    discovery: DiscoveryResult,
):
    reversed_discovery = discovery.model_copy(
        update={"papers": list(reversed(discovery.papers))}
    )
    questions = ["What problem does the paper solve?"]

    first = select_papers(discovery, ["  4D\n  MODELING  "], questions, 1)
    second = select_papers(reversed_discovery, ["  4d modeling  "], questions, 1)

    assert normalize_title("  Uni4D:\n UNIFYING\tModels ") == ("uni4d: unifying models")
    assert [task.paper_key for task in first.paper_tasks] == ["arxiv:2503.21761"]
    assert first.paper_tasks == second.paper_tasks
    assert len(first.paper_tasks) == 1


def test_rejects_malicious_arxiv_url_without_title_search(
    discovery: DiscoveryResult,
):
    uni4d = next(
        paper for paper in discovery.papers if paper.title.startswith("Uni4D:")
    )
    malicious = uni4d.model_copy(
        update={"arxiv_url": "https://arxiv.org.evil.example/abs/2503.21761"}
    )
    unsafe_discovery = discovery.model_copy(update={"papers": [malicious]})

    result = select_papers(
        unsafe_discovery,
        ["4D"],
        ["What problem does the paper solve?"],
        20,
    )

    assert result.paper_tasks == []
    assert result.rejected[0].title == uni4d.title
    assert result.rejected[0].error_code == "INVALID_ARXIV_URL"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("max_papers", 10_001),
        ("topics", ["  "]),
        ("paper_questions", []),
        ("paper_questions", ["\n"]),
    ],
)
def test_block_input_rejects_out_of_range_or_blank_values(
    discovery: DiscoveryResult,
    field: str,
    value: object,
):
    payload = {
        "discovery": discovery,
        "topics": ["4D"],
        "paper_questions": ["What problem does the paper solve?"],
        "max_papers": 20,
    }
    payload[field] = value

    with pytest.raises(ValidationError):
        SelectConferencePapersBlock.Input.model_validate(payload)


async def test_block_uses_fixed_uuid_and_only_yields_selection(
    discovery: DiscoveryResult,
):
    block = SelectConferencePapersBlock()
    input_data = block.input_schema(
        discovery=discovery,
        topics=["4D"],
        paper_questions=["What problem does the paper solve?"],
        max_papers=1,
    )

    outputs = [output async for output in block.run(input_data)]

    assert block.id == "a8c7e1d2-5b64-4f90-9a31-2d6e8b4c7f05"
    assert [name for name, _ in outputs] == ["selection"]
    assert outputs[0][1].paper_tasks[0].paper_key == "arxiv:2503.21761"


def test_empty_topics_and_zero_limit_select_all_arxiv_papers(
    discovery: DiscoveryResult,
):
    result = select_papers(
        discovery,
        [],
        ["What problem does the paper solve?"],
        0,
    )

    assert len(result.paper_tasks) == 1
    assert result.skipped_topic_mismatch == 0
