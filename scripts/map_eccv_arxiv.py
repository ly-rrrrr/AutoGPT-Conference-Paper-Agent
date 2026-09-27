import argparse
import hashlib
import json
import os
import sys
import xml.etree.ElementTree as ET
from collections import Counter
from dataclasses import asdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from conference_paper.arxiv_mapping import MATCHER_VERSION, arxiv_id, decide, queries
from conference_paper.eccv_catalog import SOURCE_URL, parse_catalog
from conference_paper.mapping_client import (
    ArxivClient,
    FetchError,
    append_checkpoint,
    atomic_text,
    fetch_text,
    fingerprint,
    load_checkpoint,
    sample_papers,
    utc_now,
)


def jsonl(records) -> str:
    return "".join(json.dumps(record, ensure_ascii=False) + "\n" for record in records)


def resolve(paper, client):
    candidates = {}
    attempts = []
    record = {
        "paper": asdict(paper),
        "fingerprint": fingerprint(paper),
        "checked_at": utc_now(),
        "source_url": SOURCE_URL,
        "attempts": attempts,
    }
    try:
        identifiers = list(
            dict.fromkeys(
                identifier
                for url in paper.project_urls
                if (identifier := arxiv_id(url))
            )
        )
        searches = [("id", identifier) for identifier in identifiers] + [
            ("title", query) for query in queries(paper)
        ]
        for kind, query in searches:
            attempt = {"kind": kind, "query": query, "started_at": utc_now()}
            attempts.append(attempt)
            found = client.by_id(query) if kind == "id" else client.search(query)
            attempt["returned"] = len(found)
            candidates.update((candidate.arxiv_id, candidate) for candidate in found)
            result = decide(paper, list(candidates.values()))
            if result["status"] == "matched":
                return {**record, **result}
        return {**record, **decide(paper, list(candidates.values()))}
    except (FetchError, ValueError, ET.ParseError) as error:
        result = decide(paper, list(candidates.values()))
        return {
            **record,
            **result,
            "status": "error",
            "arxiv_id": None,
            "arxiv_url": None,
            "reason": str(error),
            "error_type": type(error).__name__,
        }


def export(output, papers, selected, state, client, snapshot_hash, statistics):
    results = [
        state[fingerprint(paper)] for paper in selected if fingerprint(paper) in state
    ]
    atomic_text(output / "mappings.jsonl", jsonl(results))
    atomic_text(
        output / "matched-papers.jsonl",
        jsonl(record for record in results if record["status"] == "matched"),
    )
    counts = Counter(record["status"] for record in results)
    summary = {
        **statistics,
        "source_url": SOURCE_URL,
        "snapshot_sha256": snapshot_hash,
        "updated_at": utc_now(),
        "matcher_version": MATCHER_VERSION,
        "catalog_count": len(papers),
        "selected_count": len(selected),
        "processed_count": len(results),
        "pending_count": len(selected) - len(results),
        "status_counts": dict(counts),
        "network_requests_this_run": client.network_requests,
        "cache_hits_this_run": client.cache_hits,
        "topic_count": len({p.topic for p in selected}),
        "complete": len(results) == len(selected) and not counts["error"],
        "note": "Matched means conservative automatic metadata agreement, not independent manual validation. not_found means no candidates in the attempted queries, not proof of absence.",
    }
    atomic_text(
        output / "summary.json",
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
    )
    return summary


def run(args):
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    lock = output / ".mapping.lock"
    try:
        descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        raise SystemExit(
            f"Run already locked: {lock}. If interrupted, verify no mapping process is running before removing this lock."
        )
    os.close(descriptor)
    try:
        snapshot = output / "accepted-papers.html"
        if snapshot.exists():
            html = snapshot.read_text(encoding="utf-8")
        else:
            html = fetch_text(SOURCE_URL)
        statistics = {}
        papers = parse_catalog(html, statistics)
        if not snapshot.exists():
            atomic_text(snapshot, html)
            atomic_text(
                output / "source.json",
                json.dumps({"url": SOURCE_URL, "retrieved_at": utc_now()}, indent=2),
            )
        snapshot_hash = hashlib.sha256(snapshot.read_bytes()).hexdigest()
        atomic_text(output / "catalog.jsonl", jsonl(asdict(paper) for paper in papers))
        selected = sample_papers(papers, args.limit)
        checkpoint = output / "mapping-checkpoint.jsonl"
        state = load_checkpoint(checkpoint)
        client = ArxivClient(output / "arxiv-cache", refresh=args.refresh_cache)
        consecutive_errors = 0
        print(
            f"Catalog: {len(papers)}; sample: {len(selected)}; topics: {len({p.topic for p in selected})}",
            flush=True,
        )
        try:
            for index, paper in enumerate(selected, 1):
                key = fingerprint(paper)
                previous = state.get(key)
                if (
                    previous
                    and previous.get("snapshot_sha256") == snapshot_hash
                    and previous["status"] != "error"
                    and not (args.retry_unresolved and previous["status"] != "matched")
                ):
                    print(
                        f"[{index}/{len(selected)}] cached {previous['status']} {paper.title}",
                        flush=True,
                    )
                    continue
                record = resolve(paper, client)
                record["snapshot_sha256"] = snapshot_hash
                append_checkpoint(checkpoint, record)
                state[key] = record
                print(
                    f"[{index}/{len(selected)}] {record['status']} {paper.title}",
                    flush=True,
                )
                consecutive_errors = (
                    consecutive_errors + 1 if record["status"] == "error" else 0
                )
                if record["status"] == "error":
                    print(f"  {record['reason']}", flush=True)
                if consecutive_errors >= 3 or (
                    record["status"] == "error"
                    and any(
                        code in record["reason"] for code in ["HTTP 429", "HTTP 403"]
                    )
                ):
                    print(
                        "Stopped after service errors; resume with the same output directory.",
                        flush=True,
                    )
                    break
        finally:
            summary = export(
                output, papers, selected, state, client, snapshot_hash, statistics
            )
            print(json.dumps(summary, ensure_ascii=False, indent=2), flush=True)
        return 0 if summary["complete"] else 2
    finally:
        lock.unlink()


def main():
    parser = argparse.ArgumentParser(
        description="Map official ECCV 2026 papers to verified arXiv metadata; no LLM required."
    )
    parser.add_argument("--output", type=Path, default=Path("data/eccv-2026-mapping"))
    parser.add_argument(
        "--limit",
        type=int,
        default=50,
        help="Topic-stratified sample size; 0 processes all papers",
    )
    parser.add_argument(
        "--retry-unresolved",
        action="store_true",
        help="Revisit not_found and needs_review records",
    )
    parser.add_argument(
        "--refresh-cache",
        action="store_true",
        help="Fetch fresh arXiv responses for queries actually retried",
    )
    args = parser.parse_args()
    if args.limit < 0:
        parser.error("--limit must be >= 0")
    return run(args)


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(130)
    except (FetchError, ValueError) as error:
        print(str(error), file=sys.stderr)
        sys.exit(2)
