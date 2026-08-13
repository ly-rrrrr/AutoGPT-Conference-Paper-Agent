import pytest

from backend.blocks.conference_paper.models import LikesResult, LikesTask
from backend.conference_paper_bridge.store import TaskConflictError, TaskStore


@pytest.fixture(scope="session", autouse=True)
def graph_cleanup() -> None:
    return None


@pytest.fixture
def store(tmp_path) -> TaskStore:
    task_store = TaskStore(tmp_path / "bridge.db")
    task_store.initialize()
    return task_store


def likes_task(arxiv_id: str = "2503.00001") -> LikesTask:
    return LikesTask(
        paper_key=f"arxiv:{arxiv_id}",
        title=f"Paper {arxiv_id}",
        arxiv_url=f"https://arxiv.org/abs/{arxiv_id}",
        arxiv_id=arxiv_id,
    )


def success_result(arxiv_id: str = "2503.00001", likes: int = 83) -> LikesResult:
    return LikesResult(
        paper_key=f"arxiv:{arxiv_id}",
        arxiv_id=arxiv_id,
        likes=likes,
        raw_text=f"{likes} Likes",
        status="SUCCESS",
    )


def test_enqueue_is_idempotent_and_rejects_changed_identity(store: TaskStore):
    task = likes_task()

    assert store.enqueue("run-1", [task]).model_dump() == {
        "inserted": 1,
        "existing": 0,
    }
    assert store.enqueue("run-1", [task]).model_dump() == {
        "inserted": 0,
        "existing": 1,
    }

    changed = task.model_copy(update={"arxiv_url": "https://arxiv.org/abs/changed"})
    with pytest.raises(TaskConflictError, match="does not match"):
        store.enqueue("run-1", [changed])

    assert store.status("run-1").counts.pending == 1


def test_claim_is_fifo_and_each_task_is_claimed_once(store: TaskStore):
    store.enqueue("run-1", [likes_task("2503.00001"), likes_task("2503.00002")])

    first = store.claim_next("run-1")
    second = store.claim_next("run-1")

    assert first is not None
    assert second is not None
    assert first.task.arxiv_id == "2503.00001"
    assert second.task.arxiv_id == "2503.00002"
    assert first.attempts == second.attempts == 1
    assert store.claim_next("run-1") is None
    assert store.status("run-1").counts.claimed == 2


def test_success_result_cannot_be_overwritten(store: TaskStore):
    store.enqueue("run-1", [likes_task()])
    store.claim_next("run-1")
    store.record_result("run-1", success_result(likes=83))

    with pytest.raises(TaskConflictError, match="already succeeded"):
        store.record_result("run-1", success_result(likes=84))

    run_status = store.status("run-1")
    assert run_status.counts.success == 1
    assert run_status.results[0].likes == 83


def test_result_identity_mismatch_is_rejected(store: TaskStore):
    store.enqueue("run-1", [likes_task()])
    store.claim_next("run-1")
    mismatched = LikesResult(
        paper_key="arxiv:2503.00001",
        arxiv_id="2503.99999",
        status="FAILED",
        error_code="LIKES_ELEMENT_NOT_FOUND",
    )

    with pytest.raises(TaskConflictError, match="arXiv identity"):
        store.record_result("run-1", mismatched)

    assert store.status("run-1").counts.claimed == 1
