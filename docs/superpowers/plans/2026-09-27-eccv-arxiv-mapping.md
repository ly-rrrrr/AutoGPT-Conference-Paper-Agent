# ECCV arXiv Mapping Implementation Plan

> **For agentic workers:** Execute inline using superpowers:executing-plans, task by task.

**Goal:** Build and exercise a conservative, resumable ECCV 2026 to arXiv mapping stage without requiring AutoGPT, OAuth, or an LLM.

**Architecture:** Parse the official accepted-paper HTML into a complete catalog. Query arXiv's Atom API for candidates and accept only a unique normalized exact-title match with strong full-author agreement. Preserve all candidates and evidence; changed titles remain reviewable, transport failures remain errors. This stage precedes Platform integration and does not run paid analysis.

**Tech Stack:** Python 3.10+ standard library, curl HTTPS transport, unittest.

### Task 1: Official catalog and conservative matcher

Files: `src/conference_paper/eccv_catalog.py`, `src/conference_paper/arxiv_mapping.py`, `tests/test_eccv_mapping.py`.

- [x] Write offline tests for official table parsing, missing authors, duplicate IDs, misleading external URLs, exact titles, author disagreement, ambiguous candidates, version deduplication, and changed titles.
- [x] Run `python -m unittest discover -s tests -v`; establish expected missing-module failures.
- [x] Implement immutable metadata records and pure parsing/matching functions. Normalize Unicode/case/punctuation; require exact normalized title, at least two matching full names (all names for a one-author paper), and >=80% agreement on both author lists. Never accept initials-only or surname-only overlap. Distinct plausible IDs require review.
- [x] Re-run offline tests.

### Task 2: API transport and durable CLI

Files: `src/conference_paper/mapping_client.py`, `scripts/map_eccv_arxiv.py`, `tests/test_mapping_client.py`.

- [x] Test Atom parsing (including API error feeds), exact/fallback query encoding, cache reuse, rate limits, transient failure handling, stale input fingerprints, and recovery from incomplete final JSONL records.
- [x] Implement a serial curl client with a hard timeout, HTTPS-only fixed hosts, >=3.1s request spacing, bounded retries, and validated-response caching. Query full title, then distinctive title words with author surname only for candidate retrieval. Direct arXiv links use ID lookup and the same metadata checks.
- [x] CLI saves `accepted-papers.html`, `catalog.jsonl`, append-only `mapping-checkpoint.jsonl`, current `mappings.jsonl`, `matched-papers.jsonl`, and `summary.json`. Deterministic topic-stratified sampling defaults to 50; full catalog always persists. `--limit 0` processes all. Keep unresolved/errors and provenance explicit. Exit nonzero on incomplete network runs.
- [x] Run offline suite and `python scripts/map_eccv_arxiv.py --help`.

### Task 3: Real smoke run, review, documentation

Files: `docs/eccv-arxiv-mapping.md`, `README.md`.

- [x] Fetch the current official list, confirm unique IDs/count and inspect raw parsed examples.
- [x] Run a 3-paper connectivity smoke check, then a 50-paper stratified sample if API access works. If service requests fail repeatedly, retain diagnostics and stop the batch instead of reporting zero matches or hammering the service.
- [x] Review actual accepted candidates against official titles/authors; report observed coverage separately from measured precision (no unsupported accuracy claim).
- [x] Run all new tests, syntax checks, formatter/linter when available, and `git diff --check`; document exact commands, statuses, constraints and artifacts.

## Scope boundaries

No arbitrary project-page crawler, no title-similarity-only automatic acceptance, no LLM adjudication, no paid analysis, and no modification of existing CVPR checkpoints. Fuzzy titles are review candidates. Matching precision takes precedence over recall in this first version. Platform schema/Graph integration follows validation of the mapping stage.
