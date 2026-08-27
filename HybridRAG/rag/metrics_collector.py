"""メトリクス収集モジュール。

このモジュールは、検索のパフォーマンスメトリクス（レイテンシ、スループット）と
検索品質メトリクス（MRR、NDCG）を収集・記録する機能を提供します。

フェーズ5: メトリクス収集・可視化
- use_graph / use_rerank / query_type ごとの MRR・NDCG・レイテンシを計測
- 精度チューニングのループを回せるようにする
"""

from __future__ import annotations

import json
import logging
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class SearchMetrics:
    """検索メトリクスのデータクラス。
    
    Attributes:
        query: 検索クエリ（ハッシュ化または短縮版を推奨）。
        query_type: クエリタイプ（"factual", "exploratory", "procedural"など）。
        use_graph: GraphRAGを使用したかどうか。
        use_rerank: リランキングを使用したかどうか。
        use_mmr: MMRを使用したかどうか。
        use_query_expansion: クエリ拡張を使用したかどうか。
        use_evidence_extraction: GraphRAG拡張（根拠情報抽出）を使用したかどうか。
        duration_ms: 検索実行時間（ミリ秒）。
        num_results: 返された結果数。
        mrr: MRR（Mean Reciprocal Rank）スコア（オプション）。
        ndcg_at_10: NDCG@10スコア（オプション）。
        precision_at_10: Precision@10スコア（オプション）。
        recall_at_10: Recall@10スコア（オプション）。
        relevant_chunk_ids: 関連チャンクIDのリスト（評価用、オプション）。
        timestamp: 記録日時。
        timing_breakdown: 段階別の所要時間（``ms_vector`` 等）。
            duration_ms だけでは「どの段階が遅いのか」を後から追えないため、
            search_hybrid が計測している内訳をそのまま保持する。
    """

    query: str
    query_type: Optional[str] = None
    use_graph: bool = False
    use_rerank: bool = False
    use_mmr: bool = False
    use_query_expansion: bool = False
    use_evidence_extraction: bool = False
    duration_ms: float = 0.0
    num_results: int = 0
    mrr: Optional[float] = None
    ndcg_at_10: Optional[float] = None
    precision_at_10: Optional[float] = None
    recall_at_10: Optional[float] = None
    relevant_chunk_ids: Optional[List[str]] = None
    timestamp: Optional[str] = None
    timing_breakdown: Optional[Dict[str, Any]] = None


