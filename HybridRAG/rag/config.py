"""設定管理モジュール。

このモジュールは、データベースパス、OpenAI API設定などの
アプリケーション設定を管理します。
"""

from __future__ import annotations

import json
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

BASE_DIR = Path(__file__).resolve().parent.parent

# データディレクトリ
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)

# ChromaDB の永続化ディレクトリ
CHROMA_DIR = DATA_DIR / "chroma.db"

# SQLite3 DB ファイル
SQLITE_PATH = DATA_DIR / "sqlite.db"

# Lightweight GraphRAG の永続化ファイル（networkxのpickle）
GRAPH_PATH = DATA_DIR / "graph.pkl"

# 検索結果キャッシュの永続化ファイル（SQLite）
CACHE_DB_PATH = DATA_DIR / "search_cache.db"

# OpenAI 関連設定
OPENAI_API_KEY_ENV = "OPENAI_API_KEY"

# 埋め込みモデル。text-embedding-3-small は現時点でも OpenAI 推奨の現行モデルで、
# 廃止予定もない。変更すると全チャンクの再インデックスが必要になるため据え置く。
EMBEDDING_MODEL = "text-embedding-3-small"

# 生成モデル。GPT-5 系（reasoning モデル）を前提にしている。
# 注意: reasoning モデルでは以下の制約がある（2026-08 に実 API で確認済み）。
#   - temperature は非対応（デフォルト 1 のみ。値を渡すと 400）
#   - max_tokens は非対応。max_completion_tokens を使う
#   - reasoning_effort は 'none' / 'low' 等。'minimal' は非対応
#   - function tools と reasoning_effort の併用は /v1/chat/completions では不可。
#     ツールを使う呼び出しでは reasoning_effort='none' が必須
LLM_MODEL = os.getenv("RAG_LLM_MODEL", "gpt-5.6-luna")

# OpenAI クライアントのデフォルトタイムアウト（秒）
OPENAI_TIMEOUT_SECONDS: float = float(os.getenv("OPENAI_TIMEOUT_SECONDS", "30"))

# インデックス対象ファイルの制限（運用用。未設定なら制限なし）
ALLOWED_BASE_DIR_ENV = "RAG_ALLOWED_BASE_DIR"
ALLOWED_BASE_DIR: str | None = os.getenv(ALLOWED_BASE_DIR_ENV)
MAX_INDEX_FILE_BYTES: int = int(os.getenv("RAG_MAX_INDEX_FILE_BYTES", str(100 * 1024 * 1024)))
ALLOWED_INDEX_EXTENSIONS = {".txt", ".md", ".markdown", ".pdf", ".sysml", ".docx", ".xlsx", ".xls", ".pptx"}

# ログ設定
LOG_LEVEL_ENV = "RAG_LOG_LEVEL"
LOG_LEVEL = os.getenv(LOG_LEVEL_ENV, "INFO").upper()


def env_flag(name: str, default: str = "true") -> bool:
    """環境変数を真偽値として解釈する（"true"/"1"/"yes" を真とする）。

    HybridRAG/mcp_server.py・本モジュールの複数箇所で同じ判定を
    個別にインライン実装していたための共通ヘルパー。

    Args:
        name: 環境変数名。
        default: 未設定時のデフォルト値（文字列）。

    Returns:
        bool: 環境変数の値が真を表す場合True。
    """
    return os.getenv(name, default).lower() in {"true", "1", "yes"}


# ============================================================================
# 検索パラメータ設定（チューニング用）
# ============================================================================
# これらのパラメータは環境変数で上書き可能です。
# 例: export RAG_SEARCH_TOP_K_VECTOR=30
#
# チューニングガイド:
# - 小規模（数百チャンク）: top_k=10, limit_meta=10, rerank_top_k=5, graph_depth=1
# - 中規模（数千チャンク）: top_k=20, limit_meta=20, rerank_top_k=10, graph_depth=2 ← 推奨
# - 大規模（数万チャンク）: top_k=50, limit_meta=50, rerank_top_k=20, graph_depth=2

# ベクトル検索の取得件数
# 大きいほど精度向上、処理時間増加。推奨: 20-50
SEARCH_TOP_K_VECTOR: int = int(os.getenv("RAG_SEARCH_TOP_K_VECTOR", "40"))

# FTS検索の取得件数
# 大きいほど精度向上、処理時間増加。推奨: 20-50
SEARCH_LIMIT_META: int = int(os.getenv("RAG_SEARCH_LIMIT_META", "40"))

# リランキング後の上位件数
# top_k_vector + limit_meta 以下に設定。推奨: 10-20
SEARCH_RERANK_TOP_K: int = int(os.getenv("RAG_SEARCH_RERANK_TOP_K", "15"))

