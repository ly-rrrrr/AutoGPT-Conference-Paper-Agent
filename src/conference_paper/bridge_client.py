import asyncio
import ipaddress
from collections.abc import Awaitable, Callable
from types import TracebackType
from typing import Any, Literal, Self, TypeVar
from urllib.parse import quote, urlparse

import aiohttp
from pydantic import BaseModel, SecretStr, field_validator, model_validator

from backend.blocks._base import (
    Block,
    BlockCategory,
    BlockOutput,
    BlockSchemaInput,
    BlockSchemaOutput,
)
from backend.blocks.conference_paper.models import (
    LikesResult,
    LikesTask,
    PaperTask,
    ResultStatus,
)
from backend.blocks.conference_paper.checkpoints import JsonlCheckpoint
from backend.conference_paper_bridge.models import (
    BridgeRunStatus,
    EnqueueRequest,
    EnqueueResponse,
)

LIKES_BATCH_SIZE = 100
MAX_INLINE_LIKES_RESULTS = 100
from backend.data.model import SchemaField

ResponseModel = TypeVar("ResponseModel", bound=BaseModel)
PRIVATE_NETWORKS = (
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("fc00::/7"),
)
ALLOWED_BRIDGE_HOSTNAMES = frozenset({"localhost", "host.docker.internal"})
ALPHAXIV_METADATA_URL = "https://api.alphaxiv.org/v2/papers/{arxiv_id}/metadata"
LikesStrategy = Literal["alphaxiv_api", "shadowbot"]


def validate_bridge_url(url: str) -> str:
    try:
        parsed = urlparse(url)
        hostname = parsed.hostname
        port = parsed.port
    except ValueError as error:
        raise ValueError("INVALID_BRIDGE_URL") from error
    if (
        parsed.scheme.lower() != "http"
        or hostname is None
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or parsed.path not in {"", "/"}
    ):
        raise ValueError("INVALID_BRIDGE_URL")
    normalized_host = _validate_bridge_host(hostname)
    host_for_url = f"[{normalized_host}]" if ":" in normalized_host else normalized_host
    return f"http://{host_for_url}{f':{port}' if port is not None else ''}"


class BridgeClient:
    def __init__(
        self,
        bridge_url: str,
        token: SecretStr,
        *,
        retry_delays: tuple[float, ...] = (1.0, 2.0),
        request_timeout_seconds: float = 20.0,
    ):
        self.bridge_url = validate_bridge_url(bridge_url)
        self._token = token
        self._retry_delays = retry_delays[:2]
        self._timeout = aiohttp.ClientTimeout(total=request_timeout_seconds)
        self._session: aiohttp.ClientSession | None = None

    async def __aenter__(self):
        await self._get_session()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        await self.close()

    async def close(self) -> None:
        if self._session is not None:
            await self._session.close()
            self._session = None

    async def enqueue(self, run_id: str, tasks: list[LikesTask]) -> EnqueueResponse:
        request = EnqueueRequest(tasks=tasks)
        return await self._request(
            "POST",
            f"/runs/{quote(run_id, safe='')}/tasks",
            EnqueueResponse,
            request.model_dump(mode="json"),
        )

    async def status(self, run_id: str) -> BridgeRunStatus:
        return await self._request(
            "GET",
            f"/runs/{quote(run_id, safe='')}/status",
            BridgeRunStatus,
        )

    async def _request(
        self,
        method: str,
        path: str,
        response_model: type[ResponseModel],
        payload: dict | None = None,
    ) -> ResponseModel:
        delays = (*self._retry_delays, None)
        for delay in delays:
            try:
                session = await self._get_session()
                async with session.request(
                    method, f"{self.bridge_url}{path}", json=payload
                ) as response:
                    response.raise_for_status()
                    return response_model.model_validate(await response.json())
            except (aiohttp.ClientError, asyncio.TimeoutError, ValueError):
                if delay is None:
                    raise RuntimeError("RPA_BRIDGE_UNAVAILABLE") from None
                await asyncio.sleep(max(0, delay))
        raise RuntimeError("RPA_BRIDGE_UNAVAILABLE")

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                headers={"Authorization": f"Bearer {self._token.get_secret_value()}"},
                timeout=self._timeout,
            )
        return self._session


