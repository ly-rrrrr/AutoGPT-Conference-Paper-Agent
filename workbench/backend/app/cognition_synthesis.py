from __future__ import annotations

import hashlib
import json
import uuid
from datetime import UTC, datetime

import httpx
from sqlalchemy import select

from app.cognition_discovery import _response_text
from app.database import session_scope
from app.models import (
    CognitionArtifact,
    CognitionArtifactDependency,
    CognitionArtifactSource,
    ModelProviderConfig,
    Paper,
    PipelineEvent,
    PipelineRun,
)
from app.network import outbound_proxy
from app.secret_store import get_secret


SYNTHESIS_VERSION = "method-atlas-v1"


def _parse_object(text: str) -> dict:
    candidate = text.strip()
    if candidate.startswith("```"):
        candidate = candidate.split("\n", 1)[-1].rsplit("```", 1)[0]
    try:
        result = json.loads(candidate)
    except json.JSONDecodeError:
        start = candidate.find("{")
        end = candidate.rfind("}")
        if start < 0 or end <= start:
            raise RuntimeError("模型没有返回有效的 JSON 对象")
        result = json.loads(candidate[start : end + 1])
    if not isinstance(result, dict):
        raise RuntimeError("模型返回的认知结果不是 JSON 对象")
    return result


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
        raise RuntimeError("方法综合使用的模型配置不存在或已停用")
    api_key = get_secret(config.secret_ref)
    if not api_key:
        raise RuntimeError("默认模型尚未保存 API Key")
    return config, api_key


def _artifact_batch(session, conference: str, year: int, limit: int):
    processed = (
        select(CognitionArtifactDependency.depends_on_artifact_id)
        .join(
            CognitionArtifact,
            CognitionArtifactDependency.artifact_id == CognitionArtifact.id,
        )
        .where(
            CognitionArtifact.artifact_type == "METHOD_INSIGHT",
            CognitionArtifact.generator_version == SYNTHESIS_VERSION,
        )
    )
    return list(
        session.scalars(
            select(CognitionArtifact)
            .where(
                CognitionArtifact.artifact_type == "CORPUS_BATCH_OBSERVATION",
                CognitionArtifact.scope["conference"].as_string()
                == conference.upper(),
                CognitionArtifact.scope["year"].as_integer() == year,
                CognitionArtifact.id.not_in(processed),
            )
            .order_by(CognitionArtifact.created_at, CognitionArtifact.id)
            .limit(limit)
        )
    )


def _pack_artifacts(artifacts: list[CognitionArtifact], max_chars: int) -> list[dict]:
    packets = []
    per_artifact = max(1200, max_chars // max(1, len(artifacts)))
    for artifact in artifacts:
        packet = {
            "observation_artifact_id": str(artifact.id),
            "paper_ids": artifact.scope.get("paper_ids", []),
            "batch_summary": artifact.content.get("batch_summary"),
            "observations": artifact.content.get("observations", []),
            "research_agenda": artifact.content.get("research_agenda", []),
            "limitations": artifact.content.get("limitations", []),
        }
        serialized = json.dumps(packet, ensure_ascii=False)
        if len(serialized) > per_artifact:
            packet = {
                "observation_artifact_id": str(artifact.id),
                "paper_ids": artifact.scope.get("paper_ids", []),
                "batch_summary": str(artifact.content.get("batch_summary", ""))[
                    : per_artifact // 3
                ],
                "observations_excerpt": serialized[: 2 * per_artifact // 3],
                "truncated": True,
            }
        packets.append(packet)
    return packets


def _call(config, api_key: str, instructions: str, payload: dict) -> tuple[dict, dict]:
    with httpx.Client(timeout=300, proxy=outbound_proxy()) as client:
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
                        "content": json.dumps(payload, ensure_ascii=False),
                    }
                ],
            },
        )
        response.raise_for_status()
        body = response.json()
    return _parse_object(_response_text(body)), body.get("usage", {})


def _propose(config, api_key: str, packets: list[dict]) -> tuple[dict, dict]:
    instructions = """
你是 Method Cartographer。输入是多个独立论文批次产生的候选观察。
不要沿用预设领域分类，不要做词频总结。请寻找跨批次重复出现、发生改造、出现冲突或可能跨领域迁移的方法思想。
候选必须可证伪，并引用真实 observation_artifact_id 和 paper_id。
只返回 JSON：
{
  "proposals": [{
    "title": "候选方法现象",
    "claim": "具体、可证伪的主张",
    "mechanism": "真正起作用的方法机制",
    "problem_pressure": "促使这种方法出现的困难",
    "borrowed_idea": "可能借鉴的思想及来源形态",
    "adaptation": "为当前领域做出的关键改造",
    "domains": ["涉及领域"],
    "transfer_targets": ["可能迁移方向"],
    "observation_artifact_ids": ["UUID"],
    "supporting_paper_ids": ["UUID"],
    "open_questions": ["仍需调查的问题"]
  }],
  "observations": [],
  "research_agenda": []
}
""".strip()
    return _call(config, api_key, instructions, {"batch_observations": packets})


