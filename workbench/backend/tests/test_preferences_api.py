from app.scoring import PaperSignals, PreferenceSignals, score_paper


def test_score_exposes_each_component():
    score = score_paper(
        PaperSignals(
            title="Vision-language adaptation for robotics",
            topic="Vision-language learning",
            likes=42,
            year=2026,
        ),
        PreferenceSignals(
            interests=["vision-language"],
            keywords=["robotics"],
            recent_work_terms=["adaptation"],
            weights={
                "recent_work": 0.3,
                "interest": 0.25,
                "keyword": 0.2,
                "impact": 0.15,
                "freshness": 0.1,
            },
        ),
    )

    assert score.total == sum(score.components.values())
    assert set(score.components) == {
        "recent_work",
        "interest",
        "keyword",
        "impact",
        "freshness",
    }


def test_preferences_api_persists_explainable_inputs(client, api_session):
    response = client.post(
        "/api/preferences/interests",
        headers={"X-Workbench-Request": "1"},
        json={"kind": "interest", "value": "3D reconstruction", "weight": 0.8},
    )

    assert response.status_code == 201
    data = client.get("/api/preferences").json()
    assert data["interests"][0]["value"] == "3D reconstruction"
    assert data["interests"][0]["weight"] == 0.8


def test_knowledge_api_reports_missing_documents(client, seeded_db):
    response = client.get("/api/knowledge/documents")

    assert response.status_code == 200
    assert response.json()["summary"]["MISSING"] == 2
