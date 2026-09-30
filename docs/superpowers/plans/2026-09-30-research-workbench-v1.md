# Research Workbench V1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a locally launched Vue 3 + FastAPI + PostgreSQL research workbench that imports the existing conference-paper assets, exposes dashboard and paper pages, controls the existing AutoGPT workflows, and stores explainable user preferences.

**Architecture:** The workbench lives under `workbench/`. FastAPI runs on the Windows host so its pipeline adapter can reuse the existing Docker/AutoGPT control path without mounting the Docker socket. PostgreSQL runs in a small Docker Compose stack. Vue is developed with Vite and its production bundle is served by FastAPI; JSONL, HTML, Markdown and PDF assets remain authoritative inputs and are imported idempotently into PostgreSQL.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy 2, Alembic, psycopg 3, PostgreSQL 16, pytest, Vue 3, TypeScript, Vite, Vue Router, Vitest.

---

## File map

```text
workbench/
├─ docker-compose.yml                 # PostgreSQL service and persistent volume
├─ .env.example                       # Safe local defaults, no credentials
├─ backend/
│  ├─ pyproject.toml                  # Backend runtime and test dependencies
│  ├─ alembic.ini
│  ├─ migrations/
│  │  ├─ env.py
│  │  └─ versions/0001_workbench_v1.py
│  ├─ app/
│  │  ├─ main.py                      # FastAPI composition and static frontend
│  │  ├─ config.py                    # Environment-backed settings
│  │  ├─ database.py                  # Engine, sessions and health check
│  │  ├─ models.py                    # V1 relational model
│  │  ├─ schemas.py                   # Public API contracts
│  │  ├─ importers.py                 # Idempotent JSONL/manifest import
│  │  ├─ pipeline_adapter.py           # AutoGPT/mapping process adapter
│  │  └─ api/
│  │     ├─ dashboard.py
│  │     ├─ papers.py
│  │     ├─ imports.py
│  │     ├─ pipelines.py
│  │     ├─ runs.py
│  │     └─ preferences.py
│  └─ tests/
│     ├─ conftest.py
│     ├─ test_health.py
│     ├─ test_importers.py
│     ├─ test_papers_api.py
│     ├─ test_dashboard_api.py
│     ├─ test_pipelines_api.py
│     └─ test_preferences_api.py
├─ frontend/
│  ├─ package.json
│  ├─ vite.config.ts
│  ├─ tsconfig.json
│  ├─ index.html
│  └─ src/
│     ├─ main.ts
│     ├─ router.ts
│     ├─ api.ts
│     ├─ styles.css
│     ├─ App.vue
│     ├─ layouts/WorkbenchLayout.vue
│     ├─ components/StatusBadge.vue
│     └─ views/
│        ├─ DashboardView.vue
│        ├─ PapersView.vue
│        ├─ PaperDetailView.vue
│        ├─ MappingView.vue
│        ├─ AnalysisView.vue
│        ├─ RunsView.vue
│        ├─ KnowledgeView.vue
│        └─ PreferencesView.vue
└─ scripts/start.py                     # Migrate, sync, run API and open browser
启动科研工作台.cmd                       # One-click user entry
```

### Task 1: Backend health slice and PostgreSQL service

**Files:**
- Create: `workbench/docker-compose.yml`
- Create: `workbench/.env.example`
- Create: `workbench/backend/pyproject.toml`
- Create: `workbench/backend/app/__init__.py`
- Create: `workbench/backend/app/config.py`
- Create: `workbench/backend/app/database.py`
- Create: `workbench/backend/app/main.py`
- Create: `workbench/backend/tests/test_health.py`

- [x] **Step 1: Write the failing health test**

```python
from fastapi.testclient import TestClient

from app.main import create_app


def test_health_reports_database_state(monkeypatch):
    monkeypatch.setattr("app.main.database_ready", lambda: True)
    response = TestClient(create_app()).get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "database": "ready"}
```

- [x] **Step 2: Run the test and confirm the missing application failure**

Run: `python -m pytest workbench/backend/tests/test_health.py -q`

Expected: FAIL because `app.main` does not exist.

- [x] **Step 3: Add backend packaging and settings**

`workbench/backend/pyproject.toml` defines a `research-workbench` project with FastAPI, Uvicorn, SQLAlchemy, Alembic, psycopg binary, pydantic-settings, pytest and HTTPX. `config.py` defines:

