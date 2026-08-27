"""graphrag.node_summarizer のノード要約生成ロジック。優先度: GraphRAG(t6_add_tests_graphrag_gaps)。

NodeSummarizerはこれまでテストが無かった。ChunkStorage/LLMクライアントをフェイクに
置き換え、簡易版要約・LLM要約・キャッシュ・信頼度計算を手作りの小さなnx.DiGraphで
検証する。
"""

from unittest.mock import MagicMock

import networkx as nx
import pytest
from graphrag.node_summarizer import NodeSummarizer


class _FakeChunkStorage:
    def __init__(self, node_chunks=None, chunks=None, graph_id_by_filepath=None):
        self.node_chunks = node_chunks or {}
        self.chunks = chunks or {}
        self.graph_id_by_filepath = graph_id_by_filepath or {}
        self.get_node_chunks_calls = []

    def get_graph_id(self, graph_filepath):
        return self.graph_id_by_filepath.get(graph_filepath)

    def get_node_chunks(self, graph_id, node_name):
        self.get_node_chunks_calls.append((graph_id, node_name))
        return self.node_chunks.get(node_name, [])

    def get_chunks(self, graph_id, chunk_ids):
        return {cid: self.chunks[cid] for cid in chunk_ids if cid in self.chunks}


@pytest.fixture
def graph():
    g = nx.DiGraph()
    g.add_edge("requirement", "constraint", relation="depends-on")
    g.add_edge("action", "requirement", relation="satisfies")
    g.graph["graph_id"] = "g1"
    return g


# ---- summarize_node: ノード不在 ----


def test_summarize_node_returns_error_for_missing_node(graph):
    summarizer = NodeSummarizer(graph)

    result = summarizer.summarize_node("missing")

    assert result["error"] == "node_not_found"
    assert "見つかりませんでした" in result["summary"]


# ---- summarize_node: キャッシュ ----


def test_summarize_node_uses_cache_on_second_call(graph):
    storage = _FakeChunkStorage(
        node_chunks={"requirement": ["c0"]},
        chunks={"c0": "The requirement is defined here."},
    )
    summarizer = NodeSummarizer(graph, chunk_storage=storage)

    first = summarizer.summarize_node("requirement")
    second = summarizer.summarize_node("requirement")

    assert first is second
    # 2回目はキャッシュから返るのでchunk_storageへは1回しか問い合わせない
    assert len(storage.get_node_chunks_calls) == 1


def test_summarize_node_cache_key_distinguishes_summary_type(graph):
    storage = _FakeChunkStorage(
        node_chunks={"requirement": ["c0"]},
        chunks={"c0": "The requirement is defined here."},
    )
    summarizer = NodeSummarizer(graph, chunk_storage=storage)

    overview = summarizer.summarize_node("requirement", summary_type="overview")
    detailed = summarizer.summarize_node("requirement", summary_type="detailed")

    assert overview["summary_type"] == "overview"
    assert detailed["summary_type"] == "detailed"
    assert overview is not detailed


# ---- summarize_node: 関連ノード情報 ----


def test_summarize_node_includes_related_nodes(graph):
    summarizer = NodeSummarizer(graph)

    result = summarizer.summarize_node("requirement")

    assert set(result["related_nodes"]) == {"constraint", "action"}


# ---- _get_source_chunks ----


def test_get_source_chunks_returns_empty_when_no_chunk_storage(graph):
    summarizer = NodeSummarizer(graph, chunk_storage=None)

    assert summarizer._get_source_chunks("requirement", max_chunks=5) == []


def test_get_source_chunks_uses_graph_id_attribute(graph):
    storage = _FakeChunkStorage(
        node_chunks={"requirement": ["c0", "c1"]},
        chunks={"c0": "text0", "c1": "text1"},
    )
    summarizer = NodeSummarizer(graph, chunk_storage=storage)

    result = summarizer._get_source_chunks("requirement", max_chunks=5)

    assert result == ["text0", "text1"]
    assert storage.get_node_chunks_calls == [("g1", "requirement")]


def test_get_source_chunks_falls_back_to_graph_filepath_lookup():
    g = nx.DiGraph()
    g.add_node("requirement")
    g.graph["graph_filepath"] = "graphs/doc.pkl"
    storage = _FakeChunkStorage(
        graph_id_by_filepath={"graphs/doc.pkl": "resolved-id"},
        node_chunks={"requirement": ["c0"]},
        chunks={"c0": "resolved text"},
    )
    summarizer = NodeSummarizer(g, chunk_storage=storage)

    result = summarizer._get_source_chunks("requirement", max_chunks=5)

    assert result == ["resolved text"]
    assert storage.get_node_chunks_calls == [("resolved-id", "requirement")]


