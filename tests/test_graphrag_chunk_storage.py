"""GraphRAG graphrag.chunk_storage の最小結合テスト。優先度: GraphRAG。"""

from graphrag.chunk_storage import ChunkStorage


def test_chunk_storage_register_save_get(tmp_path):
    db = tmp_path / "chunks.db"
    cs = ChunkStorage(str(db))
    path = "data/graphs/sample.pkl"
    gid = cs.register_graph(path, document_name="sample", node_count=2, edge_count=1)
    assert gid == cs.get_graph_id(path)

    cs.save_chunks(gid, {"c0": "chunk body", "c1": "other"})
    chunks = cs.get_chunks(gid)
    assert chunks["c0"] == "chunk body"
    assert len(chunks) == 2

    cs.save_node_chunks(gid, {"n1": ["c0"], "n2": ["c1"]})
    assert set(cs.get_node_chunks(gid, "n1")) == {"c0"}

    cs.save_edge_chunks(gid, {("n1", "n2"): ["c0"]})
    assert cs.get_edge_chunks(gid, "n1", "n2") == ["c0"]

    cs.delete_graph(gid)
    assert cs.get_chunks(gid) == {}
