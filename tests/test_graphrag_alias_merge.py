"""表記ゆれ重複ノード統合(_merge_alias_duplicate_nodes)のテスト。優先度: GraphRAG。

GraphRAGの抽出パイプラインは、同一概念でもBNF文法名由来の連結スペル
（例: "requirementusage"）と地の文由来の分かち書き（例: "requirement usage"）を
別々のlemmaとして候補化することがある。_merge_entitiesは厳密な文字列一致でしか
統合しないため、これらは別ノードとして残り、片方にしかエッジが無い準孤立ノードを
生む（a4_graph_path_precision: qa-attribution-02で経路探索精度が低下した根本原因）。
"""

import networkx as nx
import pytest
from graphrag.graph_builder import GraphBuilder


@pytest.fixture
def builder():
    return GraphBuilder()


def test_merge_redirects_edges_from_duplicate_to_canonical(builder):
    """SYSML_V2_ALIASESに載っている表記ゆれの重複ノードが1つに統合されること。"""
    g = nx.DiGraph()
    g.add_node("requirement usage")  # 分かち書き側が既にノードとして存在する
    g.add_edge("requirement", "requirementusage", relation="satisfies", source_chunks=["chunk_1"])
    g.add_edge("requirementusage", "constraint usage", relation="is-a", source_chunks=["chunk_2"])

    merged = builder._merge_alias_duplicate_nodes(g)

    assert merged == 1
    assert "requirementusage" not in g
    assert g.has_edge("requirement", "requirement usage")
    assert g["requirement"]["requirement usage"]["relation"] == "satisfies"
    assert g.has_edge("requirement usage", "constraint usage")


def test_merge_prefers_spaced_form_as_canonical(builder):
    """連結スペルと分かち書きが両方存在する場合、分かち書き側を正として残すこと。"""
    g = nx.DiGraph()
    g.add_node("constraintdefinition")
    g.add_node("constraint definition")
    g.add_edge("constraint", "constraintdefinition", relation="is-a")

    builder._merge_alias_duplicate_nodes(g)

    assert "constraint definition" in g
    assert "constraintdefinition" not in g
    assert g.has_edge("constraint", "constraint definition")


def test_merge_combines_source_chunks_on_conflicting_edge(builder):
    """統合先に同じエッジが既に存在する場合、source_chunksを合体させ重複させないこと。"""
    g = nx.DiGraph()
    g.add_edge("requirement", "requirement usage", relation="satisfies", source_chunks=["chunk_a"])
    g.add_edge("requirement", "requirementusage", relation="satisfies", source_chunks=["chunk_b", "chunk_a"])

    builder._merge_alias_duplicate_nodes(g)

    assert g.number_of_edges() == 1
    assert sorted(g["requirement"]["requirement usage"]["source_chunks"]) == ["chunk_a", "chunk_b"]


def test_merge_is_noop_when_no_duplicates_present(builder):
    """重複が存在しない通常のグラフには影響しないこと。"""
    g = nx.DiGraph()
    g.add_edge("requirement", "requirement usage", relation="satisfies")

    merged = builder._merge_alias_duplicate_nodes(g)

    assert merged == 0
    assert g.number_of_nodes() == 2
    assert g.number_of_edges() == 1


def test_merge_avoids_self_loop_when_duplicate_points_to_canonical(builder):
    """重複ノードがcanonical自身を指すエッジ(自己ループ化しうる)を安全に処理すること。"""
    g = nx.DiGraph()
    g.add_edge("requirementusage", "requirement usage", relation="is-a")

    builder._merge_alias_duplicate_nodes(g)

    assert "requirementusage" not in g
    assert not g.has_edge("requirement usage", "requirement usage")
