"""graphrag.semantic_entry_finder のセマンティック検索ロジック。優先度: GraphRAG(t6_add_tests_graphrag_gaps)。

sentence-transformers はこの環境に実際にインストールされているため、デフォルト設定
(use_high_precision=True)のままテストすると実モデルのロードが走ってしまう。
そのため通常のロジックテストは use_high_precision=False で SimpleEmbeddingModel に
固定し、高精度モデル選択ロジックだけは SentenceTransformer をモックして検証する。
"""

import threading

import networkx as nx
import pytest
from graphrag.semantic_entry_finder import (
    SemanticEntryFinder,
    SimpleEmbeddingModel,
)

from graphrag import semantic_entry_finder as sef_module


@pytest.fixture
def graph():
    g = nx.DiGraph()
    g.add_node("port definition", concept_type="definition")
    g.add_node("part usage")
    g.add_edge("port definition", "part usage", relation="related")
    return g


@pytest.fixture
def finder(graph):
    return SemanticEntryFinder(graph, use_high_precision=False)


class _StubChunkStorage:
    def __init__(self, chunks_by_node):
        self._chunks_by_node = chunks_by_node

    def get_node_chunks(self, graph_id, node):
        return list(self._chunks_by_node.get(node, {}).keys())

    def get_chunks(self, graph_id, chunk_ids):
        result = {}
        for node_chunks in self._chunks_by_node.values():
            for cid in chunk_ids:
                if cid in node_chunks:
                    result[cid] = node_chunks[cid]
        return result


# ---- SimpleEmbeddingModel ----


def test_simple_embedding_model_returns_zero_vector_for_empty_text():
    model = SimpleEmbeddingModel()

    vector = model.embed("")

    assert len(vector) == 100
    assert all(v == 0.0 for v in vector)


def test_simple_embedding_model_returns_normalized_vector_for_text():
    model = SimpleEmbeddingModel()

    vector = model.embed("port definition")

    norm_sq = sum(v * v for v in vector)
    assert pytest.approx(1.0, rel=1e-6) == norm_sq


def test_simple_embedding_model_is_deterministic():
    model = SimpleEmbeddingModel()

    assert list(model.embed("port definition")) == list(model.embed("port definition"))


# ---- __init__ embedding model selection ----


def test_init_uses_explicit_embedding_model_when_given(graph):
    custom_model = SimpleEmbeddingModel()

    finder = SemanticEntryFinder(graph, embedding_model=custom_model)

    assert finder.embedding_model is custom_model


def test_init_falls_back_to_simple_model_when_high_precision_unavailable(graph, monkeypatch):
    monkeypatch.setattr(sef_module, "SENTENCE_TRANSFORMERS_AVAILABLE", False)

    finder = SemanticEntryFinder(graph, use_high_precision=True)

    assert isinstance(finder.embedding_model, SimpleEmbeddingModel)


def test_init_uses_high_precision_model_when_available(graph, monkeypatch):
    created = []

    class _FakeSentenceTransformer:
        def __init__(self, model_name):
            created.append(model_name)

        def encode(self, text, convert_to_numpy=True):
            return [0.0]

    monkeypatch.setattr(sef_module, "SENTENCE_TRANSFORMERS_AVAILABLE", True)
    monkeypatch.setattr(sef_module, "SentenceTransformer", _FakeSentenceTransformer)

    finder = SemanticEntryFinder(graph, use_high_precision=True)

    assert isinstance(finder.embedding_model, sef_module.HighPrecisionEmbeddingModel)
    assert created  # モデル名が渡された


def test_init_falls_back_to_simple_model_when_high_precision_init_raises(graph, monkeypatch):
    monkeypatch.setattr(sef_module, "SENTENCE_TRANSFORMERS_AVAILABLE", True)

    class _BoomSentenceTransformer:
        def __init__(self, model_name):
            raise RuntimeError("no model weights")

    monkeypatch.setattr(sef_module, "SentenceTransformer", _BoomSentenceTransformer)

    finder = SemanticEntryFinder(graph, use_high_precision=True)

    assert isinstance(finder.embedding_model, SimpleEmbeddingModel)


# ---- _cosine_similarity ----


def test_cosine_similarity_identical_vectors_is_one(finder):
    assert finder._cosine_similarity([1.0, 0.0], [1.0, 0.0]) == pytest.approx(1.0)


def test_cosine_similarity_orthogonal_vectors_is_zero(finder):
    assert finder._cosine_similarity([1.0, 0.0], [0.0, 1.0]) == pytest.approx(0.0)


def test_cosine_similarity_zero_vector_is_zero(finder):
    assert finder._cosine_similarity([0.0, 0.0], [1.0, 0.0]) == 0.0


