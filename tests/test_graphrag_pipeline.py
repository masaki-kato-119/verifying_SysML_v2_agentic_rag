"""graphrag.pipeline.OntologyGraphPipeline のオーケストレーション。優先度: GraphRAG
(t6_add_tests_graphrag_gaps)。

OntologyGraphPipelineはこれまでテストが無かった。既定の use_llm=False では
process() 内のLLM補助処理は no-op（呼び出し無し）であることを確認したうえで、
実際のSysML v2ドメイン語を含む短い英文でprocess()を通し、構築されたnx.DiGraphの
ノード/エッジを検証する。ChunkStorageは常にtmp_path配下の独立DBを注入し、
リポジトリ本体のGraphRAG/data/chunks.dbを汚さないようにする。
"""

import networkx as nx
import pytest
from graphrag.chunk_storage import ChunkStorage
from graphrag.pipeline import OntologyGraphPipeline
from graphrag.query_engine import GraphQueryEngine


@pytest.fixture
def pipeline(tmp_path):
    storage = ChunkStorage(db_path=str(tmp_path / "chunks.db"))
    return OntologyGraphPipeline(use_llm=False, chunk_storage=storage)


# ---- __init__ ----


def test_default_use_llm_is_false(pipeline):
    assert pipeline.use_llm is False


def test_init_wires_up_language_specific_modules(pipeline):
    assert pipeline.analyzer_ja is not None
    assert pipeline.candidate_generator_ja is not None
    assert pipeline.normalizer_ja is not None


# ---- process(): 実際のSysMLドメイン語での統合テスト ----


def test_process_builds_expected_nodes_and_edge_for_domain_text(pipeline):
    text = "The requirement depends on the constraint."

    graph = pipeline.process(text, language="en")

    assert isinstance(graph, nx.DiGraph)
    assert set(graph.nodes()) == {"requirement", "constraint"}
    assert graph.has_edge("requirement", "constraint")
    assert graph["requirement"]["constraint"]["relation"] == "depends-on"


def test_process_is_deterministic_across_runs(pipeline):
    text = "The requirement depends on the constraint."

    first = pipeline.process(text, language="en")
    second = pipeline.process(text, language="en")

    assert sorted(first.nodes()) == sorted(second.nodes())
    assert sorted(first.edges()) == sorted(second.edges())


def test_process_with_no_domain_terms_returns_empty_graph(pipeline):
    # ドメイン用語ゲート（GRAPHRAG_DOMAIN_TERM_GATE、既定で有効）により、
    # SysML v2辞書に無い語だけの文はノードを持たないグラフになる。
    text = "The weather today is sunny and warm outside."

    graph = pipeline.process(text, language="en")

    assert graph.number_of_nodes() == 0
    assert graph.number_of_edges() == 0


def test_process_does_not_invoke_llm_when_use_llm_false(pipeline, monkeypatch):
    # use_llm=False の既定では、LLM系の属性へ一切アクセスしないことを確認する
    # （アクセスした場合は AttributeError で失敗する）。
    class _ExplodingLLM:
        def __getattr__(self, name):
            raise AssertionError("use_llm=False なのにLLM関連属性へアクセスした")

    pipeline.llm_client = _ExplodingLLM()

    graph = pipeline.process("The requirement depends on the constraint.", language="en")

    assert isinstance(graph, nx.DiGraph)


def test_process_raises_import_error_when_english_requested_without_support(pipeline, monkeypatch):
    monkeypatch.setattr(pipeline, "english_supported", True)
    monkeypatch.setattr(pipeline, "candidate_generator_en", None)
    monkeypatch.setattr(pipeline, "english_supported", False)

    with pytest.raises(ImportError, match="NLTK"):
        pipeline.process("some text", language="en")


# ---- process(): 言語自動検出の分岐（フェイクで検証） ----


def test_process_dispatches_to_japanese_generator_when_detected_japanese(pipeline, monkeypatch):
    from graphrag.language_detector import Language

    calls = []
    monkeypatch.setattr(pipeline.language_detector, "detect", lambda text: Language.JAPANESE)
    monkeypatch.setattr(
        pipeline.candidate_generator_ja, "generate", lambda text: calls.append("ja") or []
    )
    monkeypatch.setattr(pipeline.normalizer_ja, "normalize", lambda candidates: [])

    graph = pipeline.process("dummy text")

    assert calls == ["ja"]
    assert graph.number_of_nodes() == 0


