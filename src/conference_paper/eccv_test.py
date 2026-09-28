import json
from pathlib import Path

import pytest

from backend.blocks.conference_paper.eccv import load_eccv_mapping
from backend.blocks.conference_paper.models import ConferenceRunInput, PaperTask


QUESTIONS = ["What problem does this paper solve?"]


def mapping_record(status: str = "matched") -> dict:
    return {
        "paper": {
            "paper_id": "eccv:2026:3962",
            "title": "PointSplat",
            "authors": ["Yujie Guo", "Sida Peng"],
            "detail_url": "https://eccv.ecva.net/virtual/2026/poster/3962",
            "topic": "3D Reconstruction",
            "presentation": "Poster Session 4",
            "project_urls": [],
            "conference": "ECCV",
            "year": 2026,
        },
        "status": status,
        "arxiv_id": "2606.32036" if status == "matched" else None,
        "arxiv_url": "https://arxiv.org/abs/2606.32036" if status == "matched" else None,
        "reason": "unique_exact_title_and_full_authors",
    }


def write_jsonl(path: Path, records: list[dict]) -> None:
    path.write_text(
        "".join(json.dumps(record) + "\n" for record in records), encoding="utf-8"
    )


def test_eccv_models_are_valid():
    run = ConferenceRunInput(conference="ECCV", paper_questions=QUESTIONS)
    paper = PaperTask(
        conference="ECCV",
        year=2026,
        title="PointSplat",
        authors=["Yujie Guo"],
        detail_url="https://eccv.ecva.net/virtual/2026/poster/3962",
        pdf_url="https://arxiv.org/pdf/2606.32036",
        paper_key="arxiv:2606.32036",
        arxiv_url="https://arxiv.org/abs/2606.32036",
        arxiv_id="2606.32036",
        questions=QUESTIONS,
        conference_day="3D Reconstruction | Poster Session 4",
    )
    assert run.conference == "ECCV"
    assert paper.conference == "ECCV"


def test_mapping_loader_imports_matches_and_skips_failures(tmp_path: Path):
    path = tmp_path / "mappings.jsonl"
    write_jsonl(path, [mapping_record(), mapping_record("not_found")])

    result = load_eccv_mapping(path)

    assert result.status.value == "COMPLETED"
    assert result.counts.raw_count == 2
    assert result.counts.unique_count == 1
    assert len(result.papers) == 1
    paper = result.papers[0]
    assert paper.conference == "ECCV"
    assert paper.arxiv_url == "https://arxiv.org/abs/2606.32036"
    assert paper.pdf_url == "https://arxiv.org/pdf/2606.32036"
    assert paper.conference_day == "3D Reconstruction | Poster Session 4"


def test_mapping_loader_rejects_duplicate_arxiv_ids(tmp_path: Path):
    first = mapping_record()
    second = mapping_record()
    second["paper"] = {**second["paper"], "paper_id": "eccv:2026:9999"}
    path = tmp_path / "mappings.jsonl"
    write_jsonl(path, [first, second])

    with pytest.raises(ValueError, match="DUPLICATE_ARXIV_ID"):
        load_eccv_mapping(path)


def test_mapping_loader_rejects_malformed_matched_record(tmp_path: Path):
    record = mapping_record()
    record["arxiv_id"] = None
    path = tmp_path / "mappings.jsonl"
    write_jsonl(path, [record])

    with pytest.raises(ValueError, match="INVALID_ECCV_MAPPING"):
        load_eccv_mapping(path)
