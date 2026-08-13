import asyncio
import socket
from collections.abc import AsyncIterator
from typing import get_args

from aiohttp import web
import pytest
import pytest_asyncio
import uvicorn
from pydantic import SecretStr, ValidationError

from backend.blocks.conference_paper.bridge_client import (
    BridgeClient,
    CollectPaperLikesBlock,
    collect_likes,
    collect_likes_from_alphaxiv,
    parse_alphaxiv_likes,
    validate_bridge_url,
)
from backend.blocks.conference_paper import bridge_client as bridge_client_module
from backend.blocks.conference_paper.models import LikesResult, LikesTask, PaperTask
from backend.conference_paper_bridge.app import create_app
from backend.conference_paper_bridge.store import TaskStore


@pytest.fixture(scope="session", autouse=True)
def graph_cleanup() -> None:
    return None


def paper_task(arxiv_id: str = "2503.00001") -> PaperTask:
    return PaperTask(
        paper_key=f"arxiv:{arxiv_id}",
        conference="CVPR",
        year=2025,
        title=f"Paper {arxiv_id}",
        authors=["Ada Lovelace"],
        detail_url="https://example.test/paper",
        pdf_url="https://example.test/paper.pdf",
        arxiv_url=f"https://arxiv.org/abs/{arxiv_id}",
        arxiv_id=arxiv_id,
        questions=["What problem does it solve?"],
        conference_day="Day 1",
    )


@pytest_asyncio.fixture(loop_scope="function")
async def bridge_server(tmp_path) -> AsyncIterator[tuple[str, TaskStore]]:
    database = tmp_path / "bridge.db"
    store = TaskStore(database)
    app = create_app(database, token="test-token")
    server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server_socket.bind(("127.0.0.1", 0))
    server_socket.listen()
    port = server_socket.getsockname()[1]
    server = uvicorn.Server(
        uvicorn.Config(app, log_level="error", access_log=False, lifespan="off")
    )
    task = asyncio.create_task(server.serve(sockets=[server_socket]))
    while not server.started:
        await asyncio.sleep(0.001)
    try:
        yield f"http://127.0.0.1:{port}", store
    finally:
        server.should_exit = True
        await task


@pytest_asyncio.fixture(loop_scope="function")
async def alphaxiv_server(monkeypatch) -> AsyncIterator[None]:
    async def metadata(request: web.Request) -> web.Response:
        arxiv_id = request.match_info["arxiv_id"]
        if arxiv_id == "2503.00002":
            raise web.HTTPNotFound()
        return web.json_response(
            {"data": {"paper_group": {"metrics": {"public_total_votes": 25}}}}
        )

    app = web.Application()
    app.router.add_get("/v2/papers/{arxiv_id}/metadata", metadata)
    runner = web.AppRunner(app)
    await runner.setup()
    server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server_socket.bind(("127.0.0.1", 0))
    server_socket.listen()
    port = server_socket.getsockname()[1]
    site = web.SockSite(runner, server_socket)
    await site.start()
    monkeypatch.setattr(
        bridge_client_module,
        "ALPHAXIV_METADATA_URL",
        f"http://127.0.0.1:{port}/v2/papers/{{arxiv_id}}/metadata",
    )
    try:
        yield
    finally:
        await runner.cleanup()


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("http://localhost:8765/", "http://localhost:8765"),
        (
            "http://HOST.DOCKER.INTERNAL:8765/",
            "http://host.docker.internal:8765",
        ),
        ("http://127.0.0.1:8765", "http://127.0.0.1:8765"),
        ("http://[::1]:8765/", "http://[::1]:8765"),
        ("http://10.1.2.3:8765", "http://10.1.2.3:8765"),
        ("http://172.16.2.3", "http://172.16.2.3"),
        ("http://192.168.1.2", "http://192.168.1.2"),
        ("http://[fd00::1]:8765", "http://[fd00::1]:8765"),
    ],
)
def test_validate_bridge_url_allows_local_docker_and_explicit_private_hosts(
    url: str, expected: str
):
    assert validate_bridge_url(url) == expected


@pytest.mark.parametrize(
    "url",
    [
        "https://127.0.0.1:8765",
        "http://8.8.8.8:8765",
        "http://bridge.example:8765",
        "http://token@127.0.0.1:8765",
        "http://127.0.0.1:8765?token=secret",
        "http://127.0.0.1:8765/#secret",
    ],
)
def test_validate_bridge_url_rejects_public_domains_and_url_secrets(url: str):
    with pytest.raises(ValueError, match="INVALID_BRIDGE_URL"):
        validate_bridge_url(url)


async def test_bridge_client_round_trip_uses_real_tcp_bridge(bridge_server):
    url, _ = bridge_server
    task = paper_task()
    likes_task = LikesTask.model_validate(
        task.model_dump(include={"paper_key", "title", "arxiv_url", "arxiv_id"})
    )

    async with BridgeClient(
        url, SecretStr("test-token"), retry_delays=(0, 0)
    ) as client:
        queued = await client.enqueue("run-roundtrip", [likes_task])
        status = await client.status("run-roundtrip")

    assert queued.inserted == 1
    assert status.counts.pending == 1
    assert status.results == []