def test_process_dispatches_to_english_generator_when_detected_english(pipeline, monkeypatch):
    from graphrag.language_detector import Language

    if not pipeline.english_supported:
        pytest.skip("English support (NLTK) not installed in this environment")

    calls = []
    monkeypatch.setattr(pipeline.language_detector, "detect", lambda text: Language.ENGLISH)
    monkeypatch.setattr(
        pipeline.candidate_generator_en, "generate", lambda text: calls.append("en") or []
    )
    monkeypatch.setattr(pipeline.normalizer_en, "normalize", lambda candidates: [])

    graph = pipeline.process("dummy text")

    assert calls == ["en"]
    assert graph.number_of_nodes() == 0


def test_process_passes_text_through_to_graph_builder_build(pipeline, monkeypatch):
    captured = {}
    original_build = pipeline.graph_builder.build

    def _spy_build(candidates, features_list, types, text=None):
        captured["text"] = text
        return original_build(candidates, features_list, types, text=text)

    monkeypatch.setattr(pipeline.graph_builder, "build", _spy_build)

    text = "The requirement depends on the constraint."
    pipeline.process(text, language="en")

    assert captured["text"] == text


# ---- get_statistics ----


def test_get_statistics_reports_node_and_edge_counts(pipeline):
    g = nx.DiGraph()
    g.add_node("a")
    g.add_edge("a", "b", relation="depends-on")

    stats = pipeline.get_statistics(g)

    assert stats["node_count"] == 2
    assert stats["edge_count"] == 1
    assert set(stats["nodes"]) == {"a", "b"}
    assert stats["edges"] == [("a", "b", {"relation": "depends-on"})]


# ---- create_query_engine ----


def test_create_query_engine_returns_engine_bound_to_graph(pipeline):
    g = nx.DiGraph()
    g.add_edge("a", "b")

    engine = pipeline.create_query_engine(g)

    assert isinstance(engine, GraphQueryEngine)
    assert engine.graph is g


# ---- compare_graphs ----


def test_compare_graphs_reports_diff_between_two_graphs(pipeline):
    g1 = nx.DiGraph()
    g1.add_edge("a", "b")
    g2 = nx.DiGraph()
    g2.add_edge("a", "b")
    g2.add_node("c")

    result = pipeline.compare_graphs(g1, g2)

    assert result["node_count_1"] == 2
    assert result["node_count_2"] == 3
    assert result["node_diff_rate"] > 0


# ---- get_pdf_metadata ----


def test_get_pdf_metadata_raises_when_pdf_not_supported(pipeline, monkeypatch):
    monkeypatch.setattr(pipeline, "pdf_supported", False)

    with pytest.raises(ImportError, match="pypdf"):
        pipeline.get_pdf_metadata("doc.pdf")


# ---- process_pdf ----


def test_process_pdf_raises_when_pdf_not_supported(pipeline, monkeypatch):
    monkeypatch.setattr(pipeline, "pdf_supported", False)

    with pytest.raises(ImportError, match="pypdf"):
        pipeline.process_pdf("doc.pdf")


# ---- save_graph / load_graph ----


def test_save_graph_then_load_graph_roundtrips_nodes_and_edges(pipeline, tmp_path):
    graph = nx.DiGraph()
    graph.add_node("requirement")
    graph.add_edge("requirement", "constraint", relation="depends-on")

    out_path = tmp_path / "out.pkl"
    pipeline.save_graph(graph, str(out_path), document_name="doc.txt")

    assert out_path.exists()

    loaded = pipeline.load_graph(str(out_path))

    assert set(loaded.nodes()) == {"requirement", "constraint"}
    assert loaded.has_edge("requirement", "constraint")


def test_save_graph_sets_graph_filepath_and_document_name_attributes(pipeline, tmp_path):
    graph = nx.DiGraph()
    graph.add_node("a")

    out_path = tmp_path / "out.pkl"
    pipeline.save_graph(graph, str(out_path), document_name="custom_name.txt")

    assert graph.graph["document_name"] == "custom_name.txt"
    assert "graph_filepath" in graph.graph


def test_save_graph_defaults_document_name_to_filename_when_not_given(pipeline, tmp_path):
    graph = nx.DiGraph()
    graph.add_node("a")

    out_path = tmp_path / "myfile.pkl"
    pipeline.save_graph(graph, str(out_path))

    assert graph.graph["document_name"] == "myfile.pkl"
