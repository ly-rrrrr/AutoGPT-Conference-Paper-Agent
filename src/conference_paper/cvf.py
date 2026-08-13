import asyncio
import re
from collections.abc import Awaitable, Callable
from html.parser import HTMLParser
from typing import Literal
from urllib.parse import urlparse

import aiohttp
from pydantic import BaseModel, model_validator

from backend.blocks._base import (
    Block,
    BlockCategory,
    BlockOutput,
    BlockSchemaInput,
    BlockSchemaOutput,
)
from backend.blocks.conference_paper.models import (
    ConferenceYear,
    DiscoveryCounts,
    DiscoveryResult,
    PageFailure,
    PaperSeed,
    RejectedPaperSeed,
    RunStatus,
)
from backend.blocks.conference_paper.urls import (
    ARXIV_HOSTS,
    CVF_HOSTS,
    parse_arxiv_id,
    require_https_host,
    resolve_cvf_url,
)
from backend.data.model import SchemaField

CVPR_INDEX_TEMPLATE = "https://openaccess.thecvf.com/CVPR{year}"
CVPR_INDEX = CVPR_INDEX_TEMPLATE.format(year=2026)
HtmlFetcher = Callable[[str], Awaitable[str]]
FETCH_RETRY_DELAYS = (1.0, 2.0)


class DayParseResult(BaseModel):
    papers: list[PaperSeed]
    rejected_records: list[RejectedPaperSeed]
    raw_count: int


class DayFetchResult(BaseModel):
    position: int
    url: str
    html: str | None = None
    error_code: Literal["DAY_PAGE_UNAVAILABLE"] | None = None

    @model_validator(mode="after")
    def validate_payload(self):
        if (self.html is None) == (self.error_code is None):
            raise ValueError("exactly one of html or error_code is required")
        return self


class DiscoverCVFPapersBlock(Block):
    class Input(BlockSchemaInput):
        conference: Literal["CVPR"] = SchemaField(
            default="CVPR", description="Conference name"
        )
        year: ConferenceYear = SchemaField(default=2026, description="Conference year")
        conference_index_url: str | None = SchemaField(
            default=None,
            description="Optional official CVF index override; derived from year by default",
        )

    class Output(BlockSchemaOutput):
        discovery: DiscoveryResult = SchemaField(
            description="Discovered and validated CVF paper records"
        )

    def __init__(self):
        super().__init__(
            id="f2b5d8a1-6c34-4e97-8b12-0a9d7c3e5f41",
            description="Discovers CVPR papers from the official CVF repository.",
            categories={BlockCategory.SEARCH},
            input_schema=DiscoverCVFPapersBlock.Input,
            output_schema=DiscoverCVFPapersBlock.Output,
        )

    async def run(self, input_data: Input, **kwargs) -> BlockOutput:
        index_url = input_data.conference_index_url or cvpr_index_url(input_data.year)
        discovery = await discover_papers(index_url)
        yield "discovery", discovery


def cvpr_index_url(year: ConferenceYear) -> str:
    return CVPR_INDEX_TEMPLATE.format(year=year)


def discover_day_urls(index_html: str, index_url: str) -> list[str]:
    require_https_host(index_url, CVF_HOSTS, "INVALID_CVF_URL")
    parser = _DayLinkParser()
    parser.feed(index_html)
    urls: list[str] = []
    for href, text in parser.links:
        if re.fullmatch(r"Day\s+\d+:\s+\d{4}-\d{2}-\d{2}", text) is None:
            continue
        resolved = resolve_cvf_url(index_url, href)
        if resolved not in urls:
            urls.append(resolved)
    if not urls:
        raise ValueError("NO_CONFERENCE_DAYS")
    return urls


