from typing import TypedDict

from langgraph.graph import END, START, StateGraph


class HarnessState(TypedDict, total=False):
    conference: str
    year: int
    papers: int
    paper_analyses: int
    paper_memories: int
    material_fingerprint: str
    discovery_enabled: bool
    stage: str
    next_stage: str
    decisions: list[str]


def orient(state: HarnessState) -> HarnessState:
    decisions = list(state.get("decisions", []))
    decisions.append(
        f"以 {state['papers']} 篇论文作为完整语料分母，而不是抽样分母"
    )
    return {"stage": "ORIENT", "decisions": decisions}


def reconcile_memory(state: HarnessState) -> HarnessState:
    decisions = list(state.get("decisions", []))
    if state.get("paper_memories") == state.get("paper_analyses"):
        decisions.append("已有逐篇分析全部登记为版本化论文记忆")
    else:
        decisions.append("先补齐或登记可复用论文记忆，再进入全语料发现")
    return {"stage": "PAPER_MEMORY", "decisions": decisions}


def discovery_gate(state: HarnessState) -> HarnessState:
    if state.get("discovery_enabled"):
        return {"stage": "DISCOVERY_READY", "next_stage": "corpus_discovery"}
    return {"stage": "PREPARED", "next_stage": "await_discovery_start"}


def build_cognition_harness():
    builder = StateGraph(HarnessState)
    builder.add_node("orient", orient)
    builder.add_node("reconcile_memory", reconcile_memory)
    builder.add_node("discovery_gate", discovery_gate)
    builder.add_edge(START, "orient")
    builder.add_edge("orient", "reconcile_memory")
    builder.add_edge("reconcile_memory", "discovery_gate")
    builder.add_edge("discovery_gate", END)
    return builder.compile()


def prepare_control_state(snapshot: dict) -> HarnessState:
    graph = build_cognition_harness()
    return graph.invoke(
        {
            "conference": snapshot["scope"]["conference"],
            "year": snapshot["scope"]["year"],
            "papers": snapshot["coverage"]["papers"],
            "paper_analyses": snapshot["coverage"]["paper_analyses"],
            "paper_memories": snapshot["coverage"]["paper_memories"],
            "material_fingerprint": snapshot["material_fingerprint"],
            "discovery_enabled": False,
            "decisions": [],
        }
    )
