from app.research_runtime import ResearchContext, runtime_status


def test_research_context_preserves_goal_and_policy() -> None:
    context = ResearchContext(
        brief_id="brief-1",
        objective="理解一个方法思想如何跨领域迁移",
        scope={"conference": "CVPR", "year": 2025},
        tool_policy={"allow_counterevidence_search": True},
        budget={"max_model_calls": 40},
        output_preferences={"language": "zh-CN"},
    )

    assert context.objective == "理解一个方法思想如何跨领域迁移"
    assert context.tool_policy["allow_counterevidence_search"] is True


def test_runtime_reports_real_adapter_readiness() -> None:
    status = runtime_status()

    assert status["ready"] is False
    components = {item["id"]: item for item in status["components"]}
    assert components["artifact-store"]["status"] == "READY"
    assert components["paperqa2"]["status"] in {"INSTALLED", "NOT_INSTALLED"}
    assert components["dspy"]["status"] in {"INSTALLED", "NOT_INSTALLED"}
    assert components["active-research-adapter"]["status"] == "NOT_CONFIGURED"
