import json
from pathlib import Path

from pydantic import ValidationError

from backend.blocks.conference_paper.models import (
    DiscoveryCounts,
    DiscoveryResult,
    PaperSeed,
    RunStatus,
)
from backend.blocks.conference_paper.urls import parse_arxiv_id


def load_eccv_mapping(path: Path) -> DiscoveryResult:
    papers: list[PaperSeed] = []
    seen_arxiv_ids: set[str] = set()
    raw_count = 0

    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as error:
        raise ValueError("ECCV_MAPPING_UNAVAILABLE") from error

    for line in lines:
        if not line.strip():
            continue
        raw_count += 1
        try:
            record = json.loads(line)
        except json.JSONDecodeError as error:
            raise ValueError("INVALID_ECCV_MAPPING") from error
        if record.get("status") != "matched":
            continue
        try:
            paper = _matched_record_to_seed(record)
            arxiv_id = parse_arxiv_id(paper.arxiv_url or "")
        except (KeyError, TypeError, ValidationError, ValueError) as error:
            raise ValueError("INVALID_ECCV_MAPPING") from error
        if arxiv_id in seen_arxiv_ids:
            raise ValueError("DUPLICATE_ARXIV_ID")
        seen_arxiv_ids.add(arxiv_id)
        papers.append(paper)

    return DiscoveryResult(
        status=RunStatus.COMPLETED,
        papers=papers,
        counts=DiscoveryCounts(
            raw_count=raw_count,
            unique_count=len(papers),
            duplicate_count=0,
            failed_page_count=0,
        ),
    )


def resolve_mapping_path(mapping_root: Path, mapping_file: str) -> Path:
    if not mapping_file or Path(mapping_file).is_absolute():
        raise ValueError("INVALID_ECCV_MAPPING_PATH")
    root = mapping_root.resolve()
    path = (root / mapping_file).resolve()
    if path == root or root not in path.parents:
        raise ValueError("INVALID_ECCV_MAPPING_PATH")
    return path


def _matched_record_to_seed(record: dict) -> PaperSeed:
    metadata = record["paper"]
    arxiv_id = record["arxiv_id"]
    arxiv_url = record["arxiv_url"]
    if not isinstance(arxiv_id, str) or not isinstance(arxiv_url, str):
        raise ValueError("INVALID_ECCV_MAPPING")
    if parse_arxiv_id(arxiv_url) != arxiv_id:
        raise ValueError("INVALID_ECCV_MAPPING")
    context = " | ".join(
        value.strip()
        for value in [metadata.get("topic", ""), metadata.get("presentation", "")]
        if isinstance(value, str) and value.strip()
    )
    return PaperSeed(
        conference="ECCV",
        year=2026,
        title=metadata["title"],
        authors=metadata.get("authors", []),
        detail_url=metadata["detail_url"],
        pdf_url=f"https://arxiv.org/pdf/{arxiv_id}",
        arxiv_url=arxiv_url,
        conference_day=context or "ECCV 2026",
    )
