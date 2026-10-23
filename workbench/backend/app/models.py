import uuid
from datetime import UTC, datetime

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def utc_now() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    pass


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )


class ConferenceEdition(Base, TimestampMixin):
    __tablename__ = "conference_editions"
    __table_args__ = (
        UniqueConstraint("conference", "year", name="uq_conference_edition"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    conference: Mapped[str] = mapped_column(String(40))
    year: Mapped[int] = mapped_column(Integer)
    source_url: Mapped[str | None] = mapped_column(Text)
    source_sha256: Mapped[str | None] = mapped_column(String(64))


class Paper(Base, TimestampMixin):
    __tablename__ = "papers"
    __table_args__ = (
        UniqueConstraint(
            "conference_edition_id",
            "normalized_title",
            name="uq_paper_conference_title",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    conference_edition_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("conference_editions.id", ondelete="CASCADE"), index=True
    )
    title: Mapped[str] = mapped_column(Text)
    normalized_title: Mapped[str] = mapped_column(Text)
    topic: Mapped[str | None] = mapped_column(Text, index=True)
    detail_url: Mapped[str | None] = mapped_column(Text)
    pdf_url: Mapped[str | None] = mapped_column(Text)
    arxiv_id: Mapped[str | None] = mapped_column(String(40), index=True)
    arxiv_url: Mapped[str | None] = mapped_column(Text)
    source_payload: Mapped[dict] = mapped_column(JSON, default=dict)


class PaperAuthor(Base):
    __tablename__ = "paper_authors"
    __table_args__ = (
        UniqueConstraint("paper_id", "position", name="uq_paper_author_position"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    paper_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("papers.id", ondelete="CASCADE"), index=True
    )
    position: Mapped[int] = mapped_column(Integer)
    name: Mapped[str] = mapped_column(Text)
    normalized_name: Mapped[str] = mapped_column(Text)


class PaperMapping(Base):
    __tablename__ = "paper_mappings"
    __table_args__ = (
        UniqueConstraint(
            "paper_id", "matcher_version", name="uq_paper_mapping_version"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    paper_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("papers.id", ondelete="CASCADE"), index=True
    )
    status: Mapped[str] = mapped_column(String(40), index=True)
    reason: Mapped[str | None] = mapped_column(Text)
    matcher_version: Mapped[str] = mapped_column(String(120))
    arxiv_id: Mapped[str | None] = mapped_column(String(40), index=True)
    arxiv_url: Mapped[str | None] = mapped_column(Text)
    checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    source_path: Mapped[str] = mapped_column(Text)
    source_sha256: Mapped[str] = mapped_column(String(64))
    evidence: Mapped[dict] = mapped_column(JSON, default=dict)


class MappingCandidate(Base):
    __tablename__ = "mapping_candidates"
    __table_args__ = (
        UniqueConstraint(
            "mapping_id", "arxiv_id", name="uq_mapping_candidate_arxiv"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    mapping_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("paper_mappings.id", ondelete="CASCADE"), index=True
    )
    arxiv_id: Mapped[str] = mapped_column(String(40))
    title: Mapped[str] = mapped_column(Text)
    authors: Mapped[list] = mapped_column(JSON, default=list)
    title_exact: Mapped[bool] = mapped_column(Boolean, default=False)
    title_similarity: Mapped[float] = mapped_column(Float, default=0)
    author_agreement: Mapped[float] = mapped_column(Float, default=0)
    eligible: Mapped[bool] = mapped_column(Boolean, default=False)
    evidence: Mapped[dict] = mapped_column(JSON, default=dict)


class MappingAttempt(Base):
    __tablename__ = "mapping_attempts"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    mapping_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("paper_mappings.id", ondelete="CASCADE"), index=True
    )
    kind: Mapped[str] = mapped_column(String(40))
    query: Mapped[str] = mapped_column(Text)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    returned_count: Mapped[int | None] = mapped_column(Integer)


class PaperAnalysis(Base):
    __tablename__ = "paper_analyses"
    __table_args__ = (
        UniqueConstraint(
            "paper_id",
            "analysis_mode",
            "question_set_hash",
            name="uq_paper_analysis_version",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    paper_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("papers.id", ondelete="CASCADE"), index=True
    )
    run_id: Mapped[str] = mapped_column(String(120), index=True)
    status: Mapped[str] = mapped_column(String(40), index=True)
    analysis_mode: Mapped[str] = mapped_column(String(60))
    question_set_hash: Mapped[str] = mapped_column(String(64))
    questions: Mapped[list] = mapped_column(JSON, default=list)
    payload: Mapped[dict | None] = mapped_column(JSON)
    error_code: Mapped[str | None] = mapped_column(String(160))
    error_detail: Mapped[str | None] = mapped_column(Text)
    model: Mapped[str | None] = mapped_column(String(120))
    analyzed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    source_path: Mapped[str] = mapped_column(Text)
    source_sha256: Mapped[str] = mapped_column(String(64))


class PaperAnswer(Base):
    __tablename__ = "paper_answers"
    __table_args__ = (
        UniqueConstraint("analysis_id", "position", name="uq_analysis_answer_position"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    analysis_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("paper_analyses.id", ondelete="CASCADE"), index=True
    )
    position: Mapped[int] = mapped_column(Integer)
    question: Mapped[str] = mapped_column(Text)
    answer: Mapped[str] = mapped_column(Text)
    source_references: Mapped[list] = mapped_column(JSON, default=list)
    warnings: Mapped[list] = mapped_column(JSON, default=list)


class ImpactSignal(Base):
    __tablename__ = "impact_signals"
    __table_args__ = (
        UniqueConstraint(
            "paper_id", "source", "source_sha256", name="uq_impact_source_version"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    paper_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("papers.id", ondelete="CASCADE"), index=True
    )
    source: Mapped[str] = mapped_column(String(80), index=True)
    value: Mapped[float | None] = mapped_column(Float)
    raw_text: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(40))
    error_code: Mapped[str | None] = mapped_column(String(160))
    observed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    source_path: Mapped[str] = mapped_column(Text)
    source_sha256: Mapped[str] = mapped_column(String(64))


class PipelineRun(Base, TimestampMixin):
    __tablename__ = "pipeline_runs"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    external_id: Mapped[str | None] = mapped_column(String(120), index=True)
    run_key: Mapped[str] = mapped_column(String(120), index=True)
    pipeline: Mapped[str] = mapped_column(String(40), index=True)
    status: Mapped[str] = mapped_column(String(40), index=True)
    config: Mapped[dict] = mapped_column(JSON, default=dict)
    counters: Mapped[dict] = mapped_column(JSON, default=dict)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    available_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), index=True
    )
    lease_owner: Mapped[str | None] = mapped_column(String(160), index=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), index=True
    )
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    attempt_count: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, default=2)
    last_error: Mapped[str | None] = mapped_column(Text)


class PipelineEvent(Base):
    __tablename__ = "pipeline_events"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    pipeline_run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("pipeline_runs.id", ondelete="CASCADE"), index=True
    )
    level: Mapped[str] = mapped_column(String(20))
    event_type: Mapped[str] = mapped_column(String(80), index=True)
    message: Mapped[str] = mapped_column(Text)
    details: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class ImportBatch(Base):
    __tablename__ = "import_batches"
    __table_args__ = (
        UniqueConstraint("source_path", "sha256", name="uq_import_source_hash"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    source_path: Mapped[str] = mapped_column(Text)
    sha256: Mapped[str] = mapped_column(String(64))
    parser_version: Mapped[str] = mapped_column(String(80))
    status: Mapped[str] = mapped_column(String(40), index=True)
    counts: Mapped[dict] = mapped_column(JSON, default=dict)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error: Mapped[str | None] = mapped_column(Text)


class DocumentAsset(Base, TimestampMixin):
    __tablename__ = "document_assets"
    __table_args__ = (
        UniqueConstraint("paper_id", "kind", name="uq_paper_document_kind"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    paper_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("papers.id", ondelete="CASCADE"), index=True
    )
    kind: Mapped[str] = mapped_column(String(40))
    status: Mapped[str] = mapped_column(String(40), index=True)
    path: Mapped[str | None] = mapped_column(Text)
    sha256: Mapped[str | None] = mapped_column(String(64))
    parser: Mapped[str | None] = mapped_column(String(120))
    parser_version: Mapped[str | None] = mapped_column(String(80))
    last_error: Mapped[str | None] = mapped_column(Text)
    source_uri: Mapped[str | None] = mapped_column(Text)
    media_type: Mapped[str | None] = mapped_column(String(120))
    byte_size: Mapped[int | None] = mapped_column(BigInteger)
    parent_asset_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("document_assets.id", ondelete="SET NULL"), index=True
    )
    derivation: Mapped[dict] = mapped_column(JSON, default=dict)
    metadata_payload: Mapped[dict] = mapped_column(JSON, default=dict)


class DocumentAssetRevision(Base):
    __tablename__ = "document_asset_revisions"
    __table_args__ = (
        UniqueConstraint(
            "document_asset_id",
            "content_sha256",
            name="uq_document_asset_revision_content",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    document_asset_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("document_assets.id", ondelete="CASCADE"), index=True
    )
    content_sha256: Mapped[str] = mapped_column(String(64), index=True)
    path: Mapped[str] = mapped_column(Text)
    source_uri: Mapped[str | None] = mapped_column(Text)
    media_type: Mapped[str | None] = mapped_column(String(120))
    byte_size: Mapped[int | None] = mapped_column(BigInteger)
    producer: Mapped[str | None] = mapped_column(String(120))
    producer_version: Mapped[str | None] = mapped_column(String(80))
    metadata_payload: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class DocumentChunk(Base):
    __tablename__ = "document_chunks"
    __table_args__ = (
        UniqueConstraint(
            "asset_revision_id", "chunk_key", name="uq_document_chunk_revision_key"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    asset_revision_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("document_asset_revisions.id", ondelete="CASCADE"), index=True
    )
    paper_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("papers.id", ondelete="CASCADE"), index=True
    )
    chunk_key: Mapped[str] = mapped_column(String(160))
    kind: Mapped[str] = mapped_column(String(40), index=True)
    ordinal: Mapped[int] = mapped_column(Integer)
    text: Mapped[str] = mapped_column(Text)
    section_path: Mapped[list] = mapped_column(JSON, default=list)
    page_number: Mapped[int | None] = mapped_column(Integer)
    locator: Mapped[dict] = mapped_column(JSON, default=dict)
    content_sha256: Mapped[str] = mapped_column(String(64), index=True)
    char_count: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class VectorIndexRecord(Base, TimestampMixin):
    __tablename__ = "vector_index_records"
    __table_args__ = (
        UniqueConstraint(
            "document_chunk_id",
            "embedding_model",
            "embedding_dimension",
            "index_version",
            name="uq_vector_index_chunk_model_dimension_version",
        ),
        UniqueConstraint(
            "collection_name", "entity_id", name="uq_vector_collection_entity"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    document_chunk_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("document_chunks.id", ondelete="CASCADE"), index=True
    )
    collection_name: Mapped[str] = mapped_column(String(255), index=True)
    entity_id: Mapped[str] = mapped_column(String(80))
    embedding_model: Mapped[str] = mapped_column(String(160), index=True)
    embedding_dimension: Mapped[int] = mapped_column(Integer)
    index_version: Mapped[str] = mapped_column(String(80))
    content_sha256: Mapped[str] = mapped_column(String(64), index=True)
    status: Mapped[str] = mapped_column(String(40), index=True)
    indexed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)


class UserInterest(Base, TimestampMixin):
    __tablename__ = "user_interests"
    __table_args__ = (
        UniqueConstraint("kind", "value", name="uq_interest_kind_value"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    kind: Mapped[str] = mapped_column(String(40))
    value: Mapped[str] = mapped_column(Text)
    weight: Mapped[float] = mapped_column(Float, default=1)


class RecentWork(Base, TimestampMixin):
    __tablename__ = "recent_works"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    title: Mapped[str] = mapped_column(Text)
    abstract: Mapped[str | None] = mapped_column(Text)
    arxiv_id: Mapped[str | None] = mapped_column(String(40))
    notes: Mapped[str | None] = mapped_column(Text)


class Tag(Base, TimestampMixin):
    __tablename__ = "tags"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(120), unique=True)
    color: Mapped[str | None] = mapped_column(String(20))


class PaperTag(Base):
    __tablename__ = "paper_tags"
    __table_args__ = (
        UniqueConstraint("paper_id", "tag_id", name="uq_paper_tag"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    paper_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("papers.id", ondelete="CASCADE"), index=True
    )
    tag_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tags.id", ondelete="CASCADE"), index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class Favorite(Base):
    __tablename__ = "favorites"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    paper_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("papers.id", ondelete="CASCADE"), unique=True, index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class ReferenceWork(Base, TimestampMixin):
    __tablename__ = "reference_works"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    linked_paper_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("papers.id", ondelete="SET NULL"), index=True
    )
    title: Mapped[str] = mapped_column(Text)
    normalized_title: Mapped[str] = mapped_column(Text, index=True)
    authors: Mapped[list] = mapped_column(JSON, default=list)
    publication_year: Mapped[int | None] = mapped_column(Integer, index=True)
    doi: Mapped[str | None] = mapped_column(String(255), index=True)
    arxiv_id: Mapped[str | None] = mapped_column(String(40), index=True)
    openalex_id: Mapped[str | None] = mapped_column(String(80), index=True)
    venue: Mapped[str | None] = mapped_column(Text)
    metadata_payload: Mapped[dict] = mapped_column(JSON, default=dict)


class PaperReference(Base, TimestampMixin):
    __tablename__ = "paper_references"
    __table_args__ = (
        UniqueConstraint(
            "paper_id",
            "reference_key",
            "source_sha256",
            name="uq_paper_reference_source",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    paper_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("papers.id", ondelete="CASCADE"), index=True
    )
    reference_work_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("reference_works.id", ondelete="CASCADE"), index=True
    )
    reference_key: Mapped[str] = mapped_column(String(80))
    ordinal: Mapped[int] = mapped_column(Integer)
    raw_reference: Mapped[str | None] = mapped_column(Text)
    source_path: Mapped[str] = mapped_column(Text)
    source_sha256: Mapped[str] = mapped_column(String(64), index=True)
    extractor: Mapped[str] = mapped_column(String(120))
    extractor_version: Mapped[str] = mapped_column(String(80))


class RelatedWorkEvidence(Base, TimestampMixin):
    __tablename__ = "related_work_evidence"
    __table_args__ = (
        UniqueConstraint(
            "paper_reference_id",
            "evidence_key",
            "classifier_version",
            name="uq_related_work_evidence_version",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    paper_reference_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("paper_references.id", ondelete="CASCADE"), index=True
    )
    relation_type: Mapped[str] = mapped_column(String(40), index=True)
    confidence: Mapped[float] = mapped_column(Float)
    section_title: Mapped[str | None] = mapped_column(Text)
    context_text: Mapped[str] = mapped_column(Text)
    page_number: Mapped[int | None] = mapped_column(Integer)
    coordinates: Mapped[list] = mapped_column(JSON, default=list)
    evidence_key: Mapped[str] = mapped_column(String(64))
    classifier: Mapped[str] = mapped_column(String(120))
    classifier_version: Mapped[str] = mapped_column(String(80))
    status: Mapped[str] = mapped_column(String(40), default="MACHINE", index=True)
    source_path: Mapped[str] = mapped_column(Text)
    source_sha256: Mapped[str] = mapped_column(String(64), index=True)


class ResearchBrief(Base, TimestampMixin):
    __tablename__ = "research_briefs"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    title: Mapped[str] = mapped_column(Text)
    objective: Mapped[str] = mapped_column(Text)
    scope: Mapped[dict] = mapped_column(JSON, default=dict)
    tool_policy: Mapped[dict] = mapped_column(JSON, default=dict)
    budget: Mapped[dict] = mapped_column(JSON, default=dict)
    output_preferences: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(40), default="DRAFT", index=True)


class ResearchArtifact(Base, TimestampMixin):
    __tablename__ = "research_artifacts"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    research_brief_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("research_briefs.id", ondelete="CASCADE"), index=True
    )
    workflow_run_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("pipeline_runs.id", ondelete="SET NULL"), index=True
    )
    supersedes_artifact_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("research_artifacts.id", ondelete="SET NULL"), index=True
    )
    artifact_type: Mapped[str] = mapped_column(String(80), index=True)
    status: Mapped[str] = mapped_column(String(40), default="CANDIDATE", index=True)
    content: Mapped[dict] = mapped_column(JSON, default=dict)
    narrative: Mapped[str | None] = mapped_column(Text)
    generator: Mapped[str] = mapped_column(String(120))
    generator_version: Mapped[str] = mapped_column(String(80))
    configuration: Mapped[dict] = mapped_column(JSON, default=dict)
    uncertainty: Mapped[dict] = mapped_column(JSON, default=dict)


class ResearchArtifactDependency(Base):
    __tablename__ = "research_artifact_dependencies"
    __table_args__ = (
        UniqueConstraint(
            "parent_artifact_id",
            "child_artifact_id",
            "relation",
            name="uq_research_artifact_dependency",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    parent_artifact_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("research_artifacts.id", ondelete="CASCADE"), index=True
    )
    child_artifact_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("research_artifacts.id", ondelete="CASCADE"), index=True
    )
    relation: Mapped[str] = mapped_column(String(40), default="DERIVED_FROM")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class ResearchEvidenceRef(Base, TimestampMixin):
    __tablename__ = "research_evidence_refs"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    research_artifact_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("research_artifacts.id", ondelete="CASCADE"), index=True
    )
    paper_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("papers.id", ondelete="SET NULL"), index=True
    )
    document_asset_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("document_assets.id", ondelete="SET NULL"), index=True
    )
    source_kind: Mapped[str] = mapped_column(String(60), index=True)
    source_uri: Mapped[str] = mapped_column(Text)
    page_number: Mapped[int | None] = mapped_column(Integer)
    section_title: Mapped[str | None] = mapped_column(Text)
    quote: Mapped[str | None] = mapped_column(Text)
    locator: Mapped[dict] = mapped_column(JSON, default=dict)
    source_sha256: Mapped[str | None] = mapped_column(String(64), index=True)
    stance: Mapped[str] = mapped_column(String(40), index=True)