class AlphaXivLikesClient:
    def __init__(
        self,
        *,
        concurrency: int = 5,
        retry_delays: tuple[float, ...] = (0.5, 1.0),
        request_timeout_seconds: float = 20.0,
    ):
        self._semaphore = asyncio.Semaphore(concurrency)
        self._retry_delays = retry_delays[:2]
        self._timeout = aiohttp.ClientTimeout(total=request_timeout_seconds)
        self._session: aiohttp.ClientSession | None = None

    async def __aenter__(self):
        await self._get_session()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        await self.close()

    async def close(self) -> None:
        if self._session is not None:
            await self._session.close()
            self._session = None

    async def collect(
        self,
        paper_tasks: list[PaperTask],
        on_result: Callable[[LikesResult], Awaitable[None]] | None = None,
        retain_results: bool = True,
    ) -> list[LikesResult]:
        async def fetch(paper: PaperTask) -> LikesResult:
            result = await self._fetch(paper)
            if on_result is not None:
                await on_result(result)
            return result

        retained: list[LikesResult] = []
        for start in range(0, len(paper_tasks), LIKES_BATCH_SIZE):
            batch = paper_tasks[start : start + LIKES_BATCH_SIZE]
            completed = list(await asyncio.gather(*(fetch(task) for task in batch)))
            if retain_results:
                retained.extend(completed)
        return retained

    async def _fetch(self, paper: PaperTask) -> LikesResult:
        async with self._semaphore:
            for delay in (*self._retry_delays, None):
                try:
                    session = await self._get_session()
                    url = ALPHAXIV_METADATA_URL.format(
                        arxiv_id=quote(paper.arxiv_id, safe="")
                    )
                    async with session.get(url) as response:
                        if response.status == 404:
                            return _failed_likes_result(
                                paper, "ALPHAXIV_LIKES_NOT_FOUND"
                            )
                        response.raise_for_status()
                        likes = parse_alphaxiv_likes(await response.json())
                        label = "Like" if likes == 1 else "Likes"
                        return LikesResult(
                            paper_key=paper.paper_key,
                            arxiv_id=paper.arxiv_id,
                            likes=likes,
                            raw_text=f"{likes} {label}",
                            status=ResultStatus.SUCCESS,
                        )
                except (aiohttp.ClientError, asyncio.TimeoutError, ValueError):
                    if delay is None:
                        return _failed_likes_result(paper, "ALPHAXIV_LIKES_UNAVAILABLE")
                    await asyncio.sleep(max(0, delay))
        return _failed_likes_result(paper, "ALPHAXIV_LIKES_UNAVAILABLE")

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(timeout=self._timeout)
        return self._session


async def collect_likes(
    client: BridgeClient,
    run_id: str,
    paper_tasks: list[PaperTask],
    poll_interval_seconds: float,
    timeout_seconds: float,
) -> list[LikesResult]:
    if not paper_tasks:
        return []
    expected_order = [(paper.paper_key, paper.arxiv_id) for paper in paper_tasks]
    if len({paper_key for paper_key, _ in expected_order}) != len(expected_order):
        raise ValueError("LIKES_RESULT_MISMATCH")
    likes_tasks = [
        LikesTask.model_validate(
            paper.model_dump(include={"paper_key", "title", "arxiv_url", "arxiv_id"})
        )
        for paper in paper_tasks
    ]
    deadline = asyncio.get_running_loop().time() + timeout_seconds
    await client.enqueue(run_id, likes_tasks)
    while True:
        status = await client.status(run_id)
        results_by_key = _validate_results(status.results, expected_order)
        terminal_count = status.counts.success + status.counts.failed
        if status.counts.pending == 0 and status.counts.claimed == 0:
            if terminal_count != len(expected_order) or len(results_by_key) != len(
                expected_order
            ):
                raise ValueError("LIKES_RESULT_MISMATCH")
            return [results_by_key[paper_key] for paper_key, _ in expected_order]
        remaining = deadline - asyncio.get_running_loop().time()
        if remaining <= 0:
            raise TimeoutError("RPA_BRIDGE_UNAVAILABLE")
        await asyncio.sleep(min(poll_interval_seconds, remaining))


