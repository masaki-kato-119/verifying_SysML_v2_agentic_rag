"""rag.embedding のキャッシュ・リトライロジック。優先度: HybridRAG/rag(t5_add_tests_hybridrag_gaps)。

これまでテストが無く、OpenAI Embedding APIの実呼び出しに依存する
リトライ・キャッシュの挙動が一度も検証されていなかった。
"""

from unittest.mock import MagicMock

import pytest
from rag import embedding


@pytest.fixture(autouse=True)
def _clear_cache_and_client():
    embedding.embed_text.cache_clear()
    embedding._client = None
    yield
    embedding.embed_text.cache_clear()
    embedding._client = None


def _make_fake_client(side_effects):
    """.embeddings.create が side_effects を順に返す/起こすフェイククライアント。"""
    client = MagicMock()
    client.embeddings.create.side_effect = side_effects
    return client


def _embedding_response(vectors):
    response = MagicMock()
    response.data = [MagicMock(embedding=v) for v in vectors]
    return response


def test_embed_text_returns_vector_from_client(monkeypatch):
    client = _make_fake_client([_embedding_response([[0.1, 0.2, 0.3]])])
    monkeypatch.setattr(embedding, "_get_client", lambda: client)

    result = embedding.embed_text("hello")

    assert result == [0.1, 0.2, 0.3]
    client.embeddings.create.assert_called_once()


def test_embed_text_caches_identical_text(monkeypatch):
    client = _make_fake_client([_embedding_response([[1.0]])])
    monkeypatch.setattr(embedding, "_get_client", lambda: client)

    first = embedding.embed_text("same text")
    second = embedding.embed_text("same text")

    assert first == second == [1.0]
    # lru_cache により2回目はAPIを呼ばない
    client.embeddings.create.assert_called_once()


def test_embed_text_retries_then_succeeds(monkeypatch):
    client = _make_fake_client(
        [RuntimeError("boom"), RuntimeError("boom again"), _embedding_response([[9.9]])]
    )
    monkeypatch.setattr(embedding, "_get_client", lambda: client)
    monkeypatch.setattr(embedding.time, "sleep", lambda _seconds: None)

    result = embedding.embed_text("retry me")

    assert result == [9.9]
    assert client.embeddings.create.call_count == 3


def test_embed_text_raises_after_exhausting_retries(monkeypatch):
    client = _make_fake_client([RuntimeError("a"), RuntimeError("b"), RuntimeError("c")])
    monkeypatch.setattr(embedding, "_get_client", lambda: client)
    monkeypatch.setattr(embedding.time, "sleep", lambda _seconds: None)

    with pytest.raises(RuntimeError, match="c"):
        embedding.embed_text("always fails")

    assert client.embeddings.create.call_count == 3


def test_embed_texts_empty_list_returns_empty_without_calling_client(monkeypatch):
    client = _make_fake_client([])
    monkeypatch.setattr(embedding, "_get_client", lambda: client)

    assert embedding.embed_texts([]) == []
    client.embeddings.create.assert_not_called()


def test_embed_texts_single_text_delegates_to_embed_text_cache(monkeypatch):
    client = _make_fake_client([_embedding_response([[5.0]])])
    monkeypatch.setattr(embedding, "_get_client", lambda: client)

    result = embedding.embed_texts(["only one"])

    assert result == [[5.0]]
    # embed_text経由でバッチAPIではなく単発呼び出しになる
    client.embeddings.create.assert_called_once_with(
        model=embedding.EMBEDDING_MODEL, input=["only one"]
    )


def test_embed_texts_multiple_uses_batch_call(monkeypatch):
    client = _make_fake_client([_embedding_response([[1.0], [2.0], [3.0]])])
    monkeypatch.setattr(embedding, "_get_client", lambda: client)

    result = embedding.embed_texts(["a", "b", "c"])

    assert result == [[1.0], [2.0], [3.0]]
    client.embeddings.create.assert_called_once_with(
        model=embedding.EMBEDDING_MODEL, input=["a", "b", "c"]
    )


def test_get_client_is_singleton(monkeypatch):
    monkeypatch.setattr(embedding, "require_openai_api_key", lambda: "dummy-key")
    created = []

    class _FakeOpenAI:
        def __init__(self, **kwargs):
            created.append(kwargs)

    monkeypatch.setattr(embedding, "OpenAI", _FakeOpenAI)

    first = embedding._get_client()
    second = embedding._get_client()

    assert first is second
    assert len(created) == 1
