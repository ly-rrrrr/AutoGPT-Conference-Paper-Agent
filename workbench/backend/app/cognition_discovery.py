from __future__ import annotations

import hashlib
import json
import uuid
from datetime import UTC, datetime

import httpx
from sqlalchemy import select

from app.database import session_scope
from app.models import (
    CognitionArtifact,
    CognitionArtifactSource,
    CognitionPaperMemory,
    ConferenceEdition,
    ModelProviderConfig,
    Paper,
    PaperAnalysis,
    PaperAnswer,
    PipelineEvent,
    PipelineRun,
)
from app.network import outbound_proxy
from app.secret_store import get_secret


DISCOVERY_VERSION = "corpus-discovery-v1"
DISCOVERY_FIELDS = (
    "research_problem",
    "method_summary",
    "main_contributions",
    "key_results",
    "limitations",
    "datasets",
    "source_references",
    "code_urls",
    "answer_by_question",
    "raw_answer",
)


def _event(session, run_id, event_type: str, message: str, details: dict) -> None:
    session.add(
        PipelineEvent(
            pipeline_run_id=run_id,
            level="INFO",
            event_type=event_type,
            message=message,
            details=details,
        )
    )
    session.commit()


def _provider(session, config_id: uuid.UUID) -> tuple[ModelProviderConfig, str]:
    config = session.get(ModelProviderConfig, config_id)
    if config is None or config.status != "ACTIVE":
        raise RuntimeError("认知发现使用的模型配置不存在或已停用")
    api_key = get_secret(config.secret_ref)
    if not api_key:
        raise RuntimeError("默认模型尚未保存 API Key")
    return config, api_key


def _paper_batch(session, conference: str, year: int, limit: int):
    covered = (
        select(CognitionArtifactSource.paper_id)
        .join(
            CognitionArtifact,
            CognitionArtifactSource.artifact_id == CognitionArtifact.id,
        )
        .where(
            CognitionArtifact.artifact_type == "CORPUS_BATCH_OBSERVATION",
            CognitionArtifact.generator_version == DISCOVERY_VERSION,
        )
    )
    statement = (
        select(CognitionPaperMemory, Paper, PaperAnalysis)
        .join(Paper, CognitionPaperMemory.paper_id == Paper.id)
        .join(PaperAnalysis, CognitionPaperMemory.analysis_id == PaperAnalysis.id)
        .join(
            ConferenceEdition,
            Paper.conference_edition_id == ConferenceEdition.id,
        )
        .where(
            ConferenceEdition.conference == conference.upper(),
            ConferenceEdition.year == year,
            CognitionPaperMemory.status == "SOURCE_READY",
            CognitionPaperMemory.paper_id.not_in(covered),
        )
        .order_by(CognitionPaperMemory.paper_id)
        .limit(limit)
    )
    return list(session.execute(statement))


def _compact_analysis(payload: dict | None, char_budget: int) -> dict:
    compact = {}
    seen_values = set()
    remaining = max(500, char_budget)
    for key in DISCOVERY_FIELDS:
        value = (payload or {}).get(key)
        if value in (None, "", [], {}):
            continue
        serialized = json.dumps(value, ensure_ascii=False)
        value_fingerprint = hashlib.sha256(serialized.encode()).hexdigest()
        if value_fingerprint in seen_values:
            continue
        seen_values.add(value_fingerprint)
        if len(serialized) > remaining:
            if isinstance(value, str):
                value = value[:remaining]
            else:
                continue
        compact[key] = value
        remaining -= len(json.dumps(value, ensure_ascii=False))
        if remaining <= 0:
            break
    return compact


