from pathlib import Path

import pytest

from app.api.pipelines import get_pipeline_controller
from app.models import PipelineEvent, PipelineRun
from app.pipeline_adapter import AnalysisStart, PipelineConflictError, PipelineController


class FakeBackend:
    def __init__(self):
        self.runs: list[dict[str, str]] = []
        self.calls: list[tuple[str, dict | None]] = []

    def request(self, action: str, config: dict | None = None) -> dict:
        self.calls.append((action, config))
        if action == "status":
            return {"runs": self.runs}
        if action == "start":
            return {"message": "任务已提交", "execution_id": "execution-1"}
        if action == "stop":
            return {"message": "已发送停止请求"}
        raise AssertionError(action)


@pytest.fixture
def fake_backend():
    return FakeBackend()


@pytest.fixture
def controller(fake_backend, tmp_path):
    return PipelineController(
        repository_root=tmp_path,
        platform_root=tmp_path,
        data_root=tmp_path / "data",
        backend=fake_backend,
    )


def test_analysis_start_refuses_duplicate_active_run(controller, fake_backend):
    fake_backend.runs = [{"id": "run-1", "status": "RUNNING"}]

    with pytest.raises(PipelineConflictError):
        controller.start_analysis(
            AnalysisStart(
                run_id="eccv-2026",
                analysis_concurrency=1,
                analysis_request_interval_seconds=4,
                max_new_analyses_per_run=20,
            )
        )


def test_pipeline_api_starts_analysis_and_records_event(
    client, api_session, controller, fake_backend
):
    client.app.dependency_overrides[get_pipeline_controller] = lambda: controller

    response = client.post(
        "/api/pipelines/analysis/start",
        headers={"X-Workbench-Request": "1"},
        json={
            "run_id": "eccv-2026",
            "analysis_concurrency": 1,
            "analysis_request_interval_seconds": 4,
            "max_new_analyses_per_run": 20,
        },
    )

    assert response.status_code == 202
    assert response.json()["status"] == "QUEUED"
    assert fake_backend.calls[-1][0] == "start"
    assert api_session.query(PipelineRun).one().external_id == "execution-1"
    assert api_session.query(PipelineEvent).one().event_type == "analysis_started"


def test_pipeline_api_requires_explicit_local_action_header(client, controller):
    client.app.dependency_overrides[get_pipeline_controller] = lambda: controller

    response = client.post(
        "/api/pipelines/analysis/start",
        json={
            "run_id": "eccv-2026",
            "analysis_concurrency": 1,
            "analysis_request_interval_seconds": 4,
            "max_new_analyses_per_run": 20,
        },
    )

    assert response.status_code == 403


def test_runs_endpoint_returns_stored_history(client, api_session):
    api_session.add(
        PipelineRun(
            run_key="eccv-2026",
            pipeline="analysis",
            status="COMPLETED",
            config={"analysis_concurrency": 1},
        )
    )
    api_session.commit()

    response = client.get("/api/runs")

    assert response.status_code == 200
    assert response.json()["items"][0]["run_key"] == "eccv-2026"
    assert response.json()["items"][0]["status"] == "COMPLETED"