async def test_collect_likes_polls_real_bridge_with_store_consumer(bridge_server):
    """The store consumer simulates pending RPA work; this is not RPA acceptance."""
    url, store = bridge_server
    task = paper_task()

    async def consume_from_store() -> None:
        claimed = None
        while claimed is None:
            claimed = store.claim_next("run-success")
            await asyncio.sleep(0.001)
        store.record_result(
            "run-success",
            LikesResult(
                paper_key=claimed.task.paper_key,
                arxiv_id=claimed.task.arxiv_id,
                likes=83,
                raw_text="83 Likes",
                status="SUCCESS",
            ),
        )

    async with BridgeClient(
        url, SecretStr("test-token"), retry_delays=(0, 0)
    ) as client:
        consumer = asyncio.create_task(consume_from_store())
        results = await collect_likes(client, "run-success", [task], 0.005, 2)
        await consumer

    assert results == [
        LikesResult(
            paper_key=task.paper_key,
            arxiv_id=task.arxiv_id,
            likes=83,
            raw_text="83 Likes",
            status="SUCCESS",
        )
    ]


async def test_collect_likes_rejects_unknown_terminal_result(bridge_server):
    url, store = bridge_server
    unknown = paper_task("2503.99999")
    store.enqueue(
        "run-mismatch",
        [
            LikesTask.model_validate(
                unknown.model_dump(
                    include={"paper_key", "title", "arxiv_url", "arxiv_id"}
                )
            )
        ],
    )
    claimed = store.claim_next("run-mismatch")
    assert claimed is not None
    store.record_result(
        "run-mismatch",
        LikesResult(
            paper_key=unknown.paper_key,
            arxiv_id=unknown.arxiv_id,
            likes=1,
            raw_text="1 Like",
            status="SUCCESS",
        ),
    )

    async with BridgeClient(
        url, SecretStr("test-token"), retry_delays=(0, 0)
    ) as client:
        with pytest.raises(ValueError, match="LIKES_RESULT_MISMATCH"):
            await collect_likes(client, "run-mismatch", [paper_task()], 0.005, 1)


async def test_collect_likes_times_out_against_real_pending_store(bridge_server):
    url, _ = bridge_server
    async with BridgeClient(
        url, SecretStr("test-token"), retry_delays=(0, 0)
    ) as client:
        with pytest.raises(TimeoutError, match="RPA_BRIDGE_UNAVAILABLE"):
            await collect_likes(client, "run-timeout", [paper_task()], 0.005, 0.03)


async def test_collect_likes_empty_input_does_not_contact_bridge():
    client = BridgeClient(
        "http://127.0.0.1:1", SecretStr("unused-token"), retry_delays=(0, 0)
    )
    assert await collect_likes(client, "empty", [], 0.01, 1) == []


async def test_collect_likes_from_alphaxiv_uses_metadata_and_preserves_order(
    alphaxiv_server,
):
    tasks = [paper_task("2503.00001"), paper_task("2503.00002")]

    results = await collect_likes_from_alphaxiv(tasks, 2, 1)

    assert results == [
        LikesResult(
            paper_key="arxiv:2503.00001",
            arxiv_id="2503.00001",
            likes=25,
            raw_text="25 Likes",
            status="SUCCESS",
        ),
        LikesResult(
            paper_key="arxiv:2503.00002",
            arxiv_id="2503.00002",
            status="FAILED",
            error_code="ALPHAXIV_LIKES_NOT_FOUND",
        ),
    ]


def test_parse_alphaxiv_likes_reads_public_total_votes():
    assert (
        parse_alphaxiv_likes(
            {"data": {"paper_group": {"metrics": {"public_total_votes": 25}}}}
        )
        == 25
    )

    with pytest.raises(ValueError, match="INVALID_ALPHAXIV_METADATA"):
        parse_alphaxiv_likes({"data": {}})


def test_collect_paper_likes_block_contract_and_input_boundaries():
    block = CollectPaperLikesBlock()
    token_field = block.input_schema.model_fields["bridge_token"]

    assert block.id == "e6a2c9d5-7b14-4f83-9d60-1c5e8a2b7f34"
    assert block.execution_timeout_seconds is None
    assert SecretStr in get_args(token_field.annotation)
    assert token_field.json_schema_extra["secret"] is True
    valid = block.input_schema(run_id="run-1", paper_tasks=[])
    assert valid.likes_strategy == "alphaxiv_api"
    assert valid.bridge_token is None
    assert valid.bridge_url == "http://127.0.0.1:8765"
    with pytest.raises(ValidationError, match="bridge_token is required"):
        block.input_schema(run_id="run-1", paper_tasks=[], likes_strategy="shadowbot")
    shadowbot = block.input_schema(
        run_id="run-1",
        paper_tasks=[],
        likes_strategy="shadowbot",
        bridge_token=SecretStr("test-token"),
    )
    assert shadowbot.bridge_token is not None
    with pytest.raises(ValidationError):
        block.input_schema(
            run_id="run-1",
            paper_tasks=[],
            bridge_token=SecretStr("test-token"),
            poll_interval_seconds=0,
        )
    with pytest.raises(ValidationError):
        block.input_schema(
            run_id="run-1",
            paper_tasks=[],
            bridge_token=SecretStr("test-token"),
            timeout_seconds=1801,
        )
