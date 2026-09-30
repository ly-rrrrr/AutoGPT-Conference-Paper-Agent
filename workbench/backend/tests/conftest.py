from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.database import get_session
from app.main import create_app
from app.models import (
    Base,
    ConferenceEdition,
    ImpactSignal,
    Paper,
    PaperAnalysis,
    PaperAuthor,
    PaperMapping,
)


@pytest.fixture
def api_session():
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


@pytest.fixture
def client(api_session):
    app = create_app()
    app.dependency_overrides[get_session] = lambda: api_session
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def seeded_db(api_session):
    edition = ConferenceEdition(conference="ECCV", year=2026)
    api_session.add(edition)
    api_session.flush()
    matched = Paper(
        conference_edition_id=edition.id,
        title="Vision Systems for Research",
        normalized_title="vision systems for research",
        topic="Vision Systems",
        arxiv_id="2607.00001",
        arxiv_url="https://arxiv.org/abs/2607.00001",
    )
    unresolved = Paper(
        conference_edition_id=edition.id,
        title="Unresolved Geometry Study",
        normalized_title="unresolved geometry study",
        topic="3D Vision",
    )
    api_session.add_all([matched, unresolved])
    api_session.flush()
    api_session.add_all(
        [
            PaperAuthor(
                paper_id=matched.id,
                position=0,
                name="Alice Zhang",
                normalized_name="alice zhang",
            ),
            PaperMapping(
                paper_id=matched.id,
                status="matched",
                reason="unique_exact_title_and_full_authors",
                matcher_version="v1",
                arxiv_id="2607.00001",
                arxiv_url="https://arxiv.org/abs/2607.00001",
                source_path="mappings.jsonl",
                source_sha256="mapping-hash",
            ),
            PaperMapping(
                paper_id=unresolved.id,
                status="not_found",
                reason="no_candidates_returned",
                matcher_version="v1",
                source_path="mappings.jsonl",
                source_sha256="mapping-hash",
            ),
            PaperAnalysis(
                paper_id=matched.id,
                run_id="fixture-run",
                status="SUCCESS",
                analysis_mode="structured_llm",
                question_set_hash="questions",
                questions=["Why?"],
                payload={"research_problem": "Research discovery [page 1]."},
                source_path="analysis.jsonl",
                source_sha256="analysis-hash",
            ),
            ImpactSignal(
                paper_id=matched.id,
                source="alphaxiv_likes",
                value=18,
                raw_text="18 Likes",
                status="SUCCESS",
                observed_at=datetime.now(UTC),
                source_path="likes.jsonl",
                source_sha256="likes-hash",
            ),
        ]
    )
    api_session.commit()
    return {"matched": matched, "unresolved": unresolved}