class InsightProposal(Base, TimestampMixin):
    __tablename__ = "insight_proposals"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    research_artifact_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("research_artifacts.id", ondelete="CASCADE"), unique=True, index=True
    )
    title: Mapped[str] = mapped_column(Text)
    statement: Mapped[str] = mapped_column(Text)
    why_it_matters: Mapped[str] = mapped_column(Text)
    epistemic_status: Mapped[str] = mapped_column(String(40), index=True)
    scope: Mapped[dict] = mapped_column(JSON, default=dict)
    counterarguments: Mapped[list] = mapped_column(JSON, default=list)
    open_questions: Mapped[list] = mapped_column(JSON, default=list)
    suggested_view: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(40), default="CANDIDATE", index=True)


class CognitionPaperMemory(Base, TimestampMixin):
    __tablename__ = "cognition_paper_memories"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    paper_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("papers.id", ondelete="CASCADE"), unique=True, index=True
    )
    analysis_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("paper_analyses.id", ondelete="SET NULL"), index=True
    )
    last_seen_run_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("pipeline_runs.id", ondelete="SET NULL"), index=True
    )
    input_fingerprint: Mapped[str] = mapped_column(String(64), index=True)
    program_version: Mapped[str] = mapped_column(String(80))
    status: Mapped[str] = mapped_column(String(40), index=True)
    reuse_count: Mapped[int] = mapped_column(Integer, default=0)


