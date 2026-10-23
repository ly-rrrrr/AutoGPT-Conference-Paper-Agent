from app.models import Base, Paper, PaperAnalysis, PaperMapping, ResearchArtifactDependency


def test_schema_contains_each_bounded_domain():
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
        "document_asset_revisions",
        "document_chunks",
        "vector_index_records",
        "user_interests",
        "recent_works",
        "tags",
        "paper_tags",
        "favorites",
        "reference_works",
        "paper_references",
        "related_work_evidence",
        "research_briefs",
        "research_artifacts",
        "research_artifact_dependencies",
        "research_evidence_refs",
        "insight_proposals",
        "model_provider_configs",
        "cognition_paper_memories",
        "cognition_artifacts",
        "cognition_artifact_sources",
        "cognition_artifact_dependencies",
    }


def test_paper_business_key_is_unique():
    constraints = {item.name for item in Paper.__table__.constraints}

    assert "uq_paper_conference_title" in constraints


def test_machine_results_are_versioned():
    mapping_constraints = {item.name for item in PaperMapping.__table__.constraints}
    analysis_constraints = {item.name for item in PaperAnalysis.__table__.constraints}

    assert "uq_paper_mapping_version" in mapping_constraints
    assert "uq_paper_analysis_version" in analysis_constraints
    artifact_constraints = {
        item.name for item in ResearchArtifactDependency.__table__.constraints
    }
    assert "uq_research_artifact_dependency" in artifact_constraints


def test_machine_and_user_records_are_separate():
    assert "paper_analyses" in Base.metadata.tables
    assert "favorites" in Base.metadata.tables
    assert "paper_tags" in Base.metadata.tables
