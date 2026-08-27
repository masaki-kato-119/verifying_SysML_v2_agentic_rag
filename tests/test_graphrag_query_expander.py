"""graphrag.query_expander の自然文クエリ拡張ロジック。優先度: GraphRAG(t6_add_tests_graphrag_gaps)。

これまでテストが無く、_find_direct_matches が return 文を欠いたまま実装され、
expand_query が「常に success: False を返す」という致命的な回帰が
一度も検知されていなかった（本ファイル作成時に発見・修正、詳細は下記テスト参照）。
LLM呼び出しは無く、辞書・グラフ構造ベースの純粋なロジックのみで構成される。
"""

import networkx as nx
import pytest
from graphrag.query_expander import QueryExpander

from graphrag import query_expander as query_expander_module


@pytest.fixture
def graph():
    g = nx.DiGraph()
    g.add_node("port definition", type="definition", description="A structural port element")
    g.add_node("part usage")
    g.add_node("constraint usage")
    g.add_edge("port definition", "part usage", relation="related")
    g.add_edge("port definition", "constraint usage", relation="related")
    return g


@pytest.fixture
def expander(graph):
    return QueryExpander(graph)


# ---- バグ回帰: expand_query が常に失敗していた ----


def test_expand_query_succeeds_for_a_simple_matching_query(expander):
    """_find_direct_matches が matches を return していなかったため、
    以前はどんなクエリでも success: False になっていた（回帰テスト）。
    """
    result = expander.expand_query("port definition")

    assert result["success"] is True
    assert "error" not in result
    node_names = [c["node_name"] for c in result["candidates"]]
    assert "port definition" in node_names