# ---- _generate_node_description ----


def test_generate_node_description_includes_neighbors_and_concept_type(finder):
    description = finder._generate_node_description("port definition")

    assert "port definition" in description
    assert "part usage" in description
    assert "definition" in description  # concept_type


def test_generate_node_description_includes_source_text_preview(graph):
    storage = _StubChunkStorage({"port definition": {"c1": "some spec excerpt text"}})
    graph.graph["graph_id"] = "g1"
    finder = SemanticEntryFinder(graph, use_high_precision=False, chunk_storage=storage)

    description = finder._generate_node_description("port definition")

    assert "some spec excerpt text" in description


# ---- _get_source_text_preview ----


def test_get_source_text_preview_returns_empty_without_chunk_storage(finder):
    assert finder._get_source_text_preview("port definition") == ""


def test_get_source_text_preview_returns_empty_without_graph_id(graph):
    storage = _StubChunkStorage({"port definition": {"c1": "text"}})
    finder = SemanticEntryFinder(graph, use_high_precision=False, chunk_storage=storage)

    assert finder._get_source_text_preview("port definition") == ""


def test_get_source_text_preview_swallows_storage_errors(graph):
    class _BoomStorage:
        def get_node_chunks(self, *_args, **_kwargs):
            raise RuntimeError("db down")

    graph.graph["graph_id"] = "g1"
    finder = SemanticEntryFinder(graph, use_high_precision=False, chunk_storage=_BoomStorage())

    assert finder._get_source_text_preview("port definition") == ""


# ---- find_semantic_entry_points / _simple_keyword_search ----


def test_find_semantic_entry_points_returns_empty_for_blank_query(finder):
    assert finder.find_semantic_entry_points("   ") == []


def test_simple_keyword_search_matches_by_node_name_substring(finder):
    results = finder._simple_keyword_search("port", max_entries=5)

    assert any(r["node"] == "port definition" for r in results)
    assert all(0.3 <= r["similarity"] <= 0.5 for r in results)


def test_simple_keyword_search_respects_max_entries(finder):
    results = finder._simple_keyword_search("port part", max_entries=1)

    assert len(results) <= 1


def test_find_semantic_entry_points_uses_fallback_search_before_index_built(finder, monkeypatch):
    """バックグラウンドスレッドは起動させず、フォールバック経路だけ検証する。"""

    class _NoOpThread:
        def __init__(self, target=None, daemon=None):
            self._target = target

        def start(self):
            pass  # 実際にはスレッドを起動しない(テストを決定的にする)

    monkeypatch.setattr(threading, "Thread", _NoOpThread)

    results = finder.find_semantic_entry_points("port", max_entries=5)

    assert any(r["node"] == "port definition" for r in results)
    assert finder._index_built is False


def test_find_semantic_entry_points_uses_embeddings_once_index_built(finder):
    finder._index_built = True
    finder.node_embeddings = {
        "port definition": [1.0, 0.0],
        "part usage": [0.0, 1.0],
    }
    finder.node_descriptions = {"port definition": "port definition desc"}

    class _FixedQueryEmbeddingModel(SimpleEmbeddingModel):
        def embed(self, text):
            return [1.0, 0.0]

    finder.embedding_model = _FixedQueryEmbeddingModel()

    results = finder.find_semantic_entry_points("port", max_entries=5, threshold=0.5)

    assert len(results) == 1
    assert results[0]["node"] == "port definition"
    assert results[0]["similarity"] == pytest.approx(1.0)


def test_find_semantic_entry_points_falls_back_when_no_embeddings_indexed(finder):
    finder._index_built = True
    finder.node_embeddings = {}

    results = finder.find_semantic_entry_points("port", max_entries=5)

    assert any(r["node"] == "port definition" for r in results)


# ---- stop_index_building / get_index_status ----


def test_stop_index_building_noop_when_not_building(finder):
    finder.stop_index_building()

    assert finder._stop_building is False


def test_stop_index_building_sets_flag_when_building(finder):
    finder._index_building = True

    finder.stop_index_building()

    assert finder._stop_building is True


def test_get_index_status_reports_progress(finder):
    finder.node_embeddings = {"port definition": [1.0]}

    status = finder.get_index_status()

    assert status["indexed_nodes"] == 1
    assert status["total_nodes"] == 2
    assert status["progress_percent"] == 50


def test_get_index_status_handles_empty_graph_without_division_error():
    empty_graph = nx.DiGraph()
    finder = SemanticEntryFinder(empty_graph, use_high_precision=False)

    status = finder.get_index_status()

    assert status["total_nodes"] == 0
    assert status["progress_percent"] == 0
