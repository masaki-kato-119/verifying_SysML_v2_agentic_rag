"""rag.chunking: ファイル I/O とセクション・SysML ブロック分割の結合テスト。"""

from pathlib import Path

from rag.chunking import (
    chunk_text_semantic,
    read_markdown_file,
    read_text_file,
)


def test_read_text_and_markdown_file(tmp_path: Path):
    p = tmp_path / "doc.txt"
    p.write_text("line1\nline2\n", encoding="utf-8")
    assert read_text_file(p) == "line1\nline2\n"
    md = tmp_path / "x.md"
    md.write_text("# Title\n\nbody\n", encoding="utf-8")
    assert "Title" in read_markdown_file(md)


def test_chunk_text_semantic_markdown_headings(tmp_path: Path):
    """見出しでセクション分割され、チャンクに section_title が付く。"""
    md = tmp_path / "s.md"
    md.write_text(
        "# Intro\n\nFirst paragraph. Second sentence here.\n\n"
        "## Detail\n\nMore text for chunking.\n",
        encoding="utf-8",
    )
    text = read_markdown_file(md)
    chunks = chunk_text_semantic(text)
    assert len(chunks) >= 1
    titles = {c[1].get("section_title") for c in chunks}
    assert "Intro" in titles
    assert "Detail" in titles


def test_chunk_text_semantic_sysml_like_block(tmp_path: Path):
    """SysML 風ブロックが sysml_code チャンクとしてまとまる。"""
    content = (
        "説明文です。\n\n"
        "part def Vehicle {\n"
        "  attribute mass : Real;\n"
        "};\n"
    )
    p = tmp_path / "mix.md"
    p.write_text(content, encoding="utf-8")
    chunks = chunk_text_semantic(read_text_file(p))
    kinds = {c[1].get("chunk_kind") for c in chunks}
    assert "sysml_code" in kinds