```python
class Settings(BaseSettings):
    database_url: str = "postgresql+psycopg://workbench:workbench@127.0.0.1:55432/workbench"
    source_root: Path = Path("../projects/conference-paper-research-agent/data")
    frontend_dist: Path = Path("../frontend/dist")
```

Use `SettingsConfigDict(env_prefix="WORKBENCH_", env_file=".env")` and cache `get_settings()`.

- [x] **Step 4: Add database health and FastAPI composition**

`database.py` exposes `get_engine()`, `session_scope()` and `database_ready()`; the health check runs `SELECT 1` and returns `False` on `SQLAlchemyError`. `main.py` exposes:

```python
def create_app() -> FastAPI:
    app = FastAPI(title="科研工作台", version="0.1.0")

    @app.get("/api/health")
    def health() -> dict[str, str]:
        ready = database_ready()
        return {"status": "ok" if ready else "degraded", "database": "ready" if ready else "unavailable"}

    return app


app = create_app()
```

- [x] **Step 5: Add PostgreSQL Compose service**

Use PostgreSQL 16, port `55432`, database/user/password `workbench`, a named volume, and a `pg_isready` healthcheck. Do not publish or commit user credentials; `.env.example` contains only the local development URL and source-root example.

- [x] **Step 6: Run the focused backend test**

Run: `python -m pytest workbench/backend/tests/test_health.py -q`

Expected: `1 passed`.

- [x] **Step 7: Commit**

```bash
git add workbench
git commit -m "feat(workbench): add backend health foundation"
```

### Task 2: V1 relational model and migration

**Files:**
- Create: `workbench/backend/app/models.py`
- Create: `workbench/backend/alembic.ini`
- Create: `workbench/backend/migrations/env.py`
- Create: `workbench/backend/migrations/script.py.mako`
- Create: `workbench/backend/migrations/versions/0001_workbench_v1.py`
- Create: `workbench/backend/tests/test_models.py`

- [x] **Step 1: Write model contract tests**

```python
def test_paper_business_key_is_unique():
    constraints = {item.name for item in Paper.__table__.constraints}
    assert "uq_paper_conference_title" in constraints


def test_machine_and_user_records_are_separate():
    assert "paper_analyses" in Base.metadata.tables
    assert "favorites" in Base.metadata.tables
    assert "paper_tags" in Base.metadata.tables
```

- [x] **Step 2: Run the model test and observe the missing model failure**

Run: `python -m pytest workbench/backend/tests/test_models.py -q`

Expected: FAIL importing `app.models`.

- [x] **Step 3: Define focused V1 models**

Implement SQLAlchemy 2 declarative models for `ConferenceEdition`, `Paper`, `PaperAuthor`, `PaperMapping`, `MappingCandidate`, `MappingAttempt`, `PaperAnalysis`, `PaperAnswer`, `ImpactSignal`, `PipelineRun`, `PipelineEvent`, `ImportBatch`, `DocumentAsset`, `UserInterest`, `RecentWork`, `Tag`, `PaperTag`, and `Favorite`.

Use UUID primary keys, timezone-aware timestamps, JSON columns only for variable evidence/config payloads, and explicit unique constraints:

```python
UniqueConstraint("conference_edition_id", "normalized_title", name="uq_paper_conference_title")
UniqueConstraint("paper_id", "matcher_version", name="uq_paper_mapping_version")
UniqueConstraint("paper_id", "analysis_mode", "question_set_hash", name="uq_paper_analysis_version")
UniqueConstraint("source_path", "sha256", name="uq_import_source_hash")
```

- [x] **Step 4: Add an explicit initial migration**

The migration creates exactly the V1 tables and indexes from the metadata. It must not inspect or modify the AutoGPT database. Downgrade drops only workbench-owned tables in reverse dependency order.

- [x] **Step 5: Run model tests and migration smoke check**

Run:

```powershell
python -m pytest workbench/backend/tests/test_models.py -q
docker compose -f workbench/docker-compose.yml up -d db
python -m alembic -c workbench/backend/alembic.ini upgrade head
python -m alembic -c workbench/backend/alembic.ini current
```

Expected: tests pass and Alembic reports `0001_workbench_v1 (head)`.

- [x] **Step 6: Commit**

```bash
git add workbench/backend
git commit -m "feat(workbench): add research asset schema"
```

### Task 3: Idempotent existing-asset importer

**Files:**
- Create: `workbench/backend/app/importers.py`
- Create: `workbench/backend/app/api/imports.py`
- Create: `workbench/backend/tests/fixtures/mappings.jsonl`
- Create: `workbench/backend/tests/fixtures/analysis-checkpoint.jsonl`
- Create: `workbench/backend/tests/fixtures/likes-checkpoint.jsonl`
- Create: `workbench/backend/tests/test_importers.py`

