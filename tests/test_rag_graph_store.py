"""HybridRAG rag.graph_store のテスト。優先度: HybridRAG/rag。"""

from pathlib import Path

from rag.graph_store import GraphStore, Neighbor


def test_neighbor_dataclass():
    n = Neighbor(chunk_id="c1", distance=1, relation="next")
    assert n.chunk_id == "c1" and n.distance == 1


def test_graph_store_chain_and_bfs(tmp_path: Path):
    gs = GraphStore(persist_path=None)
    gs.add_chunk_node("doc::chunk-0", metadata={"chunk_index": 0})
    gs.add_chunk_node("doc::chunk-1", metadata={"chunk_index": 1})
    gs.add_chunk_node("doc::chunk-2", metadata={"chunk_index": 2})
    gs.add_bidirectional_edge(
        "doc::chunk-0",
        "doc::chunk-1",
        relation_ab="next",
        relation_ba="prev",
    )
    gs.add_bidirectional_edge(
        "doc::chunk-1",
        "doc::chunk-2",
        relation_ab="next",
        relation_ba="prev",
    )

    assert gs.has_node("doc::chunk-1")
    assert gs.has_edge("doc::chunk-0", "doc::chunk-1")
    assert gs.num_nodes() == 3
    assert gs.num_edges() == 4
    assert gs.get_node_degree("doc::chunk-1") >= 2

    nbrs = gs.neighbors_with_distance(["doc::chunk-0"], max_depth=2, limit=10)
    ids = [n.chunk_id for n in nbrs]
    assert "doc::chunk-1" in ids

    d = gs.get_min_distance_to_seeds("doc::chunk-2", ["doc::chunk-0"], max_depth=5)
    assert d == 2

    # 有向グラフの入出次数の和は 2*(n-1) を超え得るため、実装は 1.0 を上限にしない
    c = gs.get_node_centrality("doc::chunk-1")
    assert c >= 0.0


def test_graph_store_save_load_roundtrip(tmp_path: Path):
    p = tmp_path / "g.pkl"
    gs = GraphStore(persist_path=p)
    gs.add_chunk_node("a")
    gs.add_chunk_node("b")
    gs.add_edge("a", "b", relation="next")
    gs.save()

    gs2 = GraphStore(persist_path=p)
    assert gs2.has_node("a") and gs2.has_edge("a", "b")
