"""GraphRAG graphrag.eval の単体テスト（経路・近傍評価指標）。"""

from graphrag.eval import (
    neighbor_precision_recall,
    path_exact_match,
    path_node_overlap,
    relation_sequence_match,
)


def test_path_exact_match_true():
    assert path_exact_match(["a", "b", "c"], ["a", "b", "c"]) is True


def test_path_exact_match_false_different_order():
    assert path_exact_match(["a", "c", "b"], ["a", "b", "c"]) is False


def test_path_exact_match_false_different_length():
    assert path_exact_match(["a", "b"], ["a", "b", "c"]) is False


def test_path_node_overlap_partial():
    assert path_node_overlap(["a", "b", "c"], ["a", "b", "d"]) == 0.5


def test_path_node_overlap_identical():
    assert path_node_overlap(["a", "b"], ["a", "b"]) == 1.0


def test_path_node_overlap_disjoint():
    assert path_node_overlap(["a"], ["b"]) == 0.0


def test_path_node_overlap_both_empty():
    assert path_node_overlap([], []) == 0.0


def test_relation_sequence_match_true():
    assert relation_sequence_match(["is-a", "is-a"], ["is-a", "is-a"]) is True


def test_relation_sequence_match_false():
    assert relation_sequence_match(["is-a", "satisfies"], ["is-a", "is-a"]) is False


def test_neighbor_precision_recall_partial():
    actual = {("is-a", "b")}
    expected = {("is-a", "b"), ("is-a", "c")}
    precision, recall = neighbor_precision_recall(actual, expected)
    assert precision == 1.0
    assert recall == 0.5


def test_neighbor_precision_recall_empty_actual():
    precision, recall = neighbor_precision_recall(set(), {("is-a", "b")})
    assert precision == 0.0
    assert recall == 0.0


def test_neighbor_precision_recall_empty_expected():
    precision, recall = neighbor_precision_recall({("is-a", "b")}, set())
    assert precision == 0.0
    assert recall == 0.0


def test_neighbor_precision_recall_exact_match():
    actual = {("is-a", "b"), ("defines", "c")}
    expected = {("is-a", "b"), ("defines", "c")}
    assert neighbor_precision_recall(actual, expected) == (1.0, 1.0)
