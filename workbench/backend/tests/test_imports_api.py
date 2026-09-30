from fastapi.testclient import TestClient

from app.main import create_app


def test_sync_endpoint_returns_import_counts(monkeypatch):
    monkeypatch.setattr(
        "app.api.imports.execute_sync",
        lambda: {
            "files_seen": 3,
            "files_imported": 3,
            "papers_created": 2,
            "records_updated": 4,
            "unresolved_records": 0,
        },
    )

    response = TestClient(create_app()).post("/api/imports/sync")

    assert response.status_code == 200
    assert response.json()["papers_created"] == 2


def test_sync_endpoint_rejects_a_concurrent_import():
    from app.api.imports import sync_lock

    sync_lock.acquire()
    try:
        response = TestClient(create_app()).post("/api/imports/sync")
    finally:
        sync_lock.release()

    assert response.status_code == 409
    assert response.json()["detail"] == "数据同步正在运行"
