"""メタデータストアモジュール。

このモジュールは、SQLite3 + FTS5を使用したメタデータ管理と
全文検索機能を提供します。
"""

from __future__ import annotations

import sqlite3
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence

from .config import SQLITE_PATH


@dataclass
class ChunkMetadata:
    """RDBに保持するチャンク1件分のメタデータ。

    Attributes:
        id: データベース内の自動採番ID。
        chunk_id: チャンクの一意識別子（通常は ``document_id::chunk-{index}`` 形式）。
        file_name: 元ファイル名。
        file_path: 元ファイルの絶対パス。
        file_type: ファイル種別（"txt", "md", "pdf" のいずれか）。
        chunk_text: チャンクのテキスト内容。
        chunk_index: チャンクのインデックス（0始まり）。
        page_number: PDFの場合のページ番号（1始まり）。それ以外はNone。
        created_at: 作成日時（ISO形式文字列）。
        updated_at: 更新日時（ISO形式文字列）。
    """

    id: int
    chunk_id: str
    file_name: str
    file_path: str
    file_type: str
    chunk_text: str
    chunk_index: int
    page_number: Optional[int]
    created_at: str
    updated_at: str
    # semantic_search の bm25(chunks_fts) を格納（小さいほど関連度が高い）
    bm25_score: Optional[float] = None
    # 章/節などの構造メタデータ（ステップ2で追加）
    section_id: Optional[str] = None
    section_title: Optional[str] = None
    # チャンク種別（例: "text", "sysml_code"）
    chunk_kind: Optional[str] = None
    # コードチャンクの場合の言語（例: "sysml"）
    code_language: Optional[str] = None


