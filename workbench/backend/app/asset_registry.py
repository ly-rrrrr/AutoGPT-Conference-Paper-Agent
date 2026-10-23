import hashlib
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID
from xml.etree import ElementTree

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.lineage_parser import NS, TEI
from app.models import DocumentAsset, DocumentAssetRevision, DocumentChunk, Paper


@dataclass(frozen=True)
class TextChunkInput:
    key: str
    kind: str
    ordinal: int
    text: str
    section_path: list[str]
    page_number: int | None
    locator: dict


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def record_asset_revision(
    session: Session,
    asset: DocumentAsset,
    path: Path,
    *,
    content_sha256: str | None = None,
    source_uri: str | None = None,
    media_type: str | None = None,
    producer: str | None = None,
    producer_version: str | None = None,
    metadata: dict | None = None,
) -> DocumentAssetRevision:
    digest = content_sha256 or sha256_file(path)
    byte_size = path.stat().st_size
    revision = session.scalar(
        select(DocumentAssetRevision).where(
            DocumentAssetRevision.document_asset_id == asset.id,
            DocumentAssetRevision.content_sha256 == digest,
        )
    )
    if revision is None:
        revision = DocumentAssetRevision(
            document_asset_id=asset.id,
            content_sha256=digest,
            path=str(path.resolve()),
            source_uri=source_uri,
            media_type=media_type,
            byte_size=byte_size,
            producer=producer,
            producer_version=producer_version,
            metadata_payload=metadata or {},
        )
        session.add(revision)
        session.flush()
    asset.path = str(path.resolve())
    asset.sha256 = digest
    asset.source_uri = source_uri or asset.source_uri
    asset.media_type = media_type or asset.media_type
    asset.byte_size = byte_size
    asset.parser = producer or asset.parser
    asset.parser_version = producer_version or asset.parser_version
    if metadata is not None:
        asset.metadata_payload = metadata
    return revision


def parse_tei_chunks(tei_xml: str) -> list[TextChunkInput]:
    root = ElementTree.fromstring(tei_xml)
    chunks: list[TextChunkInput] = []

    def clean_text(element: ElementTree.Element | None) -> str:
        if element is None:
            return ""
        return " ".join(" ".join(element.itertext()).split())

    def page_number(element: ElementTree.Element) -> int | None:
        for item in element.iter():
            coordinates = item.get("coords") or ""
            first = coordinates.split(";", 1)[0].split(",", 1)[0]
            if first.isdigit():
                return int(first)
        return None

    abstract = root.find(".//tei:profileDesc/tei:abstract", NS)
    abstract_text = clean_text(abstract)
    if abstract_text:
        chunks.append(
            TextChunkInput(
                key="abstract",
                kind="abstract",
                ordinal=0,
                text=abstract_text,
                section_path=["Abstract"],
                page_number=page_number(abstract),
                locator={"tei_path": ".//profileDesc/abstract"},
            )
        )

    ordinal = len(chunks)

    def visit_div(element: ElementTree.Element, parents: list[str], div_path: str) -> None:
        nonlocal ordinal
        heading = clean_text(element.find("tei:head", NS))
        section_path = [*parents, heading] if heading else parents
        paragraph_index = 0
        child_div_index = 0
        for child in element:
            if child.tag == f"{{{TEI}}}p":
                text = clean_text(child)
                if not text:
                    continue
                key = f"{div_path}:p:{paragraph_index}"
                chunks.append(
                    TextChunkInput(
                        key=key,
                        kind="paragraph",
                        ordinal=ordinal,
                        text=text,
                        section_path=section_path,
                        page_number=page_number(child),
                        locator={"tei_path": key, "paragraph": paragraph_index},
                    )
                )
                ordinal += 1
                paragraph_index += 1
            elif child.tag == f"{{{TEI}}}div":
                visit_div(child, section_path, f"{div_path}:div:{child_div_index}")
                child_div_index += 1

    body = root.find(".//tei:text/tei:body", NS)
    if body is not None:
        top_level = body.findall("tei:div", NS)
        for index, section in enumerate(top_level):
            visit_div(section, [], f"body:div:{index}")
        for index, paragraph in enumerate(body.findall("tei:p", NS)):
            text = clean_text(paragraph)
            if text:
                chunks.append(
                    TextChunkInput(
                        key=f"body:p:{index}",
                        kind="paragraph",
                        ordinal=ordinal,
                        text=text,
                        section_path=[],
                        page_number=page_number(paragraph),
                        locator={"tei_path": f"body:p:{index}", "paragraph": index},
                    )
                )
                ordinal += 1
    return chunks


def ingest_tei_chunks(
    session: Session,
    paper_id: UUID,
    revision: DocumentAssetRevision,
    tei_xml: str,
) -> int:
    if session.scalar(
        select(DocumentChunk.id).where(DocumentChunk.asset_revision_id == revision.id).limit(1)
    ):
        return 0
    chunks = parse_tei_chunks(tei_xml)
    for item in chunks:
        digest = hashlib.sha256(item.text.encode("utf-8")).hexdigest()
        session.add(
            DocumentChunk(
                asset_revision_id=revision.id,
                paper_id=paper_id,
                chunk_key=item.key,
                kind=item.kind,
                ordinal=item.ordinal,
                text=item.text,
                section_path=item.section_path,
                page_number=item.page_number,
                locator=item.locator,
                content_sha256=digest,
                char_count=len(item.text),
            )
        )
    session.flush()
    return len(chunks)


def backfill_asset_registry(session: Session) -> dict[str, int]:
    revisions = 0
    chunks = 0
    assets = session.scalars(
        select(DocumentAsset).where(DocumentAsset.path.is_not(None))
    ).all()
    by_paper_kind = {(asset.paper_id, asset.kind): asset for asset in assets}
    for asset in assets:
        path = Path(asset.path or "")
        if not path.is_file():
            continue
        paper = session.get(Paper, asset.paper_id)
        source_uri = asset.source_uri
        media_type = asset.media_type
        if asset.kind == "pdf":
            source_uri = source_uri or (paper.pdf_url if paper else None)
            media_type = media_type or "application/pdf"
        elif asset.kind == "grobid_tei":
            media_type = media_type or "application/tei+xml"
            parent = by_paper_kind.get((asset.paper_id, "pdf"))
            if parent is not None:
                asset.parent_asset_id = parent.id
                asset.derivation = {
                    "kind": "parsed_from",
                    "source_asset_id": str(parent.id),
                    "source_sha256": parent.sha256,
                }
        existing = session.scalar(
            select(DocumentAssetRevision).where(
                DocumentAssetRevision.document_asset_id == asset.id,
                DocumentAssetRevision.content_sha256 == (asset.sha256 or sha256_file(path)),
            )
        )
        revision = record_asset_revision(
            session,
            asset,
            path,
            content_sha256=asset.sha256,
            source_uri=source_uri,
            media_type=media_type,
            producer=asset.parser,
            producer_version=asset.parser_version,
        )
        if existing is None:
            revisions += 1
        if asset.kind == "grobid_tei":
            chunks += ingest_tei_chunks(
                session,
                asset.paper_id,
                revision,
                path.read_text(encoding="utf-8"),
            )
    return {"revisions": revisions, "chunks": chunks}
