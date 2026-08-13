from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from backend.blocks.conference_paper.models import LikesResult, LikesTask


class BridgeModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class TaskState(StrEnum):
    PENDING = "PENDING"
    CLAIMED = "CLAIMED"
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"


class EnqueueRequest(BridgeModel):
    tasks: list[LikesTask]


class EnqueueResponse(BridgeModel):
    inserted: int = Field(ge=0)
    existing: int = Field(ge=0)


class ClaimedTask(BridgeModel):
    task: LikesTask
    attempts: int = Field(ge=1)


class ClaimResponse(BridgeModel):
    task: LikesTask | None = None
    attempts: int | None = Field(default=None, ge=1)


class ResultResponse(BridgeModel):
    accepted: bool


class RunStateCounts(BridgeModel):
    pending: int = Field(ge=0)
    claimed: int = Field(ge=0)
    success: int = Field(ge=0)
    failed: int = Field(ge=0)


class BridgeRunStatus(BridgeModel):
    counts: RunStateCounts
    results: list[LikesResult] = Field(default_factory=list)
