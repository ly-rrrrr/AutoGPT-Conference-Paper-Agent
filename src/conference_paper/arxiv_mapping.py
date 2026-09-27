import re
import unicodedata
import xml.etree.ElementTree as ET
from dataclasses import asdict, dataclass
from difflib import SequenceMatcher
from urllib.parse import urlparse

from .eccv_catalog import CatalogPaper

MATCHER_VERSION = "exact-title-full-authors-v1"
ATOM = "{http://www.w3.org/2005/Atom}"
ARXIV = "{http://arxiv.org/schemas/atom}"


@dataclass(frozen=True)
class Candidate:
    arxiv_id: str
    title: str
    authors: list[str]
    abstract: str = ""
    published: str = ""
    comment: str = ""
    journal_ref: str = ""


def normalize(value: str) -> str:
    value = unicodedata.normalize("NFKC", value).casefold()
    return " ".join(re.findall(r"[^\W_]+", value, re.UNICODE))


def arxiv_id(url: str) -> str | None:
    parsed = urlparse(url)
    if parsed.netloc not in {
        "arxiv.org",
        "www.arxiv.org",
        "export.arxiv.org",
    } or parsed.scheme not in {"https", "http"}:
        return None
    match = re.fullmatch(
        r"/(?:abs|pdf)/(\d{4}\.\d{4,5}|[a-zA-Z-]+(?:\.[A-Z]{2})?/\d{7})(?:v\d+)?(?:\.pdf)?/?",
        parsed.path,
    )
    return match[1] if match else None


def parse_feed(xml: str) -> list[Candidate]:
    root = ET.fromstring(xml)
    if root.tag != ATOM + "feed":
        raise ValueError("Expected an arXiv Atom feed")
    candidates = {}
    for entry in root.findall(ATOM + "entry"):
        identifier = arxiv_id(entry.findtext(ATOM + "id", ""))
        title = " ".join(entry.findtext(ATOM + "title", "").split())
        if not identifier or not title:
            raise ValueError("Invalid arXiv entry or API error feed")
        authors = [
            " ".join(author.findtext(ATOM + "name", "").split())
            for author in entry.findall(ATOM + "author")
        ]
        candidates[identifier] = Candidate(
            identifier,
            title,
            authors,
            abstract=" ".join(entry.findtext(ATOM + "summary", "").split()),
            published=entry.findtext(ATOM + "published", ""),
            comment=entry.findtext(ARXIV + "comment", ""),
            journal_ref=entry.findtext(ARXIV + "journal_ref", ""),
        )
    return list(candidates.values())


def queries(paper: CatalogPaper) -> list[str]:
    words = normalize(paper.title).split()
    exact = 'ti:"' + " ".join(words) + '"'
    stopwords = {
        "a",
        "an",
        "the",
        "for",
        "of",
        "and",
        "in",
        "on",
        "with",
        "to",
        "via",
        "from",
        "by",
    }
    distinctive = sorted(set(words) - stopwords, key=lambda word: (-len(word), word))[
        :4
    ]
    broad = " AND ".join(f'ti:"{word}"' for word in distinctive)
    if paper.authors:
        surname = normalize(paper.authors[0]).split()
        if surname:
            broad += f' AND au:"{surname[-1]}"'
    return list(dict.fromkeys([exact, broad])) if broad else [exact]


def full_names(names: list[str]) -> set[str]:
    return {
        normalize(name)
        for name in names
        if len(normalize(name).split()) >= 2
        and all(len(part) > 1 for part in normalize(name).split())
    }


def decide(paper: CatalogPaper, candidates: list[Candidate]) -> dict:
    evidence = []
    for candidate in {item.arxiv_id: item for item in candidates}.values():
        expected = {normalize(name) for name in paper.authors if normalize(name)}
        actual = {normalize(name) for name in candidate.authors if normalize(name)}
        common = full_names(paper.authors) & full_names(candidate.authors)
        title_exact = normalize(paper.title) == normalize(candidate.title)
        author_agreement = min(
            len(common) / max(1, len(expected)), len(common) / max(1, len(actual))
        )
        strong = (
            author_agreement >= 0.8
            and len(common) >= min(2, len(expected))
            and bool(expected)
        )
        evidence.append(
            {
                **asdict(candidate),
                "url": f"https://arxiv.org/abs/{candidate.arxiv_id}",
                "title_exact": title_exact,
                "title_similarity": round(
                    SequenceMatcher(
                        None, normalize(paper.title), normalize(candidate.title)
                    ).ratio(),
                    4,
                ),
                "matched_full_authors": sorted(common),
                "author_agreement": author_agreement,
                "eligible": title_exact and strong,
            }
        )
    eligible = [item for item in evidence if item["eligible"]]
    plausible = [
        item
        for item in evidence
        if item["title_exact"]
        or (item["title_similarity"] >= 0.85 and item["author_agreement"] >= 0.5)
    ]
    accepted = eligible[0] if len(eligible) == 1 and len(plausible) == 1 else None
    status = "matched" if accepted else "needs_review" if evidence else "not_found"
    return {
        "status": status,
        "arxiv_id": accepted["arxiv_id"] if accepted else None,
        "arxiv_url": accepted["url"] if accepted else None,
        "reason": "unique_exact_title_and_full_authors"
        if accepted
        else "candidate_evidence_requires_review"
        if evidence
        else "no_candidates_returned",
        "matcher_version": MATCHER_VERSION,
        "candidates": evidence,
    }