def parse_day_page(html: str, page_url: str, conference_day: str) -> DayParseResult:
    require_https_host(page_url, CVF_HOSTS, "INVALID_CVF_URL")
    parser = _PaperParser()
    parser.feed(html)
    records = parser.finish()
    if not records:
        raise ValueError("EMPTY_PAPER_LIST")
    papers: list[PaperSeed] = []
    rejected: list[RejectedPaperSeed] = []
    for record in records:
        paper = _build_paper(record, page_url, conference_day)
        if paper is None:
            rejected.append(
                RejectedPaperSeed(
                    title=record.title.strip() or None,
                    detail_url=_safe_detail_url(page_url, record.detail_href),
                )
            )
        else:
            papers.append(paper)
    return DayParseResult(
        papers=papers,
        rejected_records=rejected,
        raw_count=len(records),
    )


def merge_day_results(
    results: list[DayParseResult],
    page_failures: list[PageFailure] | None = None,
) -> DiscoveryResult:
    failures = page_failures or []
    papers: list[PaperSeed] = []
    seen: set[str] = set()
    duplicate_count = 0
    for paper in (paper for result in results for paper in result.papers):
        if paper.detail_url in seen:
            duplicate_count += 1
            continue
        seen.add(paper.detail_url)
        papers.append(paper)
    rejected = [record for result in results for record in result.rejected_records]
    status = RunStatus.PARTIAL if failures or rejected else RunStatus.COMPLETED
    return DiscoveryResult(
        status=status,
        papers=papers,
        counts=DiscoveryCounts(
            raw_count=sum(result.raw_count for result in results),
            unique_count=len(papers),
            duplicate_count=duplicate_count,
            failed_page_count=len(failures),
        ),
        page_failures=failures,
        rejected_records=rejected,
    )


async def fetch_day_pages(
    day_urls: list[str],
    fetcher: HtmlFetcher,
) -> list[DayFetchResult]:
    semaphore = asyncio.Semaphore(3)

    async def fetch(position: int, url: str) -> DayFetchResult:
        require_https_host(url, CVF_HOSTS, "INVALID_CVF_URL")
        async with semaphore:
            for delay in (*FETCH_RETRY_DELAYS, None):
                try:
                    return DayFetchResult(
                        position=position,
                        url=url,
                        html=await fetcher(url),
                    )
                except (aiohttp.ClientError, asyncio.TimeoutError):
                    if delay is None:
                        return DayFetchResult(
                            position=position,
                            url=url,
                            error_code="DAY_PAGE_UNAVAILABLE",
                        )
                    await asyncio.sleep(delay)

    fetched = await asyncio.gather(
        *(fetch(position, url) for position, url in enumerate(day_urls))
    )
    return sorted(fetched, key=lambda result: result.position)


async def discover_papers(
    index_url: str = CVPR_INDEX,
    *,
    fetcher: HtmlFetcher | None = None,
) -> DiscoveryResult:
    require_https_host(index_url, CVF_HOSTS, "INVALID_CVF_URL")
    if fetcher is None:
        timeout = aiohttp.ClientTimeout(total=20)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            return await _discover_with_fetcher(index_url, _SessionFetcher(session))
    return await _discover_with_fetcher(index_url, fetcher)


class _SessionFetcher:
    def __init__(self, session: aiohttp.ClientSession):
        self.session = session

    async def __call__(self, url: str) -> str:
        timeout = aiohttp.ClientTimeout(total=20)
        async with self.session.get(url, timeout=timeout) as response:
            response.raise_for_status()
            return await response.text()


class _RawPaperRecord(BaseModel):
    title: str = ""
    detail_href: str | None = None
    authors: list[str] = []
    links: list[tuple[str, str]] = []


class _DayLinkParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links: list[tuple[str, str]] = []
        self._href: str | None = None
        self._text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]):
        if tag == "a":
            self._href = dict(attrs).get("href")
            self._text = []

    def handle_data(self, data: str):
        if self._href is not None:
            self._text.append(data)

    def handle_endtag(self, tag: str):
        if tag == "a" and self._href is not None:
            self.links.append((self._href, " ".join(self._text).strip()))
            self._href = None


