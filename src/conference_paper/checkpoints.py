import asyncio
import re
from collections.abc import Callable
from pathlib import Path
from typing import Generic, TypeVar

from pydantic import ValidationError

from backend.blocks.conference_paper.models import ContractModel

DEFAULT_OUTPUT_ROOT = (
    Path(__file__).resolve().parents[5]
    / "projects"
    / "conference-paper-research-agent"
    / "data"
    / "runs"
)
RUN_ID_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}")
CheckpointModel = TypeVar("CheckpointModel", bound=ContractModel)


class JsonlCheckpoint(Generic[CheckpointModel]):
    def __init__(
        self,
        run_id: str,
        filename: str,
        model: type[CheckpointModel],
        key: Callable[[CheckpointModel], str],
        output_root: Path = DEFAULT_OUTPUT_ROOT,
    ):
        if RUN_ID_PATTERN.fullmatch(run_id) is None:
            raise ValueError("INVALID_RUN_ID")
        root = output_root.resolve()
        run_directory = root / run_id
        if run_directory.parent != root:
            raise ValueError("INVALID_RUN_ID")
        self.path = run_directory / filename
        self._model = model
        self._key = key
        self._lock = asyncio.Lock()

    def load(self) -> dict[str, CheckpointModel]:
        if not self.path.exists():
            return {}
        results: dict[str, CheckpointModel] = {}
        for line in self.path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                item = self._model.model_validate_json(line)
            except ValidationError:
                continue
            results[self._key(item)] = item
        return results

    async def append(self, item: CheckpointModel) -> None:
        async with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8", newline="\n") as checkpoint:
                checkpoint.write(item.model_dump_json() + "\n")
