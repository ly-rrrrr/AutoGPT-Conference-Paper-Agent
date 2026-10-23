from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import httpx
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.database import session_scope
from app.models import (
    ConferenceEdition,
    InsightProposal,
    ModelProviderConfig,
    Paper,
    PaperAnalysis,
    PaperAnswer,
    PipelineEvent,
    PipelineRun,
    ResearchArtifact,
    ResearchArtifactDependency,
    ResearchBrief,
    ResearchEvidenceRef,
)
from app.secret_store import get_secret


@dataclass(frozen=True)
class ProviderSnapshot:
    name: str
    base_url: str
    model_name: str
    api_key: str


TOOLS = [
    {
        "type": "function",
        "name": "scope_overview",
        "description": "Inspect the available paper corpus and topic distribution inside the research brief scope.",
        "parameters": {
            "type": "object",
            "properties": {},
            "required": [],
            "additionalProperties": False,
        },
        "strict": True,
    },
    {
        "type": "function",
        "name": "search_papers",
        "description": "Search paper titles and imported topics inside the brief scope. Use multiple conceptually different queries when useful.",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "limit": {"type": "integer", "minimum": 1, "maximum": 20},
            },
            "required": ["query", "limit"],
            "additionalProperties": False,
        },
        "strict": True,
    },
    {
        "type": "function",
        "name": "inspect_papers",
        "description": "Read imported structured analyses for selected papers. Call this before making claims about methods, motivations, or transfers.",
        "parameters": {
            "type": "object",
            "properties": {
                "paper_ids": {
                    "type": "array",
                    "items": {"type": "string"},
                    "minItems": 1,
                    "maxItems": 8,
                }
            },
            "required": ["paper_ids"],
            "additionalProperties": False,
        },
        "strict": True,
    },
]


