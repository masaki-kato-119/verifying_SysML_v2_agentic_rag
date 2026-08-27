"""
セマンティックエントリーファインダー（Phase 5）

自然言語クエリの意図を理解し、最も関連性の高いエントリーポイントを発見する
embedding-based セマンティック検索を実装
"""
import logging
from typing import Dict, List, Optional, Union

import networkx as nx

from .chunk_storage import ChunkStorage

# numpyのインポート（オプション）
try:
    import numpy as np
    NUMPY_AVAILABLE = True
except ImportError:
    NUMPY_AVAILABLE = False
    # numpyが利用できない場合の代替実装
    class np:
        @staticmethod
        def array(data):
            return list(data)
        
        @staticmethod
        def zeros(shape):
            if isinstance(shape, int):
                return [0.0] * shape
            return [[0.0] * shape[1] for _ in range(shape[0])]
        
        @staticmethod
        def dot(a, b):
            if isinstance(a, list) and isinstance(b, list):
                return sum(x * y for x, y in zip(a, b))
            return 0.0
        
        @staticmethod
        def linalg():
            class norm:
                @staticmethod
                def norm(vec):
                    if isinstance(vec, list):
                        return sum(x * x for x in vec) ** 0.5
                    return 0.0
            return type('obj', (object,), {'norm': norm})()

logger = logging.getLogger(__name__)

# sentence-transformersのインポート（オプション）
try:
    from sentence_transformers import SentenceTransformer
    SENTENCE_TRANSFORMERS_AVAILABLE = True
except ImportError:
    SENTENCE_TRANSFORMERS_AVAILABLE = False
    SentenceTransformer = None


class HighPrecisionEmbeddingModel:
    """
    高精度embeddingモデル（sentence-transformers使用）
    
    sentence-transformersが利用可能な場合に使用される高精度なembeddingモデル
    """
    
    def __init__(self, model_name: str = "paraphrase-multilingual-MiniLM-L12-v2"):
        """
        高精度embeddingモデルを初期化
        
        Args:
            model_name: 使用するモデル名（デフォルト: 多言語対応モデル）
        """
        if not SENTENCE_TRANSFORMERS_AVAILABLE:
            raise ImportError("sentence-transformersがインストールされていません。pip install sentence-transformers を実行してください。")
        
        logger.info(f"高精度embeddingモデルを初期化中: {model_name}")
        self.model = SentenceTransformer(model_name)
        logger.info("高精度embeddingモデルの初期化が完了しました")
    
    def embed(self, text: str):
        """
        テキストをembedding化
        
        Args:
            text: 入力テキスト
        
        Returns:
            np.ndarray: embeddingベクトル
        """
        if not text:
            return self.model.encode("", convert_to_numpy=True)
        
        # sentence-transformersでembedding化
        embedding = self.model.encode(text, convert_to_numpy=True)
        return embedding


class SimpleEmbeddingModel:
    """
    簡易embeddingモデル（Phase 5）
    
    注意: 本番環境では、より高精度なembeddingモデル（sentence-transformers等）の使用を推奨
    """
    
    def __init__(self):
        """簡易embeddingモデルを初期化"""
        # 簡易版: TF-IDFベースのベクトル化
        self.vocabulary = {}
        self.idf = {}
        self._initialized = False
    
    def embed(self, text: str):
        """
        テキストをembedding化
        
        Args:
            text: 入力テキスト
        
        Returns:
            np.ndarray or list: embeddingベクトル
        """
        if not text:
            return np.zeros(100)  # デフォルト次元数
        
        # 簡易版: 単語頻度ベースのベクトル
        words = text.lower().split()
        vector = np.zeros(100)
        
        for i, word in enumerate(words[:100]):  # 最大100単語
            # 簡易ハッシュベースのベクトル化
            hash_val = hash(word) % 100
            if isinstance(vector, list):
                vector[hash_val] += 1.0 / (i + 1)  # 位置重み
            else:
                vector[hash_val] += 1.0 / (i + 1)  # 位置重み
        
        # 正規化
        norm = np.linalg.norm(vector)
        if norm > 0:
            if isinstance(vector, list):
                vector = [v / norm for v in vector]
            elif NUMPY_AVAILABLE:
                vector = vector / norm
            else:
                vector = [v / norm for v in vector]
        
        return vector


