import asyncio
from pathlib import Path

import aiohttp
import pytest

from backend.blocks.conference_paper.cvf import (
    CVPR_INDEX,
    DayFetchResult,
    DiscoverCVFPapersBlock,
    discover_day_urls,
    discover_papers,
    fetch_day_pages,
    merge_day_results,
    parse_day_page,
)
from backend.blocks.conference_paper.models import RunStatus

FIXTURE_DIR = (
    Path(__file__).parents[5]
    / "projects"
    / "conference-paper-research-agent"
    / "fixtures"
    / "cvf"
)
DAY_URLS = [
    "https://openaccess.thecvf.com/CVPR2025?day=2025-06-13",
    "https://openaccess.thecvf.com/CVPR2025?day=2025-06-14",
    "https://openaccess.thecvf.com/CVPR2025?day=2025-06-15",
]


@pytest.fixture(scope="session", autouse=True)
def graph_cleanup() -> None:
    return None


@pytest.fixture
def index_html() -> str:
    return (FIXTURE_DIR / "index.html").read_text(encoding="utf-8")


@pytest.fixture
def day_one_html() -> str:
    return (FIXTURE_DIR / "day-1.html").read_text(encoding="utf-8")


@pytest.fixture
def day_two_html() -> str:
    return (FIXTURE_DIR / "day-2.html").read_text(encoding="utf-8")


@pytest.fixture
def day_three_html() -> str:
    return (FIXTURE_DIR / "day-3.html").read_text(encoding="utf-8")


def test_index_discovers_three_unique_day_urls_in_page_order(index_html: str):
    assert discover_day_urls(index_html, CVPR_INDEX) == DAY_URLS


def test_index_rejects_untrusted_day_link(index_html: str):
    unsafe = index_html.replace(
        "/CVPR2025?day=2025-06-14",
        "https://openaccess.thecvf.com.evil.example/CVPR2025?day=2025-06-14",
    )

    with pytest.raises(ValueError, match="^INVALID_CVF_URL$"):
        discover_day_urls(unsafe, CVPR_INDEX)


def test_index_without_day_links_fails_explicitly():
    with pytest.raises(ValueError, match="^NO_CONFERENCE_DAYS$"):
        discover_day_urls("<html><body>No schedule</body></html>", CVPR_INDEX)


def test_day_parser_reads_real_fields_and_optional_arxiv(day_one_html: str):
    parsed = parse_day_page(day_one_html, DAY_URLS[0], "Day 1")

    assert parsed.raw_count == 2
    assert parsed.papers[0].title == "Towards Source-Free Machine Unlearning"
    assert parsed.papers[0].authors[:2] == ["Sk Miraj Ahmed", "Umit Yigit Basaran"]
    assert parsed.papers[0].arxiv_url is None
    assert parsed.papers[1].title.startswith("Uni4D:")
    assert parsed.papers[1].detail_url == (
        "https://openaccess.thecvf.com/content/CVPR2025/html/"
        "Yao_Uni4D_Unifying_Visual_Foundation_Models_for_4D_Modeling_from_a_"
        "CVPR_2025_paper.html"
    )
    assert parsed.papers[1].pdf_url.startswith(
        "https://openaccess.thecvf.com/content/CVPR2025/papers/"
    )
    assert parsed.papers[1].arxiv_url == "https://arxiv.org/abs/2503.21761"


def test_merge_deduplicates_copied_real_record_across_pages(
    day_one_html: str,
    day_two_html: str,
):
    first_record_start = day_one_html.index('<dt class="ptitle">')
    second_record_start = day_one_html.index(
        '<dt class="ptitle">', first_record_start + 1
    )
    copied_for_dedup_scenario = day_one_html[first_record_start:second_record_start]
    second_page_input = day_two_html + copied_for_dedup_scenario

    merged = merge_day_results(
        [
            parse_day_page(day_one_html, DAY_URLS[0], "Day 1"),
            parse_day_page(second_page_input, DAY_URLS[1], "Day 2"),
        ]
    )

    assert merged.counts.raw_count == 4
    assert merged.counts.unique_count == 3
    assert merged.counts.duplicate_count == 1


def test_invalid_real_record_is_quarantined(day_one_html: str):
    detail_anchor = (
        '<a href="/content/CVPR2025/html/'
        'Ahmed_Towards_Source-Free_Machine_Unlearning_CVPR_2025_paper.html">'
        "Towards Source-Free Machine Unlearning</a>"
    )
    missing_detail_input = day_one_html.replace(
        detail_anchor,
        "Towards Source-Free Machine Unlearning",
    )

    parsed = parse_day_page(missing_detail_input, DAY_URLS[0], "Day 1")

    assert len(parsed.papers) == 1
    assert parsed.rejected_records[0].title == "Towards Source-Free Machine Unlearning"
    assert parsed.rejected_records[0].error_code == "INVALID_PAPER_RECORD"


def test_empty_day_page_is_not_a_successful_empty_result():
    with pytest.raises(ValueError, match="^EMPTY_PAPER_LIST$"):
        parse_day_page("<html><body></body></html>", DAY_URLS[0], "Day 1")


async def test_fetch_day_pages_limits_concurrency_to_three(day_two_html: str):
    active = 0
    maximum_active = 0

    async def observable_fetcher(url: str) -> str:
        nonlocal active, maximum_active
        active += 1
        maximum_active = max(maximum_active, active)
        await asyncio.sleep(0.01)
        active -= 1
        return day_two_html

    urls = [f"{CVPR_INDEX}?day=2025-06-{day:02d}" for day in range(13, 19)]
    results = await fetch_day_pages(urls, observable_fetcher)

    assert maximum_active == 3
    assert [result.position for result in results] == list(range(6))
    assert all(result.error_code is None for result in results)


async def test_one_failed_day_marks_discovery_partial(
    index_html: str,
    day_one_html: str,
    day_three_html: str,
):
    pages = {
        CVPR_INDEX: index_html,
        DAY_URLS[0]: day_one_html,
        DAY_URLS[2]: day_three_html,
    }

    async def failing_day_fetcher(url: str) -> str:
        if url == DAY_URLS[1]:
            raise aiohttp.ClientConnectionError()
        return pages[url]

    result = await discover_papers(CVPR_INDEX, fetcher=failing_day_fetcher)

    assert result.status is RunStatus.PARTIAL
    assert result.counts.raw_count == 3
    assert result.counts.unique_count == 3
    assert result.counts.failed_page_count == 1
    assert result.page_failures[0].error_code == "DAY_PAGE_UNAVAILABLE"


async def test_unavailable_index_fails_the_batch():
    async def unavailable_fetcher(url: str) -> str:
        raise asyncio.TimeoutError()

    with pytest.raises(ValueError, match="^CONFERENCE_INDEX_UNAVAILABLE$"):
        await discover_papers(CVPR_INDEX, fetcher=unavailable_fetcher)


def test_day_fetch_result_requires_stable_error_shape():
    failed = DayFetchResult(
        position=1,
        url=DAY_URLS[1],
        error_code="DAY_PAGE_UNAVAILABLE",
    )

    assert failed.html is None


def test_discover_block_uses_fixed_v4_uuid_and_schema():
    block = DiscoverCVFPapersBlock()

    assert block.id == "f2b5d8a1-6c34-4e97-8b12-0a9d7c3e5f41"
    assert block.input_schema.model_fields["conference"].default == "CVPR"
    assert block.input_schema.model_fields["year"].default == 2026
    assert "discovery" in block.output_schema.model_fields
