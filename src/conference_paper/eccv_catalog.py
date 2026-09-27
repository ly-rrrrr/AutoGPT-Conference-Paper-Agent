import re
from dataclasses import dataclass, field
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse

SOURCE_URL = "https://eccv.ecva.net/Conferences/2026/AcceptedPapers"


@dataclass(frozen=True)
class CatalogPaper:
    paper_id: str
    title: str
    authors: list[str]
    detail_url: str
    topic: str = ""
    presentation: str = ""
    project_urls: list[str] = field(default_factory=list)
    conference: str = "ECCV"
    year: int = 2026


def clean(value: str) -> str:
    return " ".join(value.split())


class CatalogParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.rows = []
        self.row = None
        self.cell = None
        self.anchor = None
        self.in_author = False

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        if tag == "tr":
            self.row = []
        elif tag == "td" and self.row is not None:
            self.cell = {"text": [], "authors": [], "links": []}
        elif self.cell is not None:
            if tag == "a":
                self.anchor = {"href": attributes.get("href", ""), "text": []}
            elif tag == "i":
                self.in_author = True

    def handle_data(self, data):
        if self.cell is not None:
            self.cell["text"].append(data)
            if self.in_author:
                self.cell["authors"].append(data)
            if self.anchor is not None:
                self.anchor["text"].append(data)

    def handle_endtag(self, tag):
        if tag == "a" and self.cell is not None and self.anchor is not None:
            self.cell["links"].append(self.anchor)
            self.anchor = None
        elif tag == "i":
            self.in_author = False
        elif tag == "td" and self.cell is not None:
            self.row.append(self.cell)
            self.cell = None
            self.anchor = None
            self.in_author = False
        elif tag == "tr" and self.row is not None:
            if self.row:
                self.rows.append(self.row)
            self.row = None


def parse_catalog(html: str, statistics: dict | None = None) -> list[CatalogPaper]:
    parser = CatalogParser()
    parser.feed(html)
    papers = {}
    official_rows = 0
    for row in parser.rows:
        links = row[0]["links"]
        official = []
        for link in links:
            url = urljoin(SOURCE_URL, link["href"])
            parsed = urlparse(url)
            match = re.fullmatch(
                r"/virtual/2026/(?:poster|oral|spotlight)/(\d+)/?", parsed.path
            )
            if parsed.netloc == "eccv.ecva.net" and parsed.scheme == "https" and match:
                official.append((link, url, match[1]))
        if not official:
            continue
        official_rows += 1
        link, url, identifier = official[0]
        title = clean("".join(link["text"]))
        if not title:
            raise ValueError("Official paper has an empty title")
        authors = [
            clean(name)
            for name in re.split(r"[⋅·]", "".join(row[0]["authors"]))
            if clean(name)
        ]
        projects = [
            urljoin(SOURCE_URL, item["href"])
            for item in links
            if item is not link
            and urlparse(urljoin(SOURCE_URL, item["href"])).scheme == "https"
        ]
        paper = CatalogPaper(
            paper_id=f"eccv:2026:{identifier}",
            title=title,
            authors=authors,
            detail_url=url,
            topic=clean("".join(row[1]["text"])) if len(row) > 1 else "",
            presentation=clean("".join(row[2]["text"])) if len(row) > 2 else "",
            project_urls=list(dict.fromkeys(projects)),
        )
        previous = papers.get(paper.paper_id)
        if previous and (previous.title != title or previous.authors != authors):
            raise ValueError(f"Conflicting official ID: {paper.paper_id}")
        papers[paper.paper_id] = paper
    if not papers:
        raise ValueError("No official ECCV 2026 paper rows found")
    if statistics is not None:
        statistics.update(
            official_row_count=official_rows,
            duplicate_row_count=official_rows - len(papers),
            ignored_nonpaper_row_count=len(parser.rows) - official_rows,
        )
    return list(papers.values())
