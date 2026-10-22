from pathlib import Path

from app.lineage_parser import classify_relation, parse_grobid_tei


FIXTURE = Path(__file__).parent / "fixtures" / "related-work.tei.xml"


def test_grobid_tei_preserves_references_and_evidence_locations():
    parsed = parse_grobid_tei(FIXTURE.read_text(encoding="utf-8"))

    assert len(parsed.references) == 3
    assert parsed.references[0].doi == "10.1000/rendering"
    assert parsed.references[0].authors == ["Ada Lee"]
    assert parsed.references[1].arxiv_id == "2010.11929"
    assert len(parsed.citations) == 3
    assert parsed.citations[0].section_title == "Related Work"
    assert parsed.citations[0].page_number == 2
    assert parsed.citations[0].coordinates == ["2,10,20,30,8"]
    assert parsed.warnings == []


def test_relation_classifier_is_conservative_and_explainable():
    assert classify_relation("Unlike prior work, we preserve geometry.").relation_type == "differs_from"
    assert classify_relation("We build on the transformer architecture.").relation_type == "extends"
    assert classify_relation("This paper was introduced in 2020.").relation_type == "cites"