def _pack_batch(session, rows, max_input_chars: int) -> tuple[list[dict], str]:
    if not rows:
        return [], ""
    analysis_ids = [analysis.id for _, _, analysis in rows]
    answers_by_analysis: dict[uuid.UUID, list[dict]] = {}
    for answer in session.scalars(
        select(PaperAnswer)
        .where(PaperAnswer.analysis_id.in_(analysis_ids))
        .order_by(PaperAnswer.analysis_id, PaperAnswer.position)
    ):
        answers_by_analysis.setdefault(answer.analysis_id, []).append(
            {"question": answer.question, "answer": answer.answer}
        )
    per_paper_limit = max(1500, max_input_chars // len(rows))
    packets = []
    fingerprint_parts = []
    for memory, paper, analysis in rows:
        material = {
            "paper_id": str(paper.id),
            "title": paper.title,
            "topic_hint": paper.topic,
            "analysis": _compact_analysis(analysis.payload, per_paper_limit - 500),
            "answers": answers_by_analysis.get(analysis.id, [])[:12],
        }
        serialized = json.dumps(material, ensure_ascii=False)
        if len(serialized) > per_paper_limit:
            material["answers"] = []
            material["truncated"] = True
        packets.append(material)
        fingerprint_parts.append(memory.input_fingerprint)
    fingerprint = hashlib.sha256(
        f"{DISCOVERY_VERSION}\n".encode()
        + "\n".join(fingerprint_parts).encode()
    ).hexdigest()
    return packets, fingerprint


def _response_text(body: dict) -> str:
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


def _parse_json(text: str) -> dict:
    candidate = text.strip()
    if candidate.startswith("```"):
        candidate = candidate.split("\n", 1)[-1].rsplit("```", 1)[0]
    try:
        result = json.loads(candidate)
    except json.JSONDecodeError:
        start = candidate.find("{")
        end = candidate.rfind("}")
        if start < 0 or end <= start:
            raise RuntimeError("模型没有返回有效的发现结果 JSON")
        result = json.loads(candidate[start : end + 1])
    if not result.get("observations") and not result.get("research_agenda"):
        raise RuntimeError("模型没有形成批次观察或后续研究议程")
    return result


def _validate_result(result: dict, valid_ids: set[str]) -> dict:
    validated_observations = []
    for observation in result.get("observations", []):
        if not isinstance(observation, dict):
            continue
        paper_ids = sorted(
            {
                paper_id
                for paper_id in observation.get("paper_ids", [])
                if paper_id in valid_ids
            }
        )
        if not paper_ids or not observation.get("statement"):
            continue
        validated_observations.append({**observation, "paper_ids": paper_ids})
    validated_agenda = []
    for agenda in result.get("research_agenda", []):
        if not isinstance(agenda, dict):
            continue
        paper_ids = sorted(
            {
                paper_id
                for paper_id in agenda.get("paper_ids", [])
                if paper_id in valid_ids
            }
        )
        if not paper_ids or not agenda.get("question"):
            continue
        validated_agenda.append({**agenda, "paper_ids": paper_ids})
    if not validated_observations and not validated_agenda:
        raise RuntimeError("模型结果没有引用本批次中的真实论文")
    return {
        **result,
        "observations": validated_observations,
        "research_agenda": validated_agenda,
    }


def _discover(config, api_key: str, packets: list[dict]) -> tuple[dict, dict]:
    instructions = """
你是持续科研认知系统中的 Cartographer。你看到的是完整会议语料中的一个覆盖批次，而不是用户预先提出的问题。
不要把 topic_hint 当作最终分类，不要套用固定方法标签，也不要把本批次结果冒充年度趋势。
自主发现值得后续调查的方法现象、共同困难、异常差异、可能的思想迁移或叙事与证据张力。
每项观察必须引用输入中真实存在的 paper_id，并明确它只是批次级候选。
只返回 JSON：
{
  "batch_summary": "本批次总体观察",
  "observations": [{
    "title": "候选现象",
    "statement": "具体、可证伪的批次级观察",
    "why_investigate": "为什么值得扩大调查",
    "paper_ids": ["UUID"],
    "alternative_explanations": ["其他可能解释"],
    "next_questions": ["应在全语料中继续追查什么"]
  }],
  "research_agenda": [{
    "question": "系统主动提出的调查问题",
    "rationale": "提出原因",
    "paper_ids": ["UUID"]
  }],
  "limitations": ["本批次不能回答什么"]
}
""".strip()
    with httpx.Client(timeout=240, proxy=outbound_proxy()) as client:
        response = client.post(
            f"{config.base_url.rstrip('/')}/responses",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": config.model_name,
                "instructions": instructions,
                "input": [
                    {
                        "role": "user",
                        "content": json.dumps(
                            {"corpus_batch": packets}, ensure_ascii=False
                        ),
                    }
                ],
            },
        )
        response.raise_for_status()
        body = response.json()
    return _parse_json(_response_text(body)), body.get("usage", {})


