from pathlib import Path

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from app.importers import AssetImporter, ImportDataError, iter_jsonl
from app.models import Base, ImportBatch, ImpactSignal, Paper, PaperAnalysis


@pytest.fixture
def session():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as database_session:
        yield database_session


@pytest.fixture
def fixture_data():
    return Path(__file__).parent / "fixtures"


def test_sync_imports_each_asset_once(session, fixture_data):
    importer = AssetImporter(session, fixture_data)

    first = importer.sync()
    second = importer.sync()

    assert first.files_imported == 3
    assert first.papers_created == 2
    assert second.files_imported == 0
    assert second.papers_created == 0
    assert session.scalar(select(func.count(Paper.id))) == 2
    assert session.scalar(select(func.count(PaperAnalysis.id))) == 1
    assert session.scalar(select(func.count(ImpactSignal.id))) == 1
    assert session.scalar(select(func.count(ImportBatch.id))) == 3


def test_unknown_analysis_is_reported_without_creating_a_paper(
    session, fixture_data, tmp_path
):
    source = tmp_path / "data"
    source.mkdir()
    (source / "analysis-checkpoint.jsonl").write_text(
        '{"paper_key":"arxiv:9999.99999","status":"FAILED",'
        '"analysis":null,"error_code":"NOT_FOUND","error_detail":null,'
        '"analysis_mode":"structured_llm","questions":["Why?"]}\n',
        encoding="utf-8",
    )

    summary = AssetImporter(session, source).sync()

    assert summary.unresolved_records == 1
    assert session.scalar(select(func.count(Paper.id))) == 0


def test_invalid_json_reports_file_and_line(tmp_path):
    path = tmp_path / "broken.jsonl"
    path.write_text('{}\n{"broken"\n', encoding="utf-8")

    with pytest.raises(ImportDataError, match=r"broken\.jsonl:2"):
        list(iter_jsonl(path))


def test_run_papers_are_identity_sources_and_latest_checkpoint_wins(session, tmp_path):
    run = tmp_path / "runs" / "cvpr-2026"
    run.mkdir(parents=True)
    (run / "papers.jsonl").write_text(
        '{"conference":"CVPR","year":2026,"title":"A CVPR Paper",'
        '"authors":["Dana Xu"],"detail_url":"https://example.test/paper",'
        '"pdf_url":"https://example.test/paper.pdf","paper_key":"arxiv:2601.00001",'
        '"arxiv_url":"https://arxiv.org/abs/2601.00001","arxiv_id":"2601.00001",'
        '"questions":["Why?"],"conference_day":"Day 1"}\n',
        encoding="utf-8",
    )
    (run / "analysis-checkpoint.jsonl").write_text(
        '{"paper_key":"arxiv:2601.00001","status":"FAILED","analysis":null,'
        '"error_code":"OLD","error_detail":null,"analysis_mode":"structured_llm",'
        '"questions":["Why?"]}\n'
        '{"paper_key":"arxiv:2601.00001","status":"SUCCESS",'
        '"analysis":{"answer_by_question":{"Why?":"Because [page 1]."},'
        '"source_references":["page 1"],"warnings":[]},"error_code":null,'
        '"error_detail":null,"analysis_mode":"structured_llm","questions":["Why?"]}\n',
        encoding="utf-8",
    )

    summary = AssetImporter(session, tmp_path).sync()

    paper = session.scalar(select(Paper))
    analysis = session.scalar(select(PaperAnalysis))
    assert summary.unresolved_records == 0
    assert paper is not None and paper.arxiv_id == "2601.00001"
    assert analysis is not None and analysis.status == "SUCCESS"
