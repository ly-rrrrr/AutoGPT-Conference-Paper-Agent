from pydantic import field_validator

from backend.blocks._base import (
    Block,
    BlockCategory,
    BlockOutput,
    BlockSchemaInput,
    BlockSchemaOutput,
)
from backend.blocks.conference_paper.models import (
    DiscoveryResult,
    PaperTask,
    RejectedPaper,
    SelectionResult,
)
from backend.blocks.conference_paper.urls import parse_arxiv_id
from backend.data.model import SchemaField


class SelectConferencePapersBlock(Block):
    class Input(BlockSchemaInput):
        discovery: DiscoveryResult = SchemaField(
            description="Discovered conference paper records"
        )
        topics: list[str] = SchemaField(
            default_factory=list,
            description="Optional title keywords; empty means all papers",
        )
        paper_questions: list[str] = SchemaField(
            min_length=1,
            max_length=10,
            description="Questions to answer for each selected paper",
        )
        max_papers: int = SchemaField(
            default=0,
            ge=0,
            le=10_000,
            description="Maximum papers to select; 0 means all matching papers",
        )

        @field_validator("topics", "paper_questions")
        @classmethod
        def strip_non_empty_values(cls, values: list[str]) -> list[str]:
            stripped = [value.strip() for value in values]
            if any(not value for value in stripped):
                raise ValueError("list values must not be blank")
            return stripped

    class Output(BlockSchemaOutput):
        selection: SelectionResult = SchemaField(
            description="Deterministically selected arXiv-backed papers"
        )

    def __init__(self):
        super().__init__(
            id="a8c7e1d2-5b64-4f90-9a31-2d6e8b4c7f05",
            description="Selects arXiv-backed conference papers by title topic.",
            categories={BlockCategory.SEARCH},
            input_schema=SelectConferencePapersBlock.Input,
            output_schema=SelectConferencePapersBlock.Output,
        )

    async def run(self, input_data: Input, **kwargs) -> BlockOutput:
        selection = select_papers(
            discovery=input_data.discovery,
            topics=input_data.topics,
            questions=input_data.paper_questions,
            max_papers=input_data.max_papers,
        )
        yield "selection", selection


def normalize_title(title: str) -> str:
    return " ".join(title.casefold().split())


def select_papers(
    discovery: DiscoveryResult,
    topics: list[str],
    questions: list[str],
    max_papers: int,
) -> SelectionResult:
    _validate_parameters(topics, questions, max_papers)
    normalized_topics = [normalize_title(topic) for topic in topics]
    candidates: list[PaperTask] = []
    rejected: list[RejectedPaper] = []
    skipped_no_arxiv_link = 0
    skipped_topic_mismatch = 0

    for seed in discovery.papers:
        if seed.arxiv_url is None:
            skipped_no_arxiv_link += 1
            continue
        if normalized_topics and not any(
            topic in normalize_title(seed.title) for topic in normalized_topics
        ):
            skipped_topic_mismatch += 1
            continue
        try:
            arxiv_id = parse_arxiv_id(seed.arxiv_url)
        except ValueError:
            rejected.append(
                RejectedPaper(title=seed.title, error_code="INVALID_ARXIV_URL")
            )
            continue
        candidates.append(
            PaperTask(
                **seed.model_dump(),
                paper_key=f"arxiv:{arxiv_id}",
                arxiv_id=arxiv_id,
                questions=questions,
            )
        )

    candidates.sort(key=lambda paper: (normalize_title(paper.title), paper.detail_url))
    return SelectionResult(
        paper_tasks=candidates if max_papers == 0 else candidates[:max_papers],
        skipped_no_arxiv_link=skipped_no_arxiv_link,
        skipped_topic_mismatch=skipped_topic_mismatch,
        rejected=rejected,
    )


def _validate_parameters(
    topics: list[str], questions: list[str], max_papers: int
) -> None:
    if not 0 <= max_papers <= 10_000:
        raise ValueError("max_papers must be between 0 and 10000")
    if any(not topic.strip() for topic in topics):
        raise ValueError("topics must not contain blank values")
    if not 1 <= len(questions) <= 10 or any(
        not question.strip() for question in questions
    ):
        raise ValueError("questions must contain 1 to 10 non-blank values")
