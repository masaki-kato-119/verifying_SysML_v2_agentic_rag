"""
SQLite3ベースのチャンクストレージ管理
"""
import hashlib
import logging
import sqlite3
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from .config import CHUNKS_DB_PATH, PROJECT_ROOT

logger = logging.getLogger(__name__)


class ChunkStorage:
    """
    SQLite3ベースのチャンクストレージ
    
    チャンク、ノード-チャンク、エッジ-チャンクの関連を管理
    """
    
    def __init__(self, db_path: Optional[str] = None):
        """
        チャンクストレージを初期化

        Args:
            db_path: SQLite3データベースファイルのパス。
                省略時は GraphRAG/data/chunks.db（cwd に依存しない）。
        """
        self.db_path = Path(db_path) if db_path is not None else CHUNKS_DB_PATH
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_database()
    
    def _init_database(self):
        """データベースとテーブルを初期化"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                
                # graphs テーブル
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS graphs (
                        graph_id TEXT PRIMARY KEY,
                        graph_filepath TEXT NOT NULL,
                        document_name TEXT,
                        node_count INTEGER DEFAULT 0,
                        edge_count INTEGER DEFAULT 0,
                        chunk_count INTEGER DEFAULT 0,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                """)
                
                # 既存のテーブルにdocument_nameカラムを追加（マイグレーション）
                try:
                    cursor.execute("ALTER TABLE graphs ADD COLUMN document_name TEXT")
                except sqlite3.OperationalError:
                    # カラムが既に存在する場合は無視
                    pass
                
                # chunks テーブル（複合主キー: graph_id, chunk_id）
                # 既存のテーブルがある場合は削除しない（既存データを保護）
                # 注意: DROP TABLE IF EXISTS chunks を削除し、CREATE TABLE IF NOT EXISTS を使用
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS chunks (
                        graph_id TEXT NOT NULL,
                        chunk_id TEXT NOT NULL,
                        chunk_text TEXT NOT NULL,
                        chunk_index INTEGER NOT NULL,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        PRIMARY KEY (graph_id, chunk_id),
                        FOREIGN KEY (graph_id) REFERENCES graphs(graph_id)
                    )
                """)
                
                # 既存のテーブルに必要なカラムが存在するか確認（マイグレーション）
                cursor.execute("PRAGMA table_info(chunks)")
                columns = {row[1] for row in cursor.fetchall()}
                if 'chunk_index' not in columns:
                    try:
                        cursor.execute("ALTER TABLE chunks ADD COLUMN chunk_index INTEGER NOT NULL DEFAULT 0")
                        logger.info("_init_database: chunksテーブルにchunk_indexカラムを追加しました")
                    except sqlite3.OperationalError:
                        # カラムが既に存在する場合は無視
                        pass
                
                # node_chunks テーブル
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS node_chunks (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        graph_id TEXT NOT NULL,
                        node_name TEXT NOT NULL,
                        chunk_id TEXT NOT NULL,
                        FOREIGN KEY (graph_id) REFERENCES graphs(graph_id),
                        FOREIGN KEY (chunk_id) REFERENCES chunks(chunk_id),
                        UNIQUE(graph_id, node_name, chunk_id)
                    )
                """)
                
                # edge_chunks テーブル
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS edge_chunks (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        graph_id TEXT NOT NULL,
                        source TEXT NOT NULL,
                        target TEXT NOT NULL,
                        chunk_id TEXT NOT NULL,
                        FOREIGN KEY (graph_id) REFERENCES graphs(graph_id),
                        FOREIGN KEY (chunk_id) REFERENCES chunks(chunk_id),
                        UNIQUE(graph_id, source, target, chunk_id)
                    )
                """)
                
                # インデックス作成
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_chunks_graph_id ON chunks(graph_id)")
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_chunks_graph_index ON chunks(graph_id, chunk_index)")
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_node_chunks_graph_node ON node_chunks(graph_id, node_name)")
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_node_chunks_chunk ON node_chunks(chunk_id)")
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_edge_chunks_graph_edge ON edge_chunks(graph_id, source, target)")
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_edge_chunks_chunk ON edge_chunks(chunk_id)")
                
                conn.commit()
        except Exception as e:
            logger.error(f"データベース初期化エラー: {self.db_path}, error={str(e)}")
            raise
    
    def _normalize_to_relative_path(self, filepath: str) -> str:
        """
        ファイルパスを相対パスに正規化（プロジェクトルート基準）
        
        Args:
            filepath: ファイルパス（絶対パスまたは相対パス）
            
        Returns:
            str: 正規化された相対パス（スラッシュ区切り）
        """
        path = Path(filepath)

        # 絶対パスの場合は相対パスに変換
        if path.is_absolute():
            try:
                # パスを解決してから相対パスに変換（大文字小文字やドライブ文字の違いを吸収）
                resolved_path = path.resolve()
                # プロジェクトルート（GraphRAG/）からの相対パスに変換する。
                # cwd 基準にすると起動ディレクトリ次第で DB に別表記が混ざるため、
                # 保存済みレコード（data/graphs/xxx.pkl）と一致しなくなる。
                relative_path = resolved_path.relative_to(PROJECT_ROOT)
            except ValueError:
                # プロジェクトルートの外にある場合は、ファイル名部分のみを使用
                # データベースに保存されているパス形式（data/graphs/{ファイル名}）に合わせる
                file_name = path.name
                if file_name.endswith('.pkl'):
                    # data/graphs/{ファイル名}の形式に変換
                    relative_path = Path(f"data/graphs/{file_name}")
                else:
                    # 絶対パスをそのまま使用
                    relative_path = path
        else:
            # 既に相対パスの場合はそのまま
            relative_path = path
        
        # スラッシュに統一（Windowsのバックスラッシュをスラッシュに）
        normalized = str(relative_path).replace('\\', '/')
        
        # デバッグ: 正規化結果をログに出力
        if path.is_absolute() and normalized != str(relative_path).replace('\\', '/'):
            logger.debug(f"パス正規化: {filepath} -> {normalized}")
        
        return normalized
    
    def get_graph_id(self, graph_filepath: str) -> str:
        """
        グラフファイルパスからグラフIDを生成
        
        Args:
            graph_filepath: グラフファイルのパス
            
        Returns:
            str: グラフID（ハッシュ値）
        """
        # 相対パスに正規化してからハッシュを生成
        normalized_path = self._normalize_to_relative_path(graph_filepath)
        return hashlib.md5(normalized_path.encode()).hexdigest()
    
    def find_graph_id_by_path(self, graph_filepath: str) -> Optional[str]:
        """
        ファイルパスから既存のグラフIDを検索（削除機能用）
        
        Args:
            graph_filepath: グラフファイルのパス
            
        Returns:
            Optional[str]: 見つかったグラフID、見つからない場合はNone
        """
        # 正規化されたパスでグラフIDを生成
        normalized_path = self._normalize_to_relative_path(graph_filepath)
        graph_id = hashlib.md5(normalized_path.encode()).hexdigest()
        
        # データベースに存在するか確認
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT graph_id FROM graphs WHERE graph_id = ?", (graph_id,))
            if cursor.fetchone():
                return graph_id
        
        return None
    
    def register_graph(self, graph_filepath: str, document_name: Optional[str] = None, node_count: int = 0, edge_count: int = 0) -> str:
        """
        グラフを登録
        
        Args:
            graph_filepath: グラフファイルのパス
            document_name: ドキュメント名（ファイル名など）
            node_count: ノード数
            edge_count: エッジ数
            
        Returns:
            str: グラフID
        """
        # テーブルが存在するか確認（防御的プログラミング）
        # 注意: chunksテーブルが存在する場合は再初期化しない（既存データを保護）
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='graphs'")
                graphs_exists = cursor.fetchone() is not None
                
                cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='chunks'")
                chunks_exists = cursor.fetchone() is not None
                
                if not graphs_exists:
                    logger.warning(f"register_graph: graphsテーブルが存在しません。再初期化します: {self.db_path}")
                    import traceback
                    logger.warning(f"register_graph: 呼び出しスタック:\n{''.join(traceback.format_stack())}")
                    self._init_database()
                elif not chunks_exists:
                    # graphsテーブルは存在するが、chunksテーブルが存在しない場合
                    # これは異常な状態なので、再初期化する
                    logger.warning(f"register_graph: chunksテーブルが存在しません。再初期化します: {self.db_path}")
                    import traceback
                    logger.warning(f"register_graph: 呼び出しスタック:\n{''.join(traceback.format_stack())}")
                    self._init_database()
                # 両方のテーブルが存在する場合は、再初期化しない（既存データを保護）
        except sqlite3.Error as e:
            logger.error(f"register_graph: テーブル存在確認エラー: {self.db_path}, error={str(e)}")
            # 再初期化を試みる
            try:
                logger.warning(f"register_graph: 例外処理から再初期化を試みます: {self.db_path}")
                import traceback
                logger.warning(f"register_graph: 呼び出しスタック:\n{''.join(traceback.format_stack())}")
                self._init_database()
            except sqlite3.Error as init_error:
                logger.error(f"データベース再初期化エラー: {self.db_path}, error={str(init_error)}")
                raise
        
        # 相対パスに正規化（保存時と読み込み時で同じIDになるように）
        normalized_path = self._normalize_to_relative_path(graph_filepath)
        graph_id = self.get_graph_id(normalized_path)
        
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            # 正規化された相対パスを保存（将来の参照用）
            cursor.execute("""
                INSERT OR REPLACE INTO graphs 
                (graph_id, graph_filepath, document_name, node_count, edge_count, updated_at)
                VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            """, (graph_id, normalized_path, document_name, node_count, edge_count))
            conn.commit()
        
        logger.info(f"グラフを登録: {graph_filepath} -> {graph_id}, document_name={document_name}")
        return graph_id
    
    def save_chunks(self, graph_id: str, chunks: Dict[str, str], batch_size: int = 1000) -> None:
        """
        チャンクを一括保存（バッチ処理、メモリ最適化）
        
        Args:
            graph_id: グラフID
            chunks: chunk_id -> chunk_text のマッピング
            batch_size: バッチサイズ（メモリ使用量を制限するため、デフォルト1000）
        """
        if not chunks:
            logger.warning(f"save_chunks: chunksが空です。graph_id={graph_id}")
            return
        
        logger.info(f"save_chunks開始: graph_id={graph_id}, chunks数={len(chunks)}, batch_size={batch_size}")
        
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                
                # 既存のチャンクを削除（再構築時）
                # 注意: この処理は、既にチャンクが存在する場合のみ実行する
                cursor.execute("SELECT COUNT(*) FROM chunks WHERE graph_id = ?", (graph_id,))
                existing_count = cursor.fetchone()[0]
                if existing_count > 0:
                    logger.warning(f"save_chunks: 既存のチャンクを削除します（DELETE FROM chunks WHERE graph_id = ?）, 削除前のチャンク数={existing_count}, graph_id={graph_id}, db_path={self.db_path}")
                    import traceback
                    logger.warning(f"save_chunks: 呼び出しスタック:\n{''.join(traceback.format_stack())}")
                    cursor.execute("DELETE FROM chunks WHERE graph_id = ?", (graph_id,))
                    deleted_count = cursor.rowcount
                    logger.warning(f"save_chunks: 既存のチャンクを削除しました: {deleted_count}件, graph_id={graph_id}, db_path={self.db_path}")
                else:
                    logger.debug(f"既存のチャンクなし（新規保存）, graph_id={graph_id}")
                
                # バッチ処理で挿入（メモリ使用量を制限）
                total_chunks = len(chunks)
                chunk_items = list(chunks.items())
                saved_count = 0
                
                for i in range(0, total_chunks, batch_size):
                    batch = chunk_items[i:i + batch_size]
                    chunk_data = []
                    
                    for chunk_id, chunk_text in batch:
                        # chunk_index を抽出（chunk_0 -> 0）
                        try:
                            chunk_index = int(chunk_id.split('_')[1])
                        except (IndexError, ValueError):
                            chunk_index = 0
                        
                        chunk_data.append((graph_id, chunk_id, chunk_text, chunk_index))
                    
                    if chunk_data:
                        cursor.executemany("""
                            INSERT INTO chunks (graph_id, chunk_id, chunk_text, chunk_index)
                            VALUES (?, ?, ?, ?)
                        """, chunk_data)
                        saved_count += len(chunk_data)
                        
                        # バッチごとにコミット（メモリを解放）
                        conn.commit()
                        
                        # デバッグ: 保存後の確認
                        cursor.execute("SELECT COUNT(*) FROM chunks WHERE graph_id = ?", (graph_id,))
                        after_commit_count = cursor.fetchone()[0]
                        logger.debug(f"save_chunks: バッチ {i//batch_size + 1} 保存後、DB内のチャンク数={after_commit_count}, graph_id={graph_id}")
                        
                        # 進捗ログ（大きなバッチの場合）
                        if total_chunks > batch_size * 2:
                            logger.debug(f"チャンク保存進捗: {saved_count}/{total_chunks} ({saved_count*100//total_chunks}%)")
                
                # チャンク数を更新
                cursor.execute("""
                    UPDATE graphs SET chunk_count = ? WHERE graph_id = ?
                """, (total_chunks, graph_id))
                conn.commit()
                
                # 保存後の確認（同一トランザクション内）
                cursor.execute("SELECT COUNT(*) FROM chunks WHERE graph_id = ?", (graph_id,))
                actual_count = cursor.fetchone()[0]
                
                if actual_count != total_chunks:
                    logger.error(f"チャンク保存エラー: 保存数が一致しません。期待: {total_chunks}, 実際: {actual_count}, graph_id={graph_id}")
                    raise ValueError(f"チャンク保存エラー: 保存数が一致しません。期待: {total_chunks}, 実際: {actual_count}")
                
                logger.info(f"チャンクを保存: {total_chunks}チャンク, graph_id={graph_id}, 確認済み: {actual_count}件")
                
                # 別の接続で再確認（確実に保存されているか確認）
                try:
                    with sqlite3.connect(self.db_path) as verify_conn:
                        verify_cursor = verify_conn.cursor()
                        verify_cursor.execute("SELECT COUNT(*) FROM chunks WHERE graph_id = ?", (graph_id,))
                        verify_count = verify_cursor.fetchone()[0]
                        if verify_count != total_chunks:
                            logger.error(f"チャンク保存検証エラー: 別接続での確認で保存数が一致しません。期待: {total_chunks}, 実際: {verify_count}, graph_id={graph_id}, db_path={self.db_path}")
                            raise ValueError(f"チャンク保存検証エラー: 別接続での確認で保存数が一致しません。期待: {total_chunks}, 実際: {verify_count}")
                        logger.info(f"チャンク保存検証: 別接続での確認完了, {verify_count}チャンク, graph_id={graph_id}, db_path={self.db_path}")
                except Exception as e:
                    logger.error(f"チャンク保存検証中にエラー: {e}, graph_id={graph_id}, db_path={self.db_path}")
                    raise
        except Exception as e:
            logger.error(f"チャンク保存中にエラーが発生しました: graph_id={graph_id}, error={str(e)}")
            raise
    
    def save_node_chunks(self, graph_id: str, node_to_chunks: Dict[str, List[str]]) -> None:
        """
        ノード-チャンクの関連を一括保存（バッチ処理）
        
        Args:
            graph_id: グラフID
            node_to_chunks: node_name -> [chunk_id, ...] のマッピング
        """
        if not node_to_chunks:
            return
        
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            
            # 既存の関連を削除（再構築時）
            cursor.execute("DELETE FROM node_chunks WHERE graph_id = ?", (graph_id,))
            
            # バッチ挿入
            node_chunk_data = []
            for node_name, chunk_ids in node_to_chunks.items():
                for chunk_id in chunk_ids:
                    node_chunk_data.append((graph_id, node_name, chunk_id))
            
            if node_chunk_data:
                cursor.executemany("""
                    INSERT INTO node_chunks (graph_id, node_name, chunk_id)
                    VALUES (?, ?, ?)
                """, node_chunk_data)
            
            conn.commit()
        
        logger.info(f"ノード-チャンク関連を保存: {len(node_to_chunks)}ノード, graph_id={graph_id}")
    
    def save_edge_chunks(self, graph_id: str, edge_to_chunks: Dict[Tuple[str, str], List[str]]) -> None:
        """
        エッジ-チャンクの関連を一括保存（バッチ処理）
        
        Args:
            graph_id: グラフID
            edge_to_chunks: (source, target) -> [chunk_id, ...] のマッピング
        """
        if not edge_to_chunks:
            return
        
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            
            # 既存の関連を削除（再構築時）
            cursor.execute("DELETE FROM edge_chunks WHERE graph_id = ?", (graph_id,))
            
            # バッチ挿入
            edge_chunk_data = []
            for (source, target), chunk_ids in edge_to_chunks.items():
                for chunk_id in chunk_ids:
                    edge_chunk_data.append((graph_id, source, target, chunk_id))
            
            if edge_chunk_data:
                cursor.executemany("""
                    INSERT INTO edge_chunks (graph_id, source, target, chunk_id)
                    VALUES (?, ?, ?, ?)
                """, edge_chunk_data)
            
            conn.commit()
        
        logger.info(f"エッジ-チャンク関連を保存: {len(edge_to_chunks)}エッジ, graph_id={graph_id}")
    
    def get_chunks(self, graph_id: str, chunk_ids: Optional[List[str]] = None) -> Dict[str, str]:
        """
        チャンクを取得
        
        Args:
            graph_id: グラフID
            chunk_ids: 取得するチャンクIDのリスト（Noneの場合は全チャンク）
            
        Returns:
            Dict[str, str]: chunk_id -> chunk_text のマッピング
        """
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            
            if chunk_ids:
                placeholders = ','.join(['?'] * len(chunk_ids))
                cursor.execute(f"""
                    SELECT chunk_id, chunk_text FROM chunks
                    WHERE graph_id = ? AND chunk_id IN ({placeholders})
                    ORDER BY chunk_index
                """, [graph_id] + chunk_ids)
            else:
                cursor.execute("""
                    SELECT chunk_id, chunk_text FROM chunks
                    WHERE graph_id = ?
                    ORDER BY chunk_index
                """, (graph_id,))
            
            rows = cursor.fetchall()
            result = {row[0]: row[1] for row in rows}
            logger.debug(f"get_chunks: graph_id={graph_id}, chunk_ids={len(chunk_ids) if chunk_ids else 'all'}, 取得数={len(result)}")
            
            return result
    
    def get_node_chunks(self, graph_id: str, node_name: str) -> List[str]:
        """
        ノードに関連するチャンクIDを取得
        
        Args:
            graph_id: グラフID
            node_name: ノード名
            
        Returns:
            List[str]: チャンクIDのリスト
        """
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT chunk_id FROM node_chunks
                WHERE graph_id = ? AND node_name = ?
                ORDER BY chunk_id
            """, (graph_id, node_name))
            
            result = [row[0] for row in cursor.fetchall()]
            logger.debug(f"get_node_chunks: graph_id={graph_id}, node_name={node_name}, 取得数={len(result)}")
            
            return result
    
    def get_edge_chunks(self, graph_id: str, source: str, target: str) -> List[str]:
        """
        エッジに関連するチャンクIDを取得
        
        Args:
            graph_id: グラフID
            source: ソースノード名
            target: ターゲットノード名
            
        Returns:
            List[str]: チャンクIDのリスト
        """
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT chunk_id FROM edge_chunks
                WHERE graph_id = ? AND source = ? AND target = ?
                ORDER BY chunk_id
            """, (graph_id, source, target))
            
            result = [row[0] for row in cursor.fetchall()]
            logger.debug(f"get_edge_chunks: graph_id={graph_id}, source={source}, target={target}, 取得数={len(result)}")
            
            return result
    
    def delete_graph(self, graph_id: str) -> None:
        """
        グラフと関連するチャンクを削除
        
        Args:
            graph_id: グラフID
        """
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            
            # 関連データを削除（CASCADE）
            cursor.execute("SELECT COUNT(*) FROM chunks WHERE graph_id = ?", (graph_id,))
            chunks_count_before_delete = cursor.fetchone()[0]
            logger.warning(f"delete_graph: チャンクを削除します（DELETE FROM chunks WHERE graph_id = ?）, 削除前のチャンク数={chunks_count_before_delete}, graph_id={graph_id}, db_path={self.db_path}")
            import traceback
            logger.warning(f"delete_graph: 呼び出しスタック:\n{''.join(traceback.format_stack())}")
            
            cursor.execute("DELETE FROM edge_chunks WHERE graph_id = ?", (graph_id,))
            cursor.execute("DELETE FROM node_chunks WHERE graph_id = ?", (graph_id,))
            cursor.execute("DELETE FROM chunks WHERE graph_id = ?", (graph_id,))
            deleted_chunks_count = cursor.rowcount
            cursor.execute("DELETE FROM graphs WHERE graph_id = ?", (graph_id,))
            
            conn.commit()
            
            logger.warning(f"delete_graph: チャンクを削除しました: {deleted_chunks_count}件, graph_id={graph_id}, db_path={self.db_path}")
        
        logger.info(f"グラフを削除: graph_id={graph_id}")

