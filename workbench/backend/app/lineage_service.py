import hashlib
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.importers import normalize_text
from app.lineage_parser import ParsedReference, ParsedScholarlyDocument, classify_relation
from app.models import Paper, PaperReference, ReferenceWork, RelatedWorkEvidence


EXTRACTOR = "grobid"
EXTRACTOR_VERSION = "0.9.1"
CLASSIFIER = "citation-context-rules"
CLASSIFIER_VERSION = "v1"


@dataclass(frozen=True)
class IngestSummary:
    references: int
    evidence: int
    warnings: list[str]


def normalize_title(value: str) -> str:
    return normalize_text(value)


def _linked_paper(session: Session, reference: ParsedReference) -> Paper | None:
    if reference.arxiv_id:
        paper = session.scalar(select(Paper).where(Paper.arxiv_id == reference.arxiv_id))
        if paper:
            return paper
    return session.scalar(
        select(Paper).where(Paper.normalized_title == normalize_title(reference.title)).limit(1)
    )


def _reference_work(session: Session, reference: ParsedReference) -> ReferenceWork:
    work = None
    if reference.doi:
        work = session.scalar(select(ReferenceWork).where(ReferenceWork.doi == reference.doi.casefold()))
    if work is None and reference.arxiv_id:
        work = session.scalar(select(ReferenceWork).where(ReferenceWork.arxiv_id == reference.arxiv_id))
    normalized = normalize_title(reference.title)
    if work is None:
        statement = select(ReferenceWork).where(ReferenceWork.normalized_title == normalized)
        if reference.publication_year:
            statement = statement.where(ReferenceWork.publication_year == reference.publication_year)
        work = session.scalar(statement.limit(1))
    linked = _linked_paper(session, reference)
    if work is None:
        work = ReferenceWork(
            linked_paper_id=linked.id if linked else None,
            title=reference.title,
            normalized_title=normalized,
            authors=reference.authors,
            publication_year=reference.publication_year,
            doi=reference.doi.casefold() if reference.doi else None,
            arxiv_id=reference.arxiv_id,
            venue=reference.venue,
            metadata_payload={},
        )
        session.add(work)
        session.flush()
    elif linked and work.linked_paper_id is None:
        work.linked_paper_id = linked.id
    return work


def ingest_lineage(
    session: Session,
    paper: Paper,
    parsed: ParsedScholarlyDocument,
    source_path: str,
    source_sha256: str,
) -> IngestSummary:
    links: dict[str, PaperReference] = {}
    for reference in parsed.references:
        link = session.scalar(
            select(PaperReference).where(
                PaperReference.paper_id == paper.id,
                PaperReference.reference_key == reference.reference_key,
                PaperReference.source_sha256 == source_sha256,
            )
        )
        if link is None:
            link = PaperReference(
                paper_id=paper.id,
                reference_work_id=_reference_work(session, reference).id,
                reference_key=reference.reference_key,
                ordinal=reference.ordinal,
                raw_reference=reference.raw_reference,
                source_path=source_path,
                source_sha256=source_sha256,
                extractor=EXTRACTOR,
                extractor_version=EXTRACTOR_VERSION,
            )
            session.add(link)
            session.flush()
        links[reference.reference_key] = link

    evidence_count = 0
    for citation in parsed.citations:
        link = links.get(citation.reference_key)
        if link is None:
            continue
        classification = classify_relation(citation.context_text)
        evidence_key = hashlib.sha256(
            "\n".join(
                [
                    citation.reference_key,
                    citation.section_title or "",
                    citation.context_text,
                    str(citation.page_number or ""),
                ]
            ).encode("utf-8")
        ).hexdigest()
        existing = session.scalar(
            select(RelatedWorkEvidence).where(
                RelatedWorkEvidence.paper_reference_id == link.id,
                RelatedWorkEvidence.evidence_key == evidence_key,
                RelatedWorkEvidence.classifier_version == CLASSIFIER_VERSION,
            )
        )
        if existing is None:
            session.add(
                RelatedWorkEvidence(
                    paper_reference_id=link.id,
                    relation_type=classification.relation_type,
                    confidence=classification.confidence,
                    section_title=citation.section_title,
                    context_text=citation.context_text,
                    page_number=citation.page_number,
                    coordinates=citation.coordinates,
                    evidence_key=evidence_key,
                    classifier=CLASSIFIER,
                    classifier_version=CLASSIFIER_VERSION,
                    status="MACHINE",
                    source_path=source_path,
                    source_sha256=source_sha256,
                )
            )
            evidence_count += 1
    session.flush()
    return IngestSummary(
        references=len(links),
        evidence=evidence_count,
        warnings=parsed.warnings,
    )
