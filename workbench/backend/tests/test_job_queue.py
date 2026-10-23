from app.job_queue import claim_next_run, enqueue_run, fail_run, finish_run


def test_job_can_be_claimed_and_completed(api_session, seeded_db):
    run = enqueue_run(
        api_session,
        run_key=f"lineage:{seeded_db['matched'].id}",
        pipeline="lineage",
        config={"paper_id": str(seeded_db["matched"].id)},
    )
    api_session.commit()

    claimed = claim_next_run(api_session, "test-worker")
    assert claimed.id == run.id
    assert claimed.status == "RUNNING"
    assert claimed.attempt_count == 1
    finish_run(api_session, run.id)

    assert run.status == "SUCCESS"
    assert run.ended_at is not None
    assert run.lease_owner is None


def test_failed_job_retries_then_stops(api_session):
    run = enqueue_run(
        api_session,
        run_key="lineage:test",
        pipeline="lineage",
        config={"paper_id": "00000000-0000-0000-0000-000000000000"},
        max_attempts=2,
    )
    api_session.commit()
    claim_next_run(api_session, "test-worker")
    fail_run(api_session, run.id, RuntimeError("temporary"))

    assert run.status == "QUEUED"
    run.available_at = None
    claim_next_run(api_session, "test-worker")
    fail_run(api_session, run.id, RuntimeError("permanent"))

    assert run.status == "FAILED"
    assert run.last_error == "permanent"
