"""find_path のノード解決と探索履歴の永続化のテスト。優先度: GraphRAG。

いずれも「GraphRAG が一度も呼ばれていなかった」ために表面化していなかった不具合:

1. 正規化（小文字化＋記号除去）は多対一なので、目次のドットリーダー由来の
   ゴミノード "model ......." が "model" と同じキーに潰れる。最後の一致を
   採ると到達不能なノードが選ばれ、存在するパスが「見つかりません」になる。
2. LearningAdaptation._load_history が defaultdict を素の dict で置き換えるため、
   履歴に無いノード対の探索がすべて KeyError になる。
"""

import json

import networkx as nx
import pytest
from graphrag.learning_adaptation import ExplorationHistoryOptimizer
from graphrag.query_engine import GraphQueryEngine


@pytest.fixture
def graph():
    g = nx.DiGraph()
    g.add_edge("system", "model", relation="is-a")
    # 目次のドットリーダー由来のゴミノード（"model" と同じキーに正規化される）
    g.add_node("model " + "." * 120)
    return g


def test_exact_match_wins_over_normalized_collision(graph):
    qe = GraphQueryEngine(graph, enable_query_cache=False)

    assert qe._resolve_node_name("model", "model") == "model"


def test_shortest_candidate_wins_when_no_exact_match(graph):
    qe = GraphQueryEngine(graph, enable_query_cache=False)

    # 記号付きで指定された場合も、素の語を選ぶ
    assert qe._resolve_node_name("Model!", "model") == "model"


def test_unknown_node_resolves_to_none(graph):
    qe = GraphQueryEngine(graph, enable_query_cache=False)

    assert qe._resolve_node_name("nonexistent", "nonexistent") is None


def test_find_path_reaches_target_despite_collision(graph):
    """ゴミノードに引っ張られて既存パスを見失わないこと。"""
    qe = GraphQueryEngine(graph, enable_query_cache=False)

    result = qe.find_path("system", "model")

    assert result["success"] is True
    assert result["path"] == ["system", "model"]


@pytest.fixture
def graph_with_spaced_node():
    """GraphBuilder._merge_alias_duplicate_nodes後の状態を模す。

    連結スペル（"requirementusage"）は分かち書き（"requirement usage"）へ
    統合済みで、連結スペル自体のノードはグラフ上に存在しない。
    """
    g = nx.DiGraph()
    g.add_edge("requirement", "requirement usage", relation="satisfies")
    return g


def test_resolve_node_name_falls_back_to_space_insensitive_match(graph_with_spaced_node):
    """a4_graph_path_precision: 連結スペルでの問い合わせが、統合済みの

    分かち書きノードへ解決できること（表記ゆれ重複ノード統合の後方互換）。
    """
    qe = GraphQueryEngine(graph_with_spaced_node, enable_query_cache=False)

    assert qe._resolve_node_name("requirementusage", "requirementusage") == "requirement usage"
    assert qe._resolve_node_name("RequirementUsage", "requirementusage") == "requirement usage"


def test_find_path_resolves_camelcase_style_query_to_merged_node(graph_with_spaced_node):
    qe = GraphQueryEngine(graph_with_spaced_node, enable_query_cache=False)

    result = qe.find_path("requirement", "RequirementUsage")

    assert result["success"] is True
    assert result["path"] == ["requirement", "requirement usage"]


def test_record_path_accepts_unseen_pair_after_loading_history(tmp_path):
    """履歴を読み込んだあとでも、未知のノード対を記録できること。"""
    history_file = tmp_path / "history.json"
    first = ExplorationHistoryOptimizer(history_file=str(history_file))
    first.record_path("a", "b", ["a", "b"], success=True, quality_score=0.9)

    second = ExplorationHistoryOptimizer(history_file=str(history_file))
    # 履歴に無い組み合わせ。ここが KeyError になっていた。
    second.record_path("x", "y", ["x", "y"], success=True, quality_score=0.5)

    assert second.path_history[("x", "y")]


def test_history_round_trips_node_pairs(tmp_path):
    history_file = tmp_path / "history.json"
    first = ExplorationHistoryOptimizer(history_file=str(history_file))
    first.record_path("start", "end", ["start", "mid", "end"], success=True, quality_score=0.8)

    second = ExplorationHistoryOptimizer(history_file=str(history_file))

    records = second.path_history[("start", "end")]
    assert len(records) == 1
    assert records[0]["path"] == ["start", "mid", "end"]


def test_history_round_trips_node_names_containing_comma(tmp_path):
    """キーを "start,end" で連結していた旧実装では復元できなかったケース。"""
    history_file = tmp_path / "history.json"
    first = ExplorationHistoryOptimizer(history_file=str(history_file))
    first.record_path("a,b", "c", ["a,b", "c"], success=True, quality_score=0.7)

    second = ExplorationHistoryOptimizer(history_file=str(history_file))

    assert second.path_history[("a,b", "c")]


def test_legacy_history_format_is_still_readable(tmp_path):
    history_file = tmp_path / "history.json"
    history_file.write_text(
        json.dumps(
            {
                "path_history": {"start,end": [{"path": ["start", "end"], "success": True}]},
                "node_importance": {"start": 1.0},
            }
        ),
        encoding="utf-8",
    )

    optimizer = ExplorationHistoryOptimizer(history_file=str(history_file))

    assert optimizer.path_history[("start", "end")]
    # 旧形式を読んだあとでも未知の対を記録できる
    optimizer.record_path("p", "q", ["p", "q"], success=True, quality_score=0.5)
    assert optimizer.path_history[("p", "q")]


def test_node_importance_accepts_unseen_nodes_after_load(tmp_path):
    history_file = tmp_path / "history.json"
    first = ExplorationHistoryOptimizer(history_file=str(history_file))
    first.record_path("a", "b", ["a", "b"], success=True, quality_score=0.9)

    second = ExplorationHistoryOptimizer(history_file=str(history_file))
    second.record_path("m", "n", ["m", "n"], success=True, quality_score=0.4)

    assert second.node_importance["m"] > 0