class CognitionArtifact(Base, TimestampMixin):
    __tablename__ = "cognition_artifacts"
    __table_args__ = (
        UniqueConstraint(
            "artifact_type",
            "input_fingerprint",
            "generator_version",
            name="uq_cognition_artifact_cache",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    workflow_run_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("pipeline_runs.id", ondelete="SET NULL"), index=True
    )
    supersedes_artifact_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("cognition_artifacts.id", ondelete="SET NULL"), index=True
    )
    artifact_type: Mapped[str] = mapped_column(String(80), index=True)
    input_fingerprint: Mapped[str] = mapped_column(String(64), index=True)
    status: Mapped[str] = mapped_column(String(40), index=True)
    scope: Mapped[dict] = mapped_column(JSON, default=dict)
    content: Mapped[dict] = mapped_column(JSON, default=dict)
    narrative: Mapped[str | None] = mapped_column(Text)
    generator: Mapped[str] = mapped_column(String(120))
    generator_version: Mapped[str] = mapped_column(String(80))
    model: Mapped[str | None] = mapped_column(String(160))
    uncertainty: Mapped[dict] = mapped_column(JSON, default=dict)


class CognitionArtifactSource(Base):
    __tablename__ = "cognition_artifact_sources"
    __table_args__ = (
        UniqueConstraint(
            "artifact_id", "paper_id", "stance", name="uq_cognition_artifact_source"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    artifact_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("cognition_artifacts.id", ondelete="CASCADE"), index=True
    )
    paper_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("papers.id", ondelete="CASCADE"), index=True
    )
    analysis_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("paper_analyses.id", ondelete="SET NULL"), index=True
    )
    stance: Mapped[str] = mapped_column(String(40), index=True)
    locator: Mapped[dict] = mapped_column(JSON, default=dict)


