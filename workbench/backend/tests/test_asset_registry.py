import hashlib
from pathlib import Path

from sqlalchemy import func, select

from app.asset_registry import ingest_tei_chunks, parse_tei_chunks, record_asset_revision
from app.models import DocumentAsset, DocumentAssetRevision, DocumentChunk


FIXTURE = Path(__file__).parent / "fixtures" / "related-work.tei.xml"


def test_tei_becomes_section_aware_paragraph_chunks():
    chunks = parse_tei_chunks(FIXTURE.read_text(encoding="utf-8"))

    assert len(chunks) == 3
    assert chunks[0].section_path == ["Related Work"]
    assert chunks[0].page_number == 2
    assert chunks[2].page_number == 3


def test_asset_revision_and_chunks_are_idempotent(api_session, seeded_db, tmp_path):
    source = tmp_path / "paper.tei.xml"
    content = FIXTURE.read_text(encoding="utf-8")
    source.write_text(content, encoding="utf-8")
    asset = DocumentAsset(
        paper_id=seeded_db["matched"].id,
        kind="grobid_tei",
        status="PARSED",
    )
    api_session.add(asset)
    api_session.flush()

    revision = record_asset_revision(
        api_session,
        asset,
        source,
        media_type="application/tei+xml",
        producer="GROBID",
        producer_version="0.9.1",
    )
    first = ingest_tei_chunks(api_session, seeded_db["matched"].id, revision, content)
    second_revision = record_asset_revision(api_session, asset, source)
    second = ingest_tei_chunks(
        api_session, seeded_db["matched"].id, second_revision, content
    )

    assert revision.id == second_revision.id
    assert asset.sha256 == hashlib.sha256(source.read_bytes()).hexdigest()
    assert first == 3
    assert second == 0
    assert api_session.scalar(select(func.count(DocumentAssetRevision.id))) == 1
    assert api_session.scalar(select(func.count(DocumentChunk.id))) == 3
