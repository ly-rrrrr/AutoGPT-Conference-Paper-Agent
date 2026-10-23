import json

import pytest

from app.cognition_discovery import (
    _compact_analysis,
    _pack_batch,
    _paper_batch,
    _parse_json,
    _validate_result,
)


ACTION_HEADERS = {"X-Workbench-Request": "1"}


def test_parse_json_accepts_a_fenced_discovery_result():
    result = _parse_json(
        "```json\n"
        + json.dumps(
            {
                "batch_summary": "发现了可追查的共同方法动机",
                "observations": [{"title": "候选现象"}],
                "research_agenda": [],
                "limitations": ["只覆盖一个批次"],
            },
            ensure_ascii=False,
        )
        + "\n```"
    )

    assert result["observations"][0]["title"] == "候选现象"


def test_batch_uses_only_prepared_source_ready_paper_memories(
    client, api_session, seeded_db
):
    client.post(
        "/api/cognition/prepare",
        headers=ACTION_HEADERS,
        json={"conference": "ECCV", "year": 2026},
    )

    rows = _paper_batch(api_session, "ECCV", 2026, 12)
    packets, fingerprint = _pack_batch(api_session, rows, 20000)

    assert len(packets) == 1
    assert packets[0]["title"] == "Vision Systems for Research"
    assert packets[0]["paper_id"] == str(seeded_db["matched"].id)
    assert len(fingerprint) == 64


def test_compact_analysis_deduplicates_repeated_fallback_text():
    compact = _compact_analysis(
        {
            "research_problem": "same long answer",
            "method_summary": "same long answer",
            "raw_answer": "same long answer",
            "limitations": ["one limitation"],
        },
        2000,
    )

    assert compact == {
        "research_problem": "same long answer",
        "limitations": ["one limitation"],
    }


def test_discovery_result_must_cite_a_real_batch_paper():
    with pytest.raises(RuntimeError, match="真实论文"):
        _validate_result(
            {
                "observations": [
                    {
                        "statement": "无法追溯的观察",
                        "paper_ids": ["not-in-this-batch"],
                    }
                ],
                "research_agenda": [],
            },
            {"real-paper-id"},
        )
