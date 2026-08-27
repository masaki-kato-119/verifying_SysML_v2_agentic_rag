"""graphrag.entry_finder のキーワード/概念階層ベースのエントリーポイント発見。
優先度: GraphRAG(t6_add_tests_graphrag_gaps)。

LightweightEntryFinderはこれまでテストが無かった。手作りの小さなnx.DiGraphを
グラフ探索の対象にして、直接マッチ・概念階層マッチ・中心性フォールバックの
各経路と、品質スコアリングの構成要素を検証する。
"""

import networkx as nx
import pytest
from graphrag.entry_finder import LightweightEntryFinder


@pytest.fixture
def graph():
    g = nx.DiGraph()
    g.add_edge("partdefinition", "partusage", relation="is-a")
    g.add_edge("partusage", "engine", relation="part-of")
    g.add_node("requirementdefinition")
    return g


# ---- _build_keyword_index ----


def test_keyword_index_includes_full_lowercased_node_name(graph):
    finder = LightweightEntryFinder(graph)

    assert "partdefinition" in finder.keyword_index
    assert "partdefinition" in finder.keyword_index["partdefinition"]


def test_keyword_index_indexes_words_of_three_chars_or_more(graph):
    g = nx.DiGraph()
    g.add_node("engine unit")
    finder = LightweightEntryFinder(g)

    assert "engine" in finder.keyword_index
    assert "unit" in finder.keyword_index
    # 3文字未満の単語はインデックスされない
    assert "engine unit"[:2] not in finder.keyword_index


# ---- find_entry_points: 直接マッチ ----


def test_find_entry_points_direct_match_on_node_name(graph):
    finder = LightweightEntryFinder(graph)

    result = finder.find_entry_points("Tell me about partdefinition", max_entries=3)

    assert "partdefinition" in result


def test_find_entry_points_respects_max_entries(graph):
    g = nx.DiGraph()
    for i in range(5):
        g.add_node(f"enginepart{i}")
    finder = LightweightEntryFinder(g)

    result = finder.find_entry_points("enginepart", max_entries=2)

    assert len(result) <= 2


# ---- find_entry_points: 概念階層マッチ ----


def test_find_entry_points_falls_back_to_concept_hierarchy_when_no_direct_match():
    g = nx.DiGraph()
    g.add_node("partdefinition")
    g.add_node("unrelated")
    finder = LightweightEntryFinder(g)

    # "definition" 自体はノード名ではないが、概念階層のdefinition配下に
    # partdefinitionが登録されているため近似マッチする。
    result = finder.find_entry_points("explain the definition", max_entries=3)

    assert "partdefinition" in result


# ---- find_entry_points: フォールバック ----


def test_find_entry_points_falls_back_to_central_nodes_when_query_has_no_keywords(graph):
    finder = LightweightEntryFinder(graph)

    # ストップワードや短い単語のみのクエリはキーワードが空になる
    result = finder.find_entry_points("is a", max_entries=2)

    assert result == finder._get_central_nodes(2)


def test_find_entry_points_falls_back_to_central_nodes_when_nothing_matches(graph):
    finder = LightweightEntryFinder(graph)

    result = finder.find_entry_points("xyzxyz notpresent", max_entries=3)

    assert result == finder._get_central_nodes(3)


# ---- _get_central_nodes ----


def test_get_central_nodes_returns_empty_for_empty_graph():
    finder = LightweightEntryFinder(nx.DiGraph())

    assert finder._get_central_nodes(3) == []


def test_get_central_nodes_orders_by_degree_centrality(graph):
    finder = LightweightEntryFinder(graph)

    result = finder._get_central_nodes(3)

    # partusage は入次数1・出次数1で最も接続が多い
    assert result[0] == "partusage"


# ---- _extract_keywords / _extract_sysml_terms ----


def test_extract_keywords_filters_stopwords_and_short_words():
    finder = LightweightEntryFinder(nx.DiGraph())

    keywords = finder._extract_keywords("is the of requirement")

    assert "requirement" in keywords
    assert "the" not in keywords
    assert "of" not in keywords


def test_extract_sysml_terms_uses_alias_dictionary_for_japanese_query():
    finder = LightweightEntryFinder(nx.DiGraph())

    terms = finder._extract_sysml_terms("パート定義について教えて")

    assert "partdefinition" in terms
    assert "part definition" in terms


# ---- _calculate_domain_relevance ----


@pytest.mark.parametrize(
    "node,expected",
    [
        ("partdefinition", 1.0),
        ("requirementusage", 1.0),
        ("attributedefinition", 0.8),
        ("specializes", 0.6),
        ("somedefinitionvariant", 0.4),
        ("completely_unrelated", 0.0),
    ],
)
def test_calculate_domain_relevance(node, expected):
    finder = LightweightEntryFinder(nx.DiGraph())

    assert finder._calculate_domain_relevance(node) == expected


# ---- _calculate_name_similarity ----


def test_calculate_name_similarity_exact_match_returns_one():
    finder = LightweightEntryFinder(nx.DiGraph())

    assert finder._calculate_name_similarity("partdefinition", ["partdefinition"]) == 1.0


def test_calculate_name_similarity_no_match_returns_zero():
    finder = LightweightEntryFinder(nx.DiGraph())

    assert finder._calculate_name_similarity("partdefinition", ["totally_different"]) == 0.0


# ---- _evaluate_entry_quality ----


def test_evaluate_entry_quality_scores_exact_keyword_match_higher_than_partial(graph):
    finder = LightweightEntryFinder(graph)

    exact_score = finder._evaluate_entry_quality("partdefinition", ["partdefinition"])
    partial_score = finder._evaluate_entry_quality("partdefinition", ["part"])

    assert exact_score > partial_score
