"""HybridRAG rag.eval の単体テスト（指標関数）。"""

from rag.eval import (
    EvalCase,
    mean_ndcg_at_k,
    mean_precision_at_k,
    mean_recall_at_k,
    mrr,
    ndcg_at_k,
    precision_at_k,
    recall_at_k,
    reciprocal_rank,
)


def test_reciprocal_rank_hit_first():
    assert reciprocal_rank(["a", "b"], {"a"}) == 1.0


def test_reciprocal_rank_hit_second():
    assert reciprocal_rank(["x", "a"], {"a"}) == 0.5


def test_reciprocal_rank_miss():
    assert reciprocal_rank(["x", "y"], {"a"}) == 0.0


def test_mrr_empty_cases():
    assert mrr([], []) == 0.0


def test_mrr_two_cases():
    cases = [
        EvalCase("q1", {"c1"}),
        EvalCase("q2", {"c2"}),
    ]
    ranked = [["c1", "x"], ["x", "c2"]]
    assert mrr(cases, ranked) == (1.0 + 0.5) / 2.0


def test_ndcg_at_k_zero_k():
    assert ndcg_at_k(["a"], {"a"}, k=0) == 0.0


def test_ndcg_at_k_perfect():
    r = ndcg_at_k(["a", "b"], {"a"}, k=2)
    assert 0.0 < r <= 1.0


def test_ndcg_at_k_no_relevant_ideal_zero():
    assert ndcg_at_k(["a", "b"], set(), k=2) == 0.0


def test_mean_ndcg_at_k_nonempty():
    cases = [EvalCase("q", {"a"})]
    m = mean_ndcg_at_k(cases, [["a", "x"]], k=2)
    assert m == 1.0


def test_mean_ndcg_at_k_empty():
    assert mean_ndcg_at_k([], [], k=3) == 0.0


def test_precision_at_k():
    assert precision_at_k(["chunk-1", "chunk-2", "chunk-3"], {"chunk-2"}, k=3) == 1.0 / 3.0


def test_precision_at_k_zero_k():
    assert precision_at_k(["a"], {"a"}, k=0) == 0.0


def test_recall_at_k():
    assert recall_at_k(["chunk-1", "chunk-2"], {"chunk-2", "chunk-3"}, k=2) == 0.5


def test_recall_at_k_empty_relevant():
    assert recall_at_k(["a"], set(), k=1) == 0.0


def test_mean_precision_at_k_empty():
    assert mean_precision_at_k([], [], k=1) == 0.0


def test_mean_recall_at_k_empty():
    assert mean_recall_at_k([], [], k=1) == 0.0


def test_mean_precision_recall_pair():
    cases = [EvalCase("q", {"c1", "c2"})]
    ranked = [["c1", "x", "y"]]
    assert mean_precision_at_k(cases, ranked, k=3) == precision_at_k(ranked[0], {"c1", "c2"}, k=3)
    assert mean_recall_at_k(cases, ranked, k=3) == recall_at_k(ranked[0], {"c1", "c2"}, k=3)
