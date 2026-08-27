"""MetricsCollector の記録・マイグレーション。

段階別の所要時間 (timing_breakdown) が保存されることを固定する。
これが失われると、遅い検索がどの段階で時間を使ったのかを後から追跡できない。
"""

import json
import sqlite3

from rag.metrics_collector import MetricsCollector, SearchMetrics

TIMING = {
    "ms_vector": 120,
    "ms_semantic": 80,
    "ms_rerank": 45000,
    "ms_graph_rerank": 6000,
    "duration_ms": 51200,
}


def test_record_search_persists_timing_breakdown(tmp_path):
    """timing_breakdown が JSON として保存され、読み戻せる。"""
    db = tmp_path / "metrics.db"
    collector = MetricsCollector(db_path=db)
    collector.record_search(
        SearchMetrics(
            query="initial node start; は書き方あってる？",
            use_graph=True,
            use_rerank=True,
            duration_ms=51200,
            num_results=15,
            timing_breakdown=TIMING,
        )
    )

    conn = sqlite3.connect(str(db))
    row = conn.execute("SELECT timing_breakdown FROM search_metrics").fetchone()
    conn.close()

    assert row[0] is not None, "timing_breakdown が保存されていない"
    assert json.loads(row[0]) == TIMING


def test_record_search_without_timing_breakdown(tmp_path):
    """timing_breakdown 未指定でも記録できる（後方互換）。"""
    db = tmp_path / "metrics.db"
    collector = MetricsCollector(db_path=db)
    collector.record_search(SearchMetrics(query="q", duration_ms=1.0, num_results=1))

    conn = sqlite3.connect(str(db))
    row = conn.execute("SELECT timing_breakdown, duration_ms FROM search_metrics").fetchone()
    conn.close()

    assert row[0] is None
    assert row[1] == 1.0


def test_migration_adds_column_to_existing_db(tmp_path):
    """timing_breakdown 列を持たない既存DBを開いても壊れず、列が追加される。"""
    db = tmp_path / "legacy.db"
    conn = sqlite3.connect(str(db))
    conn.execute("""
        CREATE TABLE search_metrics (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            query TEXT NOT NULL,
            query_type TEXT,
            use_graph INTEGER NOT NULL DEFAULT 0,
            use_rerank INTEGER NOT NULL DEFAULT 0,
            use_mmr INTEGER NOT NULL DEFAULT 0,
            use_query_expansion INTEGER NOT NULL DEFAULT 0,
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
    conn.execute(
        "INSERT INTO search_metrics (query, duration_ms, num_results, timestamp)"
        " VALUES ('old', 10.0, 3, '2026-01-01T00:00:00')"
    )
    conn.commit()
    conn.close()

    collector = MetricsCollector(db_path=db)
    collector.record_search(
        SearchMetrics(query="new", duration_ms=2.0, num_results=1, timing_breakdown=TIMING)
    )

    conn = sqlite3.connect(str(db))
    cols = {r[1] for r in conn.execute("PRAGMA table_info(search_metrics)")}
    rows = conn.execute(
        "SELECT query, timing_breakdown FROM search_metrics ORDER BY id"
    ).fetchall()
    conn.close()

    assert "timing_breakdown" in cols
    assert "use_evidence_extraction" in cols
    # 既存行は保持され、新しい行だけ内訳を持つ
    assert rows[0][0] == "old" and rows[0][1] is None
    assert rows[1][0] == "new" and json.loads(rows[1][1]) == TIMING


def test_init_is_idempotent(tmp_path):
    """同じDBを2回開いてもマイグレーションが失敗しない。"""
    db = tmp_path / "metrics.db"
    MetricsCollector(db_path=db).record_search(
        SearchMetrics(query="a", duration_ms=1.0, num_results=1)
    )
    MetricsCollector(db_path=db).record_search(
        SearchMetrics(query="b", duration_ms=1.0, num_results=1)
    )

    conn = sqlite3.connect(str(db))
    n = conn.execute("SELECT COUNT(*) FROM search_metrics").fetchone()[0]
    conn.close()
    assert n == 2
