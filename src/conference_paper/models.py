import re
from enum import StrEnum
from typing import Literal, Self

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

ConferenceYear = Literal[2025, 2026]
AnalysisMode = Literal["mcp_qa_raw", "mcp_report", "structured_llm"]


class ContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RunStatus(StrEnum):
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    PARTIAL = "PARTIAL"
    FAILED = "FAILED"


class ResultStatus(StrEnum):
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"


class AnalysisStatus(StrEnum):
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"


class PaperStatus(StrEnum):
    COMPLETED = "COMPLETED"
    PARTIAL = "PARTIAL"
    FAILED = "FAILED"


class ConferenceRunInput(ContractModel):
    conference: Literal["CVPR"] = "CVPR"
    year: ConferenceYear = 2026
    likes_strategy: Literal["alphaxiv_api", "shadowbot"] = "alphaxiv_api"
    topics: list[str] = Field(default_factory=list)
    max_papers: int = Field(default=0, ge=0, le=10_000)
    paper_questions: list[str] = Field(min_length=1, max_length=10)
    analysis_concurrency: int = Field(default=3, ge=1, le=3)

    @field_validator("topics")
    @classmethod
    def strip_topics(cls, values: list[str]) -> list[str]:
        stripped = [value.strip() for value in values]
        if any(not value for value in stripped):
            raise ValueError("list values must not be blank")
        return stripped

    @field_validator("paper_questions")
    @classmethod
    def strip_questions(cls, values: list[str]) -> list[str]:
        stripped = [value.strip() for value in values]
        if any(not value for value in stripped):
            raise ValueError("list values must not be blank")
        return stripped


class PaperSeed(ContractModel):
    conference: Literal["CVPR"]
    year: ConferenceYear
    title: str
    authors: list[str] = Field(default_factory=list)
    detail_url: str
    pdf_url: str
    arxiv_url: str | None = None
    conference_day: str

    @field_validator("title", "detail_url", "pdf_url", "conference_day")
    @classmethod
    def strip_required_value(cls, value: str) -> str:
        return _strip_required(value)

    @field_validator("arxiv_url")
    @classmethod
    def strip_optional_value(cls, value: str | None) -> str | None:
        return _strip_required(value) if value is not None else None

    @field_validator("authors")
    @classmethod
    def strip_authors(cls, values: list[str]) -> list[str]:
        stripped = [value.strip() for value in values]
        if any(not value for value in stripped):
            raise ValueError("authors must not contain blank values")
        return stripped


class PaperTask(ContractModel):
    conference: Literal["CVPR"]
    year: ConferenceYear
    title: str
    authors: list[str] = Field(default_factory=list)
    detail_url: str
    pdf_url: str
    paper_key: str
    arxiv_url: str
    arxiv_id: str
    questions: list[str] = Field(min_length=1, max_length=10)
    conference_day: str

    @field_validator("title", "detail_url", "pdf_url", "arxiv_url", "conference_day")
    @classmethod
    def strip_required_value(cls, value: str) -> str:
        return _strip_required(value)

    @field_validator("authors")
    @classmethod
    def strip_authors(cls, values: list[str]) -> list[str]:
        stripped = [value.strip() for value in values]
        if any(not value for value in stripped):
            raise ValueError("authors must not contain blank values")
        return stripped

    @field_validator("paper_key", "arxiv_id")
    @classmethod
    def strip_identity(cls, value: str) -> str:
        return _strip_required(value)

    @field_validator("questions")
    @classmethod
    def strip_questions(cls, values: list[str]) -> list[str]:
        stripped = [value.strip() for value in values]
        if any(not value for value in stripped):
            raise ValueError("questions must not contain blank values")
        return stripped

    @model_validator(mode="after")
    def validate_identity(self) -> Self:
        if self.paper_key != f"arxiv:{self.arxiv_id}":
            raise ValueError("paper_key must equal arxiv:<arxiv_id>")
        return self