async def collect_likes_from_alphaxiv(
    paper_tasks: list[PaperTask],
    concurrency: int,
    request_timeout_seconds: float,
    on_result: Callable[[LikesResult], Awaitable[None]] | None = None,
    retain_results: bool = True,
) -> list[LikesResult]:
    if not paper_tasks:
        return []
    expected_order = [(paper.paper_key, paper.arxiv_id) for paper in paper_tasks]
    if len({paper_key for paper_key, _ in expected_order}) != len(expected_order):
        raise ValueError("LIKES_RESULT_MISMATCH")
    async with AlphaXivLikesClient(
        concurrency=concurrency,
        request_timeout_seconds=request_timeout_seconds,
    ) as client:
        results = await client.collect(
            paper_tasks, on_result, retain_results=retain_results
        )
    if not retain_results:
        return []
    results_by_key = _validate_results(results, expected_order)
    if len(results_by_key) != len(expected_order):
        raise ValueError("LIKES_RESULT_MISMATCH")
    return [results_by_key[paper_key] for paper_key, _ in expected_order]


def parse_alphaxiv_likes(payload: Any) -> int:
    try:
        likes = payload["data"]["paper_group"]["metrics"]["public_total_votes"]
    except (KeyError, TypeError) as error:
        raise ValueError("INVALID_ALPHAXIV_METADATA") from error
    if isinstance(likes, bool) or not isinstance(likes, int) or likes < 0:
        raise ValueError("INVALID_ALPHAXIV_METADATA")
    return likes