class _PaperParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.records: list[_RawPaperRecord] = []
        self.record: _RawPaperRecord | None = None
        self.in_title = False
        self.in_author_form = False
        self.href: str | None = None
        self.link_text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]):
        values = dict(attrs)
        if tag == "dt" and "ptitle" in (values.get("class") or "").split():
            self._save_record()
            self.record = _RawPaperRecord()
            self.in_title = True
        elif self.record is not None and tag == "form":
            self.in_author_form = "authsearch" in (values.get("class") or "").split()
        elif self.record is not None and self.in_author_form and tag == "input":
            author = values.get("value")
            if values.get("name") == "query_author" and author:
                self.record.authors.append(author)
        if self.record is not None and tag == "a":
            self.href = values.get("href")
            self.link_text = []
            if self.in_title:
                self.record.detail_href = self.href

    def handle_data(self, data: str):
        if self.record is not None and self.in_title:
            self.record.title += data
        if self.href is not None:
            self.link_text.append(data)

    def handle_endtag(self, tag: str):
        if tag == "dt":
            self.in_title = False
        elif tag == "form":
            self.in_author_form = False
        elif tag == "a" and self.record is not None and self.href is not None:
            self.record.links.append((self.href, "".join(self.link_text).strip()))
            self.href = None

    def finish(self) -> list[_RawPaperRecord]:
        self._save_record()
        return self.records

    def _save_record(self):
        if self.record is not None:
            self.records.append(self.record)
            self.record = None


async def _discover_with_fetcher(index_url: str, fetcher: HtmlFetcher):
    for delay in (*FETCH_RETRY_DELAYS, None):
        try:
            index_html = await fetcher(index_url)
            break
        except (aiohttp.ClientError, asyncio.TimeoutError) as error:
            if delay is None:
                raise ValueError("CONFERENCE_INDEX_UNAVAILABLE") from error
            await asyncio.sleep(delay)
    day_urls = discover_day_urls(index_html, index_url)
    fetched = await fetch_day_pages(day_urls, fetcher)
    parsed: list[DayParseResult] = []
    failures: list[PageFailure] = []
    for result in fetched:
        if result.error_code is not None:
            failures.append(PageFailure(url=result.url, error_code=result.error_code))
            continue
        try:
            parsed.append(
                parse_day_page(
                    result.html or "", result.url, f"Day {result.position + 1}"
                )
            )
        except ValueError as error:
            failures.append(PageFailure(url=result.url, error_code=str(error)))
    return merge_day_results(parsed, failures)


def _build_paper(
    record: _RawPaperRecord,
    page_url: str,
    conference_day: str,
) -> PaperSeed | None:
    title = " ".join(record.title.split())
    if not title or record.detail_href is None:
        return None
    links = {text.casefold(): href for href, text in record.links}
    pdf_href = links.get("pdf")
    if pdf_href is None:
        return None
    try:
        detail_url = resolve_cvf_url(page_url, record.detail_href)
        pdf_url = resolve_cvf_url(page_url, pdf_href)
    except ValueError:
        return None
    return PaperSeed(
        conference="CVPR",
        year=_conference_year(page_url),
        title=title,
        authors=list(dict.fromkeys(record.authors)),
        detail_url=detail_url,
        pdf_url=pdf_url,
        arxiv_url=_normalize_cvf_arxiv(links.get("arxiv")),
        conference_day=conference_day,
    )


def _conference_year(page_url: str) -> ConferenceYear:
    match = re.search(r"/CVPR(2025|2026)(?:\?|/|$)", page_url)
    if match is None:
        raise ValueError("UNSUPPORTED_CONFERENCE_YEAR")
    return 2025 if match.group(1) == "2025" else 2026


def _normalize_cvf_arxiv(href: str | None) -> str | None:
    if href is None:
        return None
    parsed = urlparse(href)
    if (
        parsed.scheme not in {"http", "https"}
        or parsed.hostname not in ARXIV_HOSTS
        or parsed.username is not None
        or parsed.password is not None
    ):
        return None
    secure = parsed._replace(scheme="https", netloc=parsed.hostname or "").geturl()
    try:
        parse_arxiv_id(secure)
    except ValueError:
        return None
    return secure


def _safe_detail_url(page_url: str, href: str | None) -> str | None:
    if href is None:
        return None
    try:
        return resolve_cvf_url(page_url, href)
    except ValueError:
        return None
