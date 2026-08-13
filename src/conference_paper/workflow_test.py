import json
from pathlib import Path

import pytest

from backend.blocks.conference_paper.analysis import AnalyzeConferencePapersBlock
from backend.blocks.conference_paper.bridge_client import CollectPaperLikesBlock
from backend.blocks.conference_paper.cvf import DiscoverCVFPapersBlock
from backend.blocks.conference_paper.results import (
    AggregatePaperReportBlock,
    PersistPaperResultsBlock,
)
from backend.blocks.conference_paper.selection import SelectConferencePapersBlock
from backend.blocks.io import AgentInputBlock, AgentOutputBlock
from backend.data.graph import GraphModel

GRAPH_PATH = Path(__file__).parents[3] / "agents/conference-paper-research-agent.json"

DOMAIN_BLOCKS = (
    DiscoverCVFPapersBlock,
    SelectConferencePapersBlock,
    AnalyzeConferencePapersBlock,
    CollectPaperLikesBlock,
    PersistPaperResultsBlock,
    AggregatePaperReportBlock,
)


@pytest.fixture(scope="session", autouse=True)
def graph_cleanup() -> None:
    return None


@pytest.fixture
def graph_data() -> dict:
    return json.loads(GRAPH_PATH.read_text(encoding="utf-8"))


@pytest.fixture
def graph(graph_data: dict) -> GraphModel:
    return GraphModel.model_validate(graph_data)


def test_graph_loads_with_repository_graph_model(graph: GraphModel):
    assert graph.name == "Conference Paper Research Agent"
    assert len(graph.nodes) == 8


def test_graph_uses_real_block_ids_and_schema_fields(graph: GraphModel):
    blocks = [
        AgentInputBlock(),
        *(block_class() for block_class in DOMAIN_BLOCKS),
        AgentOutputBlock(),
    ]
    blocks_by_id = {block.id: block for block in blocks}
    nodes_by_block = {node.block_id: node for node in graph.nodes}

    for block in blocks:
        node = nodes_by_block[block.id]
        assert set(node.input_default) <= set(block.input_schema.model_fields)
        assert set(block.output_schema.model_fields)

    for link in graph.links:
        source = next(node for node in graph.nodes if node.id == link.source_id)
        sink = next(node for node in graph.nodes if node.id == link.sink_id)
        source_field = link.source_name.split("_#_", maxsplit=1)[0]
        sink_field = link.sink_name.split("_#_", maxsplit=1)[0]
        assert source_field in blocks_by_id[source.block_id].output_schema.model_fields
        assert sink_field in blocks_by_id[sink.block_id].input_schema.model_fields


def test_graph_exposes_required_config_with_safe_defaults(graph: GraphModel):
    input_node = next(
        node for node in graph.nodes if node.block_id == AgentInputBlock().id
    )
    config = input_node.input_default["value"]

    assert config["conference"] == "CVPR"
    assert config["year"] == 2026
    assert config["max_papers"] == 0
    assert config["likes_strategy"] == "alphaxiv_api"
    assert config["bridge_url"] == "http://host.docker.internal:8765"
    assert config["topics"] == []
    assert config["paper_questions"]
    assert config["run_id"]

    analyze_node = next(
        node
        for node in graph.nodes
        if node.block_id == AnalyzeConferencePapersBlock().id
    )
    assert analyze_node.input_default["analysis_mode"] == "structured_llm"
    assert analyze_node.input_default["model"] == "gpt-5.6-luna"


def test_top_level_and_node_link_copies_are_identical(graph: GraphModel):
    top_level = {link.id: link.model_dump() for link in graph.links}
    node_inputs = {
        link.id: link.model_dump() for node in graph.nodes for link in node.input_links
    }
    node_outputs = {
        link.id: link.model_dump() for node in graph.nodes for link in node.output_links
    }

    assert top_level == node_inputs == node_outputs


def test_selection_fans_out_then_results_join_before_agent_output(graph: GraphModel):
    nodes_by_block = {node.block_id: node for node in graph.nodes}
    select = nodes_by_block[SelectConferencePapersBlock().id]
    analyze = nodes_by_block[AnalyzeConferencePapersBlock().id]
    likes = nodes_by_block[CollectPaperLikesBlock().id]
    persist = nodes_by_block[PersistPaperResultsBlock().id]
    aggregate = nodes_by_block[AggregatePaperReportBlock().id]
    output = nodes_by_block[AgentOutputBlock().id]
    edges = {
        (link.source_id, link.source_name, link.sink_id, link.sink_name)
        for link in graph.links
    }

    assert (select.id, "selection_#_paper_tasks", analyze.id, "paper_tasks") in edges
    assert (select.id, "selection_#_paper_tasks", likes.id, "paper_tasks") in edges
    assert (analyze.id, "analyses", persist.id, "analyses") in edges
    assert (likes.id, "likes_results", persist.id, "likes_results") in edges
    assert (persist.id, "paper_results", aggregate.id, "paper_results") in edges
    assert (aggregate.id, "summary_path", output.id, "value") in edges


def test_graph_contains_no_plain_credentials(graph_data: dict):
    serialized = json.dumps(graph_data).lower()

    assert "bridge_token" not in serialized
    assert "alphaxiv_credentials" not in serialized
    assert "llm_credentials" not in serialized
    assert "cookie" not in serialized
    assert "bearer " not in serialized
