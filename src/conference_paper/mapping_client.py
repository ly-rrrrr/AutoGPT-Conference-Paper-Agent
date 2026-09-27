import hashlib
import json
import os
import shutil
import subprocess
import time
import xml.etree.ElementTree as ET
from collections import defaultdict
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode, urlparse

from .arxiv_mapping import MATCHER_VERSION, parse_feed
from .eccv_catalog import CatalogPaper

API_URL = "https://export.arxiv.org/api/query"
USER_AGENT = "ConferencePaperAgent/0.2 (+https://github.com/ly-rrrrr/AutoGPT-Conference-Paper-Agent)"


class FetchError(RuntimeError):
    pass


def fetch_text(url: str) -> str:
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.netloc not in {
        "eccv.ecva.net",
        "export.arxiv.org",
    }:
        raise ValueError("Unexpected remote source")
    timeout = 180 if parsed.netloc == "eccv.ecva.net" else 45
    command = [
        "curl",
        "--silent",
        "--show-error",
        "--compressed",
        "--proto",
        "=https",
        "--connect-timeout",
        "10",
        "--max-time",
        str(timeout),
        "--max-filesize",
        "15000000",
        "--user-agent",
        USER_AGENT,
        "--write-out",
        "\n%{http_code}",
        url,
    ]
    try:
        result = subprocess.run(
            command, capture_output=True, timeout=timeout + 5, check=False
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise FetchError(f"curl transport failed: {type(error).__name__}") from error
    if result.returncode:
        raise FetchError(
            f"curl exit {result.returncode}: {result.stderr.decode('utf-8', 'replace').strip()[:300]}"
        )
    body, _, status = result.stdout.rpartition(b"\n")
    if status != b"200":
        raise FetchError(f"HTTP {status.decode('ascii', 'replace')}")
    return body.decode("utf-8")


def atomic_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(text)
        handle.flush()
        os.fsync(handle.fileno())
    temporary.replace(path)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def fingerprint(paper: CatalogPaper) -> str:
    value = json.dumps(
        {"paper": asdict(paper), "matcher": MATCHER_VERSION},
        sort_keys=True,
        ensure_ascii=False,
    )
    return hashlib.sha256(value.encode()).hexdigest()


def sample_papers(papers: list[CatalogPaper], limit: int) -> list[CatalogPaper]:
    if limit < 0:
        raise ValueError("limit must not be negative")
    groups = defaultdict(list)
    for paper in papers:
        groups[paper.topic].append(paper)
    for group in groups.values():
        group.sort(
            key=lambda paper: hashlib.sha256(paper.paper_id.encode()).hexdigest()
        )
    result = []
    for index in range(max(map(len, groups.values()), default=0)):
        for topic in sorted(groups):
            if index < len(groups[topic]):
                result.append(groups[topic][index])
    return result[:limit] if limit else result


def load_checkpoint(path: Path) -> dict:
    if not path.exists():
        return {}
    raw = path.read_bytes()
    lines = raw.splitlines(keepends=True)
    state = {}
    for index, line in enumerate(lines):
        try:
            record = json.loads(line)
            state[record["fingerprint"]] = record
        except (ValueError, KeyError, TypeError) as error:
            if index != len(lines) - 1 or line.endswith(b"\n"):
                raise ValueError(
                    f"Corrupt checkpoint at line {index + 1}: {path}"
                ) from error
            backup = path.with_name(path.name + f".interrupted-{time.time_ns()}")
            shutil.copy2(path, backup)
            atomic_text(path, b"".join(lines[:index]).decode("utf-8"))
            break
    else:
        if raw and not raw.endswith(b"\n"):
            with path.open("ab") as handle:
                handle.write(b"\n")
    return state


def append_checkpoint(path: Path, record: dict) -> None:
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")
        handle.flush()
        os.fsync(handle.fileno())


class ArxivClient:
    def __init__(
        self,
        cache: Path,
        fetch=fetch_text,
        clock=time.monotonic,
        sleep=time.sleep,
        refresh=False,
    ):
        self.cache = cache
        self.cache.mkdir(parents=True, exist_ok=True)
        self.fetch = fetch
        self.clock = clock
        self.sleep = sleep
        self.refresh = refresh
        self.last_request = None
        self.network_requests = 0
        self.cache_hits = 0

    def search(self, query: str):
        return self.request({"search_query": query, "start": 0, "max_results": 20})

    def by_id(self, identifier: str):
        return self.request({"id_list": identifier, "max_results": 20})

    def request(self, parameters: dict):
        url = API_URL + "?" + urlencode(parameters)
        key = hashlib.sha256(url.encode()).hexdigest()
        path = self.cache / (key + ".xml")
        if path.exists() and not self.refresh:
            xml = path.read_text(encoding="utf-8")
            candidates = self.validate(xml)
            self.cache_hits += 1
            return candidates
        for attempt in range(2):
            if self.last_request is not None:
                self.sleep(max(0, 3.1 - (self.clock() - self.last_request)))
            self.last_request = self.clock()
            self.network_requests += 1
            try:
                xml = self.fetch(url)
                candidates = self.validate(xml)
            except FetchError as error:
                if attempt == 1 or "HTTP 429" in str(error) or "HTTP 403" in str(error):
                    raise
                self.sleep(5)
                continue
            atomic_text(path, xml)
            atomic_text(
                self.cache / (key + ".json"),
                json.dumps({"url": url, "retrieved_at": utc_now()}, indent=2),
            )
            return candidates
        raise FetchError("arXiv request failed")

    @staticmethod
    def validate(xml: str):
        candidates = parse_feed(xml)
        root = ET.fromstring(xml)
        total = root.findtext("{http://a9.com/-/spec/opensearch/1.1/}totalResults")
        if total is not None and int(total) > len(
            root.findall("{http://www.w3.org/2005/Atom}entry")
        ):
            raise ValueError(
                "Candidate search is truncated; narrow the query before confirming identity"
            )
        return candidates