def test_get_source_chunks_returns_empty_when_graph_id_cannot_be_resolved():
    g = nx.DiGraph()
    g.add_node("requirement")
    storage = _FakeChunkStorage()
    summarizer = NodeSummarizer(g, chunk_storage=storage)

    assert summarizer._get_source_chunks("requirement", max_chunks=5) == []
    assert storage.get_node_chunks_calls == []


def test_get_source_chunks_returns_empty_on_storage_exception(graph):
    class _RaisingStorage:
        def get_node_chunks(self, graph_id, node_name):
            raise RuntimeError("boom")

    summarizer = NodeSummarizer(graph, chunk_storage=_RaisingStorage())

    assert summarizer._get_source_chunks("requirement", max_chunks=5) == []


# ---- _get_related_nodes_info ----


def test_get_related_nodes_info_reports_neighbor_and_predecessor_counts(graph):
    summarizer = NodeSummarizer(graph)

    info = summarizer._get_related_nodes_info("requirement")

    assert info["neighbor_count"] == 1  # requirement -> constraint
    assert info["predecessor_count"] == 1  # action -> requirement
    assert set(info["nodes"]) == {"constraint", "action"}


# ---- _generate_summary_simple ----


def test_generate_summary_simple_without_chunks_uses_related_nodes(graph):
    summarizer = NodeSummarizer(graph)

    summary = summarizer._generate_summary_simple(
        "requirement", [], {"nodes": ["constraint"]}, "overview"
    )

    assert "constraint" in summary


def test_generate_summary_simple_without_chunks_or_related_nodes_reports_not_found():
    g = nx.DiGraph()
    g.add_node("lonely")
    summarizer = NodeSummarizer(g)

    summary = summarizer._generate_summary_simple("lonely", [], {"nodes": []}, "overview")

    assert "見つかりませんでした" in summary


@pytest.mark.parametrize("summary_type", ["overview", "detailed", "technical"])
def test_generate_summary_simple_prioritizes_sentence_mentioning_node_name(graph, summary_type):
    chunks = ["Something else entirely. The requirement must be met by design."]
    summarizer = NodeSummarizer(graph)

    summary = summarizer._generate_summary_simple(
        "requirement", chunks, {"nodes": ["constraint"]}, summary_type
    )

    assert "requirement" in summary.lower()


# ---- _generate_summary_with_llm ----


def test_generate_summary_with_llm_uses_generate_method(graph):
    llm_client = MagicMock()
    llm_client.generate.return_value = "LLM generated summary"
    summarizer = NodeSummarizer(graph, llm_client=llm_client)

    summary = summarizer._generate_summary_with_llm(
        "requirement", ["chunk text"], {"nodes": ["constraint"]}, "overview"
    )

    assert summary == "LLM generated summary"
    llm_client.generate.assert_called_once()


def test_generate_summary_with_llm_uses_openai_chat_completions_format(graph):
    llm_client = MagicMock(spec=["chat"])
    response = MagicMock()
    response.choices = [MagicMock(message=MagicMock(content="chat completion summary"))]
    llm_client.chat.completions.create.return_value = response
    summarizer = NodeSummarizer(graph, llm_client=llm_client)

    summary = summarizer._generate_summary_with_llm(
        "requirement", ["chunk text"], {"nodes": ["constraint"]}, "technical"
    )

    assert summary == "chat completion summary"


def test_generate_summary_with_llm_falls_back_to_simple_on_exception(graph):
    llm_client = MagicMock()
    llm_client.generate.side_effect = RuntimeError("api down")
    summarizer = NodeSummarizer(graph, llm_client=llm_client)

    summary = summarizer._generate_summary_with_llm(
        "requirement", [], {"nodes": ["constraint"]}, "overview"
    )

    # 簡易版へフォールバックしても関連ノード情報は含まれる
    assert "constraint" in summary


def test_summarize_node_prefers_llm_when_client_present(graph):
    llm_client = MagicMock()
    llm_client.generate.return_value = "from llm"
    summarizer = NodeSummarizer(graph, llm_client=llm_client)

    result = summarizer.summarize_node("requirement")

    assert result["summary"] == "from llm"


# ---- _calculate_confidence ----


@pytest.mark.parametrize(
    "chunk_count,expected",
    [(0, 0.0), (1, 0.5), (2, 0.5), (3, 0.7), (4, 0.7), (5, 0.9), (10, 0.9)],
)
def test_calculate_confidence_thresholds(graph, chunk_count, expected):
    summarizer = NodeSummarizer(graph)

    assert summarizer._calculate_confidence(["chunk"] * chunk_count) == expected
