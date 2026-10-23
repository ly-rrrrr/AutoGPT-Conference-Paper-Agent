ACTION_HEADERS = {"X-Workbench-Request": "1"}


def create_brief(client, title: str = "CVPR 方法迁移") -> dict:
    response = client.post(
        "/api/research/briefs",
        headers=ACTION_HEADERS,
        json={
            "title": title,
            "objective": "发现语言推理方法迁移到视觉与机器人领域时保留和改变了什么。",
            "scope": {"conference": "CVPR", "year": 2026},
            "tool_policy": {"allowed": ["paper_qa", "paper_catalog"]},
            "budget": {"model_calls": 12},
            "output_preferences": {"language": "zh-CN"},
        },
    )
    assert response.status_code == 201
    return response.json()


def create_artifact(client, brief_id: str, **overrides) -> dict:
    payload = {
        "artifact_type": "METHOD_TRANSFER_INVESTIGATION",
        "content": {"question": "GRPO 如何迁移到 VLA？"},
        "narrative": "研究 Agent 正在调查迁移机制。",
        "generator": "paperqa-dspy-adapter",
        "generator_version": "poc-1",
        "configuration": {"workflow": "active-research"},
        "uncertainty": {"status": "OPEN"},
    }
    payload.update(overrides)
    response = client.post(
        f"/api/research/briefs/{brief_id}/artifacts",
        headers=ACTION_HEADERS,
        json=payload,
    )
    assert response.status_code == 201
    return response.json()


def test_research_contract_preserves_goal_evidence_counterpoint_and_provenance(
    client, seeded_db
):
    brief = create_brief(client)
    artifact = create_artifact(client, brief["id"])
    paper = seeded_db["matched"]

    evidence = client.post(
        f"/api/research/artifacts/{artifact['id']}/evidence",
        headers=ACTION_HEADERS,
        json={
            "paper_id": str(paper.id),
            "source_kind": "PAPER_TEXT",
            "source_uri": "analysis.jsonl",
            "page_number": 4,
            "section_title": "Method",
            "quote": "We adapt group relative policy optimization to action reasoning.",
            "locator": {"paragraph": 3},
            "source_sha256": "a" * 64,
            "stance": "SUPPORTS",
        },
    )
    assert evidence.status_code == 201

    insight = client.post(
        f"/api/research/artifacts/{artifact['id']}/insight",
        headers=ACTION_HEADERS,
        json={
            "title": "语言推理优化正在迁移到具身动作推理",
            "statement": "GRPO 被改造为面向多模态动作结果的优化机制。",
            "why_it_matters": "这展示了优化思想跨领域迁移时需要重新定义可验证信号。",
            "epistemic_status": "SYNTHESIZED",
            "scope": {"paper_ids": [str(paper.id)]},
            "counterarguments": ["当前只有一篇论文证据，不能声称形成年度趋势。"],
            "open_questions": ["其他 VLA 工作是否出现同类迁移？"],
            "suggested_view": {"type": "transfer_map"},
        },
    )
    assert insight.status_code == 201

    detail = client.get(f"/api/research/briefs/{brief['id']}")
    assert detail.status_code == 200
    data = detail.json()
    assert data["objective"].startswith("发现语言推理方法")
    assert data["artifacts"][0]["generator"] == "paperqa-dspy-adapter"
    assert data["evidence"][0]["stance"] == "SUPPORTS"
    assert data["insights"][0]["counterarguments"]
    assert data["insights"][0]["epistemic_status"] == "SYNTHESIZED"


def test_artifact_versioning_keeps_dependencies_and_supersedes_without_overwrite(client):
    brief = create_brief(client)
    first = create_artifact(client, brief["id"])
    second = create_artifact(
        client,
        brief["id"],
        supersedes_artifact_id=first["id"],
        parent_artifact_ids=[first["id"]],
        generator_version="poc-2",
        uncertainty={"status": "REVISED"},
    )

    detail = client.get(f"/api/research/briefs/{brief['id']}").json()
    artifacts = {item["id"]: item for item in detail["artifacts"]}
    assert artifacts[first["id"]]["status"] == "SUPERSEDED"
    assert artifacts[second["id"]]["supersedes_artifact_id"] == first["id"]
    assert detail["dependencies"] == [
        {
            "parent_artifact_id": first["id"],
            "child_artifact_id": second["id"],
            "relation": "DERIVED_FROM",
        }
    ]


def test_research_brief_can_be_retargeted_before_running(client):
    brief = create_brief(client)

    response = client.put(
        f"/api/research/briefs/{brief['id']}",
        headers=ACTION_HEADERS,
        json={
            "title": "ECCV 方法迁移",
            "objective": "从已有年度材料中寻找跨领域迁移。",
            "scope": {"conference": "ECCV", "year": 2026},
            "tool_policy": brief["tool_policy"],
            "budget": brief["budget"],
            "output_preferences": brief["output_preferences"],
        },
    )

    assert response.status_code == 200
    assert response.json()["scope"] == {"conference": "ECCV", "year": 2026}
    assert response.json()["status"] == "DRAFT"


def test_research_mutations_require_explicit_local_action(client):
    response = client.post(
        "/api/research/briefs",
        json={"title": "Rejected", "objective": "Must not be written silently."},
    )

    assert response.status_code == 403


def test_research_runtime_exposes_adapter_readiness(client):
    response = client.get("/api/research/runtime")

    assert response.status_code == 200
    body = response.json()
    assert body["ready"] is False
    assert any(item["id"] == "artifact-store" for item in body["components"])


def test_research_brief_reports_material_readiness(client, seeded_db):
    brief = client.post(
        "/api/research/briefs",
        headers=ACTION_HEADERS,
        json={
            "title": "ECCV evidence readiness",
            "objective": "Identify evidence-backed limitations.",
            "scope": {
                "conference": "ECCV",
                "year": 2026,
                "research_scale": "conference_landscape",
                "focus": "robustness",
            },
            "tool_policy": {},
            "budget": {"max_model_calls": 12, "max_papers": 20},
            "output_preferences": {"must_answer": ["What remains unresolved?"]},
        },
    ).json()

    detail = client.get(f"/api/research/briefs/{brief['id']}").json()

    assert detail["coverage"]["paper_count"] == 2
    assert detail["coverage"]["analysis_count"] == 1
    assert detail["coverage"]["document_count"] == 0
    assert detail["coverage"]["status"] == "LIMITED"
    assert detail["coverage"]["warnings"]
    assert detail["events"] == []
