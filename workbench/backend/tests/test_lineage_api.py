import hashlib
from pathlib import Path

from sqlalchemy import func, select

from app.lineage_parser import parse_grobid_tei
from app.lineage_service import ingest_lineage
from app.lineage_extractor import _pdf_source_url, _trusted_pdf_url
from app.models import PaperReference, ReferenceWork, RelatedWorkEvidence


FIXTURE = Path(__file__).parent / "fixtures" / "related-work.tei.xml"


def test_pdf_source_falls_back_to_arxiv_and_rejects_local_hosts(seeded_db):
    assert _pdf_source_url(seeded_db["matched"]) == "https://arxiv.org/pdf/2607.00001"
    assert _trusted_pdf_url("https://arxiv.org/pdf/2607.00001")
    assert not _trusted_pdf_url("http://127.0.0.1/private.pdf")


def seed_lineage(api_session, seeded_db):
    content = FIXTURE.read_text(encoding="utf-8")
    parsed = parse_grobid_tei(content)
    digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
    summary = ingest_lineage(
        api_session,
        seeded_db["matched"],
        parsed,
        "fixtures/related-work.tei.xml",
        digest,
    )
    api_session.commit()
    return summary


def test_lineage_ingest_is_idempotent(api_session, seeded_db):
    first = seed_lineage(api_session, seeded_db)
    second = seed_lineage(api_session, seeded_db)

    assert first.references == 3
    assert first.evidence == 3
    assert second.evidence == 0
    assert api_session.scalar(select(func.count(ReferenceWork.id))) == 3
    assert api_session.scalar(select(func.count(PaperReference.id))) == 3
    assert api_session.scalar(select(func.count(RelatedWorkEvidence.id))) == 3


def test_lineage_graph_exposes_relation_evidence(client, api_session, seeded_db):
    seed_lineage(api_session, seeded_db)

    response = client.get(f"/api/lineage/papers/{seeded_db['matched'].id}")

    assert response.status_code == 200
    data = response.json()
    assert len(data["nodes"]) == 4
    assert {edge["relation_type"] for edge in data["edges"]} == {
        "differs_from",
        "extends",
        "compares_with",
    }
    assert data["edges"][0]["evidence"]["source_sha256"]


def test_lineage_graph_can_filter_relation_types(client, api_session, seeded_db):
    seed_lineage(api_session, seeded_db)

    response = client.get(
        f"/api/lineage/papers/{seeded_db['matched'].id}",
        params={"relation_type": "extends"},
    )

    assert response.status_code == 200
    assert [edge["relation_type"] for edge in response.json()["edges"]] == ["extends"]


def test_lineage_overview_reports_parser_and_counts(
    client, api_session, seeded_db, monkeypatch
):
    seed_lineage(api_session, seeded_db)
    monkeypatch.setattr("app.api.lineage.grobid_ready", lambda: True)

    response = client.get("/api/lineage/overview")

    assert response.status_code == 200
    assert response.json()["papers_with_lineage"] == 1
    assert response.json()["parser"] == {"name": "GROBID", "ready": True}


def test_start_extraction_creates_observable_background_run(
    client, seeded_db, monkeypatch
):
    called = []
    monkeypatch.setattr(
        "app.api.lineage.execute_lineage_run",
        lambda run_id, paper_id: called.append((run_id, paper_id)),
    )

    response = client.post(
        f"/api/lineage/papers/{seeded_db['matched'].id}/extract",
        headers={"X-Workbench-Request": "1"},
    )

    assert response.status_code == 202
    assert response.json()["status"] == "QUEUED"
    assert called and called[0][1] == seeded_db["matched"].id
