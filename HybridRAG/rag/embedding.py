"""埋め込み処理モジュール。

このモジュールは、OpenAIの埋め込みAPIを使用してテキストを
ベクトル化する機能を提供します。キャッシュ機能により
同じテキストの再計算を避けます。
"""

from __future__ import annotations

import logging
import time
from functools import lru_cache
from typing import Iterable, List

from openai import OpenAI

from .config import EMBEDDING_MODEL, OPENAI_TIMEOUT_SECONDS, require_openai_api_key

_client: OpenAI | None = None
logger = logging.getLogger(__name__)


def _get_client() -> OpenAI:
    """OpenAI クライアントをシングルトンとして取得する。

    Returns:
        OpenAI: OpenAIクライアントインスタンス。
    """
    global _client
    if _client is None:
        api_key = require_openai_api_key()
        _client = OpenAI(api_key=api_key, timeout=OPENAI_TIMEOUT_SECONDS)
    return _client


@lru_cache(maxsize=2048)
def embed_text(text: str) -> List[float]:
    """単一テキストを埋め込みベクトルに変換する。

    同一テキストに対する埋め込みはキャッシュから再利用されます。
    キャッシュサイズは2048件まで。

    Args:
        text: 埋め込み対象のテキスト。

    Returns:
        List[float]: 埋め込みベクトル（浮動小数点数のリスト）。

    Raises:
        RuntimeError: OpenAI APIキーが設定されていない場合。
        Exception: OpenAI API呼び出しに失敗した場合。

    Example:
        >>> vector = embed_text("サンプルテキスト")
        >>> print(len(vector))
        1536
    """
    client = _get_client()
    last_err: Exception | None = None
    for attempt in range(1, 4):
        try:
            response = client.embeddings.create(model=EMBEDDING_MODEL, input=[text])
            return response.data[0].embedding
        except Exception as e:
            last_err = e
            # 最終試行はそのまま例外化
            if attempt >= 3:
                logger.exception("embed_text.failed", extra={"event": "embed_text.failed", "attempt": attempt})
                raise
            sleep_s = min(8.0, 0.5 * (2 ** (attempt - 1)))
            logger.warning(
                "embed_text.retry",
                extra={
                    "event": "embed_text.retry",
                    "attempt": attempt,
                    "sleep_s": sleep_s,
                    "error_type": type(e).__name__,
                },
            )
            time.sleep(sleep_s)
    # 到達しない想定
    raise last_err  # type: ignore[misc]


def embed_texts(texts: Iterable[str]) -> List[List[float]]:
    """複数のテキストを埋め込みベクトルに変換する。

    使用モデル: ``text-embedding-3-small``
    バッチAPIを利用して効率的に処理します。

    Args:
        texts: 埋め込み対象のテキストのイテラブル。

    Returns:
        List[List[float]]: 各テキストの埋め込みベクトルのリスト。
            入力の順序と対応します。

    Raises:
        RuntimeError: OpenAI APIキーが設定されていない場合。
        Exception: OpenAI API呼び出しに失敗した場合。

    Example:
        >>> texts = ["テキスト1", "テキスト2"]
        >>> vectors = embed_texts(texts)
        >>> print(len(vectors))
        2
    """
    texts_list = list(texts)
    if not texts_list:
        return []

    # すべて同一テキストの場合など、キャッシュを最大限活用する
    if len(texts_list) == 1:
        return [embed_text(texts_list[0])]

    client = _get_client()
    last_err: Exception | None = None
    for attempt in range(1, 4):
        try:
            response = client.embeddings.create(model=EMBEDDING_MODEL, input=texts_list)
            return [item.embedding for item in response.data]
        except Exception as e:
            last_err = e
            if attempt >= 3:
                logger.exception(
                    "embed_texts.failed",
                    extra={"event": "embed_texts.failed", "attempt": attempt, "num_texts": len(texts_list)},
                )
                raise
            sleep_s = min(8.0, 0.5 * (2 ** (attempt - 1)))
            logger.warning(
                "embed_texts.retry",
                extra={
                    "event": "embed_texts.retry",
                    "attempt": attempt,
                    "sleep_s": sleep_s,
                    "num_texts": len(texts_list),
                    "error_type": type(e).__name__,
                },
            )
            time.sleep(sleep_s)
    raise last_err  # type: ignore[misc]