- [x] **Step 1: Write a two-pass idempotency test**

```python
def test_sync_imports_each_asset_once(session, fixture_data):
    importer = AssetImporter(session, fixture_data)
    first = importer.sync()
    second = importer.sync()
    assert first.papers_created == 2
    assert second.papers_created == 0
    assert session.scalar(select(func.count(Paper.id))) == 2
    assert session.scalar(select(func.count(ImportBatch.id))) == 3
```

- [x] **Step 2: Run the importer test and verify it fails**

Run: `python -m pytest workbench/backend/tests/test_importers.py -q`

Expected: FAIL because `AssetImporter` is missing.

- [x] **Step 3: Implement streaming JSONL input and hashes**

Add `iter_jsonl(path)`, `sha256_file(path)` and normalization helpers. Invalid non-empty JSON lines raise `ImportDataError` containing the filename and line number; errors must not partially commit a batch.

- [x] **Step 4: Implement mapping import**

Read `eccv-2026-mapping/mappings.jsonl`. Upsert the conference edition and paper from the nested `paper` object, then persist mapping status, reason, matcher version, accepted arXiv data, candidates and attempts. Use normalized conference/year/title as the paper business key.

- [x] **Step 5: Implement analysis and Likes import**

Read each `runs/*/analysis-checkpoint.jsonl` and `likes-checkpoint.jsonl`. Resolve papers by `arxiv_id`, preserve error code/detail, analysis mode, questions and answers, and store Likes as an `ImpactSignal` with source `alphaxiv_likes`. Unknown arXiv IDs are counted as unresolved instead of creating untraceable papers.

- [x] **Step 6: Add sync endpoint**

`POST /api/imports/sync` runs one synchronous local import in V1 and returns:

```json
{
  "files_seen": 3,
  "files_imported": 3,
  "papers_created": 2,
  "records_updated": 6,
  "unresolved_records": 0
}
```

Reject a second concurrent sync with HTTP 409.

- [x] **Step 7: Run importer tests twice**

Run: `python -m pytest workbench/backend/tests/test_importers.py -q`

Expected: all tests pass, including unchanged-file skip and changed-file upsert.

- [x] **Step 8: Commit**

```bash
git add workbench/backend
git commit -m "feat(workbench): import existing paper assets"
```

### Task 4: Dashboard and paper query APIs

**Files:**
- Create: `workbench/backend/app/schemas.py`
- Create: `workbench/backend/app/api/dashboard.py`
- Create: `workbench/backend/app/api/papers.py`
- Create: `workbench/backend/tests/test_dashboard_api.py`
- Create: `workbench/backend/tests/test_papers_api.py`
- Modify: `workbench/backend/app/main.py`

- [x] **Step 1: Write API behavior tests**

```python
def test_papers_support_search_and_status_filter(client, seeded_db):
    response = client.get("/api/papers", params={"query": "vision", "mapping_status": "matched"})
    assert response.status_code == 200
    assert response.json()["total"] == 1
    assert response.json()["items"][0]["arxiv_id"] == "2607.00001"


def test_dashboard_separates_total_and_completed_counts(client, seeded_db):
    data = client.get("/api/dashboard").json()
    assert data["papers_total"] == 2
    assert data["mappings"]["matched"] == 1
    assert data["analyses"]["success"] == 1
```

- [x] **Step 2: Run and observe 404 failures**

Run: `python -m pytest workbench/backend/tests/test_dashboard_api.py workbench/backend/tests/test_papers_api.py -q`

Expected: FAIL with 404 for missing routes.

- [x] **Step 3: Implement query schemas and routes**

`GET /api/papers` supports `query`, `conference`, `year`, `topic`, `mapping_status`, `analysis_status`, `sort`, `page`, and `page_size`. Allowed sorts are `updated_at`, `title`, `likes`; page size is 1–100. `GET /api/papers/{id}` returns metadata, authors, mapping evidence, latest compatible analysis, answers, Likes, document state and source/version fields.

- [x] **Step 4: Implement dashboard aggregation**

Return totals by conference, mapping status, analysis status and document status; current active runs; five recent errors; and last import time. Use grouped SQL queries rather than reading JSONL in request handlers.

- [x] **Step 5: Register routers and run focused tests**

Run: `python -m pytest workbench/backend/tests/test_dashboard_api.py workbench/backend/tests/test_papers_api.py -q`

