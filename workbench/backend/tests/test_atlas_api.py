from app.models import (
    CognitionArtifact,
    CognitionArtifactDependency,
    CognitionArtifactSource,
)


def test_atlas_projects_method_insights_into_an_interactive_graph(
    client, api_session, seeded_db
):
    observation = CognitionArtifact(
        artifact_type="CORPUS_BATCH_OBSERVATION",
        input_fingerprint="a" * 64,
        status="CANDIDATE",
        scope={
            "conference": "ECCV",
            "year": 2026,
            "paper_ids": [str(seeded_db["matched"].id)],
        },
        content={"batch_summary": "批次观察"},
        generator="cartographer",
        generator_version="corpus-discovery-v1",
        uncertainty={},
    )
    api_session.add(observation)
    api_session.flush()
    insight = CognitionArtifact(
        artifact_type="METHOD_INSIGHT",
        input_fingerprint="b" * 64,
        status="CHALLENGED",
        scope={"conference": "ECCV", "year": 2026},
        content={
            "title": "由问题压力驱动的方法迁移",
            "claim": "同一机制经过适配进入视觉系统",
            "mechanism": "共享表征同步",
            "problem_pressure": "模态错位",
            "borrowed_idea": "无监督适配",
            "adaptation": "跨模态同步约束",
            "domains": ["视觉语言"],
            "transfer_targets": ["机器人"],
            "supporting_paper_ids": [str(seeded_db["matched"].id)],
            "counter_paper_ids": [],
            "confidence": 0.72,
        },
        generator="cartographer-challenger-curator",
        generator_version="method-atlas-v1",
        uncertainty={"evidence_boundary": "单批次"},
    )
    api_session.add(insight)
    api_session.flush()
    api_session.add_all(
        [
            CognitionArtifactDependency(
                artifact_id=insight.id,
                depends_on_artifact_id=observation.id,
                relation="SYNTHESIZES",
            ),
            CognitionArtifactSource(
                artifact_id=insight.id,
                paper_id=seeded_db["matched"].id,
                stance="SUPPORTING",
                locator={"source": "test"},
            ),
        ]
    )
    api_session.commit()

    overview = client.get("/api/atlas/overview?conference=ECCV&year=2026").json()
    graph = client.get("/api/atlas/graph?conference=ECCV&year=2026").json()
    listed = client.get("/api/atlas/insights?conference=ECCV&year=2026").json()

    assert overview["discovery_artifacts"] == 1
    assert overview["consumed_discovery_artifacts"] == 1
    assert overview["insights"] == 1
    assert listed["items"][0]["sources"][0]["stance"] == "SUPPORTING"
    assert {node["kind"] for node in graph["nodes"]} == {
        "insight",
        "mechanism",
        "pressure",
        "domain",
        "transfer",
    }


def test_synthesis_requires_discovery_artifacts(client, seeded_db):
    response = client.post(
        "/api/atlas/synthesis/start",
        headers={"X-Workbench-Request": "1"},
        json={"conference": "ECCV", "year": 2026},
    )

    assert response.status_code == 409
