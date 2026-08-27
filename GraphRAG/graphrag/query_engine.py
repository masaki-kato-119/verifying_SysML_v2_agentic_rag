"""
GraphRAG Query Engine（仕様書: GraphRAG Query Engine）
グラフから情報を検索・推論する機能
"""
import logging
from pathlib import Path
from typing import Optional

import networkx as nx

from .cache_manager import CacheManager
from .chunk_storage import ChunkStorage
from .evidence_extractor import EvidenceExtractor
from .parallel_processor import ParallelProcessor
from .query_engine_parts.context_retrieval import ContextRetrievalMixin
from .query_engine_parts.node_search import NodeSearchMixin
from .query_engine_parts.path_finding import PathFindingMixin
from .query_engine_parts.query_expansion import QueryExpansionMixin
from .query_engine_parts.semantic_delegation import SemanticDelegationMixin
from .query_expander import QueryExpander

logger = logging.getLogger(__name__)


class GraphQueryEngine(QueryExpansionMixin, NodeSearchMixin, PathFindingMixin, ContextRetrievalMixin, SemanticDelegationMixin):
    """
    GraphRAG Query Engine
    
    グラフから情報を検索・推論する機能を提供
    """
    
    def __init__(
        self, 
        graph: nx.DiGraph,
        enable_query_cache: bool = True,
        query_cache_ttl: Optional[float] = None,
        query_cache_persistent: bool = True,
        cache_dir: Optional[str] = None,
        chunk_storage: Optional[ChunkStorage] = None
    ):
        """
        Query Engineを初期化
        
        Args:
            graph: 検索対象のグラフ
            enable_query_cache: クエリ結果キャッシュを有効にするか
            query_cache_ttl: クエリキャッシュのTTL（秒、Noneの場合は永続化）
            query_cache_persistent: クエリキャッシュを永続化するか
            cache_dir: キャッシュディレクトリ（Noneの場合はメモリのみ）
            chunk_storage: チャンクストレージ（Noneの場合はデフォルトを使用）
        """
        self.graph = graph
        self.chunk_storage = chunk_storage or ChunkStorage()
        
        # グラフファイルパスを取得（チャンク取得に使用）
        graph_filepath = graph.graph.get('graph_filepath')
        import logging
        logger = logging.getLogger(__name__)
        
        if graph_filepath:
            # 正規化されたパスでグラフIDを生成
            self.graph_filepath = self.chunk_storage._normalize_to_relative_path(graph_filepath)
            self.graph_id = self.chunk_storage.get_graph_id(self.graph_filepath)
            logger.debug(f"GraphQueryEngine初期化: graph_filepath={self.graph_filepath}, graph_id={self.graph_id}")
        else:
            self.graph_filepath = None
            self.graph_id = None
            logger.warning("グラフにgraph_filepathが設定されていません。チャンク取得ができません。")
        
        # キャッシュマネージャーを初期化
        self.cache = CacheManager(
            enable_query_cache=enable_query_cache,
            query_cache_ttl=query_cache_ttl,
            query_cache_persistent=query_cache_persistent,
            cache_dir=cache_dir
        )
        
        # Phase 3 enhancements
        self.evidence_extractor = EvidenceExtractor(self.chunk_storage)
        self.query_expander = QueryExpander(self.graph)
        self.parallel_processor = ParallelProcessor(
            max_workers=4,  # デフォルトで4並列
            timeout=30.0,
            enable_early_termination=True
        )
        
        # Phase 2: エントリーファインダーと標識システム
        from .entry_finder import LightweightEntryFinder
        from .node_signage import NodeSignageManager
        self.entry_finder = LightweightEntryFinder(self.graph)
        self.signage_manager = NodeSignageManager(self.graph)
        
        # Phase 4: 学習・適応機能
        from .learning_adaptation import (
            DynamicSignageAdjuster,
            ExplorationHistoryOptimizer,
            QueryPatternLearner,
        )
        learning_cache_dir = cache_dir or Path.home() / '.graphrag' / 'learning'
        if cache_dir:
            learning_cache_dir = Path(cache_dir) / 'learning'
        learning_cache_dir.mkdir(parents=True, exist_ok=True)
        
        self.query_learner = QueryPatternLearner(
            history_file=str(learning_cache_dir / 'query_patterns.json')
        )
        self.exploration_optimizer = ExplorationHistoryOptimizer(
            history_file=str(learning_cache_dir / 'exploration_history.json')
        )
        self.signage_adjuster = DynamicSignageAdjuster(
            self.graph,
            self.signage_manager,
            self.exploration_optimizer
        )
        
        # Phase 5: セマンティック統合機能
        
        # LLMクライアント（オプション、環境変数から取得）
        self.llm_client = None
        try:
            import os
            if os.environ.get("OPENAI_API_KEY"):
                from openai import OpenAI
                self.llm_client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))
        except ImportError:
            logger.debug("OpenAIクライアントが利用できません（オプション機能）")
        
        # Phase 5コンポーネント初期化（遅延初期化: 必要になったときに構築）
        self._semantic_entry_finder = None
        self._node_summarizer = None
        self._semantic_path_finder = None
