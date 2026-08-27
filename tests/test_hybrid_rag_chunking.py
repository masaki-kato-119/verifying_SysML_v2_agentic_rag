"""HybridRAG rag.chunking の軽量テスト（ファイル I/O なし）。"""

from rag.chunking import (
    chunk_sentences,
    chunk_text,
    chunk_text_semantic,
    split_to_sentences,
)


def test_split_to_sentences_japanese():
    text = "これは最初の文です。これは二番目の文です。"
    sents = split_to_sentences(text)
    assert len(sents) >= 1


def test_chunk_sentences():
    out = chunk_sentences(["a", "b", "c"])
    assert isinstance(out, list)
    assert len(out) >= 1


def test_chunk_text_basic():
    out = chunk_text("短いテキスト。")
    assert isinstance(out, list)


def test_chunk_text_semantic_empty():
    out = chunk_text_semantic("")
    assert out == []


def test_chunk_text_semantic_short():
    out = chunk_text_semantic("Hello world. Second sentence here.")
    assert isinstance(out, list)