def _challenge(
    config, api_key: str, packets: list[dict], proposals: dict
) -> tuple[dict, dict]:
    instructions = """
你是独立 Challenger。你的任务不是润色候选主张，而是尽力推翻它们。
检查批次覆盖偏差、叙事相似但机制不同、相同机制却目标不同、反例论文、替代解释和证据不足。
只能引用输入中真实的 observation_artifact_id 和 paper_id，不得补造事实。
只返回 JSON：
{
  "challenges": [{
    "proposal_title": "对应候选",
    "verdict": "SURVIVES|REVISE|REJECT",
    "counterclaim": "最强反方解释",
    "counter_paper_ids": ["UUID"],
    "missing_evidence": ["缺失证据"],
    "required_revision": "需要怎样修改"
  }],
  "observations": [],
  "research_agenda": []
}
""".strip()
    return _call(
        config,
        api_key,
        instructions,
        {"batch_observations": packets, "proposals": proposals.get("proposals", [])},
    )


def _curate(
    config,
    api_key: str,
    packets: list[dict],
    proposals: dict,
    challenges: dict,
) -> tuple[dict, dict]:
    instructions = """
你是 Method Atlas Curator。根据原始批次观察、候选主张和独立反驳，生成可下钻的方法认知制品。
拒绝无法经受反驳的主张；保留不确定性，不得把局部覆盖冒充年度结论。
坐标不是固定标签，而是本轮证据中浮现的问题压力、机制、改造方式、领域和迁移可能。
所有论文与观察制品 ID 必须来自输入。
只返回 JSON：
{
  "insights": [{
    "title": "认知标题",
    "claim": "经反驳修订后的主张",
    "mechanism": "方法机制",
    "problem_pressure": "问题压力",
    "borrowed_idea": "思想来源",
    "adaptation": "关键改造",
    "domains": ["领域"],
    "transfer_targets": ["迁移方向"],
    "supporting_paper_ids": ["UUID"],
    "counter_paper_ids": ["UUID"],
    "observation_artifact_ids": ["UUID"],
    "counterargument": "最强反方解释",
    "evidence_boundary": "当前结论可以外推到哪里",
    "open_questions": ["下一轮问题"],
    "confidence": 0.0
  }],
  "observations": [],
  "research_agenda": []
}
""".strip()
    return _call(
        config,
        api_key,
        instructions,
        {
            "batch_observations": packets,
            "proposals": proposals.get("proposals", []),
            "challenges": challenges.get("challenges", []),
        },
    )


def _validated_insights(
    result: dict, valid_artifact_ids: set[str], valid_paper_ids: set[str]
) -> list[dict]:
    validated = []
    for insight in result.get("insights", []):
        if not isinstance(insight, dict) or not insight.get("title") or not insight.get("claim"):
            continue
        artifact_ids = sorted(
            set(insight.get("observation_artifact_ids", [])) & valid_artifact_ids
        )
        supporting = sorted(
            set(insight.get("supporting_paper_ids", [])) & valid_paper_ids
        )
        counter = sorted(set(insight.get("counter_paper_ids", [])) & valid_paper_ids)
        if not artifact_ids or not supporting:
            continue
        try:
            confidence = max(0.0, min(1.0, float(insight.get("confidence", 0))))
        except (TypeError, ValueError):
            confidence = 0.0
        validated.append(
            {
                **insight,
                "observation_artifact_ids": artifact_ids,
                "supporting_paper_ids": supporting,
                "counter_paper_ids": counter,
                "confidence": confidence,
            }
        )
    if not validated:
        raise RuntimeError("Curator 没有形成带真实来源的有效认知制品")
    return validated


def _add_usage(total: dict, usage: dict) -> None:
    for key in total:
        total[key] += int(usage.get(key, 0) or 0)


