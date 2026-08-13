from collections.abc import AsyncIterator

import httpx
import pytest

from backend.conference_paper_bridge.app import create_app


@pytest.fixture(scope="session", autouse=True)
def graph_cleanup() -> None:
    return None


@pytest.fixture
async def client(tmp_path) -> AsyncIterator[httpx.AsyncClient]:
    app = create_app(tmp_path / "bridge.db", token="test-token")
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://test",
        headers={"Authorization": "Bearer test-token"},
    ) as test_client:
        yield test_client


def task_payload(arxiv_id: str = "2503.00001") -> dict[str, object]:
    return {
        "paper_key": f"arxiv:{arxiv_id}",
        "title": f"Paper {arxiv_id}",
        "arxiv_url": f"https://arxiv.org/abs/{arxiv_id}",
        "arxiv_id": arxiv_id,
    }


def success_payload(arxiv_id: str = "2503.00001", likes: int = 83):
    return {
        "paper_key": f"arxiv:{arxiv_id}",
        "arxiv_id": arxiv_id,
        "likes": likes,
        "raw_text": f"{likes} Likes",
        "status": "SUCCESS",
        "error_code": None,
    }


async def test_api_round_trip_uses_real_sqlite(client: httpx.AsyncClient):
    queued = await client.post("/runs/run-1/tasks", json={"tasks": [task_payload()]})
    claimed = await client.get("/runs/run-1/tasks/next")
    saved = await client.post("/runs/run-1/results", json=success_payload())
    status = await client.get("/runs/run-1/status")

    assert queued.status_code == 201
    assert queued.json() == {"inserted": 1, "existing": 0}
    assert claimed.status_code == 200
    assert claimed.json()["task"]["paper_key"] == "arxiv:2503.00001"
    assert claimed.json()["attempts"] == 1
    assert saved.status_code == 201
    assert saved.json() == {"accepted": True}
    assert status.json()["counts"] == {
        "pending": 0,
        "claimed": 0,
        "success": 1,
        "failed": 0,
    }
    assert status.json()["results"] == [success_payload()]
    assert "test-token" not in status.text


@pytest.mark.parametrize("authorization", [None, "Bearer wrong"])
async def test_api_rejects_missing_or_wrong_bearer_token(
    client: httpx.AsyncClient, authorization: str | None
):
    request = client.build_request("GET", "/runs/run-1/status")
    if authorization is None:
        del request.headers["Authorization"]
    else:
        request.headers["Authorization"] = authorization

    response = await client.send(request)

    assert response.status_code == 401


async def test_empty_queue_returns_null_task(client: httpx.AsyncClient):
    response = await client.get("/runs/empty/tasks/next")

    assert response.status_code == 200
    assert response.json() == {"task": None, "attempts": None}
