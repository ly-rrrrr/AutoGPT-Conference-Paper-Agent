import hashlib
from pathlib import Path
from urllib.parse import urlparse
from uuid import UUID

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.database import session_scope
from app.lineage_parser import parse_grobid_tei
from app.lineage_service import EXTRACTOR, EXTRACTOR_VERSION, ingest_lineage
from app.models import DocumentAsset, Paper, PipelineRun


TRUSTED_PDF_HOSTS = {
    "arxiv.org",
    "export.arxiv.org",
    "www.ecva.net",
    "eccv.ecva.net",
    "openaccess.thecvf.com",
}


class LineageExtractionError(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def _asset(session: Session, paper_id: UUID, kind: str) -> DocumentAsset:
    item = session.scalar(
        select(DocumentAsset).where(
            DocumentAsset.paper_id == paper_id,
            DocumentAsset.kind == kind,
        )
    )
    if item is None:
        item = DocumentAsset(paper_id=paper_id, kind=kind, status="MISSING")
        session.add(item)
        session.flush()
    return item


def _trusted_pdf_url(url: str) -> bool:
    parsed = urlparse(url)
    return parsed.scheme == "https" and (parsed.hostname or "").casefold() in TRUSTED_PDF_HOSTS


def _pdf_source_url(paper: Paper) -> str | None:
    if paper.pdf_url:
        return paper.pdf_url
    if paper.arxiv_id:
        return f"https://arxiv.org/pdf/{paper.arxiv_id}"
    return None


def _download_pdf(paper: Paper, target: Path, settings: Settings) -> str:
    source_url = _pdf_source_url(paper)
    if not source_url or not _trusted_pdf_url(source_url):
        raise LineageExtractionError(
            "PDF_SOURCE_MISSING",
            "论文没有可用的受信任 HTTPS PDF 地址",
        )
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(".part")
    digest = hashlib.sha256()
    total = 0
    try:
        with httpx.stream(
            "GET",
            source_url,
            follow_redirects=True,
            timeout=60,
            headers={"User-Agent": "ResearchAtlas/0.2"},
        ) as response:
            response.raise_for_status()
            if not _trusted_pdf_url(str(response.url)):
                raise LineageExtractionError(
                    "PDF_DOWNLOAD_FAILED",
                    "PDF 重定向到了未受信任的域名",
                )
            content_type = response.headers.get("content-type", "").casefold()
            if "pdf" not in content_type and not str(response.url).casefold().endswith(".pdf"):
                raise LineageExtractionError("PDF_DOWNLOAD_FAILED", "远程地址没有返回 PDF")
            with temporary.open("wb") as output:
                for chunk in response.iter_bytes():
                    total += len(chunk)
                    if total > settings.max_pdf_bytes:
                        raise LineageExtractionError("PDF_TOO_LARGE", "PDF 超过工作台配置的大小上限")
                    digest.update(chunk)
                    output.write(chunk)
        temporary.replace(target)
        return digest.hexdigest()
    except LineageExtractionError:
        temporary.unlink(missing_ok=True)
        raise
    except (OSError, httpx.HTTPError) as error:
        temporary.unlink(missing_ok=True)
        raise LineageExtractionError("PDF_DOWNLOAD_FAILED", str(error)) from error


def _grobid_tei(pdf_path: Path, settings: Settings) -> str:
    endpoint = f"{settings.grobid_url.rstrip('/')}/api/processFulltextDocument"
    try:
        with pdf_path.open("rb") as source:
            response = httpx.post(
                endpoint,
                files={"input": (pdf_path.name, source, "application/pdf")},
                data={
                    "consolidateHeader": "0",
                    "consolidateCitations": "0",
                    "includeRawCitations": "1",
                    "segmentSentences": "1",
                    "teiCoordinates": ["ref", "biblStruct"],
                },
                timeout=settings.grobid_timeout_seconds,
            )
    except (OSError, httpx.ConnectError, httpx.TimeoutException) as error:
        raise LineageExtractionError(
            "PARSER_UNAVAILABLE",
            f"GROBID 不可用：{error}",
        ) from error
    if response.status_code == 204 or not response.text.strip():
        raise LineageExtractionError("PARSER_EMPTY_RESULT", "GROBID 没有解析出内容")
    try:
        response.raise_for_status()
    except httpx.HTTPError as error:
        raise LineageExtractionError(
            "PARSER_FAILED",
            f"GROBID 返回 HTTP {response.status_code}",
        ) from error
    return response.text


def extract_lineage(session: Session, paper: Paper, settings: Settings | None = None) -> dict:
    settings = settings or get_settings()
    paper_root = settings.asset_root.resolve() / "papers" / str(paper.id)
    pdf_path = paper_root / "source.pdf"
    pdf_asset = _asset(session, paper.id, "pdf")
    if pdf_path.is_file():
        pdf_sha256 = hashlib.sha256(pdf_path.read_bytes()).hexdigest()
    else:
        pdf_asset.status = "DOWNLOADING"
        session.flush()
        pdf_sha256 = _download_pdf(paper, pdf_path, settings)
    pdf_asset.status = "AVAILABLE"
    pdf_asset.path = str(pdf_path)
    pdf_asset.sha256 = pdf_sha256

    tei_asset = _asset(session, paper.id, "grobid_tei")
    tei_asset.status = "PARSING"
    session.flush()
    tei_xml = _grobid_tei(pdf_path, settings)
    tei_path = paper_root / "grobid.tei.xml"
    tei_path.write_text(tei_xml, encoding="utf-8")
    tei_sha256 = hashlib.sha256(tei_xml.encode("utf-8")).hexdigest()
    parsed = parse_grobid_tei(tei_xml)
    summary = ingest_lineage(session, paper, parsed, str(tei_path), tei_sha256)
    tei_asset.status = "PARSED"
    tei_asset.path = str(tei_path)
    tei_asset.sha256 = tei_sha256
    tei_asset.parser = EXTRACTOR
    tei_asset.parser_version = EXTRACTOR_VERSION
    tei_asset.last_error = None
    return {
        "references": summary.references,
        "evidence": summary.evidence,
        "warnings": summary.warnings,
    }


def execute_lineage_run(run_id: UUID, paper_id: UUID) -> None:
    with session_scope() as session:
        run = session.get(PipelineRun, run_id)
        paper = session.get(Paper, paper_id)
        if run is None or paper is None:
            return
        run.status = "RUNNING"
        session.commit()
        try:
            run.counters = extract_lineage(session, paper)
            run.status = "SUCCESS"
        except LineageExtractionError as error:
            run.status = "FAILED"
            run.counters = {"error_code": error.code, "error_detail": str(error)}
            tei_asset = _asset(session, paper.id, "grobid_tei")
            tei_asset.status = "FAILED"
            tei_asset.last_error = f"{error.code}: {error}"
        except Exception as error:
            run.status = "FAILED"
            run.counters = {"error_code": "UNEXPECTED_ERROR", "error_detail": str(error)}


def grobid_ready(settings: Settings | None = None) -> bool:
    settings = settings or get_settings()
    try:
        response = httpx.get(f"{settings.grobid_url.rstrip('/')}/api/isalive", timeout=1)
        return response.status_code == 200
    except httpx.HTTPError:
        return False
