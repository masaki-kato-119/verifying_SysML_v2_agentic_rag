"""GraphRAG graph_persistence の roundtrip テスト。優先度: GraphRAG。"""

import networkx as nx
from graphrag.graph_persistence import GraphPersistence


def test_save_load_json_roundtrip(tmp_path):
    g = nx.DiGraph()
    g.add_node("n1", label="A")
    g.add_edge("n1", "n2", relation="is-a")
    g.graph["source_chunks"] = {"x": 1}

    p = tmp_path / "g.json"
    GraphPersistence.save_json(g, str(p))
    loaded = GraphPersistence.load_json(str(p))

    assert "n1" in loaded.nodes
    assert loaded.has_edge("n1", "n2")
    assert loaded.graph.get("graph_filepath") == str(p)


def test_save_load_pickle_roundtrip(tmp_path):
    g = nx.DiGraph()
    g.add_edge("a", "b")
    path = tmp_path / "g.pkl"
    GraphPersistence.save_pickle(g, str(path))
    g2 = GraphPersistence.load_pickle(str(path))
    assert list(g2.edges()) == [("a", "b")]
    assert "graph_filepath" in g2.graph


def test_compare_graphs():
    g1 = nx.DiGraph()
    g1.add_edge("a", "b")
    g2 = nx.DiGraph()
    g2.add_edge("a", "b")
    g2.add_node("c")
    r = GraphPersistence.compare_graphs(g1, g2)
    assert r["node_count_1"] == 2
    assert r["node_count_2"] == 3
    assert r["node_diff_rate"] > 0


def test_save_load_helpers(tmp_path):
    g = nx.DiGraph()
    g.add_node("only")
    p = tmp_path / "x.pkl"
    GraphPersistence.save(g, str(p), format="pickle")
    g2 = GraphPersistence.load(str(p), format="auto")
    assert "only" in g2.nodes