Expected: all tests pass.

- [x] **Step 6: Commit**

```bash
git add workbench/backend
git commit -m "feat(workbench): expose dashboard and paper APIs"
```

### Task 5: Pipeline and run APIs

**Files:**
- Create: `workbench/backend/app/pipeline_adapter.py`
- Create: `workbench/backend/app/api/pipelines.py`
- Create: `workbench/backend/app/api/runs.py`
- Create: `workbench/backend/tests/test_pipelines_api.py`
- Modify: `scripts/paper_console.py`
- Modify: `workbench/backend/app/main.py`

- [x] **Step 1: Extract a side-effect-free controller boundary**

Move path discovery, service readiness, mapping start/stop, AutoGPT start/stop and status operations behind a `PipelineController` whose constructor receives platform root, data root and command runner. Importing the module must not start Docker, open a browser or create a server.

- [x] **Step 2: Write controller tests with a fake command runner**

```python
def test_analysis_start_refuses_duplicate_active_run(controller, fake_backend):
    fake_backend.status = [{"id": "run-1", "status": "RUNNING"}]
    with pytest.raises(PipelineConflictError):
        controller.start_analysis(AnalysisStart(run_id="eccv-2026", concurrency=1, interval_seconds=4, limit=20))
```

- [x] **Step 3: Run the controller test and confirm failure**

Run: `python -m pytest workbench/backend/tests/test_pipelines_api.py -q`

Expected: FAIL because the controller boundary is absent.

- [x] **Step 4: Implement normalized task state**

Expose `IDLE`, `QUEUED`, `RUNNING`, `COMPLETED`, `FAILED`, and `STOPPED`. Store start/stop/status events in `pipeline_runs` and `pipeline_events`. Never place credentials or full Docker output in an event.

- [x] **Step 5: Implement local-only endpoints**

Add status endpoints and explicit mapping/analysis start and stop endpoints. Preserve Host, Origin and CSRF protection. Starting analysis requires `run_id`, `analysis_concurrency`, `analysis_request_interval_seconds`, and `max_new_analyses_per_run`; it must not happen during health checks or startup.

- [x] **Step 6: Run focused controller/API tests**

Run: `python -m pytest workbench/backend/tests/test_pipelines_api.py tests/test_paper_console.py -q`

Expected: tests pass and existing console behavior remains compatible.

- [x] **Step 7: Commit**

```bash
git add scripts workbench/backend
git commit -m "feat(workbench): integrate paper pipeline controls"
```

### Task 6: Vue application shell and hierarchical navigation

**Files:**
- Create: `workbench/frontend/package.json`
- Create: `workbench/frontend/tsconfig.json`
- Create: `workbench/frontend/vite.config.ts`
- Create: `workbench/frontend/index.html`
- Create: `workbench/frontend/src/main.ts`
- Create: `workbench/frontend/src/router.ts`
- Create: `workbench/frontend/src/api.ts`
- Create: `workbench/frontend/src/styles.css`
- Create: `workbench/frontend/src/App.vue`
- Create: `workbench/frontend/src/layouts/WorkbenchLayout.vue`
- Create: `workbench/frontend/src/views/*.vue`
- Create: `workbench/frontend/src/layouts/WorkbenchLayout.test.ts`

- [ ] **Step 1: Scaffold package scripts and test environment**

Define `dev`, `build`, `test`, and `typecheck` scripts with Vue 3, Vue Router, Vite, TypeScript, Vitest, Vue Test Utils and jsdom.

- [ ] **Step 2: Write the navigation test**

```typescript
it("groups secondary pages under first-level modules", () => {
  const wrapper = mount(WorkbenchLayout, { global: { plugins: [router] }, slots: { default: "页面" } })
  expect(wrapper.text()).toContain("工作台")
  expect(wrapper.text()).toContain("论文资产")
  expect(wrapper.text()).toContain("采集与分析")
  expect(wrapper.text()).toContain("知识库")
  expect(wrapper.text()).toContain("个性化")
})
```

- [ ] **Step 3: Run the frontend test and confirm failure**

Run: `pnpm.cmd --dir workbench/frontend test --run`

Expected: FAIL because the layout is missing.

- [ ] **Step 4: Implement the application shell**

Build a fixed left sidebar with collapsible first-level modules, secondary route links, a compact system-health area and a right content outlet. Use semantic HTML, CSS variables and responsive behavior that collapses the sidebar below 900px. Do not add a UI framework in V1.

- [ ] **Step 5: Define routes**