class LikesTask(ContractModel):
    paper_key: str
    title: str
    arxiv_url: str
    arxiv_id: str


class LikesResult(ContractModel):
    paper_key: str
    arxiv_id: str
    likes: int | None = Field(default=None, ge=0)
    raw_text: str | None = None
    status: ResultStatus
    error_code: str | None = None

    @model_validator(mode="after")
    def validate_payload(self) -> Self:
        if self.status is ResultStatus.SUCCESS:
            self._validate_success()
        else:
            self._validate_failure()
        return self

    def _validate_success(self) -> None:
        if self.likes is None or self.raw_text is None:
            raise ValueError("SUCCESS requires likes and raw_text")
        if self.error_code is not None:
            raise ValueError("SUCCESS requires null error_code")
        if re.fullmatch(r"\s*[\d,]+\s+Likes?\s*", self.raw_text) is None:
            raise ValueError("raw_text must contain the full Likes control text")
        raw_count = self.raw_text.strip().split()[0].replace(",", "")
        if not raw_count or int(raw_count) != self.likes:
            raise ValueError("likes must match raw_text")

    def _validate_failure(self) -> None:
        if self.likes is not None or self.raw_text is not None:
            raise ValueError("FAILED requires null likes and raw_text")
        if self.error_code is None or not self.error_code.strip():
            raise ValueError("FAILED requires error_code")


class DiscoveryCounts(ContractModel):
    raw_count: int = Field(ge=0)
    unique_count: int = Field(ge=0)
    duplicate_count: int = Field(ge=0)
    failed_page_count: int = Field(ge=0)


class PageFailure(ContractModel):
    url: str
    error_code: str


class RejectedPaperSeed(ContractModel):
    title: str | None = None
    detail_url: str | None = None
    error_code: Literal["INVALID_PAPER_RECORD"] = "INVALID_PAPER_RECORD"


class DiscoveryResult(ContractModel):
    status: RunStatus
    papers: list[PaperSeed] = Field(default_factory=list)
    counts: DiscoveryCounts
    page_failures: list[PageFailure] = Field(default_factory=list)
    rejected_records: list[RejectedPaperSeed] = Field(default_factory=list)


class RejectedPaper(ContractModel):
    title: str
    error_code: str


class SelectionResult(ContractModel):
    paper_tasks: list[PaperTask] = Field(default_factory=list)
    skipped_no_arxiv_link: int = Field(ge=0)
    skipped_topic_mismatch: int = Field(ge=0)
    rejected: list[RejectedPaper] = Field(default_factory=list)


class PaperAnalysis(ContractModel):
    paper_key: str
    research_problem: str
    main_contributions: list[str] = Field(default_factory=list)
    method_summary: str
    datasets: list[str] = Field(default_factory=list)
    key_results: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    code_urls: list[str] = Field(default_factory=list)
    answer_by_question: dict[str, str] = Field(default_factory=dict)
    source_references: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    raw_answer: str | None = None


class AnalysisResult(ContractModel):
    paper_key: str
    status: AnalysisStatus
    analysis: PaperAnalysis | None = None
    error_code: str | None = None
    error_detail: str | None = None
    analysis_mode: AnalysisMode | None = None
    questions: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_payload(self) -> Self:
        if self.status is AnalysisStatus.SUCCESS:
            if self.analysis is None:
                raise ValueError("SUCCESS requires analysis")
            if self.analysis.paper_key != self.paper_key:
                raise ValueError("analysis paper_key must match result paper_key")
            if self.error_code is not None:
                raise ValueError("SUCCESS requires null error_code")
            if self.error_detail is not None:
                raise ValueError("SUCCESS requires null error_detail")
        elif self.analysis is not None or self.error_code is None:
            raise ValueError("FAILED requires null analysis and error_code")
        elif not self.error_code.strip():
            raise ValueError("FAILED requires non-empty error_code")
        return self


