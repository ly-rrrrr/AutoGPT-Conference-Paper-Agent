from app.active_research import OpenAICompatibleResearchAdapter, ResearchCorpusTools
from app.models import ResearchBrief


def test_research_tools_respect_scope_and_track_inspected_sources(api_session, seeded_db):
    brief = ResearchBrief(
        title="ECCV exploration",
        objective="Find method limitations",
        scope={"conference": "ECCV", "year": 2026},
        tool_policy={},
        budget={},
        output_preferences={},
    )
    api_session.add(brief)
    api_session.commit()
    tools = ResearchCorpusTools(api_session, brief)

    overview = tools.scope_overview()
    search = tools.search_papers("Vision", 10)
    inspected = tools.inspect_papers([str(seeded_db["matched"].id)])

    assert overview["paper_count"] == 2
    assert search["items"][0]["paper_id"] == str(seeded_db["matched"].id)
    assert inspected["items"][0]["analysis"]["research_problem"]
    assert seeded_db["matched"].id in tools.accessed_paper_ids


def test_research_tools_enforce_explicit_paper_scope(api_session, seeded_db):
    brief = ResearchBrief(
        title="Selected paper exploration",
        objective="Inspect only the selected paper",
        scope={
            "conference": "ECCV",
            "year": 2026,
            "paper_ids": [str(seeded_db["matched"].id)],
        },
        tool_policy={},
        budget={"max_papers": 1},
        output_preferences={},
    )
    api_session.add(brief)
    api_session.commit()
    tools = ResearchCorpusTools(api_session, brief)

    assert tools.scope_overview()["paper_count"] == 1
    assert tools.inspect_papers([str(seeded_db["unresolved"].id)])["items"] == []


def test_research_report_parser_accepts_json_and_rejects_empty_insights():
    report = OpenAICompatibleResearchAdapter._parse_report(
        '{"summary":"finding","insights":[{"title":"candidate"}]}'
    )

    assert report["summary"] == "finding"

    try:
        OpenAICompatibleResearchAdapter._parse_report(
            '{"summary":"nothing","insights":[]}'
        )
    except RuntimeError as error:
        assert "候选洞察" in str(error)
    else:
        raise AssertionError("empty insight reports must be rejected")