def run_method_synthesis(run_id: uuid.UUID) -> None:
    with session_scope() as session:
        run = session.get(PipelineRun, run_id)
        if run is None:
            return
        try:
            model_config, api_key = _provider(
                session, uuid.UUID(run.config["model_config_id"])
            )
            max_rounds = int(run.config["max_rounds"])
            batch_size = int(run.config["artifacts_per_round"])
            max_input_chars = int(run.config["max_input_chars"])
            calls = 0
            created = 0
            source_artifacts = 0
            total_usage = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}
            _event(
                session,
                run.id,
                "SYNTHESIS_STARTED",
                "方法认知综合已启动",
                {"max_rounds": max_rounds, "artifacts_per_round": batch_size},
            )
            for round_index in range(max_rounds):
                session.refresh(run)
                if run.status == "STOP_REQUESTED":
                    break
                artifacts = _artifact_batch(
                    session,
                    run.config["conference"],
                    int(run.config["year"]),
                    batch_size,
                )
                if not artifacts:
                    break
                packets = _pack_artifacts(artifacts, max_input_chars)
                valid_artifact_ids = {str(item.id) for item in artifacts}
                valid_paper_ids = {
                    str(paper_id)
                    for item in artifacts
                    for paper_id in item.scope.get("paper_ids", [])
                }
                _event(
                    session,
                    run.id,
                    "SYNTHESIS_ROUND_STARTED",
                    f"正在综合第 {round_index + 1} 组批次观察",
                    {"observation_artifacts": len(artifacts)},
                )
                proposals, usage = _propose(model_config, api_key, packets)
                calls += 1
                _add_usage(total_usage, usage)
                challenges, usage = _challenge(
                    model_config, api_key, packets, proposals
                )
                calls += 1
                _add_usage(total_usage, usage)
                curated, usage = _curate(
                    model_config, api_key, packets, proposals, challenges
                )
                calls += 1
                _add_usage(total_usage, usage)
                insights = _validated_insights(
                    curated, valid_artifact_ids, valid_paper_ids
                )
                for insight_index, insight in enumerate(insights):
                    fingerprint = hashlib.sha256(
                        (
                            SYNTHESIS_VERSION
                            + model_config.model_name
                            + "".join(sorted(insight["observation_artifact_ids"]))
                            + str(insight_index)
                            + insight["claim"]
                        ).encode()
                    ).hexdigest()
                    artifact = CognitionArtifact(
                        workflow_run_id=run.id,
                        artifact_type="METHOD_INSIGHT",
                        input_fingerprint=fingerprint,
                        status="CHALLENGED",
                        scope={
                            "conference": run.config["conference"],
                            "year": run.config["year"],
                            "paper_ids": sorted(
                                set(insight["supporting_paper_ids"])
                                | set(insight["counter_paper_ids"])
                            ),
                            "observation_artifact_ids": insight[
                                "observation_artifact_ids"
                            ],
                        },
                        content=insight,
                        narrative=insight["claim"],
                        generator="cartographer-challenger-curator",
                        generator_version=SYNTHESIS_VERSION,
                        model=model_config.model_name,
                        uncertainty={
                            "evidence_boundary": insight.get("evidence_boundary"),
                            "open_questions": insight.get("open_questions", []),
                            "confidence": insight.get("confidence", 0),
                        },
                    )
                    session.add(artifact)
                    session.flush()
                    cited_dependencies = set(insight["observation_artifact_ids"])
                    for dependency in artifacts:
                        session.add(
                            CognitionArtifactDependency(
                                artifact_id=artifact.id,
                                depends_on_artifact_id=dependency.id,
                                relation=(
                                    "SYNTHESIZES"
                                    if str(dependency.id) in cited_dependencies
                                    else "CONSUMED_CONTEXT"
                                ),
                            )
                        )
                    stances = {
                        **{
                            paper_id: "SUPPORTING"
                            for paper_id in insight["supporting_paper_ids"]
                        },
                        **{
                            paper_id: "COUNTER"
                            for paper_id in insight["counter_paper_ids"]
                        },
                    }
                    for paper_id, stance in stances.items():
                        session.add(
                            CognitionArtifactSource(
                                artifact_id=artifact.id,
                                paper_id=uuid.UUID(paper_id),
                                stance=stance,
                                locator={"source": "corpus_batch_observation"},
                            )
                        )
                    created += 1
                source_artifacts += len(artifacts)
                run.counters = {
                    "model_calls": calls,
                    "insights_created": created,
                    "observation_artifacts_consumed": source_artifacts,
                    **total_usage,
                }
                session.commit()
                _event(
                    session,
                    run.id,
                    "SYNTHESIS_ROUND_COMPLETED",
                    f"第 {round_index + 1} 轮产生 {len(insights)} 个经反驳认知制品",
                    {"insights": len(insights), "model_calls": 3},
                )
            session.refresh(run)
            stopped = run.status == "STOP_REQUESTED"
            run.status = "STOPPED" if stopped else "COMPLETED"
            run.ended_at = datetime.now(UTC)
            run.counters = {
                "model_calls": calls,
                "insights_created": created,
                "observation_artifacts_consumed": source_artifacts,
                **total_usage,
            }
            _event(
                session,
                run.id,
                "SYNTHESIS_STOPPED" if stopped else "SYNTHESIS_COMPLETED",
                "方法综合已按请求停止" if stopped else "方法认知综合已完成",
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
                    event_type="SYNTHESIS_FAILED",
                    message="方法认知综合失败",
                    details={"error": str(error)[:3000]},
                )
            )
