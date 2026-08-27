"""LLMによるクエリ拡張。

OpenAIクライアントの遅延生成もここに置く(search_graph_augment.pyの
_apply_local_graph_summaryもこのクライアントを利用する)。
"""

from __future__ import annotations

import logging
import time
from typing import List

from openai import OpenAI

from .config import LLM_MODEL, OPENAI_TIMEOUT_SECONDS, require_openai_api_key

logger = logging.getLogger(__name__)

_openai_client: OpenAI | None = None
def _get_openai_client() -> OpenAI:
    """OpenAI クライアントを取得するヘルパー。

    Returns:
        OpenAI: OpenAIクライアントインスタンス。

    Raises:
        RuntimeError: OpenAI APIキーが設定されていない場合。
    """
    global _openai_client
    if _openai_client is None:
        api_key = require_openai_api_key()
        _openai_client = OpenAI(api_key=api_key, timeout=OPENAI_TIMEOUT_SECONDS)
    return _openai_client
def expand_query_with_llm(
    query: str,
    *,
    max_keywords: int = 5,
) -> List[str]:
    """LLM を使ってクエリ拡張を行う。

    元のクエリから関連キーワード・同義語・言い換えを生成し、
    元クエリ + 拡張キーワード文字列のリストを返します。

    Args:
        query: 元のクエリ文字列。
        max_keywords: 生成するキーワードの最大数（デフォルト: 5）。

    Returns:
        List[str]: 元クエリ + 拡張キーワードのリスト。

    Raises:
        RuntimeError: OpenAI APIキーが設定されていない場合。
        Exception: OpenAI API呼び出しに失敗した場合。

    Example:
        >>> queries = expand_query_with_llm("Python", max_keywords=3)
        >>> print(queries)
        ['Python', 'プログラミング言語', 'スクリプト', '開発']
    """
    client = _get_openai_client()

    prompt = (
        "以下のクエリに関連するキーワードや同義語を"
        f"{max_keywords}個生成してください。\n"
        "クエリをそのまま繰り返すのではなく、関連しそうな専門用語や別表現を挙げてください。\n"
        "出力は日本語で、カンマ区切りで列挙してください。\n\n"
        f"クエリ: {query}\n\n"
        "キーワード（カンマ区切り）:"
    )

    last_err: Exception | None = None
    for attempt in range(1, 4):
        try:
            response = client.chat.completions.create(
                model=LLM_MODEL,
                messages=[{"role": "user", "content": prompt}],
                # クエリ拡張は検索前段でレイテンシが効くため推論なしで回す
                reasoning_effort="none",
                max_completion_tokens=256,
            )
            content = response.choices[0].message.content or ""
            keywords = [k.strip() for k in content.split(",") if k.strip()]
            break
        except Exception as e:
            last_err = e
            if attempt >= 3:
                logger.exception("expand_query_with_llm.failed", extra={"event": "expand_query_with_llm.failed"})
                raise
            sleep_s = min(8.0, 0.5 * (2 ** (attempt - 1)))
            logger.warning(
                "expand_query_with_llm.retry",
                extra={"event": "expand_query_with_llm.retry", "attempt": attempt, "sleep_s": sleep_s},
            )
            time.sleep(sleep_s)
    else:
        raise last_err  # type: ignore[misc]

    # 元クエリ + 各キーワードを単独クエリとして扱う
    return [query] + keywords