def test_expand_query_returns_error_payload_on_internal_failure(expander, monkeypatch):
    """例外発生時は success: False とエラーメッセージを返す(try/exceptの健全性確認)。"""
    def _boom(self, *_args, **_kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(query_expander_module.QueryExpander, "_extract_keyphrases", _boom)

    result = expander.expand_query("anything")

    assert result["success"] is False
    assert result["error"] == "boom"
    assert result["original_query"] == "anything"


# ---- _find_direct_matches ----


def test_find_direct_matches_returns_exact_match(expander):
    matches = expander._find_direct_matches(["port definition"])

    exact = [m for m in matches if m["match_type"] == "exact"]
    assert len(exact) == 1
    assert exact[0]["node_name"] == "port definition"
    assert exact[0]["base_score"] == 1.0


def test_find_direct_matches_returns_empty_list_not_none_when_no_match(expander):
    """回帰確認: 一致が無い場合でも None ではなく空リストが返ること。"""
    matches = expander._find_direct_matches(["totally_unrelated_xyz"])

    assert matches == []


def test_find_direct_matches_finds_partial_match_via_word_boundary(expander):
    matches = expander._find_direct_matches(["port"])

    partial = [m for m in matches if m["match_type"] == "partial" and m["node_name"] == "port definition"]
    assert len(partial) == 1


# ---- _is_valid_partial_match ----


@pytest.mark.parametrize(
    "phrase,node_name,expected",
    [
        ("part", "partdefinition", True),  # 有効な例外リストに載っている
        ("part", "aparts", False),  # 無効パターン(^.*parts$)に一致
        ("port", "port definition", True),  # 単語境界一致
        ("x", "x", True),  # 完全一致
        ("usage", "portusage", True),  # 有効な例外(接尾語)
    ],
)
def test_is_valid_partial_match_cases(expander, phrase, node_name, expected):
    assert expander._is_valid_partial_match(phrase, node_name) is expected


# ---- _extract_keyphrases ----


def test_extract_keyphrases_filters_stopwords_and_short_words(expander, monkeypatch):
    monkeypatch.setattr(query_expander_module.config, "STOPWORDS", {"is", "a", "the"})

    keyphrases = expander._extract_keyphrases("is a port")

    assert "is" not in keyphrases
    assert "a" not in keyphrases
    assert "port" in keyphrases


def test_extract_keyphrases_includes_sysml_alias_terms(expander, monkeypatch):
    monkeypatch.setattr(
        query_expander_module.config,
        "SYSML_V2_ALIASES",
        {"port def": ["port definition"]},
    )

    keyphrases = expander._extract_keyphrases("what is a port def used for")

    assert "port def" in keyphrases
    assert "port definition" in keyphrases


def test_extract_keyphrases_generates_ngrams(expander):
    keyphrases = expander._extract_keyphrases("port definition usage")

    assert "port definition" in keyphrases
    assert "port definition usage" in keyphrases


# ---- _find_alias_matches ----


def test_find_alias_matches_exact_alias_hit(expander, monkeypatch):
    monkeypatch.setattr(
        query_expander_module.config,
        "NODE_ALIASES",
        {"port def": ["port definition"]},
    )

    matches = expander._find_alias_matches(["port def"])

    assert len(matches) == 1
    assert matches[0]["node_name"] == "port definition"
    assert matches[0]["match_type"] == "alias_exact"


def test_find_alias_matches_skips_alias_pointing_to_missing_node(expander, monkeypatch):
    monkeypatch.setattr(
        query_expander_module.config,
        "NODE_ALIASES",
        {"port def": ["node that does not exist"]},
    )

    matches = expander._find_alias_matches(["port def"])

    assert matches == []


def test_find_alias_matches_returns_empty_when_no_alias_dict(expander, monkeypatch):
    monkeypatch.setattr(query_expander_module.config, "NODE_ALIASES", None)

    assert expander._find_alias_matches(["anything"]) == []


# ---- _find_fuzzy_matches / _calculate_similarity / _levenshtein_distance ----


def test_calculate_similarity_identical_strings_is_one(expander):
    assert expander._calculate_similarity("port", "port") == 1.0


def test_calculate_similarity_empty_string_is_zero(expander):
    assert expander._calculate_similarity("", "port") == 0.0


def test_calculate_similarity_returns_zero_when_length_difference_too_large(expander):
    assert expander._calculate_similarity("a", "aaaaaaaaaaaaaaaaaaaa") == 0.0


def test_levenshtein_distance_known_values(expander):
    assert expander._levenshtein_distance("kitten", "sitting") == 3
    assert expander._levenshtein_distance("abc", "abc") == 0


def test_find_fuzzy_matches_finds_close_typo(expander):
    matches = expander._find_fuzzy_matches(["port definitoin"], min_score=0.7)

    node_names = [m["node_name"] for m in matches]
    assert "port definition" in node_names


def test_find_fuzzy_matches_skips_phrases_shorter_than_three_chars(expander):
    matches = expander._find_fuzzy_matches(["it"], min_score=0.0)

    assert matches == []


# ---- _find_attribute_matches ----


def test_find_attribute_matches_matches_node_description_attribute(expander):
    matches = expander._find_attribute_matches(["structural port element"])

    assert any(m["node_name"] == "port definition" for m in matches)


# ---- _score_and_deduplicate ----


def test_score_and_deduplicate_returns_empty_for_no_candidates(expander):
    assert expander._score_and_deduplicate([], "query") == []


def test_score_and_deduplicate_ignores_candidates_without_node_name(expander):
    candidates = [{"match_type": "exact", "base_score": 1.0}]

    assert expander._score_and_deduplicate(candidates, "query") == []


def test_score_and_deduplicate_applies_exact_match_bonus(expander):
    candidates = [
        {"node_name": "port definition", "match_type": "exact", "matched_phrase": "port definition", "base_score": 1.0}
    ]

    scored = expander._score_and_deduplicate(candidates, "port definition")

    assert len(scored) == 1
    assert scored[0]["match_info"]["type_bonus"] == 0.2
    # port definitionは2本のエッジを持つ -> degree_bonus > 0
    assert scored[0]["match_info"]["node_degree"] == 2


def test_score_and_deduplicate_merges_duplicate_node_candidates(expander):
    candidates = [
        {"node_name": "port definition", "match_type": "partial", "matched_phrase": "port", "base_score": 0.5},
        {"node_name": "port definition", "match_type": "fuzzy", "matched_phrase": "port defn", "base_score": 0.6},
    ]

    scored = expander._score_and_deduplicate(candidates, "port")

    assert len(scored) == 1
    assert scored[0]["all_matches"] == 2


# ---- expand_query filtering behavior ----


def test_expand_query_respects_max_candidates(expander):
    result = expander.expand_query("port definition part usage constraint usage", max_candidates=1)

    assert result["success"] is True
    assert len(result["candidates"]) <= 1


def test_expand_query_filters_below_min_score(expander):
    result = expander.expand_query("zzz_totally_unrelated_zzz", min_score=0.99)

    assert result["success"] is True
    assert result["candidates"] == []


# ---- get_expansion_suggestions ----


def test_get_expansion_suggestions_includes_related_nodes(expander):
    result = expander.get_expansion_suggestions("port definition")

    assert result["success"] is True
    suggestion = next(s for s in result["suggestions"] if s["node_name"] == "port definition")
    assert "part usage" in suggestion["related_nodes"] or "constraint usage" in suggestion["related_nodes"]


def test_get_expansion_suggestions_propagates_expand_query_failure(expander, monkeypatch):
    monkeypatch.setattr(
        expander, "expand_query", lambda *a, **k: {"success": False, "error": "x", "original_query": "q"}
    )

    result = expander.get_expansion_suggestions("q")

    assert result["success"] is False
