from fastapi.testclient import TestClient

from app.main import create_app


def test_health_reports_database_state(monkeypatch):
    monkeypatch.setattr("app.main.database_ready", lambda: True)

    response = TestClient(create_app()).get("/api/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "database": "ready"}


def test_health_degrades_when_database_is_unavailable(monkeypatch):
    monkeypatch.setattr("app.main.database_ready", lambda: False)

    response = TestClient(create_app()).get("/api/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "degraded",
        "database": "unavailable",
    }
