"""graphrag.workflow_engine の keyword_explore ワークフロー統合ロジックのテスト。優先度: GraphRAG。

WorkflowEngine は内部で GraphQueryEngine を生成するため、コンストラクタ後に
`.query_engine` をフェイクの探索エンジンへ差し替えることで、実グラフ探索や
SQLiteのchunk_storageに依存せず、ワークフロー自体の集約ロジック
（ノード検索結果の限定、探索結果の統合、エッジ重複除去、件数制限、
根拠チャンク取得、サマリ生成）を検証する。

このテストを書く過程で以下のバグを発見し修正した:
  GraphRAG/graphrag/workflow_engine.py 91-103行目
  修正前は `max_edges` によるエッジ数制限を重複除去より先に適用していたため、
  制限対象の先頭部分に重複エッジが含まれるケースで、本来残るはずの
  ユニークなエッジが誤って切り捨てられ、`max_edges` を指定しても
  それより少ないユニークエッジしか返らないことがあった。
  重複除去を先に行い、その後に `max_edges` で制限する順序へ修正した。
"""

import networkx as nx
import pytest
from graphrag.workflow_engine import WorkflowEngine


class _FakeQueryEngine:
    """GraphQueryEngine の代替。ノード検索/探索/根拠取得の結果を固定値で返す。"""

    def __init__(self, matched_nodes=None, explore_results=None, source_texts=None):
        self.matched_nodes = matched_nodes or []
        self.explore_results = explore_results or {}
        self.source_texts = source_texts or {}
        self.search_calls = []
        self.explore_calls = []
        self.source_calls = []

    def search_nodes(self, keyword, max_results=10):
        self.search_calls.append((keyword, max_results))
        return self.matched_nodes[:max_results]

    def explore_graph(self, node_name, depth=1, max_nodes=10):
        self.explore_calls.append((node_name, depth, max_nodes))
        return self.explore_results.get(node_name, {"success": False})

    def get_source_text(self, node_name, max_chunks=3):
        self.source_calls.append((node_name, max_chunks))
        return self.source_texts.get(node_name, [])


def _make_engine(fake_query_engine):
    engine = WorkflowEngine(nx.DiGraph(), chunk_storage=object())
    engine.query_engine = fake_query_engine
    return engine


def _edge(source, target, relation="rel"):
    return {"source": source, "target": target, "relation": relation}


# ---- ノードが1件もマッチしない場合 ----


def test_keyword_explore_returns_empty_summary_when_no_matches():
    fake = _FakeQueryEngine(matched_nodes=[])
    engine = _make_engine(fake)

    result = engine.keyword_explore("nothing")

    assert result == {
        "success": True,
        "workflow": "keyword_explore",
        "keyword": "nothing",
        "matched_nodes": [],
        "explored_nodes": [],
        "edges": [],
        "source_texts": [],
        "summary": "キーワード 'nothing' にマッチするノードが見つかりませんでした",
        "node_count": 0,
        "edge_count": 0,
    }
    # マッチが無い場合は探索・根拠取得を呼ばない
    assert fake.explore_calls == []
    assert fake.source_calls == []


# ---- 正常系の統合ロジック ----


def test_keyword_explore_aggregates_nodes_and_dedupes_edges():
    fake = _FakeQueryEngine(
        matched_nodes=[{"node": "A", "score": 0.9}, {"node": "B", "score": 0.5}],
        explore_results={
            "A": {
                "success": True,
                "nodes": ["A", "X"],
                "edges": [_edge("A", "X")],
            },
            "B": {
                "success": True,
                "nodes": ["B", "Y"],
                "edges": [_edge("A", "X"), _edge("B", "Y")],  # A-X は重複
            },
        },
        source_texts={"A": ["chunk-a1"], "B": []},
    )
    engine = _make_engine(fake)

    result = engine.keyword_explore("kw", max_nodes=2)

    assert sorted(result["explored_nodes"]) == ["A", "B", "X", "Y"]
    assert result["edge_count"] == 2
    assert sorted((e["source"], e["target"]) for e in result["edges"]) == [
        ("A", "X"),
        ("B", "Y"),
    ]
    # B の根拠チャンクは空なので source_texts に含まれない
    assert [st["node"] for st in result["source_texts"]] == ["A"]
    assert result["source_texts"][0]["chunk_count"] == 1