class CognitionArtifactDependency(Base):
    __tablename__ = "cognition_artifact_dependencies"
    __table_args__ = (
        UniqueConstraint(
            "artifact_id",
            "depends_on_artifact_id",
            "relation",
            name="uq_cognition_artifact_dependency",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    artifact_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("cognition_artifacts.id", ondelete="CASCADE"), index=True
    )
    depends_on_artifact_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("cognition_artifacts.id", ondelete="CASCADE"), index=True
    )
    relation: Mapped[str] = mapped_column(String(40), index=True)


class ModelProviderConfig(Base, TimestampMixin):
    __tablename__ = "model_provider_configs"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(120), unique=True)
    provider: Mapped[str] = mapped_column(String(80))
    base_url: Mapped[str] = mapped_column(Text)
    model_name: Mapped[str] = mapped_column(String(160))
    secret_ref: Mapped[str] = mapped_column(String(160), unique=True)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    status: Mapped[str] = mapped_column(String(40), default="ACTIVE", index=True)


class EmbeddingProviderConfig(Base, TimestampMixin):
    __tablename__ = "embedding_provider_configs"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(120), unique=True)
    provider: Mapped[str] = mapped_column(String(80))
    base_url: Mapped[str] = mapped_column(Text)
    model_name: Mapped[str] = mapped_column(String(160))
    dimension: Mapped[int] = mapped_column(Integer)
    secret_ref: Mapped[str] = mapped_column(String(160), unique=True)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    status: Mapped[str] = mapped_column(String(40), default="ACTIVE", index=True)
