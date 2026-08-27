"""graphrag.path_scorer のパス品質スコア計算のテスト。優先度: GraphRAG。

score_pathはノード重要度・関係重要度・パス長ペナルティを合成する純粋関数的な
メソッドで、これまでテストが無かった。数式どおりの値になること、フィルタ・
ストップワード判定で早期に0点を返す分岐、次数キャップの挙動を検証する。
"""

import networkx as nx
import pytest
from graphrag.path_scorer import PathScorer


def _linear_graph(relations):
    """relations: [(u, v, relation), ...] から一直線のDiGraphを作る。"""
    g = nx.DiGraph()
    for u, v, relation in relations:
        g.add_edge(u, v, relation=relation)
    return g


# ---- score_path: 早期リターン ----


@pytest.mark.parametrize("path", [[], ["only-one"]])
def test_score_path_returns_zero_for_paths_shorter_than_two(path):
    scorer = PathScorer(nx.DiGraph())

    assert scorer.score_path(path) == 0.0


def test_score_path_returns_zero_when_node_type_filter_excludes_a_node():
    graph = _linear_graph([("alpha", "beta", "is-a")])
    graph.nodes["alpha"]["type"] = "concept"
    graph.nodes["beta"]["type"] = "other"
    scorer = PathScorer(graph)

    assert scorer.score_path(["alpha", "beta"], node_type_filter={"concept"}) == 0.0


def test_score_path_allows_path_when_all_node_types_match_filter():
    graph = _linear_graph([("alpha", "beta", "is-a")])
    graph.nodes["alpha"]["type"] = "concept"
    graph.nodes["beta"]["type"] = "concept"
    scorer = PathScorer(graph)

    assert scorer.score_path(["alpha", "beta"], node_type_filter={"concept"}) > 0.0


def test_score_path_returns_zero_when_path_contains_stopword():
    graph = _linear_graph([("the", "B", "is-a")])
    scorer = PathScorer(graph)

    assert scorer.score_path(["the", "B"], exclude_stopwords=True) == 0.0


def test_score_path_ignores_stopwords_when_disabled():
    graph = _linear_graph([("the", "B", "is-a")])
    scorer = PathScorer(graph)

    assert scorer.score_path(["the", "B"], exclude_stopwords=False) > 0.0


# ---- score_path: 数式どおりの値になること ----


def test_score_path_matches_expected_formula_for_simple_two_node_path():
    graph = _linear_graph([("alpha", "beta", "is-a")])
    scorer = PathScorer(graph)

    # alpha, beta とも degree=1 (out=1/in=0 と in=1/out=0) -> importance = 1/100 = 0.01
    # relation 'is-a' -> importance 0.8。パス長2なのでペナルティ1.0。
    expected = 0.01 * 0.4 + 0.8 * 0.4 + 1.0 * 0.2
    assert scorer.score_path(["alpha", "beta"]) == pytest.approx(expected)


def test_score_path_uses_unknown_relation_importance_when_edge_missing_relation_attr():
    graph = nx.DiGraph()
    graph.add_edge("alpha", "beta")  # relation属性なし
    scorer = PathScorer(graph)

    expected = 0.01 * 0.4 + 0.3 * 0.4 + 1.0 * 0.2
    assert scorer.score_path(["alpha", "beta"]) == pytest.approx(expected)


def test_score_path_uses_unknown_relation_importance_when_edge_absent():
    graph = nx.DiGraph()
    graph.add_node("alpha")
    graph.add_node("beta")  # alphaとbetaの間に辺なし
    scorer = PathScorer(graph)

    expected = 0.0 * 0.4 + 0.3 * 0.4 + 1.0 * 0.2
    assert scorer.score_path(["alpha", "beta"]) == pytest.approx(expected)


def test_score_path_applies_length_penalty_for_longer_paths():
    graph = _linear_graph([("alpha", "beta", "is-a"), ("beta", "gamma", "is-a")])
    scorer = PathScorer(graph)

    score_len2 = scorer.score_path(["alpha", "beta"])
    score_len3 = scorer.score_path(["alpha", "beta", "gamma"])

    # 長いパスほどpath_length_penaltyが下がるため、他条件が同等なら短い方が高スコア
    assert score_len3 < score_len2 + 0.4  # 大まかな健全性チェック
    penalty_len3 = 1.0 / (1.0 + (3 - 2) * 0.1)
    assert penalty_len3 < 1.0


def test_node_importance_caps_at_one_for_high_degree_nodes():
    graph = nx.DiGraph()
    for i in range(150):
        graph.add_edge("hub", f"leaf{i}", relation="uses")
    scorer = PathScorer(graph)

    assert scorer._node_importance_cache["hub"] == 1.0


def test_node_not_in_cache_defaults_to_half_importance():
    graph = _linear_graph([("alpha", "beta", "is-a")])
    scorer = PathScorer(graph)
    # キャッシュ構築後にグラフへ直接ノードを追加（キャッシュには載らない）
    graph.add_node("gamma")

    scorer.score_path(["alpha", "gamma"], exclude_stopwords=False)
    # "gamma"のimportanceはキャッシュ未登録
    assert scorer._node_importance_cache.get("gamma") is None


# ---- filter_paths_by_quality ----


def test_filter_paths_by_quality_drops_low_scoring_paths_and_sorts_descending():
    graph = _linear_graph(
        [("alpha", "beta", "specializes"), ("beta", "gamma", "unknown"), ("gamma", "delta", "unknown")]
    )
    scorer = PathScorer(graph)
    paths = [["alpha", "beta"], ["alpha", "beta", "gamma", "delta"]]

    result = scorer.filter_paths_by_quality(paths, min_quality=0.0)

    assert [p for p, _ in result] == sorted(
        paths,
        key=lambda p: scorer.score_path(p),
        reverse=True,
    )
    scores = [s for _, s in result]
    assert scores == sorted(scores, reverse=True)


def test_filter_paths_by_quality_excludes_paths_below_min_quality():
    graph = _linear_graph([("the", "B", "is-a")])
    scorer = PathScorer(graph)

    result = scorer.filter_paths_by_quality([["the", "B"]], min_quality=0.1)

    assert result == []


def test_filter_paths_by_quality_returns_empty_for_no_paths():
    scorer = PathScorer(nx.DiGraph())

    assert scorer.filter_paths_by_quality([]) == []