Map `/`, `/papers`, `/papers/:id`, `/pipelines/mapping`, `/pipelines/analysis`, `/runs`, `/knowledge`, and `/preferences`. Placeholder views contain only the route heading until their task implements real content.

- [ ] **Step 6: Run test, typecheck and build**

Run:

```powershell
pnpm.cmd --dir workbench/frontend test --run
pnpm.cmd --dir workbench/frontend typecheck
pnpm.cmd --dir workbench/frontend build
```

Expected: all exit 0 and `workbench/frontend/dist` exists.

- [ ] **Step 7: Commit**

```bash
git add workbench/frontend
git commit -m "feat(workbench): add hierarchical application shell"
```

### Task 7: Dashboard, papers and paper detail pages

**Files:**
- Create: `workbench/frontend/src/components/StatusBadge.vue`
- Modify: `workbench/frontend/src/api.ts`
- Modify: `workbench/frontend/src/views/DashboardView.vue`
- Modify: `workbench/frontend/src/views/PapersView.vue`
- Modify: `workbench/frontend/src/views/PaperDetailView.vue`
- Create: `workbench/frontend/src/views/PapersView.test.ts`

- [ ] **Step 1: Write a filtered-list interaction test**

```typescript
it("loads papers with the selected mapping status", async () => {
  server.use(http.get("/api/papers", ({ request }) => {
    expect(new URL(request.url).searchParams.get("mapping_status")).toBe("matched")
    return HttpResponse.json({ total: 0, page: 1, page_size: 25, items: [] })
  }))
  const wrapper = mount(PapersView)
  await wrapper.get("select[name=mapping_status]").setValue("matched")
  await flushPromises()
})
```

- [ ] **Step 2: Run the page test and confirm failure**

Run: `pnpm.cmd --dir workbench/frontend test --run src/views/PapersView.test.ts`

Expected: FAIL because real page controls are absent.

- [ ] **Step 3: Implement typed API helpers**

Add `getDashboard`, `getPapers`, and `getPaper`. Convert non-2xx responses into `ApiError` with the backend message; views show retry actions rather than raw exceptions.

- [ ] **Step 4: Implement dashboard**

Show asset totals, mapping/analysis funnels, active task, latest import and recent actionable errors. Distinguish historical cumulative totals from current-run changes.

- [ ] **Step 5: Implement paper list and detail**

The list provides debounced search, conference/year/topic/status filters, Likes/title/update sorting and pagination. The detail page separates factual metadata, mapping evidence, machine analysis, question answers, influence signals, document state and provenance.

- [ ] **Step 6: Run focused frontend checks**

Run:

```powershell
pnpm.cmd --dir workbench/frontend test --run src/views/PapersView.test.ts
pnpm.cmd --dir workbench/frontend typecheck
pnpm.cmd --dir workbench/frontend build
```

Expected: all exit 0.

- [ ] **Step 7: Commit**

```bash
git add workbench/frontend
git commit -m "feat(workbench): add paper exploration pages"
```

### Task 8: Operational mapping, analysis and run pages

**Files:**
- Modify: `workbench/frontend/src/api.ts`
- Modify: `workbench/frontend/src/views/MappingView.vue`
- Modify: `workbench/frontend/src/views/AnalysisView.vue`
- Modify: `workbench/frontend/src/views/RunsView.vue`
- Create: `workbench/frontend/src/views/AnalysisView.test.ts`

- [ ] **Step 1: Write the explicit-start test**

```typescript
it("does not start analysis until the user submits", async () => {
  const start = vi.fn()
  const wrapper = mount(AnalysisView, { global: { provide: { startAnalysis: start } } })
  expect(start).not.toHaveBeenCalled()
  await wrapper.get("button[type=submit]").trigger("click")
  expect(start).toHaveBeenCalledTimes(1)
})
```

- [ ] **Step 2: Implement mapping operations page**

Display status counts, process state, last error, candidate/query metrics and start/stop controls. Require a confirmation only when the requested action can trigger external requests.

- [ ] **Step 3: Implement analysis operations page**

Expose run ID, new-analysis limit, concurrency and interval with the existing safe bounds. Show active run, cumulative completion, current-run change, normalized errors and stop control. Never auto-start analysis on mount or refresh.

- [ ] **Step 4: Implement run history page**

List runs and expose their config, timestamps, status, result deltas and recent events. Do not render credentials, access tokens or full container logs.

- [ ] **Step 5: Run focused checks and commit**

Run:

