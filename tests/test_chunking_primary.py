"""HybridRAG rag.chunking の主要パス（長文チャンク・見出し分割）。"""

from pathlib import Path

from rag.chunking import chunk_text, chunk_text_semantic, read_text_file


def test_chunk_text_splits_when_over_size():
    """CHUNK_SIZE を超えると複数チャンクに分かれる。"""
    sentence = "あ" * 400 + "。"
    text = sentence * 5
    chunks = chunk_text(text)
    assert len(chunks) >= 2


def test_chunk_text_semantic_numeric_heading():
    """数字見出し（8.1 形式）でセクションが分かれる。"""
    text = "8.1 SectionTitle\n\n本文です。もう一段。\n\n8.2 Next\n\n続き。"
    out = chunk_text_semantic(text)
    titles = {m.get("section_title") for _, m in out}
    assert "SectionTitle" in titles or "Next" in titles


def test_read_text_file_roundtrip(tmp_path: Path):
    f = tmp_path / "t.txt"
    f.write_text("hello\n", encoding="utf-8")
    assert read_text_file(f) == "hello\n"
