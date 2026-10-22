import re
from dataclasses import dataclass, field
from xml.etree import ElementTree


TEI = "http://www.tei-c.org/ns/1.0"
XML = "http://www.w3.org/XML/1998/namespace"
NS = {"tei": TEI}


@dataclass(frozen=True)
class ParsedReference:
    reference_key: str
    ordinal: int
    title: str
    authors: list[str]
    publication_year: int | None
    doi: str | None
    arxiv_id: str | None
    venue: str | None
    raw_reference: str | None


@dataclass(frozen=True)
class ParsedCitation:
    reference_key: str
    section_title: str | None
    context_text: str
    page_number: int | None
    coordinates: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class ParsedScholarlyDocument:
    references: list[ParsedReference]
    citations: list[ParsedCitation]
    warnings: list[str]


@dataclass(frozen=True)
class ClassifiedRelation:
    relation_type: str
    confidence: float


RELATION_PATTERNS = [
    (
        "differs_from",
        0.94,
        re.compile(r"\b(unlike|in contrast to|different from|differs? from|rather than)\b", re.I),
    ),
    (
        "addresses_gap_of",
        0.91,
        re.compile(
            r"\b(overcome(?:s|ing)? (?:the )?(?:limitation|drawback|shortcoming)|"
            r"address(?:es|ing)? (?:this|the) (?:gap|limitation|problem)|"
            r"fails? to|unable to|remain(?:s|ed)? (?:an )?open)\b",
            re.I,
        ),
    ),
    (
        "improves",
        0.9,
        re.compile(r"\b(improve(?:s|d|ment)? (?:upon|over|on)|outperform(?:s|ed)?|better than|surpass(?:es|ed)?)\b", re.I),
    ),
    (
        "extends",
        0.88,
        re.compile(r"\b(extend(?:s|ed|ing)?|build(?:s|ing)? (?:on|upon)|based on|following)\b", re.I),
    ),
    (
        "compares_with",
        0.86,
        re.compile(r"\b(compare(?:s|d|ing)? (?:with|against|to)|baseline|benchmark against)\b", re.I),
    ),
    (
        "uses",
        0.8,
        re.compile(r"\b(adopt(?:s|ed|ing)?|use(?:s|d|ing)?|employ(?:s|ed|ing)?|leverage(?:s|d|ing)?)\b", re.I),
    ),
]


def _text(element: ElementTree.Element | None) -> str:
    if element is None:
        return ""
    return " ".join(" ".join(element.itertext()).split())


def _first_text(element: ElementTree.Element, paths: list[str]) -> str | None:
    for path in paths:
        value = _text(element.find(path, NS))
        if value:
            return value
    return None


def _year(element: ElementTree.Element) -> int | None:
    for date in element.findall(".//tei:date", NS):
        raw = date.get("when") or _text(date)
        match = re.search(r"\b(19|20)\d{2}\b", raw or "")
        if match:
            return int(match.group(0))
    return None


def _identifier(element: ElementTree.Element, kind: str) -> str | None:
    for item in element.findall(".//tei:idno", NS):
        if (item.get("type") or "").casefold() == kind.casefold():
            value = _text(item)
            if value:
                return value.removeprefix("https://doi.org/").removeprefix("arXiv:")
    return None


def _authors(element: ElementTree.Element) -> list[str]:
    values = []
    for author in element.findall(".//tei:author", NS):
        name = _text(author.find("tei:persName", NS)) or _text(author)
        if name and name not in values:
            values.append(name)
    return values


def _page_and_coordinates(element: ElementTree.Element) -> tuple[int | None, list[str]]:
    raw = element.get("coords") or ""
    coordinates = [value.strip() for value in raw.split(";") if value.strip()]
    if not coordinates:
        return None, []
    page = coordinates[0].split(",", 1)[0]
    return (int(page) if page.isdigit() else None), coordinates


def parse_grobid_tei(tei_xml: str) -> ParsedScholarlyDocument:
    root = ElementTree.fromstring(tei_xml)
    references = []
    reference_keys = set()
    warnings = []

    for ordinal, item in enumerate(root.findall(".//tei:listBibl/tei:biblStruct", NS)):
        key = item.get(f"{{{XML}}}id") or f"b{ordinal}"
        title = _first_text(
            item,
            ["tei:analytic/tei:title", "tei:monogr/tei:title", ".//tei:title"],
        )
        raw = _first_text(item, ["tei:note[@type='raw_reference']", ".//tei:note"])
        if not title:
            title = raw or f"未识别参考文献 {ordinal + 1}"
            warnings.append(f"REFERENCE_TITLE_MISSING:{key}")
        venue = _first_text(item, ["tei:monogr/tei:title", ".//tei:meeting"])
        references.append(
            ParsedReference(
                reference_key=key,
                ordinal=ordinal,
                title=title,
                authors=_authors(item),
                publication_year=_year(item),
                doi=_identifier(item, "doi"),
                arxiv_id=_identifier(item, "arxiv"),
                venue=venue if venue != title else None,
                raw_reference=raw,
            )
        )
        reference_keys.add(key)

    citations = []

    def collect(container: ElementTree.Element, inherited_title: str | None = None) -> None:
        section_title = _text(container.find("tei:head", NS)) or inherited_title
        for child in container:
            if child.tag == f"{{{TEI}}}p":
                context = _text(child)
                for marker in child.findall(".//tei:ref[@type='bibr']", NS):
                    targets = (marker.get("target") or "").split()
                    page_number, coordinates = _page_and_coordinates(marker)
                    for target in targets:
                        key = target.lstrip("#")
                        if not key:
                            continue
                        if key not in reference_keys:
                            warnings.append(f"CITATION_TARGET_MISSING:{key}")
                            continue
                        citations.append(
                            ParsedCitation(
                                reference_key=key,
                                section_title=section_title,
                                context_text=context,
                                page_number=page_number,
                                coordinates=coordinates,
                            )
                        )
            elif child.tag == f"{{{TEI}}}div":
                collect(child, section_title)

    body = root.find(".//tei:text/tei:body", NS)
    if body is None:
        warnings.append("BODY_MISSING")
    else:
        collect(body)

    return ParsedScholarlyDocument(
        references=references,
        citations=citations,
        warnings=list(dict.fromkeys(warnings)),
    )


def classify_relation(context_text: str) -> ClassifiedRelation:
    for relation_type, confidence, pattern in RELATION_PATTERNS:
        if pattern.search(context_text):
            return ClassifiedRelation(relation_type, confidence)
    return ClassifiedRelation("cites", 0.55)
