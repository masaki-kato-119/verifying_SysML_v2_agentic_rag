"""検索結果のキャッシングモジュール。

このモジュールは、検索結果をキャッシュして、同じクエリの再検索を高速化します。
"""

from __future__ import annotations

import hashlib
import json
import logging
import sqlite3
import time
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class CachedSearchResult:
    """キャッシュされた検索結果。

    Attributes:
        results: 検索結果のリスト（シリアライズ可能な形式）。
        timestamp: キャッシュ作成時刻（Unix timestamp）。
        query_hash: クエリとパラメータのハッシュ値。
    """

    results: List[Dict[str, Any]]
    timestamp: float
    query_hash: str


class SearchCache:
    """検索結果のキャッシュ管理クラス。

    メモリ内キャッシュ（LRU）と永続化キャッシュ（SQLite）の両方をサポートします。
    """

    def __init__(
        self,
        *,
        max_size: int = 1000,
        ttl_seconds: Optional[float] = None,
        persist_path: Optional[Path] = None,
    ) -> None:
        """SearchCacheを初期化する。

        Args:
            max_size: メモリ内キャッシュの最大サイズ（デフォルト: 1000）。
            ttl_seconds: キャッシュの有効期限（秒）。Noneの場合は無期限（デフォルト: None）。
            persist_path: 永続化キャッシュのパス（SQLite）。Noneの場合は永続化しない（デフォルト: None）。
        """
        self.max_size = max_size
        self.ttl_seconds = ttl_seconds
        self.persist_path = persist_path

        # メモリ内キャッシュ（OrderedDictでLRU順序を維持）
        self._memory_cache: "OrderedDict[str, CachedSearchResult]" = OrderedDict()
        
        # キャッシュ統計（パフォーマンス測定用）
        self._hits: int = 0
        self._misses: int = 0

        # 永続化キャッシュ（SQLite）の初期化
        self._db_conn = None
        if persist_path:
            self._init_persistent_cache()

    def _init_persistent_cache(self) -> None:
        """永続化キャッシュ（SQLite）を初期化する。"""
        if self.persist_path is None:
            return

        try:
            self.persist_path.parent.mkdir(parents=True, exist_ok=True)
            self._db_conn = sqlite3.connect(str(self.persist_path), check_same_thread=False)
            cursor = self._db_conn.cursor()
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS search_cache (
                    query_hash TEXT PRIMARY KEY,
                    results_json TEXT NOT NULL,
                    timestamp REAL NOT NULL
                )
                """
            )
            cursor.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_timestamp ON search_cache(timestamp)
                """
            )
            self._db_conn.commit()
            logger.info(f"永続化キャッシュを初期化: {self.persist_path}")
        except (OSError, sqlite3.Error) as e:
            logger.warning(f"永続化キャッシュの初期化に失敗: {e}。メモリ内キャッシュのみ使用します。")
            self._db_conn = None

    def _generate_cache_key(
        self,
        query: str,
        **kwargs: Any,
    ) -> str:
        """キャッシュキーを生成する。

        Args:
            query: 検索クエリ。
            **kwargs: 検索パラメータ（top_k_vector, limit_meta, use_rerankなど）。

        Returns:
            str: キャッシュキー（ハッシュ値）。
        """
        # キャッシュに影響するパラメータのみを含める
        cache_params = {
            "query": query,
            "top_k_vector": kwargs.get("top_k_vector"),
            "limit_meta": kwargs.get("limit_meta"),
            "use_rerank": kwargs.get("use_rerank"),
            "use_mmr": kwargs.get("use_mmr"),
            "mmr_lambda": kwargs.get("mmr_lambda"),
            "mmr_top_k": kwargs.get("mmr_top_k"),
            "use_graph": kwargs.get("use_graph"),
            "graph_depth": kwargs.get("graph_depth"),
            "file_name": kwargs.get("file_name"),
            "file_path": kwargs.get("file_path"),
            "file_type": kwargs.get("file_type"),
            "page_number": kwargs.get("page_number"),
            "scoring": kwargs.get("scoring"),
        }
        # ソートして一貫性を保つ
        cache_str = json.dumps(cache_params, sort_keys=True, ensure_ascii=False)
        return hashlib.md5(cache_str.encode("utf-8")).hexdigest()

    def get(
        self,
        query: str,
        **kwargs: Any,
    ) -> Optional[List[Dict[str, Any]]]:
        """キャッシュから検索結果を取得する。

        Args:
            query: 検索クエリ。
            **kwargs: 検索パラメータ。

        Returns:
            Optional[List[Dict[str, Any]]]: キャッシュされた検索結果。見つからない場合はNone。
        """
        cache_key = self._generate_cache_key(query, **kwargs)

        # メモリ内キャッシュから取得
        if cache_key in self._memory_cache:
            cached = self._memory_cache[cache_key]
            if self._is_valid(cached):
                logger.info(f"メモリ内キャッシュから取得: {cache_key[:8]}... (hits={self._hits + 1}, misses={self._misses})")
                self._hits += 1
                # LRU: アクセスされたエントリを最新として末尾に移動
                self._memory_cache.move_to_end(cache_key)
                return cached.results
            else:
                # 期限切れの場合は削除
                del self._memory_cache[cache_key]

        # 永続化キャッシュから取得
        if self._db_conn:
            try:
                cursor = self._db_conn.cursor()
                cursor.execute(
                    "SELECT results_json, timestamp FROM search_cache WHERE query_hash = ?",
                    (cache_key,),
                )
                row = cursor.fetchone()
                if row:
                    results_json, timestamp = row
                    cached = CachedSearchResult(
                        results=json.loads(results_json),
                        timestamp=timestamp,
                        query_hash=cache_key,
                    )
                    if self._is_valid(cached):
                        logger.info(f"永続化キャッシュから取得: {cache_key[:8]}... (hits={self._hits + 1}, misses={self._misses})")
                        # メモリ内キャッシュにも追加
                        self._set_memory_cache(cache_key, cached)
                        self._hits += 1
                        return cached.results
                    else:
                        # 期限切れの場合は削除
                        cursor.execute("DELETE FROM search_cache WHERE query_hash = ?", (cache_key,))
                        self._db_conn.commit()
            except (sqlite3.Error, json.JSONDecodeError) as e:
                logger.warning(f"永続化キャッシュからの取得に失敗: {e}")

        self._misses += 1
        logger.info(f"キャッシュミス: {cache_key[:8]}... (hits={self._hits}, misses={self._misses})")
        return None

    def set(
        self,
        query: str,
        results: List[Dict[str, Any]],
        **kwargs: Any,
    ) -> None:
        """検索結果をキャッシュに保存する。

        Args:
            query: 検索クエリ。
            results: 検索結果のリスト（シリアライズ可能な形式）。
            **kwargs: 検索パラメータ。
        """
        cache_key = self._generate_cache_key(query, **kwargs)
        timestamp = time.time()

        cached = CachedSearchResult(
            results=results,
            timestamp=timestamp,
            query_hash=cache_key,
        )

        # メモリ内キャッシュに保存
        self._set_memory_cache(cache_key, cached)

        # 永続化キャッシュに保存
        if self._db_conn:
            try:
                results_json = json.dumps(results, ensure_ascii=False)
                cursor = self._db_conn.cursor()
                cursor.execute(
                    "INSERT OR REPLACE INTO search_cache (query_hash, results_json, timestamp) VALUES (?, ?, ?)",
                    (cache_key, results_json, timestamp),
                )
                self._db_conn.commit()
                logger.info(f"永続化キャッシュに保存: {cache_key[:8]}... (cache_size={len(self._memory_cache)})")
            except (TypeError, ValueError, sqlite3.Error) as e:
                logger.warning(f"永続化キャッシュへの保存に失敗: {e}")

    def _set_memory_cache(self, cache_key: str, cached: CachedSearchResult) -> None:
        """メモリ内キャッシュに保存する（サイズ制限を考慮）。

        max_sizeを超える場合は、最も長くアクセスされていないエントリ（LRU）を
        削除してから新しいエントリを追加します。既存キーへの上書きもアクセスとして
        扱い、末尾（最新）に移動します。

        Args:
            cache_key: キャッシュキー（ハッシュ値）。
            cached: キャッシュする検索結果。
        """
        # 既存キーの上書きの場合、先に削除してから末尾に再挿入し、最新として扱う
        if cache_key in self._memory_cache:
            del self._memory_cache[cache_key]
        elif len(self._memory_cache) >= self.max_size:
            # サイズ制限を超える場合は、最も長くアクセスされていないエントリを削除
            self._memory_cache.popitem(last=False)

        self._memory_cache[cache_key] = cached

    def _is_valid(self, cached: CachedSearchResult) -> bool:
        """キャッシュが有効かどうかを確認する。

        Args:
            cached: キャッシュされた検索結果。

        Returns:
            bool: キャッシュが有効な場合True。
        """
        if self.ttl_seconds is None:
            return True
        return (time.time() - cached.timestamp) < self.ttl_seconds

    def clear(self) -> None:
        """キャッシュをクリアする。

        メモリ内キャッシュと永続化キャッシュの両方をクリアし、
        キャッシュ統計（hits、misses）もリセットします。
        """
        self._memory_cache.clear()
        self._hits = 0
        self._misses = 0
        if self._db_conn:
            try:
                cursor = self._db_conn.cursor()
                cursor.execute("DELETE FROM search_cache")
                self._db_conn.commit()
                logger.info("永続化キャッシュをクリアしました")
            except sqlite3.Error as e:
                logger.warning(f"永続化キャッシュのクリアに失敗: {e}")

    def get_stats(self) -> Dict[str, Any]:
        """キャッシュの統計情報を取得する。

        Returns:
            Dict[str, Any]: 統計情報（メモリ内キャッシュサイズ、永続化キャッシュサイズ、ヒット率など）。
        """
        stats = {
            "memory_cache_size": len(self._memory_cache),
            "memory_cache_max_size": self.max_size,
            "hits": self._hits,
            "misses": self._misses,
        }
        
        # ヒット率を計算
        total_requests = self._hits + self._misses
        if total_requests > 0:
            stats["hit_rate"] = self._hits / total_requests
        else:
            stats["hit_rate"] = 0.0

        if self._db_conn:
            try:
                cursor = self._db_conn.cursor()
                cursor.execute("SELECT COUNT(*) FROM search_cache")
                stats["persistent_cache_size"] = cursor.fetchone()[0]
            except sqlite3.Error as e:
                logger.warning(f"永続化キャッシュの統計取得に失敗: {e}")
                stats["persistent_cache_size"] = 0
        else:
            stats["persistent_cache_size"] = 0

        return stats

    def close(self) -> None:
        """キャッシュをクローズする（永続化キャッシュの接続を閉じる）。

        永続化キャッシュ（SQLite）の接続を閉じます。
        メモリ内キャッシュは保持されます。
        コンテキストマネージャーとして使用する場合、自動的に呼び出されます。
        """
        if self._db_conn:
            self._db_conn.close()
            self._db_conn = None

    def __enter__(self) -> "SearchCache":
        """コンテキストマネージャーのエントリ。

        Returns:
            SearchCache: 自身のインスタンス。
        """
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        """コンテキストマネージャーのエグジット。

        自動的にclose()を呼び出して永続化キャッシュの接続を閉じます。

        Args:
            exc_type: 例外の型（発生した場合）。
            exc_val: 例外の値（発生した場合）。
            exc_tb: 例外のトレースバック（発生した場合）。
        """
        self.close()
