"""HybridRAG rag.metadata_store のテスト（tmp SQLite）。優先度: HybridRAG/rag。"""

from pathlib import Path

from rag.metadata_store import ChunkMetadata, MetadataStore


def _store(tmp_path: Path) -> MetadataStore:
    return MetadataStore(db_path=tmp_path / "meta_test.db")


def test_insert_meta_search_get_chunk(tmp_path: Path):
    s = _store(tmp_path)
    try:
        row_id = s.insert_chunk(
            chunk_id="doc::chunk-0",
            file_name="doc.txt",
            file_path=str(tmp_path / "doc.txt"),
            file_type="txt",
            chunk_text="hello unique_token_alpha",
            chunk_index=0,
            section_id="1",
            section_title="Intro",
            chunk_kind="text",
        )
        assert row_id > 0

        rows = s.meta_search(file_name="doc.txt", limit=5)
        assert len(rows) == 1
        assert rows[0].chunk_id == "doc::chunk-0"
        assert rows[0].section_id == "1"

        one = s.get_chunk_by_chunk_id("doc::chunk-0")
        assert one is not None
        assert one.chunk_text == "hello unique_token_alpha"
        assert isinstance(one, ChunkMetadata)
    finally:
        s.close()


def test_semantic_search_finds_text(tmp_path: Path):
    s = _store(tmp_path)
    try:
        s.insert_chunk(
            chunk_id="c1",
            file_name="a.md",
            file_path=str(tmp_path / "a.md"),
            file_type="md",
            chunk_text="python rag pipeline",
            chunk_index=0,
        )
        hits = s.semantic_search("python", limit=5)
        assert any("python" in h.chunk_text for h in hits)
    finally:
        s.close()


def test_bulk_insert_and_delete(tmp_path: Path):
    s = _store(tmp_path)
    try:
        s.bulk_insert_chunks(
            [
                {
                    "chunk_id": "b0",
                    "file_name": "f.txt",
                    "file_path": "/x/f.txt",
                    "file_type": "txt",
                    "chunk_text": "t0",
                    "chunk_index": 0,
                },
                {
                    "chunk_id": "b1",
                    "file_name": "f.txt",
                    "file_path": "/x/f.txt",
                    "file_type": "txt",
                    "chunk_text": "t1",
                    "chunk_index": 1,
                },
            ]
        )
        got = s.get_chunks_by_chunk_ids(["b0", "b1"])
        assert len(got) == 2
        s.delete_by_chunk_ids(["b0"])
        assert s.get_chunk_by_chunk_id("b0") is None
        assert s.get_chunk_by_chunk_id("b1") is not None
    finally:
        s.close()


def test_semantic_search_empty_query(tmp_path: Path):
    s = _store(tmp_path)
    try:
        assert s.semantic_search("   ") == []
    finally:
        s.close()