class MetricsCollector:
    """メトリクス収集クラス。
    
    SQLiteベースの軽量実装で、検索メトリクスを記録・集計します。
    
    Attributes:
        db_path: SQLiteデータベースのパス。
        _conn: SQLite接続（内部使用）。
    """
    
    def __init__(self, db_path: Optional[Path] = None) -> None:
        """MetricsCollectorを初期化する。
        
        Args:
            db_path: SQLiteデータベースのパス。
                Noneの場合はメモリ内データベースを使用します。
        """
        if db_path is None:
            self.db_path = None
            self._conn = sqlite3.connect(":memory:", check_same_thread=False, timeout=5.0)
        else:
            self.db_path = Path(db_path)
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
            self._conn = sqlite3.connect(str(self.db_path), check_same_thread=False, timeout=5.0)
        
        self._conn.row_factory = sqlite3.Row
        # スレッドセーフのための設定
        self._conn.execute("PRAGMA journal_mode=WAL")  # Write-Ahead Logging でスレッドセーフ性を向上
        self._conn.commit()
        self._init_db()
    
    def _init_db(self) -> None:
        """データベーススキーマを初期化する。"""
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS search_metrics (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                query TEXT NOT NULL,
                query_type TEXT,
                use_graph INTEGER NOT NULL DEFAULT 0,
                use_rerank INTEGER NOT NULL DEFAULT 0,
                use_mmr INTEGER NOT NULL DEFAULT 0,
                use_query_expansion INTEGER NOT NULL DEFAULT 0,
                use_evidence_extraction INTEGER NOT NULL DEFAULT 0,
                duration_ms REAL NOT NULL,
                num_results INTEGER NOT NULL,
                mrr REAL,
                ndcg_at_10 REAL,
                precision_at_10 REAL,
                recall_at_10 REAL,
                relevant_chunk_ids TEXT,
                timestamp TEXT NOT NULL
            )
        """)
        
        # 既存DBへのマイグレーション（列追加）。
        # 列が既に存在する場合 ALTER TABLE は OperationalError になるため個別に握る。
        migrations = [
            "ALTER TABLE search_metrics ADD COLUMN use_evidence_extraction INTEGER NOT NULL DEFAULT 0",
            # 段階別の所要時間。duration_ms だけでは遅い段階を特定できないため追加。
            "ALTER TABLE search_metrics ADD COLUMN timing_breakdown TEXT",
        ]
        for stmt in migrations:
            try:
                self._conn.execute(stmt)
                self._conn.commit()
            except sqlite3.OperationalError:
                # カラムが既に存在する場合は想定内なので続行する。
                logger.debug("マイグレーションをスキップしました: %s", stmt)

        # インデックスを作成（クエリパフォーマンス向上）
        self._conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_query_type 
            ON search_metrics(query_type)
        """)
        self._conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_use_graph 
            ON search_metrics(use_graph)
        """)
        self._conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_use_rerank 
            ON search_metrics(use_rerank)
        """)
        self._conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_timestamp 
            ON search_metrics(timestamp)
        """)
        
        self._conn.commit()
    
    def record_search(self, metrics: SearchMetrics) -> None:
        """検索メトリクスを記録する。
        
        Args:
            metrics: 記録する検索メトリクス。
        """
        if metrics.timestamp is None:
            metrics.timestamp = datetime.now(timezone.utc).isoformat()
        
        relevant_chunk_ids_json = None
        if metrics.relevant_chunk_ids:
            relevant_chunk_ids_json = json.dumps(metrics.relevant_chunk_ids)

        timing_breakdown_json = None
        if metrics.timing_breakdown:
            timing_breakdown_json = json.dumps(metrics.timing_breakdown, ensure_ascii=False)

        self._conn.execute("""
            INSERT INTO search_metrics (
                query, query_type, use_graph, use_rerank, use_mmr, use_query_expansion, use_evidence_extraction,
                duration_ms, num_results, mrr, ndcg_at_10, precision_at_10, recall_at_10,
                relevant_chunk_ids, timestamp, timing_breakdown
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            metrics.query,
            metrics.query_type,
            1 if metrics.use_graph else 0,
            1 if metrics.use_rerank else 0,
            1 if metrics.use_mmr else 0,
            1 if metrics.use_query_expansion else 0,
            1 if metrics.use_evidence_extraction else 0,
            metrics.duration_ms,
            metrics.num_results,
            metrics.mrr,
            metrics.ndcg_at_10,
            metrics.precision_at_10,
            metrics.recall_at_10,
            relevant_chunk_ids_json,
            metrics.timestamp,
            timing_breakdown_json,
        ))
        self._conn.commit()
    
    def get_metrics_summary(
        self,
        *,
        use_graph: Optional[bool] = None,
        use_rerank: Optional[bool] = None,
        use_mmr: Optional[bool] = None,
        use_query_expansion: Optional[bool] = None,
        use_evidence_extraction: Optional[bool] = None,
        query_type: Optional[str] = None,
        limit: Optional[int] = None,
    ) -> Dict[str, Any]:
        """メトリクスの集計結果を取得する。
        
        Args:
            use_graph: GraphRAGを使用した検索のみを対象にする。
            use_rerank: リランキングを使用した検索のみを対象にする。
            use_mmr: MMRを使用した検索のみを対象にする。
            use_query_expansion: クエリ拡張を使用した検索のみを対象にする。
            use_evidence_extraction: GraphRAG拡張（根拠情報抽出）を使用した検索のみを対象にする。
            query_type: クエリタイプでフィルタ。
            limit: 集計対象の最大件数。Noneの場合はすべて。
        
        Returns:
            Dict[str, Any]: 集計結果。以下のキーを含みます:
                - count: 記録数
                - avg_duration_ms: 平均レイテンシ（ミリ秒）
                - avg_num_results: 平均結果数
                - avg_mrr: 平均MRR（MRRが記録されている場合のみ）
                - avg_ndcg_at_10: 平均NDCG@10（NDCG@10が記録されている場合のみ）
                - avg_precision_at_10: 平均Precision@10（Precision@10が記録されている場合のみ）
                - avg_recall_at_10: 平均Recall@10（Recall@10が記録されている場合のみ）
        """
        conditions = []
        params = []
        
        if use_graph is not None:
            conditions.append("use_graph = ?")
            params.append(1 if use_graph else 0)
        
        if use_rerank is not None:
            conditions.append("use_rerank = ?")
            params.append(1 if use_rerank else 0)
        
        if use_mmr is not None:
            conditions.append("use_mmr = ?")
            params.append(1 if use_mmr else 0)
        
        if use_query_expansion is not None:
            conditions.append("use_query_expansion = ?")
            params.append(1 if use_query_expansion else 0)
        
        if use_evidence_extraction is not None:
            conditions.append("use_evidence_extraction = ?")
            params.append(1 if use_evidence_extraction else 0)
        
        if query_type is not None:
            conditions.append("query_type = ?")
            params.append(query_type)
        
        where_clause = ""
        if conditions:
            where_clause = "WHERE " + " AND ".join(conditions)
        
        limit_clause = ""
        if limit is not None:
            limit_clause = f"LIMIT {limit}"
        
        query = f"""
            SELECT 
                COUNT(*) as count,
                AVG(duration_ms) as avg_duration_ms,
                AVG(num_results) as avg_num_results,
                AVG(mrr) as avg_mrr,
                AVG(ndcg_at_10) as avg_ndcg_at_10,
                AVG(precision_at_10) as avg_precision_at_10,
                AVG(recall_at_10) as avg_recall_at_10
            FROM search_metrics
            {where_clause}
            {limit_clause}
        """
        
        row = self._conn.execute(query, params).fetchone()
        
        if row is None or row["count"] == 0:
            return {
                "count": 0,
                "avg_duration_ms": 0.0,
                "avg_num_results": 0.0,
                "avg_mrr": None,
                "avg_ndcg_at_10": None,
                "avg_precision_at_10": None,
                "avg_recall_at_10": None,
            }
        
        return {
            "count": row["count"],
            "avg_duration_ms": row["avg_duration_ms"] or 0.0,
            "avg_num_results": row["avg_num_results"] or 0.0,
            "avg_mrr": row["avg_mrr"],
            "avg_ndcg_at_10": row["avg_ndcg_at_10"],
            "avg_precision_at_10": row["avg_precision_at_10"],
            "avg_recall_at_10": row["avg_recall_at_10"],
        }
    
    def get_metrics_by_config(
        self,
        *,
        group_by: List[str] = ["use_graph", "use_rerank"],
    ) -> List[Dict[str, Any]]:
        """設定ごとにメトリクスを集計する。
        
        Args:
            group_by: グループ化するカラム名のリスト。
                デフォルト: ["use_graph", "use_rerank"]
        
        Returns:
            List[Dict[str, Any]]: 設定ごとの集計結果のリスト。
        """
        group_by_clause = ", ".join(group_by)
        
        query = f"""
            SELECT 
                {group_by_clause},
                COUNT(*) as count,
                AVG(duration_ms) as avg_duration_ms,
                AVG(num_results) as avg_num_results,
                AVG(mrr) as avg_mrr,
                AVG(ndcg_at_10) as avg_ndcg_at_10,
                AVG(precision_at_10) as avg_precision_at_10,
                AVG(recall_at_10) as avg_recall_at_10
            FROM search_metrics
            GROUP BY {group_by_clause}
            ORDER BY {group_by_clause}
        """
        
        rows = self._conn.execute(query).fetchall()
        
        results = []
        for row in rows:
            result = {}
            for col in group_by:
                result[col] = bool(row[col]) if isinstance(row[col], int) else row[col]
            result["count"] = row["count"]
            result["avg_duration_ms"] = row["avg_duration_ms"] or 0.0
            result["avg_num_results"] = row["avg_num_results"] or 0.0
            result["avg_mrr"] = row["avg_mrr"]
            result["avg_ndcg_at_10"] = row["avg_ndcg_at_10"]
            result["avg_precision_at_10"] = row["avg_precision_at_10"]
            result["avg_recall_at_10"] = row["avg_recall_at_10"]
            results.append(result)
        
        return results
    
    def close(self) -> None:
        """データベース接続を閉じる。"""
        self._conn.close()
    
    def __enter__(self) -> "MetricsCollector":
        """コンテキストマネージャーとして使用する場合のエントリ。"""
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        """コンテキストマネージャーとして使用する場合のエグジット。"""
        self.close()