```powershell
pnpm.cmd --dir workbench/frontend test --run src/views/AnalysisView.test.ts
pnpm.cmd --dir workbench/frontend typecheck
pnpm.cmd --dir workbench/frontend build
```

Expected: all exit 0.

Commit: `feat(workbench): add pipeline operations pages`.

### Task 9: Explainable preferences and document status

**Files:**
- Create: `workbench/backend/app/api/preferences.py`
- Create: `workbench/backend/app/api/knowledge.py`
- Create: `workbench/backend/app/scoring.py`
- Create: `workbench/backend/tests/test_preferences_api.py`
- Modify: `workbench/frontend/src/views/PreferencesView.vue`
- Modify: `workbench/frontend/src/views/KnowledgeView.vue`
- Modify: `workbench/frontend/src/views/PapersView.vue`

- [ ] **Step 1: Write an explainable-score test**

```python
def test_score_exposes_each_component():
    score = score_paper(paper, preferences)
    assert score.total == sum(score.components.values())
    assert set(score.components) == {"recent_work", "interest", "keyword", "impact", "freshness"}
```

- [ ] **Step 2: Implement preference CRUD and scoring**

Persist interests, recent-work records, keywords and five normalized weights. Reject weights outside 0–1. Return total score plus all component scores; never store the total as an unexplained permanent field.

- [ ] **Step 3: Implement favorites and tags**

Add explicit create/delete routes with unique constraints. These user records never overwrite imported paper or analysis fields.

- [ ] **Step 4: Implement document state API and page**

Expose `MISSING`, `AVAILABLE`, `PARSED`, and `FAILED`, with path, parser, parser version, checksum and last error. V1 does not upload, parse or embed documents.

- [ ] **Step 5: Implement preferences and knowledge views**

Preferences edit the explainable inputs and show a live scoring explanation. Knowledge lists document status and clearly labels unavailable V1 actions rather than presenting nonfunctional controls.

- [ ] **Step 6: Run focused tests and commit**

Run:

```powershell
python -m pytest workbench/backend/tests/test_preferences_api.py -q
pnpm.cmd --dir workbench/frontend test --run
pnpm.cmd --dir workbench/frontend typecheck
```

Expected: all exit 0.

Commit: `feat(workbench): add explainable research preferences`.

### Task 10: One-click launcher, production serving and handoff

**Files:**
- Create: `workbench/scripts/start.py`
- Create: `启动科研工作台.cmd`
- Modify: `workbench/backend/app/main.py`
- Modify: `README.md`
- Create: `docs/科研工作台操作指南.md`
- Create: `workbench/backend/tests/test_startup.py`

- [ ] **Step 1: Write startup decision tests**

```python
def test_startup_reuses_healthy_database(fake_commands):
    fake_commands.compose_ps.add("db")
    actions = startup_actions(fake_commands)
    assert "compose_up_db" not in actions
    assert actions == ["migrate", "sync", "serve"]
```

- [ ] **Step 2: Implement production frontend serving**

FastAPI serves `frontend/dist` only when it exists, keeps `/api/*` authoritative, and returns `index.html` for known Vue routes. Missing frontend assets produce an actionable startup error instead of an API 404 loop.

- [ ] **Step 3: Implement start script**

The script checks Python, Node/pnpm only when a frontend build is missing, and Docker. It starts the workbench database, runs Alembic, builds the frontend if needed, performs an idempotent sync, starts Uvicorn on `127.0.0.1:8767`, and opens the browser. Existing healthy services are reused.

- [ ] **Step 4: Add Windows launcher and guide**

The `.cmd` sets UTF-8, changes to the repository directory, runs `python workbench\scripts\start.py`, and pauses on exit. The guide covers normal operation, data locations, recovery and the distinction between workbench data sync and paid analysis.

- [ ] **Step 5: Run risk-proportionate verification**

Run:

```powershell
python -m pytest workbench/backend/tests -q
pnpm.cmd --dir workbench/frontend test --run
pnpm.cmd --dir workbench/frontend typecheck
pnpm.cmd --dir workbench/frontend build
python -m py_compile workbench/scripts/start.py
git diff --check
```

Then perform one no-cost smoke path: start the workbench, sync existing data, open dashboard, search a known paper, open its detail and inspect current task status. Do not start mapping or analysis during verification.

- [ ] **Step 6: Commit and push**

```bash
git add workbench README.md docs/科研工作台操作指南.md 启动科研工作台.cmd
git commit -m "feat(workbench): deliver local research workbench v1"
git push origin feat/eccv-arxiv-mapping
```
