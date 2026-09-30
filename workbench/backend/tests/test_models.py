from app.models import Base, Paper, PaperAnalysis, PaperMapping


def test_v1_schema_contains_each_bounded_domain():
    assert set(Base.metadata.tables) == {
        "conference_editions",
        "papers",
        "paper_authors",
        "paper_mappings",
        "mapping_candidates",
        "mapping_attempts",
        "paper_analyses",
        "paper_answers",
        "impact_signals",
        "pipeline_runs",
        "pipeline_events",
        "import_batches",
        "document_assets",
        "user_interests",
        "recent_works",
        "tags",
        "paper_tags",
        "favorites",
    }


def test_paper_business_key_is_unique():
    constraints = {item.name for item in Paper.__table__.constraints}

    assert "uq_paper_conference_title" in constraints


def test_machine_results_are_versioned():
    mapping_constraints = {item.name for item in PaperMapping.__table__.constraints}
    analysis_constraints = {item.name for item in PaperAnalysis.__table__.constraints}

    assert "uq_paper_mapping_version" in mapping_constraints
    assert "uq_paper_analysis_version" in analysis_constraints


def test_machine_and_user_records_are_separate():
    assert "paper_analyses" in Base.metadata.tables
    assert "favorites" in Base.metadata.tables
    assert "paper_tags" in Base.metadata.tables
