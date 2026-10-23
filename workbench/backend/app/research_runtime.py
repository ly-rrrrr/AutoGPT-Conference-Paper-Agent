from __future__ import annotations

from dataclasses import dataclass
from importlib.util import find_spec
from typing import Any, Protocol


@dataclass(frozen=True)
class ResearchContext:
    brief_id: str
    objective: str
    scope: dict[str, Any]
    tool_policy: dict[str, Any]
    budget: dict[str, Any]
    output_preferences: dict[str, Any]


@dataclass(frozen=True)
class ResearchToolResult:
    content: dict[str, Any]
    evidence: list[dict[str, Any]]
    uncertainty: dict[str, Any]


class ResearchTool(Protocol):
    name: str

    def execute(
        self, request: dict[str, Any], context: ResearchContext
    ) -> ResearchToolResult: ...


class SemanticProgram(Protocol):
    name: str
    version: str

    def propose(
        self, context: ResearchContext, observations: list[ResearchToolResult]
    ) -> list[dict[str, Any]]: ...

    def revise(
        self,
        context: ResearchContext,
        proposal: dict[str, Any],
        observations: list[ResearchToolResult],
    ) -> dict[str, Any]: ...


class ResearchWorkflowAdapter(Protocol):
    name: str
    version: str

    def run(self, context: ResearchContext) -> list[dict[str, Any]]: ...


def runtime_status(provider_ready: bool = False) -> dict[str, Any]:
    paperqa_installed = find_spec("paperqa") is not None
    dspy_installed = find_spec("dspy") is not None
    return {
        "ready": provider_ready,
        "control_plane": {
            "name": "AutoGPT",
            "status": "AVAILABLE",
            "detail": "现有任务调度保留为外层控制面。",
        },
        "components": [
            {
                "id": "artifact-store",
                "name": "Research Artifact Store",
                "status": "READY",
                "detail": "研究目标、版本化产物、证据、反证与洞察契约已经启用。",
            },
            {
                "id": "paperqa2",
                "name": "PaperQA2",
                "status": "INSTALLED" if paperqa_installed else "NOT_INSTALLED",
                "detail": "科学文献检索、证据阅读与带引文回答适配器。",
            },
            {
                "id": "dspy",
                "name": "DSPy",
                "status": "INSTALLED" if dspy_installed else "NOT_INSTALLED",
                "detail": "研究提议、质疑、修订与综合的声明式语义程序。",
            },
            {
                "id": "model-provider",
                "name": "OpenAI-compatible Provider",
                "status": "READY" if provider_ready else "NOT_CONFIGURED",
                "detail": "为主动研究循环提供模型推理与工具选择。",
            },
            {
                "id": "active-research-adapter",
                "name": "Active Research Adapter",
                "status": "READY" if provider_ready else "NOT_CONFIGURED",
                "detail": "目标驱动的论文检索、材料读取、反证探索与洞察发布循环。",
            },
        ],
    }
