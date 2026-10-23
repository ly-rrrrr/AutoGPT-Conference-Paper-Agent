import pytest

from app.cognition_synthesis import _parse_object, _validated_insights


def test_parse_object_accepts_fenced_curator_output():
    assert _parse_object('```json\n{"insights": []}\n```') == {"insights": []}


def test_curator_output_requires_real_observation_and_paper_sources():
    with pytest.raises(RuntimeError, match="真实来源"):
        _validated_insights(
            {
                "insights": [
                    {
                        "title": "无法追溯",
                        "claim": "一个主张",
                        "observation_artifact_ids": ["invented"],
                        "supporting_paper_ids": ["invented"],
                    }
                ]
            },
            {"observation-1"},
            {"paper-1"},
        )
