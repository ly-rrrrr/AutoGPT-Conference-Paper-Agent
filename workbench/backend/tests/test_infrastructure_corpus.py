from pathlib import Path

from app import storage


def test_storage_configuration_changes_live_asset_root(
    client, api_session, tmp_path, monkeypatch
):
    config_path = tmp_path / "system" / "storage.json"
    asset_path = tmp_path / "large-assets"
    monkeypatch.setattr(storage, "STORAGE_CONFIG_PATH", config_path)

    response = client.put(
        "/api/infrastructure/storage",
        headers={"X-Workbench-Request": "1"},
        json={"asset_root": str(asset_path)},
    )

    assert response.status_code == 200
    assert Path(response.json()["asset_root"]) == asset_path.resolve()
    assert storage.get_asset_root() == asset_path.resolve()
    assert config_path.is_file()


def test_corpus_build_queues_pauses_and_resumes_without_duplicate_runs(
    client, api_session, seeded_db, monkeypatch
):
    monkeypatch.setattr(
        "app.api.infrastructure.storage_overview",
        lambda: {"capacity_status": "READY", "free_bytes": 200 * 1024**3},
    )
    payload = {"conference": "ECCV", "year": 2026, "max_papers": 5000}

    status = client.get("/api/infrastructure/corpus/status?conference=ECCV&year=2026")
    started = client.post(
        "/api/infrastructure/corpus/start",
        headers={"X-Workbench-Request": "1"},
        json=payload,
    )
    paused = client.post(
        "/api/infrastructure/corpus/pause",
        headers={"X-Workbench-Request": "1"},
        json=payload,
    )
    resumed = client.post(
        "/api/infrastructure/corpus/resume",
        headers={"X-Workbench-Request": "1"},
        json=payload,
    )
    started_again = client.post(
        "/api/infrastructure/corpus/start",
        headers={"X-Workbench-Request": "1"},
        json=payload,
    )

    assert status.status_code == 200
    assert status.json()["total"] == 2
    assert status.json()["source_ready"] == 1
    assert started.json()["queued"] == 1
    assert paused.json()["paused"] == 1
    assert resumed.json()["resumed"] == 1
    assert started_again.json()["queued"] == 0


def test_corpus_build_refuses_low_capacity(client, seeded_db, monkeypatch):
    monkeypatch.setattr(
        "app.api.infrastructure.storage_overview",
        lambda: {"capacity_status": "LOW", "free_bytes": 1},
    )

    response = client.post(
        "/api/infrastructure/corpus/start",
        headers={"X-Workbench-Request": "1"},
        json={"conference": "ECCV", "year": 2026, "max_papers": 10},
    )

    assert response.status_code == 409
    assert "空间不足" in response.json()["detail"]
