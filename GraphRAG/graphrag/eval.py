"""GraphRAG のパス探索・近傍探索を評価するための指標関数。

``HybridRAG/rag/eval.py``（Recall@k/nDCG@k/MRR）に対応する、グラフ側の指標。
チャンク検索と違い「順位付きリスト」ではなく「単一の経路」「隣接ノード集合」を
評価対象とするため、指標の形が異なる。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence, Set, Tuple


@dataclass(frozen=True)
class PathEvalCase:
    """経路探索1件分の評価ケース（開始・終了ノードと正解経路）。"""

    start_node: str
    end_node: str
    expected_nodes: Sequence[str]
    expected_relations: Sequence[str]


def path_exact_match(actual_nodes: Sequence[str], expected_nodes: Sequence[str]) -> bool:
    """実際の経路のノード列が正解と完全一致するか。

    Args:
        actual_nodes: find_path が返した経路上のノード列（順序どおり）。
        expected_nodes: 正解のノード列。

    Returns:
        bool: 完全一致すれば True。

    Example:
        >>> path_exact_match(["a", "b", "c"], ["a", "b", "c"])
        True
    """
    return list(actual_nodes) == list(expected_nodes)


def path_node_overlap(actual_nodes: Sequence[str], expected_nodes: Sequence[str]) -> float:
    """経路上のノード集合のJaccard係数（順序を無視した重なり具合）。

    完全一致ほど厳密ではないが、経路が部分的に正しい場合の度合いを見るのに使う。

    Args:
        actual_nodes: find_path が返した経路上のノード列。
        expected_nodes: 正解のノード列。

    Returns:
        float: Jaccard係数（0.0〜1.0）。両方空なら0.0。

    Example:
        >>> path_node_overlap(["a", "b", "c"], ["a", "b", "d"])
        0.5
    """
    actual_set = set(actual_nodes)
    expected_set = set(expected_nodes)
    union = actual_set | expected_set
    if not union:
        return 0.0
    return len(actual_set & expected_set) / len(union)


def relation_sequence_match(actual_relations: Sequence[str], expected_relations: Sequence[str]) -> bool:
    """経路上の関係種別（is-a / satisfies 等）の並びが正解と一致するか。

    Args:
        actual_relations: find_path が返した経路上のエッジの関係種別（順序どおり）。
        expected_relations: 正解の関係種別列。

    Returns:
        bool: 完全一致すれば True。
    """
    return list(actual_relations) == list(expected_relations)


def neighbor_precision_recall(
    actual: Set[Tuple[str, str]], expected: Set[Tuple[str, str]]
) -> Tuple[float, float]:
    """近傍探索（1ホップ）の (relation, node) 集合に対するPrecision/Recall。

    Args:
        actual: 実際に取得できた (relation, node) の集合。
        expected: 正解の (relation, node) の集合。

    Returns:
        Tuple[float, float]: (precision, recall)。expected が空ならrecallは0.0。

    Example:
        >>> neighbor_precision_recall({("is-a", "b")}, {("is-a", "b"), ("is-a", "c")})
        (1.0, 0.5)
    """
    if not actual:
        precision = 0.0
    else:
        precision = len(actual & expected) / len(actual)
    if not expected:
        recall = 0.0
    else:
        recall = len(actual & expected) / len(expected)
    return precision, recall