class ResearchCorpusTools:
    def __init__(self, session: Session, brief: ResearchBrief):
        self.session = session
        self.brief = brief
        self.accessed_paper_ids: set[uuid.UUID] = set()

    def _scope_query(self):
        query = select(Paper).join(
            ConferenceEdition, Paper.conference_edition_id == ConferenceEdition.id
        )
        conference = self.brief.scope.get("conference")
        year = self.brief.scope.get("year")
        if conference:
            query = query.where(ConferenceEdition.conference == str(conference).upper())
        if year:
            query = query.where(ConferenceEdition.year == int(year))
        return query

    def call(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        if name == "scope_overview":
            return self.scope_overview()
        if name == "search_papers":
            return self.search_papers(str(arguments["query"]), int(arguments["limit"]))
        if name == "inspect_papers":
            return self.inspect_papers(arguments["paper_ids"])
        return {"error": f"unknown tool: {name}"}

    def scope_overview(self) -> dict[str, Any]:
        papers = list(self.session.scalars(self._scope_query()))
        topic_counts: dict[str, int] = {}
        for paper in papers:
            topic = paper.topic or "未标注"
            topic_counts[topic] = topic_counts.get(topic, 0) + 1
        topics = sorted(topic_counts.items(), key=lambda item: item[1], reverse=True)[:30]
        return {
            "paper_count": len(papers),
            "top_imported_topics": [
                {"topic": topic, "count": count} for topic, count in topics
            ],
            "note": "Imported topics are navigation signals, not final method categories.",
        }

    def search_papers(self, query: str, limit: int) -> dict[str, Any]:
        pattern = f"%{query.strip()}%"
        statement = (
            self._scope_query()
            .where(or_(Paper.title.ilike(pattern), Paper.topic.ilike(pattern)))
            .limit(min(max(limit, 1), 20))
        )
        papers = list(self.session.scalars(statement))
        return {
            "query": query,
            "items": [
                {
                    "paper_id": str(paper.id),
                    "title": paper.title,
                    "topic": paper.topic,
                    "arxiv_id": paper.arxiv_id,
                }
                for paper in papers
            ],
        }

    def inspect_papers(self, paper_ids: list[str]) -> dict[str, Any]:
        valid_ids = []
        for value in paper_ids[:8]:
            try:
                valid_ids.append(uuid.UUID(value))
            except ValueError:
                continue
        if not valid_ids:
            return {"items": [], "warning": "No valid paper IDs were supplied."}
        scoped_ids = set(
            self.session.scalars(
                self._scope_query().where(Paper.id.in_(valid_ids)).with_only_columns(Paper.id)
            )
        )
        papers = list(
            self.session.scalars(select(Paper).where(Paper.id.in_(scoped_ids)))
        )
        items = []
        for paper in papers:
            analysis = self.session.scalar(
                select(PaperAnalysis)
                .where(
                    PaperAnalysis.paper_id == paper.id,
                    PaperAnalysis.status == "SUCCESS",
                )
                .order_by(PaperAnalysis.analyzed_at.desc())
            )
            answers = []
            if analysis:
                answers = [
                    {"question": item.question, "answer": item.answer}
                    for item in self.session.scalars(
                        select(PaperAnswer)
                        .where(PaperAnswer.analysis_id == analysis.id)
                        .order_by(PaperAnswer.position)
                    )
                ]
            self.accessed_paper_ids.add(paper.id)
            payload = analysis.payload if analysis else None
            serialized_payload = json.dumps(payload, ensure_ascii=False) if payload else ""
            items.append(
                {
                    "paper_id": str(paper.id),
                    "title": paper.title,
                    "topic": paper.topic,
                    "arxiv_id": paper.arxiv_id,
                    "analysis": json.loads(serialized_payload[:12000])
                    if serialized_payload and len(serialized_payload) <= 12000
                    else serialized_payload[:12000],
                    "answers": answers[:12],
                    "source": {
                        "kind": "PAPER_ANALYSIS",
                        "uri": analysis.source_path if analysis else "paper-catalog",
                        "sha256": analysis.source_sha256 if analysis else None,
                    },
                }
            )
        return {"items": items}


class OpenAICompatibleResearchAdapter:
    name = "openai-compatible-active-research"
    version = "v1"

    def __init__(self, provider: ProviderSnapshot, timeout_seconds: float = 180):
        self.provider = provider
        self.timeout_seconds = timeout_seconds

    def run(
        self, brief: ResearchBrief, tools: ResearchCorpusTools
    ) -> tuple[dict[str, Any], int]:
        max_calls = min(max(int(brief.budget.get("max_model_calls", 12)), 1), 40)
        instructions = self._instructions(brief)
        input_items: list[Any] = [
            {
                "role": "user",
                "content": (
                    f"研究任务：{brief.title}\n研究目标：{brief.objective}\n"
                    f"范围：{json.dumps(brief.scope, ensure_ascii=False)}\n"
                    "请自主决定调查路径，并在证据足够或预算不足时形成当前最可靠的认识。"
                ),
            }
        ]
        calls = 0
        with httpx.Client(timeout=self.timeout_seconds) as client:
            while calls < max_calls:
                payload = {
                    "model": self.provider.model_name,
                    "instructions": instructions,
                    "input": input_items,
                    "tools": TOOLS,
                    "tool_choice": "required" if calls == 0 else "auto",
                }
                response = client.post(
                    f"{self.provider.base_url.rstrip('/')}/responses",
                    headers={
                        "Authorization": f"Bearer {self.provider.api_key}",
                        "Content-Type": "application/json",
                    },
                    json=payload,
                )
                response.raise_for_status()
                body = response.json()
                calls += 1
                output = body.get("output", [])
                input_items.extend(output)
                tool_calls = [item for item in output if item.get("type") == "function_call"]
                if tool_calls:
                    for call in tool_calls:
                        try:
                            arguments = json.loads(call.get("arguments") or "{}")
                            result = tools.call(call.get("name", ""), arguments)
                        except (KeyError, TypeError, ValueError) as error:
                            result = {"error": str(error)}
                        input_items.append(
                            {
                                "type": "function_call_output",
                                "call_id": call.get("call_id"),
                                "output": json.dumps(result, ensure_ascii=False),
                            }
                        )
                    continue
                text = self._output_text(body)
                if text:
                    return self._parse_report(text), calls
                raise RuntimeError("模型没有返回工具调用或研究报告")
        raise RuntimeError(f"研究任务达到模型调用预算上限（{max_calls}）但没有形成报告")

    @staticmethod
    def _instructions(brief: ResearchBrief) -> str:
        language = brief.output_preferences.get("language", "zh-CN")
        return f"""
你是科研工作台中的主动研究 Agent。输出语言为 {language}。
你的职责不是把论文压缩进预置标签，而是围绕用户目标发现值得表达的方法现象。
必须先使用工具查看任务范围与论文材料。根据当前认识自主选择搜索词和需要深读的论文；主动寻找支持、差异、反例与证据缺口。
不得把导入主题、标题相似度或单篇作者叙事直接冒充年度趋势。只能引用 inspect_papers 实际返回过的 paper_id。
完成调查后只返回一个 JSON 对象，不要使用 Markdown 围栏：
{{
  "summary": "对当前任务的综合认识",
  "limitations": ["证据边界或未解决问题"],
  "insights": [
    {{
      "title": "洞察标题",
      "statement": "具体、可证伪的认识",
      "why_it_matters": "为什么值得关注",
      "epistemic_status": "OBSERVED|AUTHOR_CLAIM|INFERRED|SYNTHESIZED",
      "evidence": [{{"paper_id": "UUID", "stance": "SUPPORTS|CHALLENGES|CONTEXT", "rationale": "该材料如何作用于结论"}}],
      "counterarguments": ["反方解释"],
      "open_questions": ["需要继续调查的问题"],
      "suggested_view": {{"type": "timeline|method_map|transfer_map|comparison"}}
    }}
  ]
}}
至少给出一个洞察；没有充分证据时降低 epistemic_status，并明确 limitations，而不是编造。
""".strip()

    @staticmethod
    def _output_text(body: dict[str, Any]) -> str:
        if isinstance(body.get("output_text"), str):
            return body["output_text"]
        parts = []
        for item in body.get("output", []):
            if item.get("type") != "message":
                continue
            for content in item.get("content", []):
                if content.get("type") == "output_text" and content.get("text"):
                    parts.append(content["text"])
        return "\n".join(parts)

    @staticmethod
    def _parse_report(text: str) -> dict[str, Any]:
        candidate = text.strip()
        if candidate.startswith("```"):
            candidate = candidate.split("\n", 1)[-1].rsplit("```", 1)[0]
        try:
            report = json.loads(candidate)
        except json.JSONDecodeError:
            start = candidate.find("{")
            end = candidate.rfind("}")
            if start < 0 or end <= start:
                raise RuntimeError("模型报告不是有效 JSON")
            report = json.loads(candidate[start : end + 1])
        if not isinstance(report.get("insights"), list) or not report["insights"]:
            raise RuntimeError("模型报告没有提供候选洞察")
        return report


def _provider_snapshot(session: Session) -> ProviderSnapshot:
    config = session.scalar(
        select(ModelProviderConfig)
        .where(ModelProviderConfig.is_default.is_(True), ModelProviderConfig.status == "ACTIVE")
        .order_by(ModelProviderConfig.updated_at.desc())
    )
    if config is None:
        raise RuntimeError("尚未配置默认模型")
    api_key = get_secret(config.secret_ref)
    if not api_key:
        raise RuntimeError("默认模型尚未保存 API Key")
    return ProviderSnapshot(config.name, config.base_url, config.model_name, api_key)


def run_research_brief(brief_id: uuid.UUID, run_id: uuid.UUID) -> None:
    with session_scope() as session:
        brief = session.get(ResearchBrief, brief_id)
        run = session.get(PipelineRun, run_id)
        if brief is None or run is None:
            return
        try:
            provider = _provider_snapshot(session)
            tools = ResearchCorpusTools(session, brief)
            report, model_calls = OpenAICompatibleResearchAdapter(provider).run(
                brief, tools
            )
            overview = ResearchArtifact(
                research_brief_id=brief.id,
                workflow_run_id=run.id,
                artifact_type="ACTIVE_RESEARCH_REPORT",
                status="CANDIDATE",
                content={
                    "summary": report.get("summary", ""),
                    "limitations": report.get("limitations", []),
                },
                narrative=report.get("summary"),
                generator=OpenAICompatibleResearchAdapter.name,
                generator_version=OpenAICompatibleResearchAdapter.version,
                configuration={"provider": provider.name, "model": provider.model_name},
                uncertainty={"limitations": report.get("limitations", [])},
            )
            session.add(overview)
            session.flush()
            persisted = 0
            for insight_data in report["insights"][:20]:
                artifact = ResearchArtifact(
                    research_brief_id=brief.id,
                    workflow_run_id=run.id,
                    artifact_type="INSIGHT_PROPOSAL",
                    status="CANDIDATE",
                    content=insight_data,
                    narrative=insight_data.get("statement"),
                    generator=OpenAICompatibleResearchAdapter.name,
                    generator_version=OpenAICompatibleResearchAdapter.version,
                    configuration={"provider": provider.name, "model": provider.model_name},
                    uncertainty={
                        "counterarguments": insight_data.get("counterarguments", []),
                        "open_questions": insight_data.get("open_questions", []),
                    },
                )
                session.add(artifact)
                session.flush()
                session.add(
                    ResearchArtifactDependency(
                        parent_artifact_id=overview.id,
                        child_artifact_id=artifact.id,
                        relation="CONTAINS_INSIGHT",
                    )
                )
                status = insight_data.get("epistemic_status", "INFERRED")
                if status not in {"OBSERVED", "AUTHOR_CLAIM", "INFERRED", "SYNTHESIZED"}:
                    status = "INFERRED"
                insight = InsightProposal(
                    research_artifact_id=artifact.id,
                    title=str(insight_data.get("title", "未命名洞察")),
                    statement=str(insight_data.get("statement", "")),
                    why_it_matters=str(insight_data.get("why_it_matters", "")),
                    epistemic_status=status,
                    scope=brief.scope,
                    counterarguments=insight_data.get("counterarguments", []),
                    open_questions=insight_data.get("open_questions", []),
                    suggested_view=insight_data.get("suggested_view", {}),
                    status="CANDIDATE",
                )
                session.add(insight)
                for evidence in insight_data.get("evidence", []):
                    try:
                        paper_id = uuid.UUID(str(evidence.get("paper_id")))
                    except (TypeError, ValueError):
                        continue
                    if paper_id not in tools.accessed_paper_ids:
                        continue
                    analysis = session.scalar(
                        select(PaperAnalysis)
                        .where(PaperAnalysis.paper_id == paper_id, PaperAnalysis.status == "SUCCESS")
                        .order_by(PaperAnalysis.analyzed_at.desc())
                    )
                    stance = evidence.get("stance", "CONTEXT")
                    if stance not in {"SUPPORTS", "CHALLENGES", "CONTEXT"}:
                        stance = "CONTEXT"
                    session.add(
                        ResearchEvidenceRef(
                            research_artifact_id=artifact.id,
                            paper_id=paper_id,
                            source_kind="PAPER_ANALYSIS",
                            source_uri=analysis.source_path if analysis else "paper-catalog",
                            source_sha256=analysis.source_sha256 if analysis else None,
                            locator={"rationale": evidence.get("rationale", "")},
                            stance=stance,
                        )
                    )
                persisted += 1
            brief.status = "COMPLETED"
            run.status = "COMPLETED"
            run.counters = {
                "model_calls": model_calls,
                "papers_inspected": len(tools.accessed_paper_ids),
                "insights": persisted,
            }
            run.ended_at = datetime.now(UTC)
        except Exception as error:
            brief.status = "FAILED"
            run.status = "FAILED"
            run.ended_at = datetime.now(UTC)
            run.counters = {"error": str(error)[:1000]}
            session.add(
                PipelineEvent(
                    pipeline_run_id=run.id,
                    level="ERROR",
                    event_type="RESEARCH_FAILED",
                    message="主动研究任务失败",
                    details={"error": str(error)[:3000]},
                )
            )