class PaperResult(ContractModel):
    paper: PaperTask
    likes: LikesResult
    analysis: PaperAnalysis | None
    status: PaperStatus
    warnings: list[str] = Field(default_factory=list)

    @classmethod
    def from_parts(
        cls,
        paper: PaperTask,
        likes: LikesResult,
        analysis_result: AnalysisResult,
    ) -> Self:
        if analysis_result.paper_key != paper.paper_key:
            raise ValueError("analysis result paper_key must match paper paper_key")
        likes_ok = likes.status is ResultStatus.SUCCESS
        analysis_ok = analysis_result.status is AnalysisStatus.SUCCESS
        if likes_ok and analysis_ok:
            status = PaperStatus.COMPLETED
        elif likes_ok or analysis_ok:
            status = PaperStatus.PARTIAL
        else:
            status = PaperStatus.FAILED
        errors = (likes.error_code, analysis_result.error_code)
        warnings = [code for code in errors if code is not None]
        return cls(
            paper=paper,
            likes=likes,
            analysis=analysis_result.analysis,
            status=status,
            warnings=warnings,
        )

    @model_validator(mode="after")
    def validate_identity(self) -> Self:
        if self.likes.paper_key != self.paper.paper_key:
            raise ValueError("likes paper_key must match paper paper_key")
        if self.likes.arxiv_id != self.paper.arxiv_id:
            raise ValueError("likes arxiv_id must match paper arxiv_id")
        if (
            self.analysis is not None
            and self.analysis.paper_key != self.paper.paper_key
        ):
            raise ValueError("analysis paper_key must match paper paper_key")
        return self


class PaperQARecord(ContractModel):
    paper_key: str
    arxiv_id: str
    title: str
    questions: list[str]
    answer: str | None = None
    status: AnalysisStatus

    @classmethod
    def from_analysis(
        cls, paper: PaperTask, result: AnalysisResult
    ) -> "PaperQARecord":
        if result.paper_key != paper.paper_key:
            raise ValueError("analysis result paper_key must match paper paper_key")
        answer = None
        if result.analysis is not None:
            if result.analysis.answer_by_question:
                answer = "\n\n".join(
                    f"Question: {question}\nAnswer: "
                    f"{result.analysis.answer_by_question[question]}"
                    for question in paper.questions
                    if question in result.analysis.answer_by_question
                )
            else:
                answer = result.analysis.raw_answer or result.analysis.method_summary
            answer = answer or None
        return cls(
            paper_key=paper.paper_key,
            arxiv_id=paper.arxiv_id,
            title=paper.title,
            questions=paper.questions,
            answer=answer,
            status=(
                AnalysisStatus.SUCCESS if answer is not None else AnalysisStatus.FAILED
            ),
        )

    @classmethod
    def from_result(cls, result: PaperResult) -> Self:
        return cls.from_analysis(
            result.paper,
            AnalysisResult(
                paper_key=result.paper.paper_key,
                status=(
                    AnalysisStatus.SUCCESS
                    if result.analysis is not None
                    else AnalysisStatus.FAILED
                ),
                analysis=result.analysis,
                error_code=(
                    None if result.analysis is not None else "MISSING_ANALYSIS_RESULT"
                ),
            ),
        )


class RunCounts(ContractModel):
    discovered: int = Field(ge=0)
    skipped: int = Field(ge=0)
    selected: int = Field(ge=0)
    likes_success: int = Field(ge=0)
    likes_failed: int = Field(ge=0)
    analysis_success: int = Field(ge=0)
    analysis_failed: int = Field(ge=0)
    completed: int = Field(ge=0)
    partial: int = Field(ge=0)
    failed: int = Field(ge=0)


class RunManifest(ContractModel):
    run_id: str
    status: RunStatus
    input: ConferenceRunInput
    started_at: AwareDatetime
    finished_at: AwareDatetime | None = None
    discovered_page_count: int = Field(ge=0)
    counts: RunCounts
    warnings: list[str] = Field(default_factory=list)


def _strip_required(value: str) -> str:
    stripped = value.strip()
    if not stripped:
        raise ValueError("value must not be blank")
    return stripped
