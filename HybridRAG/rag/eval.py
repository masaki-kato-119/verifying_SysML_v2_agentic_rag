from __future__ import annotations

from dataclasses import dataclass
from math import log2
from typing import Iterable, Sequence, Set


@dataclass(frozen=True)
class EvalCase:
    """評価1件分（クエリと正解集合）。"""

    query: str
    relevant_chunk_ids: Set[str]


def reciprocal_rank(ranked_ids: Sequence[str], relevant: Set[str]) -> float:
    """RR: 1/(最初に当たった順位) / 無ければ0."""
    for i, cid in enumerate(ranked_ids, start=1):
        if cid in relevant:
            return 1.0 / float(i)
    return 0.0


def mrr(cases: Iterable[EvalCase], ranked_lists: Sequence[Sequence[str]]) -> float:
    cases_list = list(cases)
    if not cases_list:
        return 0.0
    total = 0.0
    for c, ranked in zip(cases_list, ranked_lists):
        total += reciprocal_rank(ranked, c.relevant_chunk_ids)
    return total / float(len(cases_list))


def ndcg_at_k(ranked_ids: Sequence[str], relevant: Set[str], k: int) -> float:
    """二値関連（relevant=1）でNDCG@kを計算。"""
    if k <= 0:
        return 0.0
    ranked_k = ranked_ids[:k]

    def dcg(ids: Sequence[str]) -> float:
        s = 0.0
        for i, cid in enumerate(ids, start=1):
            rel = 1.0 if cid in relevant else 0.0
            if rel > 0:
                s += rel / log2(i + 1)
        return s

    actual = dcg(ranked_k)
    # 理想DCG（relevantを上から詰める）
    ideal_hits = min(len(relevant), k)
    ideal = sum(1.0 / log2(i + 1) for i in range(1, ideal_hits + 1))
    if ideal == 0.0:
        return 0.0
    return actual / ideal


def mean_ndcg_at_k(cases: Iterable[EvalCase], ranked_lists: Sequence[Sequence[str]], k: int) -> float:
    cases_list = list(cases)
    if not cases_list:
        return 0.0
    total = 0.0
    for c, ranked in zip(cases_list, ranked_lists):
        total += ndcg_at_k(ranked, c.relevant_chunk_ids, k=k)
    return total / float(len(cases_list))


def precision_at_k(ranked_ids: Sequence[str], relevant: Set[str], k: int) -> float:
    """Precision@K: 上位K件中に正解が含まれる割合。

    Args:
        ranked_ids: 検索結果のチャンクIDリスト（順位順）。
        relevant: 正解チャンクIDの集合。
        k: 評価対象の上位K件。

    Returns:
        float: Precision@K（0.0〜1.0）。

    Example:
        >>> precision_at_k(["chunk-1", "chunk-2", "chunk-3"], {"chunk-2"}, k=3)
        0.3333333333333333
    """
    if k <= 0:
        return 0.0
    ranked_k = ranked_ids[:k]
    hits = sum(1 for cid in ranked_k if cid in relevant)
    return float(hits) / float(k)


def recall_at_k(ranked_ids: Sequence[str], relevant: Set[str], k: int) -> float:
    """Recall@K: 正解チャンクが上位K件に含まれる割合。

    Args:
        ranked_ids: 検索結果のチャンクIDリスト（順位順）。
        relevant: 正解チャンクIDの集合。
        k: 評価対象の上位K件。

    Returns:
        float: Recall@K（0.0〜1.0）。

    Example:
        >>> recall_at_k(["chunk-1", "chunk-2"], {"chunk-2", "chunk-3"}, k=2)
        0.5
    """
    if k <= 0 or not relevant:
        return 0.0
    ranked_k = ranked_ids[:k]
    hits = sum(1 for cid in ranked_k if cid in relevant)
    return float(hits) / float(len(relevant))


def mean_precision_at_k(
    cases: Iterable[EvalCase], ranked_lists: Sequence[Sequence[str]], k: int
) -> float:
    """平均Precision@K。

    Args:
        cases: 評価ケースのリスト。
        ranked_lists: 各ケースの検索結果リスト。
        k: 評価対象の上位K件。

    Returns:
        float: 平均Precision@K（0.0〜1.0）。
    """
    cases_list = list(cases)
    if not cases_list:
        return 0.0
    total = 0.0
    for c, ranked in zip(cases_list, ranked_lists):
        total += precision_at_k(ranked, c.relevant_chunk_ids, k=k)
    return total / float(len(cases_list))


def mean_recall_at_k(
    cases: Iterable[EvalCase], ranked_lists: Sequence[Sequence[str]], k: int
) -> float:
    """平均Recall@K。

    Args:
        cases: 評価ケースのリスト。
        ranked_lists: 各ケースの検索結果リスト。
        k: 評価対象の上位K件。

    Returns:
        float: 平均Recall@K（0.0〜1.0）。
    """
    cases_list = list(cases)
    if not cases_list:
        return 0.0
    total = 0.0
    for c, ranked in zip(cases_list, ranked_lists):
        total += recall_at_k(ranked, c.relevant_chunk_ids, k=k)
    return total / float(len(cases_list))

