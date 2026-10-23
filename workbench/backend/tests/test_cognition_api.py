ACTION_HEADERS = {"X-Workbench-Request": "1"}


def test_cognition_overview_uses_complete_conference_denominator(client, seeded_db):
    response = client.get("/api/cognition/overview?conference=ECCV&year=2026")

    assert response.status_code == 200
    body = response.json()
    assert body["coverage"]["papers"] == 2
    assert body["coverage"]["arxiv_links"] == 1
    assert body["coverage"]["paper_analyses"] == 1
    assert body["coverage"]["likes"] == 1
    assert body["gaps"]["missing_analysis"] == 1
    assert body["stages"][0]["status"] == "SOURCE_READY"
    assert body["stages"][1]["status"] == "NOT_IMPLEMENTED"


def test_preparing_same_corpus_twice_reuses_material_snapshot(client, seeded_db):
    payload = {"conference": "ECCV", "year": 2026}

    first = client.post(
        "/api/cognition/prepare", headers=ACTION_HEADERS, json=payload
    )
    second = client.post(
        "/api/cognition/prepare", headers=ACTION_HEADERS, json=payload
    )

    assert first.status_code == 200
    assert first.json()["status"] == "PREPARED"
    assert first.json()["run"]["counters"]["model_calls"] == 0
    assert second.status_code == 200
    assert second.json()["status"] == "REUSED"
    assert second.json()["run"]["id"] == first.json()["run"]["id"]

    overview = client.get("/api/cognition/overview?conference=ECCV&year=2026").json()
    assert [event["event_type"] for event in overview["events"]] == [
        "CORPUS_SNAPSHOT_CREATED",
        "CACHE_PLAN_CREATED",
        "HARNESS_PREPARED",
    ]
