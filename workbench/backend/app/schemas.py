from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


class PaperListItem(BaseModel):
    id: UUID
    conference: str
    year: int
    title: str
    authors: list[str]
    topic: str | None
    arxiv_id: str | None
    mapping_status: str | None
    analysis_status: str | None
    likes: float | None
    updated_at: datetime


class PaginatedPapers(BaseModel):
    total: int
    page: int
    page_size: int
    items: list[PaperListItem]


class MappingDetail(BaseModel):
    status: str
    reason: str | None
    matcher_version: str
    arxiv_id: str | None
    arxiv_url: str | None
    checked_at: datetime | None
    source_path: str
    source_sha256: str
    evidence: dict[str, Any]


class AnswerDetail(BaseModel):
    question: str
    answer: str
    source_references: list[Any]
    warnings: list[Any]


class AnalysisDetail(BaseModel):
    status: str
    analysis_mode: str
    questions: list[Any]
    payload: dict[str, Any] | None
    error_code: str | None
    error_detail: str | None
    model: str | None
    source_path: str
    source_sha256: str
    answers: list[AnswerDetail]


class PaperDetail(BaseModel):
    id: UUID
    conference: str
    year: int
    title: str
    authors: list[str]
    topic: str | None
    detail_url: str | None
    pdf_url: str | None
    arxiv_id: str | None
    arxiv_url: str | None
    mapping: MappingDetail | None
    analysis: AnalysisDetail | None
    likes: float | None
    document: dict[str, Any] | None


class DashboardResponse(BaseModel):
    papers_total: int
    conferences: dict[str, int]
    mappings: dict[str, int]
    analyses: dict[str, int]
    documents: dict[str, int]
    likes_success: int
    active_runs: list[dict[str, Any]]
    recent_errors: list[dict[str, Any]]
    last_import_at: datetime | None


class PaperQuery(BaseModel):
    query: str | None = None
    conference: str | None = None
    year: int | None = None
    topic: str | None = None
    mapping_status: str | None = None
    analysis_status: str | None = None
    sort: str = Field(default="updated_at", pattern="^(updated_at|title|likes)$")
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=25, ge=1, le=100)

