"""構造制約チェックのテスト。優先度: GraphRAG。

以前は nx.simple_cycles で全ての単純閉路を列挙しており、密なグラフで
指数爆発した。ドメイン用語ゲート導入後、is-a エッジ 399 本で MemoryError を
起こして再構築が落ちている。知りたいのは「循環があるか」だけなので
DAG 判定で足りる。
"""

import random

import networkx as nx
import pytest
from graphrag.ontology_validator import OntologyValidator


@pytest.fixture
def validator():
    return OntologyValidator()


def _graph(edges, relation="is-a"):
    g = nx.DiGraph()
    for u, v in edges:
        g.add_edge(u, v, relation=relation)
    return g


def test_dag_passes(validator):
    ok, errors = validator.check_structure_constraints(_graph([("a", "b"), ("b", "c")]))

    assert ok is True
    assert errors == []


def test_is_a_cycle_is_reported_with_example(validator):
    ok, errors = validator.check_structure_constraints(
        _graph([("a", "b"), ("b", "c"), ("c", "a")])
    )

    assert ok is False
    assert "循環" in errors[0]
    # 件数ではなく実例を示す（全列挙しないため件数は出せない）
    assert "a" in errors[0]


def test_part_of_cycle_is_reported(validator):
    ok, errors = validator.check_structure_constraints(
        _graph([("x", "y"), ("y", "x")], relation="part-of")
    )

    assert ok is False
    assert "part-of" in errors[0]


def test_dense_graph_does_not_explode(validator):
    """全閉路列挙だと MemoryError になっていた規模。"""
    random.seed(0)
    nodes = [f"n{i}" for i in range(102)]
    g = nx.DiGraph()
    while g.number_of_edges() < 399:
        u, v = random.sample(nodes, 2)
        g.add_edge(u, v, relation="is-a")

    ok, errors = validator.check_structure_constraints(g)

    # 落ちずに判定できること（この規模はまず循環を含む）
    assert isinstance(ok, bool)
    assert isinstance(errors, list)


def test_large_edge_count_is_still_checked(validator):
    """従来は 1000 本以上で検査を丸ごと諦めていた（線形判定なので不要）。"""
    edges = [(f"n{i}", f"n{i + 1}") for i in range(1200)]
    edges.append(("n1200", "n0"))  # 循環を仕込む

    ok, errors = validator.check_structure_constraints(_graph(edges))

    assert ok is False
    assert "循環" in errors[0]


def test_fast_mode_only_checks_self_loops(validator):
    g = _graph([("a", "b"), ("b", "a")])

    ok, errors = validator.check_structure_constraints(g, fast_mode=True)

    assert ok is True  # 循環チェックはスキップされる
    assert errors == []


def test_self_loop_is_reported_in_fast_mode(validator):
    g = _graph([("a", "a")])

    ok, errors = validator.check_structure_constraints(g, fast_mode=True)

    assert ok is False
    assert "自己ループ" in errors[0]