# リランキングを使用するか
# True: 精度向上（+10-20%）、処理時間増加
SEARCH_USE_RERANK: bool = env_flag("RAG_SEARCH_USE_RERANK")

# クエリ拡張を使用するか
# True: リコール向上（+15-25%）、LLM APIコスト増加
SEARCH_USE_QUERY_EXPANSION: bool = env_flag("RAG_SEARCH_USE_QUERY_EXPANSION")

# GraphRAGを使用するか
# True: リコール向上（+10-20%）、特に手順書・仕様書で効果的
SEARCH_USE_GRAPH: bool = env_flag("RAG_SEARCH_USE_GRAPH")

# Graph探索の深さ（1=浅い、2=深い）
# 1: 処理速度優先、2: 回収率優先（推奨）
SEARCH_GRAPH_DEPTH: int = int(os.getenv("RAG_SEARCH_GRAPH_DEPTH", "2"))

# Graph探索の起点となる上位候補数
# 大きいほど探索範囲拡大。推奨: 3-5
SEARCH_GRAPH_SEED_K: int = int(os.getenv("RAG_SEARCH_GRAPH_SEED_K", "4"))

# Graphから追加する近傍候補の最大数
# 大きいほど回収率向上、処理時間増加。推奨: 30-50
SEARCH_GRAPH_MAX_NEIGHBORS: int = int(os.getenv("RAG_SEARCH_GRAPH_MAX_NEIGHBORS", "40"))

# 近傍候補のスコア付与係数（距離減衰）
# 0.0-1.0。大きいほど近傍候補のスコアが高くなる。推奨: 0.5
SEARCH_GRAPH_NEIGHBOR_WEIGHT: float = float(os.getenv("RAG_SEARCH_GRAPH_NEIGHBOR_WEIGHT", "0.5"))

# MMR (Maximal Marginal Relevance) を使用するか
# True: 多様性向上（+10-15%）、処理時間増加
SEARCH_USE_MMR: bool = env_flag("RAG_SEARCH_USE_MMR", default="false")

# MMRの関連性と多様性のバランス
# 0.0=多様性優先、1.0=関連性優先。推奨: 0.5
SEARCH_MMR_LAMBDA: float = float(os.getenv("RAG_SEARCH_MMR_LAMBDA", "0.5"))

# MMR適用後の返却件数
# Noneの場合はすべて返す。推奨: 5-10
SEARCH_MMR_TOP_K: Optional[int] = (
    int(os.getenv("RAG_SEARCH_MMR_TOP_K", "15")) if os.getenv("RAG_SEARCH_MMR_TOP_K", "15") != "0" else None
)


def require_openai_api_key() -> str:
    """環境変数から OpenAI API キーを取得し、存在しなければ例外を投げる。

    Returns:
        str: OpenAI APIキー文字列。

    Raises:
        RuntimeError: 環境変数 ``OPENAI_API_KEY`` が設定されていない場合。

    Example:
        >>> api_key = require_openai_api_key()
        >>> print(api_key[:10])
        sk-...
    """
    api_key = os.getenv(OPENAI_API_KEY_ENV)
    if not api_key:
        raise RuntimeError(
            f"環境変数 {OPENAI_API_KEY_ENV} が設定されていません。OpenAI API キーを設定してください。"
        )
    return api_key

class JsonFormatter(logging.Formatter):
    """JSON形式のログフォーマッタ（追加依存なし）。"""

    _RESERVED = {
        "name",
        "msg",
        "args",
        "levelname",
        "levelno",
        "pathname",
        "filename",
        "module",
        "exc_info",
        "exc_text",
        "stack_info",
        "lineno",
        "funcName",
        "created",
        "msecs",
        "relativeCreated",
        "thread",
        "threadName",
        "processName",
        "process",
    }

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "ts": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }

        # extra で渡された項目を取り込む
        for k, v in record.__dict__.items():
            if k in self._RESERVED:
                continue
            # exc_info などは別扱い
            if k in {"exc_info", "exc_text", "stack_info"}:
                continue
            payload[k] = v

        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)

        return json.dumps(payload, ensure_ascii=False)


def configure_logging() -> None:
    """アプリ全体のログ（JSON）を設定する。

    - 既にハンドラが設定済みなら何もしない（重複設定防止）
    - 標準エラー出力にJSONで出力（MCPサーバーではstdoutはJSON-RPC専用のため）
    """
    root = logging.getLogger()
    if root.handlers:
        return

    level = getattr(logging, LOG_LEVEL, logging.INFO)
    root.setLevel(level)

    handler = logging.StreamHandler(stream=sys.stderr)
    handler.setFormatter(JsonFormatter())
    root.addHandler(handler)



