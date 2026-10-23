from app.cognition_workflow import prepare_control_state


def test_langgraph_harness_prepares_without_starting_discovery():
    state = prepare_control_state(
        {
            "scope": {"conference": "CVPR", "year": 2026},
            "coverage": {
                "papers": 2672,
                "paper_analyses": 2664,
                "paper_memories": 2664,
            },
            "material_fingerprint": "a" * 64,
        }
    )

    assert state["stage"] == "PREPARED"
    assert state["next_stage"] == "await_discovery_start"
    assert state["decisions"] == [
        "以 2672 篇论文作为完整语料分母，而不是抽样分母",
        "已有逐篇分析全部登记为版本化论文记忆",
    ]