class CollectPaperLikesBlock(Block):
    execution_timeout_seconds = None

    class Input(BlockSchemaInput):
        run_id: str = SchemaField(description="Conference run identifier", min_length=1)
        paper_tasks: list[PaperTask] = SchemaField(
            description="Selected conference papers"
        )
        likes_strategy: LikesStrategy = SchemaField(
            default="alphaxiv_api",
            description="Likes source: direct alphaXiv metadata API or ShadowBot RPA",
        )
        api_concurrency: int = SchemaField(
            default=20,
            description="Maximum concurrent alphaXiv metadata requests",
            ge=1,
            le=20,
        )
        api_request_timeout_seconds: float = SchemaField(
            default=20.0,
            description="Timeout for each alphaXiv metadata request",
            ge=0,
            le=60,
        )
        bridge_url: str = SchemaField(
            default="http://127.0.0.1:8765",
            description="Local RPA Bridge base URL used by the ShadowBot strategy",
        )
        bridge_token: SecretStr | None = SchemaField(
            default=None,
            description="RPA Bridge bearer token required by the ShadowBot strategy",
            secret=True,
        )
        poll_interval_seconds: float = SchemaField(
            default=5.0, description="Bridge status polling interval", ge=0
        )
        timeout_seconds: float = SchemaField(
            default=1740.0,
            description="Maximum Bridge wait time",
            ge=0,
            le=1800,
        )

        @field_validator(
            "api_request_timeout_seconds",
            "poll_interval_seconds",
            "timeout_seconds",
        )
        @classmethod
        def require_positive_duration(cls, value: float) -> float:
            if value <= 0:
                raise ValueError("duration must be positive")
            return value

        @field_validator("bridge_url")
        @classmethod
        def normalize_bridge_url(cls, value: str) -> str:
            return validate_bridge_url(value)

        @field_validator("bridge_token")
        @classmethod
        def reject_blank_bridge_token(cls, value: SecretStr | None) -> SecretStr | None:
            if value is not None and not value.get_secret_value().strip():
                raise ValueError("bridge_token must not be blank")
            return value

        @model_validator(mode="after")
        def require_shadowbot_token(self) -> Self:
            if self.likes_strategy == "shadowbot" and self.bridge_token is None:
                raise ValueError(
                    "bridge_token is required when likes_strategy is shadowbot"
                )
            return self

    class Output(BlockSchemaOutput):
        likes_results: list[LikesResult] = SchemaField(
            description="Terminal likes results in paper input order"
        )

    def __init__(self):
        super().__init__(
            id="e6a2c9d5-7b14-4f83-9d60-1c5e8a2b7f34",
            description=(
                "Collects paper likes through the alphaXiv metadata API by default, "
                "with ShadowBot RPA available as a fallback."
            ),
            categories={BlockCategory.SEARCH},
            input_schema=CollectPaperLikesBlock.Input,
            output_schema=CollectPaperLikesBlock.Output,
        )

    async def run(self, input_data: Input, **kwargs) -> BlockOutput:
        checkpoint = JsonlCheckpoint(
            input_data.run_id,
            "likes-checkpoint.jsonl",
            LikesResult,
            lambda result: result.paper_key,
        )
        cached = checkpoint.load()
        completed = {
            paper.paper_key: cached[paper.paper_key]
            for paper in input_data.paper_tasks
            if paper.paper_key in cached
            and cached[paper.paper_key].status is ResultStatus.SUCCESS
            and cached[paper.paper_key].arxiv_id == paper.arxiv_id
        }
        remaining = [
            paper
            for paper in input_data.paper_tasks
            if paper.paper_key not in completed
        ]
        if input_data.likes_strategy == "alphaxiv_api":
            compact_output = len(input_data.paper_tasks) > MAX_INLINE_LIKES_RESULTS
            fresh = await collect_likes_from_alphaxiv(
                remaining,
                input_data.api_concurrency,
                input_data.api_request_timeout_seconds,
                checkpoint.append,
                retain_results=not compact_output,
            )
            if compact_output:
                yield "likes_results", []
                return
        else:
            if input_data.bridge_token is None:
                raise ValueError(
                    "bridge_token is required when likes_strategy is shadowbot"
                )
            async with BridgeClient(
                input_data.bridge_url, input_data.bridge_token
            ) as client:
                fresh = await collect_likes(
                    client,
                    input_data.run_id,
                    remaining,
                    input_data.poll_interval_seconds,
                    input_data.timeout_seconds,
                )
            for result in fresh:
                await checkpoint.append(result)
        by_key = {**completed, **{result.paper_key: result for result in fresh}}
        yield "likes_results", [
            by_key[paper.paper_key] for paper in input_data.paper_tasks
        ]


def _validate_bridge_host(hostname: str) -> str:
    normalized_hostname = hostname.casefold()
    if normalized_hostname in ALLOWED_BRIDGE_HOSTNAMES:
        return normalized_hostname
    try:
        address = ipaddress.ip_address(hostname)
    except ValueError as error:
        raise ValueError("INVALID_BRIDGE_URL") from error
    if not address.is_loopback and not any(
        address in network for network in PRIVATE_NETWORKS
    ):
        raise ValueError("INVALID_BRIDGE_URL")
    return address.compressed


def _validate_results(
    results: list[LikesResult], expected_order: list[tuple[str, str]]
) -> dict[str, LikesResult]:
    expected = dict(expected_order)
    results_by_key: dict[str, LikesResult] = {}
    for result in results:
        if (
            result.paper_key in results_by_key
            or expected.get(result.paper_key) != result.arxiv_id
        ):
            raise ValueError("LIKES_RESULT_MISMATCH")
        results_by_key[result.paper_key] = result
    return results_by_key


def _failed_likes_result(paper: PaperTask, error_code: str) -> LikesResult:
    return LikesResult(
        paper_key=paper.paper_key,
        arxiv_id=paper.arxiv_id,
        status=ResultStatus.FAILED,
        error_code=error_code,
    )