class MetadataStore:
    """SQLite3 + FTS5 を用いたメタデータ・セマンティック検索用ストア。

    メタ検索: 通常のWHERE句でファイル名や種別などを絞り込み
    セマンティック検索: FTS5のMATCH句で全文検索

    Attributes:
        _conn: SQLite3接続オブジェクト。
    """

    def __init__(self, db_path: Optional[Path | str] = None) -> None:
        """MetadataStoreを初期化する。

        Args:
            db_path: SQLiteデータベースファイルのパス。
                Noneの場合は ``config.SQLITE_PATH`` を使用。
        """
        path = Path(db_path or SQLITE_PATH)
        path.parent.mkdir(parents=True, exist_ok=True)
        self._db_path = path
        # check_same_thread=False でスレッド間共有を許可（並列検索対応）
        # timeout=5.0 でロック待機時間を設定
        self._conn = sqlite3.connect(
            str(path),
            check_same_thread=False,
            timeout=5.0,
        )
        self._conn.row_factory = sqlite3.Row
        # WAL モードを有効化（並行読み取り性能向上）
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.commit()
        self._ensure_schema()
        # semantic_search 用にスレッドローカル接続を使う（同一接続を別スレッドで触らないため）
        self._tls = threading.local()

    def _get_thread_conn(self) -> sqlite3.Connection:
        """スレッドローカルのSQLite接続を返す（主にsemantic_search用）。"""
        conn = getattr(self._tls, "conn", None)
        if conn is None:
            conn = sqlite3.connect(
                str(self._db_path),
                check_same_thread=False,
                timeout=5.0,
            )
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode=WAL")
            conn.commit()
            self._tls.conn = conn
        return conn

    # ------------------------------------------------------------------ #
    # スキーマ
    # ------------------------------------------------------------------ #
    def _ensure_schema(self) -> None:
        cur = self._conn.cursor()

        # メインテーブル
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS chunks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chunk_id TEXT UNIQUE,
                file_name TEXT NOT NULL,
                file_path TEXT NOT NULL,
                file_type TEXT NOT NULL,
                chunk_text TEXT NOT NULL,
                chunk_index INTEGER NOT NULL,
                page_number INTEGER,
                section_id TEXT,
                section_title TEXT,
                chunk_kind TEXT,
                code_language TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )

        # FTS5仮想テーブル（chunk_text を対象とした全文検索）
        cur.execute(
            """
            CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts
            USING fts5(
                chunk_text,
                chunk_id UNINDEXED,
                content='',
                tokenize='unicode61'
            )
            """
        )

        # メタ情報検索のためのインデックス
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_chunks_file_path ON chunks(file_path)"
        )
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_chunks_file_name ON chunks(file_name)"
        )
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_chunks_file_type ON chunks(file_type)"
        )
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_chunks_chunk_id ON chunks(chunk_id)"
        )

        # 既存DBへのマイグレーション（列追加）
        cur.execute("PRAGMA table_info(chunks)")
        existing_cols = {r[1] for r in cur.fetchall()}  # 1: name
        for col_name, col_type in [
            ("section_id", "TEXT"),
            ("section_title", "TEXT"),
            ("chunk_kind", "TEXT"),
            ("code_language", "TEXT"),
        ]:
            if col_name not in existing_cols:
                cur.execute(f"ALTER TABLE chunks ADD COLUMN {col_name} {col_type}")

        self._conn.commit()

    # ------------------------------------------------------------------ #
    # 挿入・更新
    # ------------------------------------------------------------------ #
    def insert_chunk(
        self,
        *,
        chunk_id: str,
        file_name: str,
        file_path: str,
        file_type: str,
        chunk_text: str,
        chunk_index: int,
        page_number: Optional[int] = None,
        section_id: Optional[str] = None,
        section_title: Optional[str] = None,
        chunk_kind: Optional[str] = None,
        code_language: Optional[str] = None,
    ) -> int:
        """チャンク1件を登録する。

        Args:
            chunk_id: チャンクの一意識別子。
            file_name: ファイル名。
            file_path: ファイルの絶対パス。
            file_type: ファイル種別（"txt", "md", "pdf"）。
            chunk_text: チャンクのテキスト内容。
            chunk_index: チャンクのインデックス（0始まり）。
            page_number: PDFの場合のページ番号（1始まり）。オプション。

        Returns:
            int: データベース内の自動採番ID。

        Raises:
            sqlite3.IntegrityError: chunk_idが既に存在する場合。
        """
        now = datetime.now(timezone.utc).isoformat()
        cur = self._conn.cursor()
        cur.execute(
            """
            INSERT INTO chunks (
                chunk_id, file_name, file_path, file_type,
                chunk_text, chunk_index, page_number,
                section_id, section_title, chunk_kind, code_language,
                created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                chunk_id,
                file_name,
                file_path,
                file_type,
                chunk_text,
                chunk_index,
                page_number,
                section_id,
                section_title,
                chunk_kind,
                code_language,
                now,
                now,
            ),
        )
        row_id = cur.lastrowid

        # FTS5 にも登録
        cur.execute(
            "INSERT INTO chunks_fts (rowid, chunk_text, chunk_id) VALUES (?, ?, ?)",
            (row_id, chunk_text, chunk_id),
        )

        self._conn.commit()
        return row_id

    def bulk_insert_chunks(
        self,
        records: Sequence[Dict[str, Any]],
    ) -> None:
        """複数チャンクをまとめて登録する。

        records の各要素は ``insert_chunk`` と同じキーを持つ dict を想定します。
        バッチサイズ500件ずつ処理されます。

        Args:
            records: チャンク情報の辞書のシーケンス。
                各辞書には以下のキーが必要:
                - chunk_id: str
                - file_name: str
                - file_path: str
                - file_type: str
                - chunk_text: str
                - chunk_index: int
                - page_number: Optional[int]（オプション）

        Raises:
            sqlite3.IntegrityError: chunk_idが既に存在する場合。
        """
        if not records:
            return

        now = datetime.now(timezone.utc).isoformat()
        cur = self._conn.cursor()

        # 非常に大きなドキュメントでもメモリ使用量を抑えつつ処理できるよう、
        # シンプルなバッチループにしている（トランザクションはこの関数全体で1つ）。
        # 例外発生時はロールバックして「部分的な書き込み」を残さない。
        try:
            BATCH_SIZE = 500
            for start in range(0, len(records), BATCH_SIZE):
                batch = records[start : start + BATCH_SIZE]
                for rec in batch:
                    cur.execute(
                        """
                        INSERT INTO chunks (
                            chunk_id, file_name, file_path, file_type,
                            chunk_text, chunk_index, page_number,
                            section_id, section_title, chunk_kind, code_language,
                            created_at, updated_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            rec["chunk_id"],
                            rec["file_name"],
                            rec["file_path"],
                            rec["file_type"],
                            rec["chunk_text"],
                            rec["chunk_index"],
                            rec.get("page_number"),
                            rec.get("section_id"),
                            rec.get("section_title"),
                            rec.get("chunk_kind"),
                            rec.get("code_language"),
                            now,
                            now,
                        ),
                    )
                    row_id = cur.lastrowid
                    cur.execute(
                        "INSERT INTO chunks_fts (rowid, chunk_text, chunk_id) VALUES (?, ?, ?)",
                        (row_id, rec["chunk_text"], rec["chunk_id"]),
                    )
        except Exception:
            # commit前の例外でも、コネクションが中途半端なトランザクション状態になるのを防ぐ
            self._conn.rollback()
            raise
        else:
            self._conn.commit()

    # ------------------------------------------------------------------ #
    # メタ検索
    # ------------------------------------------------------------------ #
    def meta_search(
        self,
        *,
        file_name: Optional[str] = None,
        file_path: Optional[str] = None,
        file_type: Optional[str] = None,
        page_number: Optional[int] = None,
        min_updated_at: Optional[str] = None,
        max_updated_at: Optional[str] = None,
        limit: int = 10,
    ) -> List[ChunkMetadata]:
        """メタ情報に基づく検索を実行する。

        ファイル名・種別・更新日時範囲などでフィルタリングします。

        Args:
            file_name: ファイル名でフィルタ（完全一致）。
            file_path: ファイルパスでフィルタ（完全一致）。
            file_type: ファイル種別でフィルタ（"txt", "md", "pdf", "docx", "xlsx", "pptx"）。
            page_number: ページ番号でフィルタ（PDFの場合）。
            min_updated_at: 最小更新日時（ISO形式文字列）。
            max_updated_at: 最大更新日時（ISO形式文字列）。
            limit: 返す結果の最大件数（デフォルト: 10）。

        Returns:
            List[ChunkMetadata]: 検索結果のリスト。
                更新日時の降順、IDの昇順でソートされます。

        Example:
            >>> store = MetadataStore()
            >>> results = store.meta_search(file_type="pdf", limit=5)
            >>> print(len(results))
            5
        """
        clauses: List[str] = []
        params: List[Any] = []

        if file_name:
            clauses.append("file_name = ?")
            params.append(file_name)
        if file_path:
            clauses.append("file_path = ?")
            params.append(file_path)
        if file_type:
            clauses.append("file_type = ?")
            params.append(file_type)
        if page_number is not None:
            clauses.append("page_number = ?")
            params.append(page_number)
        if min_updated_at:
            clauses.append("updated_at >= ?")
            params.append(min_updated_at)
        if max_updated_at:
            clauses.append("updated_at <= ?")
            params.append(max_updated_at)

        where_sql = "WHERE " + " AND ".join(clauses) if clauses else ""
        sql = f"""
            SELECT *
            FROM chunks
            {where_sql}
            ORDER BY updated_at DESC, id ASC
            LIMIT ?
        """
        params.append(limit)

        cur = self._conn.cursor()
        cur.execute(sql, params)
        rows = cur.fetchall()
        return [self._row_to_metadata(r) for r in rows]

    # ------------------------------------------------------------------ #
    # セマンティック検索（FTS5）
    # ------------------------------------------------------------------ #
    def semantic_search(
        self,
        query: str,
        *,
        limit: int = 10,
    ) -> List[ChunkMetadata]:
        """FTS5 を用いた全文検索（セマンティック検索）を実行する。

        Args:
            query: 検索クエリ文字列。
            limit: 返す結果の最大件数（デフォルト: 10）。

        Returns:
            List[ChunkMetadata]: 検索結果のリスト。

        Example:
            >>> store = MetadataStore()
            >>> results = store.semantic_search("Python", limit=10)
            >>> print(len(results))
            10
        """
        # 並列実行時に「同じ connection を別スレッドから触る」事故を避けるため、
        # semantic_search はスレッドローカル接続を使用する。
        cur = self._get_thread_conn().cursor()

        q = (query or "").strip()
        if not q:
            return []

        # 以前は「常にフレーズ検索（"..."）」にしていたが、
        # - 改行/句読点を跨ぐとヒットしにくい
        # - 記号を含む（例: "python mcp_server.py"）と tokenizer 次第でヒットしない
        # ため、デフォルトはトークン検索（AND）に寄せる。
        #
        # 呼び出し側が高度な FTS クエリ（OR/AND/NEAR, "..." など）を渡した場合はそのまま使う。
        looks_advanced = any(tok in q for tok in ['"', " OR ", " AND ", " NEAR ", "*", ":", "NOT "])
        fts_query = q if looks_advanced else q
        # FTS結果と実テーブルをJOINしてメタ情報を取得
        # SQLite/FTS5 では MATCH 句にテーブル別名を使えない実装があるため、
        # 元のテーブル名 chunks_fts に対して MATCH を指定する。
        try:
            cur.execute(
                """
                SELECT c.*, bm25(chunks_fts) AS bm25_score
                FROM chunks_fts AS f
                JOIN chunks AS c ON c.id = f.rowid
                WHERE chunks_fts MATCH ?
                ORDER BY bm25(chunks_fts) ASC
                LIMIT ?
                """,
                (fts_query, limit),
            )
            rows = cur.fetchall()
            if rows:
                return [self._row_to_metadata(r) for r in rows]
        except sqlite3.OperationalError:
            # クエリが FTS 構文として解釈できないケース（例: ハイフンを含む語が列指定扱いになる等）
            # はフォールバックへ回す。
            pass

        # フォールバック: tokenizer の都合で FTS がヒットしない場合がある（特に日本語/記号混在）。
        # 回帰テストやデバッグ用途では「何も返らない」より有用なので、
        # 0件の場合は substring 検索で補う（スコアは付かない）。
        like = f"%{q}%"
        cur.execute(
            """
            SELECT *
            FROM chunks
            WHERE chunk_text LIKE ?
            ORDER BY updated_at DESC, id ASC
            LIMIT ?
            """,
            (like, limit),
        )
        rows = cur.fetchall()
        return [self._row_to_metadata(r) for r in rows]

    # ------------------------------------------------------------------ #
    # 削除
    # ------------------------------------------------------------------ #
    def delete_by_chunk_ids(self, chunk_ids: Iterable[str]) -> None:
        """指定したchunk_idのレコードを削除する。

        chunksテーブルとchunks_ftsテーブルの両方から削除します。
        FTS5のcontentlessテーブルの場合、メインテーブルから削除すると
        自動的にFTSテーブルからも削除されます。

        Args:
            chunk_ids: 削除対象のchunk_idのイテラブル。
        """
        ids = list(chunk_ids)
        if not ids:
            return
        cur = self._conn.cursor()
        # rowid を取得してからメインテーブルから削除
        # contentless FTS5テーブルの場合、メインテーブルから削除すると
        # 自動的にFTSテーブルからも削除される
        cur.execute(
            f"SELECT id, chunk_id FROM chunks WHERE chunk_id IN ({','.join('?' for _ in ids)})",
            ids,
        )
        rows = cur.fetchall()
        row_ids = [r["id"] for r in rows]

        if row_ids:
            # メインテーブルから削除（FTSテーブルは自動的に削除される）
            cur.execute(
                f"DELETE FROM chunks WHERE id IN ({','.join('?' for _ in row_ids)})",
                row_ids,
            )
        self._conn.commit()

    # ------------------------------------------------------------------ #
    # 参照（コンテキスト補完用）
    # ------------------------------------------------------------------ #
    def get_chunk_by_chunk_id(self, chunk_id: str) -> Optional[ChunkMetadata]:
        """chunk_id からチャンクを1件取得する。

        軽量GraphRAGで近傍チャンクの実体を取得する際に使用します。

        Args:
            chunk_id: 取得対象のchunk_id（通常は `document_id::chunk-{index}` 形式）。

        Returns:
            ChunkMetadata | None: 見つかった場合はChunkMetadata、存在しない場合はNone。

        Example:
            >>> store = MetadataStore()
            >>> chunk = store.get_chunk_by_chunk_id("E:/doc.pdf::chunk-5")
            >>> if chunk:
            ...     print(chunk.chunk_text[:100])
        """
        cur = self._conn.cursor()
        cur.execute("SELECT * FROM chunks WHERE chunk_id = ? LIMIT 1", (chunk_id,))
        row = cur.fetchone()
        return self._row_to_metadata(row) if row else None

    def get_chunks_by_chunk_ids(self, chunk_ids: Sequence[str]) -> List[ChunkMetadata]:
        """chunk_id のリストからチャンクを取得する（入力順を維持）。

        軽量GraphRAGで複数の近傍チャンクの実体を一括取得する際に使用します。
        存在しないchunk_idは無視され、入力順が維持されます。

        Args:
            chunk_ids: 取得対象のchunk_idリスト。

        Returns:
            List[ChunkMetadata]: 取得できたチャンクのリスト（入力順）。
                存在しないchunk_idは結果に含まれません。

        Example:
            >>> store = MetadataStore()
            >>> ids = ["E:/doc.pdf::chunk-5", "E:/doc.pdf::chunk-6", "E:/doc.pdf::chunk-7"]
            >>> chunks = store.get_chunks_by_chunk_ids(ids)
            >>> print(len(chunks))
            3
        """
        ids = [c for c in chunk_ids if c]
        if not ids:
            return []

        cur = self._conn.cursor()
        cur.execute(
            f"SELECT * FROM chunks WHERE chunk_id IN ({','.join('?' for _ in ids)})",
            ids,
        )
        rows = cur.fetchall()
        by_id: Dict[str, ChunkMetadata] = {r["chunk_id"]: self._row_to_metadata(r) for r in rows}
        return [by_id[c] for c in ids if c in by_id]

    def get_chunks_by_file_and_index_range(
        self,
        *,
        file_path: str,
        start_index: int,
        end_index: int,
    ) -> List[ChunkMetadata]:
        """指定ファイルの chunk_index 範囲のチャンクを取得する（昇順）。"""
        cur = self._conn.cursor()
        cur.execute(
            """
            SELECT *
            FROM chunks
            WHERE file_path = ?
              AND chunk_index BETWEEN ? AND ?
            ORDER BY chunk_index ASC, id ASC
            """,
            (file_path, start_index, end_index),
        )
        rows = cur.fetchall()
        return [self._row_to_metadata(r) for r in rows]

    # ------------------------------------------------------------------ #
    # ユーティリティ
    # ------------------------------------------------------------------ #
    def _row_to_metadata(self, row: sqlite3.Row) -> ChunkMetadata:
        """SQLiteのRowオブジェクトをChunkMetadataに変換する。

        Args:
            row: SQLite3のRowオブジェクト。

        Returns:
            ChunkMetadata: 変換されたメタデータオブジェクト。
        """
        bm25_score: Optional[float] = None
        try:
            if "bm25_score" in row.keys():
                v = row["bm25_score"]
                bm25_score = float(v) if v is not None else None
        except (IndexError, TypeError, ValueError):
            bm25_score = None

        def _get_if_present(key: str) -> Optional[str]:
            try:
                if key in row.keys():
                    v = row[key]
                    return str(v) if v is not None else None
            except (IndexError, TypeError):
                return None
            return None

        return ChunkMetadata(
            id=row["id"],
            chunk_id=row["chunk_id"],
            file_name=row["file_name"],
            file_path=row["file_path"],
            file_type=row["file_type"],
            chunk_text=row["chunk_text"],
            chunk_index=row["chunk_index"],
            page_number=row["page_number"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            bm25_score=bm25_score,
            section_id=_get_if_present("section_id"),
            section_title=_get_if_present("section_title"),
            chunk_kind=_get_if_present("chunk_kind"),
            code_language=_get_if_present("code_language"),
        )

    def close(self) -> None:
        """データベース接続を閉じる。

        使用後は必ず呼び出すことを推奨します。
        """
        self._conn.close()