def run_corpus_discovery(run_id: uuid.UUID) -> None:
    with session_scope() as session:
        run = session.get(PipelineRun, run_id)
        if run is None:
            return
        try:
            model_config, api_key = _provider(
                session, uuid.UUID(run.config["model_config_id"])
            )
            max_calls = int(run.config["max_model_calls"])
            batch_size = int(run.config["papers_per_batch"])
            max_input_chars = int(run.config["max_input_chars"])
            total_usage = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}
            artifacts = 0
            covered_papers = 0
            _event(
                session,
                run.id,
                "DISCOVERY_STARTED",
                "全语料自主发现已启动",
                {"max_model_calls": max_calls, "papers_per_batch": batch_size},
            )
            for call_index in range(max_calls):
                session.refresh(run)
                if run.status == "STOP_REQUESTED":
                    break
                rows = _paper_batch(
                    session,
                    run.config["conference"],
                    int(run.config["year"]),
                    batch_size,
                )
                packets, input_fingerprint = _pack_batch(
                    session, rows, max_input_chars
                )
                if not packets:
                    break
                cache_fingerprint = hashlib.sha256(
                    f"{input_fingerprint}:{model_config.model_name}".encode()
                ).hexdigest()
                _event(
                    session,
                    run.id,
                    "DISCOVERY_BATCH_STARTED",
                    f"正在观察第 {call_index + 1} 个语料批次",
                    {"papers": len(packets), "input_fingerprint": cache_fingerprint},
                )
                valid_ids = {str(packet["paper_id"]) for packet in packets}
                result, usage = _discover(model_config, api_key, packets)
                result = _validate_result(result, valid_ids)
                artifact = CognitionArtifact(
                    workflow_run_id=run.id,
                    artifact_type="CORPUS_BATCH_OBSERVATION",
                    input_fingerprint=cache_fingerprint,
                    status="CANDIDATE",
                    scope={
                        "conference": run.config["conference"],
                        "year": run.config["year"],
                        "paper_ids": sorted(valid_ids),
                    },
                    content=result,
                    narrative=result.get("batch_summary"),
                    generator="langgraph-cartographer",
                    generator_version=DISCOVERY_VERSION,
                    model=model_config.model_name,
                    uncertainty={"limitations": result.get("limitations", [])},
                )
                session.add(artifact)
                session.flush()
                analysis_by_paper = {
                    paper.id: analysis.id for _, paper, analysis in rows
                }
                for paper_id in valid_ids:
                    paper_uuid = uuid.UUID(paper_id)
                    session.add(
                        CognitionArtifactSource(
                            artifact_id=artifact.id,
                            paper_id=paper_uuid,
                            analysis_id=analysis_by_paper.get(paper_uuid),
                            stance="CONTEXT",
                            locator={"source": "paper_memory"},
                        )
                    )
                session.commit()
                artifacts += 1
                covered_papers += len(valid_ids)
                for key in total_usage:
                    total_usage[key] += int(usage.get(key, 0) or 0)
                run.counters = {
                    "model_calls": artifacts,
                    "artifacts": artifacts,
                    "papers_covered": covered_papers,
                    **total_usage,
                }
                session.commit()
                _event(
                    session,
                    run.id,
                    "DISCOVERY_BATCH_COMPLETED",
                    f"第 {call_index + 1} 个批次已形成候选观察",
                    {
                        "artifact_id": str(artifact.id),
                        "papers": len(valid_ids),
                        "observations": len(result.get("observations", [])),
                        "research_agenda": len(result.get("research_agenda", [])),
                        "usage": usage,
                    },
                )
            session.refresh(run)
            stopped = run.status == "STOP_REQUESTED"
            run.status = "STOPPED" if stopped else "COMPLETED"
            run.ended_at = datetime.now(UTC)
            run.counters = {
                "model_calls": artifacts,
                "artifacts": artifacts,
                "papers_covered": covered_papers,
                **total_usage,
            }
            _event(
                session,
                run.id,
                "DISCOVERY_STOPPED" if stopped else "DISCOVERY_COMPLETED",
                "本轮发现已按请求停止" if stopped else "本轮全语料发现已完成",
                run.counters,
            )
        except Exception as error:
            run.status = "FAILED"
            run.ended_at = datetime.now(UTC)
            run.counters = {"error": str(error)[:1000]}
            session.add(
                PipelineEvent(
                    pipeline_run_id=run.id,
                    level="ERROR",
                    event_type="DISCOVERY_FAILED",
                    message="全语料发现运行失败",
                    details={"error": str(error)[:3000]},
                )
            )