def test_keyword_explore_skips_failed_exploration_for_a_node():
    fake = _FakeQueryEngine(
        matched_nodes=[{"node": "A"}, {"node": "B"}],
        explore_results={
            "A": {"success": True, "nodes": ["A"], "edges": []},
            "B": {"success": False, "error": "not found"},
        },
    )
    engine = _make_engine(fake)

    result = engine.keyword_explore("kw")

    assert result["explored_nodes"] == ["A"]


def test_keyword_explore_respects_max_nodes_for_search_and_iteration():
    fake = _FakeQueryEngine(
        matched_nodes=[{"node": "A"}, {"node": "B"}, {"node": "C"}],
    )
    engine = _make_engine(fake)

    engine.keyword_explore("kw", max_nodes=2)

    # search_nodes には max_nodes がそのまま渡される
    assert fake.search_calls == [("kw", 2)]
    # search_nodes が2件に絞って返す前提のフェイクなので、探索対象も2件になる
    assert len(fake.explore_calls) == 2


# ---- 重複除去とmax_edgesの適用順序（見つけたバグの回帰テスト） ----


def test_keyword_explore_max_edges_counts_unique_edges_not_raw_edges():
    """重複エッジがmax_edgesの範囲内にあっても、後方のユニークなエッジを失わないこと。

    修正前は all_edges を先に max_edges で切り詰めてから重複除去していたため、
    切り詰め範囲内に重複(A-X が2回)があると、3つ目のユニークエッジ(B-Z)が
    失われ、edge_count が max_edges=3 未満になってしまっていた。
    """
    fake = _FakeQueryEngine(
        matched_nodes=[{"node": "A"}, {"node": "B"}],
        explore_results={
            "A": {
                "success": True,
                "nodes": ["A"],
                "edges": [_edge("A", "X"), _edge("A", "Y")],
            },
            "B": {
                "success": True,
                "nodes": ["B"],
                # 先頭が A-X の重複、続いてユニークな B-Z
                "edges": [_edge("A", "X"), _edge("B", "Z")],
            },
        },
    )
    engine = _make_engine(fake)

    result = engine.keyword_explore("kw", max_nodes=2, max_edges=3)

    pairs = sorted((e["source"], e["target"]) for e in result["edges"])
    assert pairs == [("A", "X"), ("A", "Y"), ("B", "Z")]
    assert result["edge_count"] == 3


def test_keyword_explore_max_edges_none_means_unlimited():
    fake = _FakeQueryEngine(
        matched_nodes=[{"node": "A"}],
        explore_results={
            "A": {
                "success": True,
                "nodes": ["A"],
                "edges": [_edge("A", str(i)) for i in range(10)],
            }
        },
    )
    engine = _make_engine(fake)

    result = engine.keyword_explore("kw", max_edges=None)

    assert result["edge_count"] == 10


@pytest.mark.parametrize("max_edges,expected_count", [(1, 1), (2, 2), (100, 3)])
def test_keyword_explore_max_edges_trims_unique_edges_to_limit(max_edges, expected_count):
    fake = _FakeQueryEngine(
        matched_nodes=[{"node": "A"}],
        explore_results={
            "A": {
                "success": True,
                "nodes": ["A"],
                "edges": [_edge("A", "X"), _edge("A", "Y"), _edge("A", "Z")],
            }
        },
    )
    engine = _make_engine(fake)

    result = engine.keyword_explore("kw", max_edges=max_edges)

    assert result["edge_count"] == expected_count


# ---- サマリ文字列 ----


def test_keyword_explore_summary_includes_counts_and_top_matches():
    fake = _FakeQueryEngine(
        matched_nodes=[{"node": "A", "score": 0.87, "match_type": "exact"}],
        explore_results={"A": {"success": True, "nodes": ["A"], "edges": [_edge("A", "B")]}},
        source_texts={"A": ["chunk1"]},
    )
    engine = _make_engine(fake)

    result = engine.keyword_explore("widget")

    assert "キーワード 'widget' の検索結果:" in result["summary"]
    assert "- マッチしたノード数: 1" in result["summary"]
    assert "- エッジ数: 1" in result["summary"]
    assert "A (スコア: 0.87)" in result["summary"]
    assert "A --[rel]--> B" in result["summary"]


def test_keyword_explore_matched_nodes_with_scores_defaults_when_missing():
    fake = _FakeQueryEngine(matched_nodes=[{"node": "A"}])
    engine = _make_engine(fake)

    result = engine.keyword_explore("kw")

    assert result["matched_nodes_with_scores"] == [
        {"node": "A", "score": 0.0, "match_type": "unknown"}
    ]