class SemanticEntryFinder:
    """
    セマンティックエントリーファインダー
    
    自然言語クエリの意図を理解し、最も関連性の高い
    エントリーポイントを発見する
    """
    
    def __init__(
        self, 
        graph: nx.DiGraph,
        embedding_model: Optional[Union[SimpleEmbeddingModel, HighPrecisionEmbeddingModel]] = None,
        chunk_storage: Optional[ChunkStorage] = None,
        use_high_precision: bool = True
    ):
        """
        セマンティックエントリーファインダーを初期化
        
        Args:
            graph: 対象のグラフ
            embedding_model: embeddingモデル（Noneの場合は自動選択）
            chunk_storage: チャンクストレージ（ソーステキスト取得用）
            use_high_precision: 高精度embeddingモデルを使用するか（デフォルト: True）
        """
        self.graph = graph
        self.chunk_storage = chunk_storage
        
        # embeddingモデルの選択
        if embedding_model:
            self.embedding_model = embedding_model
        elif use_high_precision and SENTENCE_TRANSFORMERS_AVAILABLE:
            try:
                self.embedding_model = HighPrecisionEmbeddingModel()
                logger.info("高精度embeddingモデルを使用します")
            # sentence-transformersのモデルロードは環境依存の多様な例外（I/O、依存ライブラリ起因等）を
            # 送出しうるため、種類を問わず簡易版embeddingへフォールバックさせる
            except Exception as e:  # noqa: BLE001
                logger.warning(f"高精度embeddingモデルの初期化に失敗しました: {e}。簡易版にフォールバックします。")
                self.embedding_model = SimpleEmbeddingModel()
        else:
            self.embedding_model = SimpleEmbeddingModel()
            if use_high_precision:
                logger.info("sentence-transformersが利用できないため、簡易embeddingモデルを使用します")
        
        self.node_embeddings = {}
        self.node_descriptions = {}
        self._index_built = False
        self._index_building = False
        self._build_thread = None
        self._stop_building = False
        # 遅延初期化: 最初の使用時にインデックスを構築
        # これにより、MCPサーバーの起動をブロックしない
    
    
    def _build_semantic_index(self):
        """ノードのセマンティックインデックスを構築（バッチ処理対応）"""
        logger.info("セマンティックインデックスを構築中...")
        total_nodes = self.graph.number_of_nodes()
        
        # 1. すべてのノードの説明文を生成
        nodes_list = list(self.graph.nodes())
        descriptions_list = []
        for node in nodes_list:
            description = self._generate_node_description(node)
            self.node_descriptions[node] = description
            descriptions_list.append(description)
        
        # 2. バッチ処理でembedding化（sentence-transformersの場合）
        if isinstance(self.embedding_model, HighPrecisionEmbeddingModel):
            # sentence-transformersはバッチ処理をサポート
            batch_size = 32  # バッチサイズ（メモリに応じて調整可能）
            logger.info(f"バッチ処理でembedding化を実行（バッチサイズ: {batch_size}）")
            
            for i in range(0, len(descriptions_list), batch_size):
                # 停止要求をチェック
                if self._stop_building:
                    logger.info(f"セマンティックインデックス構築を停止しました（{i}/{total_nodes}ノードまで処理済み）")
                    break
                
                batch_descriptions = descriptions_list[i:i + batch_size]
                batch_nodes = nodes_list[i:i + batch_size]
                
                # バッチでembedding化
                batch_embeddings = self.embedding_model.model.encode(
                    batch_descriptions,
                    convert_to_numpy=True,
                    show_progress_bar=False
                )
                
                # 結果を保存
                for node, embedding in zip(batch_nodes, batch_embeddings):
                    self.node_embeddings[node] = embedding
                
                if (i + batch_size) % 1000 == 0 or (i + batch_size) >= len(descriptions_list):
                    progress = min(i + batch_size, len(descriptions_list))
                    logger.info(f"セマンティックインデックス構築進捗: {progress}/{total_nodes}ノード ({progress*100//total_nodes}%)")
        else:
            # 簡易モデルの場合は1つずつ処理
            for i, (node, description) in enumerate(zip(nodes_list, descriptions_list)):
                embedding = self.embedding_model.embed(description)
                self.node_embeddings[node] = embedding
                
                if (i + 1) % 1000 == 0:
                    logger.info(f"セマンティックインデックス構築進捗: {i + 1}/{total_nodes}ノード ({(i + 1)*100//total_nodes}%)")
        
        logger.info(f"セマンティックインデックス構築完了: {total_nodes}ノード")
    
    def _generate_node_description(self, node: str) -> str:
        """
        ノードの説明文を生成
        
        Args:
            node: ノード名
        
        Returns:
            str: ノードの説明文
        """
        description_parts = [node]
        
        # 隣接ノード情報を追加
        neighbors = list(self.graph.neighbors(node))
        if neighbors:
            description_parts.append(f"関連: {', '.join(neighbors[:3])}")
        
        # ソーステキスト抜粋を追加
        source_text = self._get_source_text_preview(node)
        if source_text:
            description_parts.append(f"内容: {source_text[:200]}")
        
        # ノード属性から情報を追加
        node_attrs = self.graph.nodes[node]
        if 'concept_type' in node_attrs:
            description_parts.append(f"タイプ: {node_attrs['concept_type']}")
        
        return " ".join(description_parts)
    
    def _get_source_text_preview(self, node: str) -> str:
        """
        ノードのソーステキストプレビューを取得
        
        Args:
            node: ノード名
        
        Returns:
            str: ソーステキストの抜粋（最大200文字）
        """
        if not self.chunk_storage:
            return ""
        
        try:
            # グラフIDを取得（graph属性から）
            graph_id = self.graph.graph.get('graph_id')
            if not graph_id:
                return ""
            
            # チャンクIDを取得
            chunk_ids = self.chunk_storage.get_node_chunks(graph_id, node)
            if not chunk_ids:
                return ""
            
            # 最初のチャンクを取得
            chunks = self.chunk_storage.get_chunks(graph_id, chunk_ids[:1])
            if chunks:
                chunk_text = list(chunks.values())[0]
                return chunk_text[:200]
        # chunk_storageはテスト・利用先で差し替え可能なインターフェースであり、
        # 実装依存の様々な例外（DB以外のバックエンドを含む）を返しうるため意図的に広く捕捉する
        except Exception as e:  # noqa: BLE001
            logger.debug(f"ソーステキスト取得エラー: {e}")
        
        return ""
    
    def _cosine_similarity(self, vec1, vec2) -> float:
        """
        コサイン類似度を計算
        
        Args:
            vec1: ベクトル1（np.ndarray or list）
            vec2: ベクトル2（np.ndarray or list）
        
        Returns:
            float: コサイン類似度（0.0-1.0）
        """
        dot_product = np.dot(vec1, vec2)
        norm1 = np.linalg.norm(vec1)
        norm2 = np.linalg.norm(vec2)
        
        if norm1 == 0 or norm2 == 0:
            return 0.0
        
        return dot_product / (norm1 * norm2)
    
    def find_semantic_entry_points(
        self, 
        query: str, 
        max_entries: int = 3,
        threshold: Optional[float] = None  # Noneの場合は自動設定
    ) -> List[Dict]:
        """
        セマンティック検索でエントリーポイントを発見
        
        Args:
            query: 自然言語クエリ
            max_entries: 最大返却数
            threshold: 類似度閾値（Noneの場合は自動設定: 高精度モデルは0.5、簡易版は0.3）
        
        Returns:
            List[Dict]: エントリーポイント情報
        """
        if not query or not query.strip():
            return []
        
        # インデックスがまだ構築されていない場合、簡易検索を返す
        # 大規模グラフではインデックス構築に時間がかかるため、最初は簡易検索を使用
        if not self._index_built:
            # バックグラウンドでインデックス構築を開始（非ブロッキング）
            if not self._index_building and not self._stop_building:
                import threading
                self._build_thread = threading.Thread(target=self._build_semantic_index_background, daemon=True)
                self._build_thread.start()
            
            # 簡易フォールバック: ノード名の部分一致検索
            if self._index_building:
                logger.debug("セマンティックインデックス構築中。簡易検索を使用します。")
            return self._simple_keyword_search(query, max_entries)
        
        # インデックスが構築されている場合、セマンティック検索を実行
        if not self.node_embeddings:
            return self._simple_keyword_search(query, max_entries)
        
        # 閾値の自動設定
        if threshold is None:
            if isinstance(self.embedding_model, HighPrecisionEmbeddingModel):
                threshold = 0.5  # 高精度モデルはより高い閾値
            else:
                threshold = 0.3  # 簡易版は低い閾値
        
        # 1. クエリをembedding化
        query_embedding = self.embedding_model.embed(query)
        
        # 2. 各ノードとの類似度計算
        similarities = []
        for node, node_embedding in self.node_embeddings.items():
            similarity = self._cosine_similarity(query_embedding, node_embedding)
            if similarity >= threshold:
                similarities.append({
                    'node': node,
                    'similarity': float(similarity),
                    'description': self.node_descriptions.get(node, node),
                    'reason': f"クエリとの意味的類似度: {similarity:.2f}"
                })
        
        # 3. 類似度順でソート・返却
        similarities.sort(key=lambda x: x['similarity'], reverse=True)
        return similarities[:max_entries]
    
    def _simple_keyword_search(self, query: str, max_entries: int) -> List[Dict]:
        """
        簡易キーワード検索（インデックス未構築時用）
        
        Args:
            query: 検索クエリ
            max_entries: 最大返却数
        
        Returns:
            List[Dict]: 検索結果
        """
        query_lower = query.lower()
        query_words = query_lower.split()
        matches = []
        
        # ノード名の部分一致検索
        for node in self.graph.nodes():
            node_lower = node.lower()
            # クエリの単語がノード名に含まれているかチェック
            match_score = sum(1 for word in query_words if word in node_lower)
            if match_score > 0:
                matches.append({
                    'node': node,
                    'similarity': 0.3 + (match_score / len(query_words)) * 0.2,  # 0.3-0.5のスコア
                    'description': node,
                    'reason': f'ノード名の部分一致 ({match_score}/{len(query_words)}単語)'
                })
                if len(matches) >= max_entries * 5:  # より多くの候補を収集
                    break
        
        # スコア順でソート
        matches.sort(key=lambda x: x['similarity'], reverse=True)
        return matches[:max_entries]
    
    def _build_semantic_index_background(self):
        """バックグラウンドでセマンティックインデックスを構築（非ブロッキング）"""
        if self._index_building:
            return
        
        self._index_building = True
        self._stop_building = False
        try:
            self._build_semantic_index()
            if not self._stop_building:
                self._index_built = True
                logger.info("セマンティックインデックスのバックグラウンド構築が完了しました。")
            else:
                logger.info("セマンティックインデックスの構築が停止されました。")
        # バックグラウンドスレッドでの構築処理全体（embedding計算等）を対象とするため、
        # 例外の種類を問わずログに記録してスレッドを静かに終了させる
        except Exception as e:  # noqa: BLE001
            logger.error(f"セマンティックインデックス構築エラー: {e}")
        finally:
            self._index_building = False
            self._build_thread = None
    
    def stop_index_building(self):
        """セマンティックインデックスの構築を停止"""
        if self._index_building:
            self._stop_building = True
            logger.info("セマンティックインデックスの構築停止を要求しました。")
    
    def get_index_status(self) -> Dict:
        """セマンティックインデックスの状態を取得"""
        return {
            'index_built': self._index_built,
            'index_building': self._index_building,
            'indexed_nodes': len(self.node_embeddings),
            'total_nodes': self.graph.number_of_nodes(),
            'progress_percent': (len(self.node_embeddings) * 100 // self.graph.number_of_nodes()) if self.graph.number_of_nodes() > 0 else 0
        }
