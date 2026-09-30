import hashlib
import json
import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.models import (
    ConferenceEdition,
    ImpactSignal,
    ImportBatch,
    MappingAttempt,
    MappingCandidate,
    Paper,
    PaperAnalysis,
    PaperAnswer,
    PaperAuthor,
    PaperMapping,
    utc_now,
)


PARSER_VERSION = "workbench-import-v1"


class ImportDataError(ValueError):
    pass


@dataclass
class ImportSummary:
    files_seen: int = 0
    files_imported: int = 0
    papers_created: int = 0
    records_updated: int = 0
    unresolved_records: int = 0


def iter_jsonl(path: Path) -> Iterable[dict]:
    with path.open(encoding="utf-8") as source:
        for line_number, line in enumerate(source, start=1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as error:
                raise ImportDataError(f"{path.name}:{line_number}: {error.msg}") from error
            if not isinstance(row, dict):
                raise ImportDataError(f"{path.name}:{line_number}: expected object")
            yield row


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def normalize_text(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).casefold()
    return " ".join(re.findall(r"[^\W_]+", normalized, re.UNICODE))


def parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


class AssetImporter:
    def __init__(self, session: Session, source_root: Path):
        self.session = session
        self.source_root = source_root.resolve()

    def sync(self) -> ImportSummary:
        summary = ImportSummary()
        files = self._source_files()
        summary.files_seen = len(files)
        for kind, path in files:
            checksum = sha256_file(path)
            existing = self.session.scalar(
                select(ImportBatch).where(
                    ImportBatch.source_path == str(path),
                    ImportBatch.sha256 == checksum,
                )
            )
            if existing is not None:
                continue
            records = list(iter_jsonl(path))
            try:
                with self.session.begin_nested():
                    before = summary.records_updated
                    if kind == "mapping":
                        self._import_mappings(records, path, checksum, summary)
                    elif kind == "papers":
                        self._import_run_papers(records, summary)
                    elif kind == "analysis":
                        self._import_analyses(records, path, checksum, summary)
                    else:
                        self._import_likes(records, path, checksum, summary)
                    imported = summary.records_updated - before
                    self.session.add(
                        ImportBatch(
                            source_path=str(path),
                            sha256=checksum,
                            parser_version=PARSER_VERSION,
                            status="SUCCESS",
                            counts={"records": len(records), "updated": imported},
                            finished_at=utc_now(),
                        )
                    )
                self.session.commit()
                summary.files_imported += 1
            except Exception:
                self.session.rollback()
                raise
        return summary

    def _source_files(self) -> list[tuple[str, Path]]:
        found: list[tuple[str, Path]] = []
        mapping_candidates = [
            self.source_root / "eccv-2026-mapping" / "mappings.jsonl",
            self.source_root / "mappings.jsonl",
        ]
        for mapping in mapping_candidates:
            if mapping.is_file():
                found.append(("mapping", mapping.resolve()))
                break
        for path in sorted(self.source_root.rglob("papers.jsonl")):
            found.append(("papers", path.resolve()))
        for path in sorted(self.source_root.rglob("analysis-checkpoint.jsonl")):
            found.append(("analysis", path.resolve()))
        for path in sorted(self.source_root.rglob("likes-checkpoint.jsonl")):
            found.append(("likes", path.resolve()))
        return found

    def _import_mappings(
        self,
        records: list[dict],
        path: Path,
        checksum: str,
        summary: ImportSummary,
    ) -> None:
        for record in records:
            source = record["paper"]
            paper = self._upsert_paper(source, summary)
            edition = self.session.get(ConferenceEdition, paper.conference_edition_id)
            if edition is not None:
                edition.source_url = record.get("source_url")
                edition.source_sha256 = record.get("snapshot_sha256")
            paper.arxiv_id = record.get("arxiv_id")
            paper.arxiv_url = record.get("arxiv_url")
            matcher_version = record.get("matcher_version") or "unknown"
            mapping = self.session.scalar(
                select(PaperMapping).where(
                    PaperMapping.paper_id == paper.id,
                    PaperMapping.matcher_version == matcher_version,
                )
            )
            if mapping is None:
                mapping = PaperMapping(
                    paper_id=paper.id,
                    matcher_version=matcher_version,
                    status=record["status"],
                    source_path=str(path),
                    source_sha256=checksum,
                )
                self.session.add(mapping)
                self.session.flush()
            mapping.status = record["status"]
            mapping.reason = record.get("reason")
            mapping.arxiv_id = record.get("arxiv_id")
            mapping.arxiv_url = record.get("arxiv_url")
            mapping.checked_at = parse_datetime(record.get("checked_at"))
            mapping.source_path = str(path)
            mapping.source_sha256 = checksum
            mapping.evidence = {
                "fingerprint": record.get("fingerprint"),
                "snapshot_sha256": record.get("snapshot_sha256"),
                "source_url": record.get("source_url"),
            }
            self.session.execute(
                delete(MappingCandidate).where(MappingCandidate.mapping_id == mapping.id)
            )
            self.session.execute(
                delete(MappingAttempt).where(MappingAttempt.mapping_id == mapping.id)
            )
            for candidate in record.get("candidates", []):
                self.session.add(
                    MappingCandidate(
                        mapping_id=mapping.id,
                        arxiv_id=candidate["arxiv_id"],
                        title=candidate["title"],
                        authors=candidate.get("authors", []),
                        title_exact=bool(candidate.get("title_exact")),
                        title_similarity=float(candidate.get("title_similarity", 0)),
                        author_agreement=float(candidate.get("author_agreement", 0)),
                        eligible=bool(candidate.get("eligible")),
                        evidence=candidate,
                    )
                )
            for attempt in record.get("attempts", []):
                self.session.add(
                    MappingAttempt(
                        mapping_id=mapping.id,
                        kind=attempt["kind"],
                        query=attempt["query"],
                        started_at=parse_datetime(attempt.get("started_at")),
                        returned_count=attempt.get("returned"),
                    )
                )
            summary.records_updated += 1

    def _import_run_papers(
        self, records: list[dict], summary: ImportSummary
    ) -> None:
        for source in self._latest_records(records):
            self._upsert_paper(source, summary)
            summary.records_updated += 1

    def _import_analyses(
        self,
        records: list[dict],
        path: Path,
        checksum: str,
        summary: ImportSummary,
    ) -> None:
        run_id = path.parent.name
        for record in self._latest_records(records):
            paper = self._paper_for_key(record.get("paper_key", ""))
            if paper is None:
                summary.unresolved_records += 1
                continue
            questions = record.get("questions") or []
            question_hash = hashlib.sha256(
                json.dumps(questions, ensure_ascii=False).encode("utf-8")
            ).hexdigest()
            mode = record.get("analysis_mode") or "unknown"
            analysis = self.session.scalar(
                select(PaperAnalysis).where(
                    PaperAnalysis.paper_id == paper.id,
                    PaperAnalysis.analysis_mode == mode,
                    PaperAnalysis.question_set_hash == question_hash,
                )
            )
            if analysis is None:
                analysis = PaperAnalysis(
                    paper_id=paper.id,
                    run_id=run_id,
                    status=record["status"],
                    analysis_mode=mode,
                    question_set_hash=question_hash,
                    source_path=str(path),
                    source_sha256=checksum,
                )
                self.session.add(analysis)
                self.session.flush()
            analysis.run_id = run_id
            analysis.status = record["status"]
            analysis.questions = questions
            analysis.payload = record.get("analysis")
            analysis.error_code = record.get("error_code")
            analysis.error_detail = record.get("error_detail")
            analysis.model = record.get("model")
            analysis.source_path = str(path)
            analysis.source_sha256 = checksum
            self.session.execute(
                delete(PaperAnswer).where(PaperAnswer.analysis_id == analysis.id)
            )
            payload = record.get("analysis") or {}
            answers = payload.get("answer_by_question") or {}
            for position, question in enumerate(questions):
                if question not in answers:
                    continue
                self.session.add(
                    PaperAnswer(
                        analysis_id=analysis.id,
                        position=position,
                        question=question,
                        answer=str(answers[question]),
                        source_references=payload.get("source_references", []),
                        warnings=payload.get("warnings", []),
                    )
                )
            summary.records_updated += 1

    def _import_likes(
        self,
        records: list[dict],
        path: Path,
        checksum: str,
        summary: ImportSummary,
    ) -> None:
        for record in self._latest_records(records):
            paper = self._paper_for_key(record.get("paper_key", ""))
            if paper is None:
                summary.unresolved_records += 1
                continue
            signal = self.session.scalar(
                select(ImpactSignal).where(
                    ImpactSignal.paper_id == paper.id,
                    ImpactSignal.source == "alphaxiv_likes",
                    ImpactSignal.source_sha256 == checksum,
                )
            )
            if signal is None:
                signal = ImpactSignal(
                    paper_id=paper.id,
                    source="alphaxiv_likes",
                    status=record["status"],
                    source_path=str(path),
                    source_sha256=checksum,
                )
                self.session.add(signal)
            signal.value = record.get("likes")
            signal.raw_text = record.get("raw_text")
            signal.status = record["status"]
            signal.error_code = record.get("error_code")
            signal.source_path = str(path)
            signal.source_sha256 = checksum
            summary.records_updated += 1

    def _paper_for_key(self, paper_key: str) -> Paper | None:
        prefix = "arxiv:"
        if not paper_key.startswith(prefix):
            return None
        return self.session.scalar(
            select(Paper).where(Paper.arxiv_id == paper_key.removeprefix(prefix))
        )

    def _upsert_paper(self, source: dict, summary: ImportSummary) -> Paper:
        edition = self.session.scalar(
            select(ConferenceEdition).where(
                ConferenceEdition.conference == source["conference"],
                ConferenceEdition.year == int(source["year"]),
            )
        )
        if edition is None:
            edition = ConferenceEdition(
                conference=source["conference"],
                year=int(source["year"]),
            )
            self.session.add(edition)
            self.session.flush()
        normalized_title = normalize_text(source["title"])
        paper = self.session.scalar(
            select(Paper).where(
                Paper.conference_edition_id == edition.id,
                Paper.normalized_title == normalized_title,
            )
        )
        if paper is None:
            paper = Paper(
                conference_edition_id=edition.id,
                title=source["title"],
                normalized_title=normalized_title,
            )
            self.session.add(paper)
            self.session.flush()
            summary.papers_created += 1
        paper.title = source["title"]
        paper.topic = source.get("topic") or source.get("conference_day")
        paper.detail_url = source.get("detail_url")
        paper.pdf_url = source.get("pdf_url")
        paper.arxiv_id = source.get("arxiv_id") or paper.arxiv_id
        paper.arxiv_url = source.get("arxiv_url") or paper.arxiv_url
        paper.source_payload = source
        self.session.execute(delete(PaperAuthor).where(PaperAuthor.paper_id == paper.id))
        for position, name in enumerate(source.get("authors", [])):
            self.session.add(
                PaperAuthor(
                    paper_id=paper.id,
                    position=position,
                    name=name,
                    normalized_name=normalize_text(name),
                )
            )
        return paper

    @staticmethod
    def _latest_records(records: list[dict]) -> list[dict]:
        latest = {}
        for record in records:
            key = record.get("paper_key") or record.get("arxiv_id")
            if key:
                latest[key] = record
        return list(latest.values())
