"""ハイブリッド検索モジュール。

このモジュールは、ベクトル検索とFTS検索を統合した
ハイブリッド検索機能を提供します。リランキングと
クエリ拡張機能も含まれます。
"""

from __future__ import annotations

import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from .config import (
    SEARCH_MMR_TOP_K,
)
from .graph_store import GraphStore
from .metadata_store import ChunkMetadata, MetadataStore
from .query_expansion import expand_query_with_llm
from .search_diversity import (  # noqa: F401  (一部は本モジュール内で未使用だが後方互換のため再エクスポート)
    _apply_context_window,
    _apply_diversity_limit,
    _apply_mmr,
)
from .search_graph_augment import (  # noqa: F401
    EVIDENCE_NOT_AVAILABLE_NOTE,
    _apply_graph_aware_rerank,
    _apply_graph_expansion,
    _apply_local_graph_summary,
    _extract_evidence_from_results,
    annotate_evidence_status,
)
from .search_result import HybridSearchResult
from .search_scoring import (  # noqa: F401
    _apply_metadata_filter_to_meta,
    _apply_metadata_filter_to_vector,
    _dedupe_meta_results,
    _dedupe_vector_results,
    _extract_chunk_index,
    _extract_file_key,
    _min_max_normalize,
    _rank_based_scores,
    _rrf_scores,
    choose_weights_for_query,
    combine_for_hybrid,
    combine_for_hybrid_rrf,
    combine_for_hybrid_with_scores,
    detect_query_type,
)
from .vector_store import VectorRecord, VectorStoreAPI

# キャッシュ機能をオプションでインポート
try:
    from .cache import SearchCache
    _CACHE_AVAILABLE = True
except ImportError:
    _CACHE_AVAILABLE = False
    SearchCache = None  # type: ignore

# メトリクス収集をオプションでインポート
try:
    from .metrics_collector import MetricsCollector, SearchMetrics
    _METRICS_COLLECTOR_AVAILABLE = True
except ImportError:
    _METRICS_COLLECTOR_AVAILABLE = False
    MetricsCollector = None  # type: ignore
    SearchMetrics = None  # type: ignore

logger = logging.getLogger(__name__)


@dataclass















































class Reranker:
    """Cross-Encoder を用いたリランカー。

    クエリとチャンクテキストのペアを評価し、関連度スコアで再ランキングします。

    Attributes:
        model: CrossEncoderモデルインスタンス。
    """

    def __init__(self, model_name: str = "cross-encoder/ms-marco-MiniLM-L-6-v2") -> None:
        """Rerankerを初期化する。

        Args:
            model_name: 使用するCross-Encoderモデル名
                （デフォルト: "cross-encoder/ms-marco-MiniLM-L-6-v2"）。
        """
        # sentence-transformers は環境によって NumPy/依存のABI差で import 時に落ちることがあるため、
        # リランキングを使うときだけ遅延importする。
        try:
            from sentence_transformers import CrossEncoder  # type: ignore
        except Exception as e:  # ImportError以外（ABIエラー等）も拾う
            import warnings
            error_msg = str(e)
            # NumPy互換性エラーの場合は警告を出して、より詳細なメッセージを提供
            if "numpy" in error_msg.lower() or "_ARRAY_API" in error_msg or "AttributeError" in str(type(e).__name__):
                warnings.warn(
                    f"NumPy互換性エラーが発生しました。NumPy 1.xへのダウングレードを推奨します: {error_msg}",
                    RuntimeWarning,
                )
            raise RuntimeError(
                "Cross-Encoder リランキングを使うには `sentence-transformers` とその依存関係が必要です。\n"
                "NumPy 2.xでエラーが発生する場合は、`pip install 'numpy<2.0.0'` でNumPy 1.xにダウングレードしてください。\n"
                f"エラー詳細: {error_msg}"
            ) from e

        self.model = CrossEncoder(model_name)

    def rerank(
        self,
        query: str,
        candidates: List[HybridSearchResult],
        top_k: Optional[int] = None,
    ) -> List[HybridSearchResult]:
        """候補をリランキングする。

        Args:
            query: 検索クエリ。
            candidates: リランキング対象の候補リスト。
            top_k: 返す結果の最大件数。Noneの場合はすべて返します。

        Returns:
            List[HybridSearchResult]: リランキングされた結果のリスト。
                score_rerankの降順でソートされます。
        """
        if not candidates:
            return []

        pairs = [[query, c.text] for c in candidates]
        scores = self.model.predict(pairs)

        for c, score in zip(candidates, scores):
            c.score_rerank = float(score)

        candidates.sort(key=lambda c: c.score_rerank, reverse=True)

        if top_k is None:
            return candidates
        return candidates[:top_k]


_GLOBAL_RERANKER: Reranker | None = None
_RERANKER_LOCK = threading.Lock()


def get_global_reranker() -> Reranker:
    """Cross-Encoder リランカーのグローバル共有インスタンスを取得する。

    モデルロードのオーバーヘッドを最小化するため、
    プロセス内で1つだけ生成します。

    Returns:
        Reranker: グローバルリランカーインスタンス。
    """
    global _GLOBAL_RERANKER
    with _RERANKER_LOCK:
        if _GLOBAL_RERANKER is None:
            _GLOBAL_RERANKER = Reranker()
        return _GLOBAL_RERANKER


def is_reranker_ready() -> bool:
    """Cross-Encoder が既にロード済みかどうか。"""
    return _GLOBAL_RERANKER is not None


def preload_reranker() -> bool:
    """Cross-Encoder をメインスレッドで先読みする。

    MCP サーバ（FastMCP の stdio サーバ）はツール関数をワーカースレッドで実行する。
    そのワーカースレッド内で Cross-Encoder の初回ロードを行うと**デッドロックし、
    ``use_rerank=True`` の呼び出しが永久に返らない**（実測で 27 分以上無応答、
    CPU もゼロ）。同じ呼び出しを直接実行すると 11 秒で完了するため、
    MCP 経由でのみ発生する。

    実測では、専用スレッドでの先読みでも解消しなかった。
    **イベントループが動き出す前に、メインスレッドで同期的にロードする**必要がある。
    ロードには 25 秒ほどかかるため、起動時間とのトレードオフになる。

    Returns:
        bool: ロードに成功したら True。
    """
    try:
        get_global_reranker()
        logger.info("reranker.preloaded", extra={"event": "reranker.preloaded"})
        return True
    except Exception:
        # 先読みに失敗しても use_rerank=False の検索は動く
        logger.warning(
            "reranker.preload_failed",
            extra={"event": "reranker.preload_failed"},
            exc_info=True,
        )
        return False







class RAGSearcher:
    """ベクトル検索・メタ検索・セマンティック検索・ハイブリッド検索をまとめて扱う高レベルAPI。

    Attributes:
        vector_store: ベクトルストアAPIインスタンス。
        metadata_store: メタデータストアインスタンス。
        _reranker: リランカーインスタンス（オプション）。
        graph_store: グラフストアインスタンス（軽量GraphRAG用、オプション）。
    """

    def __init__(
        self,
        vector_store: Optional[VectorStoreAPI] = None,
        metadata_store: Optional[MetadataStore] = None,
        reranker: Optional[Reranker] = None,
        graph_store: Optional[GraphStore] = None,
        metrics_collector: Optional["MetricsCollector"] = None,
        search_cache: Optional["SearchCache"] = None,
    ) -> None:
        """RAGSearcherを初期化する。

        Args:
            vector_store: ベクトルストアAPIインスタンス。
                Noneの場合は新規作成されます。
            metadata_store: メタデータストアインスタンス。
                Noneの場合は新規作成されます。
            reranker: リランカーインスタンス。
                Noneの場合は必要時にグローバルインスタンスを使用します。
            graph_store: グラフストアインスタンス（軽量GraphRAG用）。
                Noneの場合はGraph機能は無効になります。
            metrics_collector: メトリクス収集インスタンス（フェーズ5: メトリクス収集・可視化）。
                Noneの場合はメトリクス収集は無効になります。
            search_cache: 検索結果キャッシュインスタンス（フェーズ6: 検索結果のキャッシング）。
                Noneの場合はキャッシュは無効になります。
        """
        self.vector_store = vector_store or VectorStoreAPI()
        self.metadata_store = metadata_store or MetadataStore()
        self._reranker = reranker
        self.graph_store = graph_store
        self.metrics_collector = metrics_collector
        self.search_cache = search_cache
        # 最後の検索のタイミング情報（パフォーマンス測定用）
        self.last_timing_info: Optional[Dict[str, float]] = None

    # -------- 個別検索 --------
    def search_vector(self, query: str, *, top_k: int = 10) -> List[VectorRecord]:
        """ベクトル検索のみを実行する。

        Args:
            query: 検索クエリ。
            top_k: 返す結果の最大件数（デフォルト: 10）。

        Returns:
            List[VectorRecord]: ベクトル検索結果のリスト。
        """
        return self.vector_store.search(query_text=query, top_k=top_k)

    def search_meta(
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
        """メタ情報に基づく検索のみを実行する。

        Args:
            file_name: ファイル名でフィルタ。
            file_path: ファイルパスでフィルタ。
            file_type: ファイル種別でフィルタ。
            page_number: ページ番号でフィルタ。
            min_updated_at: 最小更新日時。
            max_updated_at: 最大更新日時。
            limit: 返す結果の最大件数（デフォルト: 10）。

        Returns:
            List[ChunkMetadata]: メタ検索結果のリスト。
        """
        return self.metadata_store.meta_search(
            file_name=file_name,
            file_path=file_path,
            file_type=file_type,
            page_number=page_number,
            min_updated_at=min_updated_at,
            max_updated_at=max_updated_at,
            limit=limit,
        )

    def search_semantic(self, query: str, *, limit: int = 10) -> List[ChunkMetadata]:
        """FTS5 による全文検索（セマンティック検索）のみを実行する。

        Args:
            query: 検索クエリ。
            limit: 返す結果の最大件数（デフォルト: 10）。

        Returns:
            List[ChunkMetadata]: セマンティック検索結果のリスト。
        """
        return self.metadata_store.semantic_search(query=query, limit=limit)

    def _get_reranker(self) -> Reranker:
        """リランカーインスタンスを取得する（遅延初期化）。

        インスタンス変数にリランカーが設定されていない場合は、
        グローバル共有インスタンスを取得して設定します。

        Returns:
            Reranker: リランカーインスタンス。
        """
        if self._reranker is None:
            self._reranker = get_global_reranker()
        return self._reranker

    # -------- ハイブリッド検索 --------
    def search_hybrid(
        self,
        query: str,
        *,
        top_k_vector: int = 10,
        limit_meta: int = 10,
        weight_vector: float = 0.7,
        weight_meta: float = 0.3,
        scoring: str = "rank",
        dynamic_weight: bool = False,
        max_chunks_per_file: Optional[int] = None,
        context_window: int = 0,
        parallel: bool = True,
        use_query_expansion: bool = False,
        use_rerank: bool = False,
        rerank_top_k: Optional[int] = None,
        use_mmr: bool = False,
        mmr_lambda: float = 0.5,
        mmr_top_k: Optional[int] = None,
        use_graph: bool = False,
        graph_depth: int = 1,
        graph_seed_k: int = 3,
        graph_max_neighbors: int = 30,
        graph_neighbor_weight: float = 0.5,
        use_local_graph_summary: bool = False,
        use_evidence_extraction: bool = False,
        evidence_max_depth: int = 2,
        file_name: Optional[str] = None,
        file_path: Optional[str] = None,
        file_type: Optional[str] = None,
        page_number: Optional[int] = None,
        query_type: Optional[str] = None,
        relevant_chunk_ids: Optional[List[str]] = None,
    ) -> List[HybridSearchResult]:
        """ハイブリッド検索を実行する。

        クエリに対してベクトル検索とセマンティック検索を実行し、
        その結果を統合してハイブリッドスコアでランキングします。

        ベクトル検索: OpenAI埋め込み + ChromaDB
        セマンティック検索: SQLite3 FTS5（``semantic_search`` を利用）

        Args:
            query: 検索クエリ。
            top_k_vector: ベクトル検索で取得する最大件数（デフォルト: 10）。
            limit_meta: セマンティック検索で取得する最大件数（デフォルト: 10）。
            weight_vector: ベクトル検索スコアの重み（デフォルト: 0.7）。
            weight_meta: メタ検索スコアの重み（デフォルト: 0.3）。
            scoring: 統合方式（"rank" | "score" | "rrf"）。
                - "rank": 順位ベースのスコア（デフォルト）
                - "score": 距離（Chroma）/ bm25（FTS）を正規化して統合
                - "rrf": RRF（Reciprocal Rank Fusion）で統合
            dynamic_weight: Trueの場合、クエリ種別に応じてベクトル/FTSの重みを動的に調整（デフォルト: False）。
            max_chunks_per_file: 1ファイルから返す最大チャンク数（多様性確保）。Noneで無効。
            context_window: 前後何チャンクを結合して返すか（0で無効、デフォルト: 0）。
            parallel: Trueの場合、ベクトル検索とFTS検索を並列実行する（デフォルト: True）。
            use_query_expansion: Trueの場合、LLMによるクエリ拡張を行う（デフォルト: False）。
            use_rerank: Trueの場合、Cross-Encoderによるリランキングを行う（デフォルト: False）。
            rerank_top_k: リランキング後の返却件数。Noneの場合はすべて返します。
            use_mmr: Trueの場合、MMR (Maximal Marginal Relevance) を適用して多様性を確保する（デフォルト: False）。
            mmr_lambda: MMRの関連性と多様性のバランス（0.0=多様性優先、1.0=関連性優先、デフォルト: 0.5）。
            mmr_top_k: MMR適用後の返却件数。Noneの場合はすべて返します。
            use_graph: Trueの場合、Graph近傍を用いて候補を拡張する（軽量GraphRAG、デフォルト: False）。
            graph_depth: Graph探索の深さ（hop数、デフォルト: 1）。
            graph_seed_k: 既存結果の上位何件を起点にするか（デフォルト: 3）。
            graph_max_neighbors: Graphから追加する近傍候補の最大数（デフォルト: 30）。
            graph_neighbor_weight: 近傍候補のスコア付与係数（距離減衰、デフォルト: 0.5）。
            use_local_graph_summary: Trueの場合、局所グラフサマリを生成する（GraphRAG強化: フェーズ6、デフォルト: False）。
                注意: LLM呼び出しが必要なため、コストと時間がかかります。
            use_evidence_extraction: Trueの場合、根拠情報（Constraint, SyntaxRule, SpecClause）を抽出する（GraphRAG拡張、デフォルト: False）。
            evidence_max_depth: 根拠抽出時のGraph探索の最大深さ（hop数、デフォルト: 2）。
            file_name: ファイル名でフィルタ（完全一致）。Noneで無効。
            file_path: ファイルパスでフィルタ（完全一致）。Noneで無効。
            file_type: ファイル種別でフィルタ（"txt", "md", "pdf"）。Noneで無効。
            page_number: ページ番号でフィルタ（PDFの場合）。Noneで無効。
            query_type: クエリタイプ（"factual", "exploratory", "procedural"など）。メトリクス収集用。
            relevant_chunk_ids: 関連チャンクIDのリスト（評価用）。提供された場合、MRR/NDCGを計算して記録。

        Returns:
            List[HybridSearchResult]: ハイブリッド検索結果のリスト。
                スコアの降順でソートされます。

        Example:
            >>> searcher = RAGSearcher()
            >>> # 基本的なハイブリッド検索
            >>> results = searcher.search_hybrid("Python")
            >>> print(len(results))
            10
            >>> # メタデータフィルタリング付き検索
            >>> results = searcher.search_hybrid(
            ...     "SysML",
            ...     file_name="SysML_Language_Specification_v2.pdf",
            ...     file_type="pdf"
            ... )
            >>> # リランキングとクエリ拡張を有効化
            >>> results = searcher.search_hybrid(
            ...     "Python",
            ...     use_query_expansion=True,
            ...     use_rerank=True,
            ...     rerank_top_k=5
            ... )
            >>> # 軽量GraphRAGを有効化（手順書・仕様書など順序が重要な場合）
            >>> results = searcher.search_hybrid(
            ...     "手順",
            ...     use_graph=True,
            ...     graph_depth=2,
            ...     graph_seed_k=3,
            ...     graph_max_neighbors=20
            ... )
        """
        started = time.perf_counter()
        query_len = len(query or "")
        
        # デフォルト値の適用
        if mmr_top_k is None:
            mmr_top_k = SEARCH_MMR_TOP_K
        
        # キャッシュから取得を試みる（キャッシュが有効な場合）
        if self.search_cache is not None:
            cached_results = self.search_cache.get(
                query,
                top_k_vector=top_k_vector,
                limit_meta=limit_meta,
                use_rerank=use_rerank,
                use_mmr=use_mmr,
                mmr_lambda=mmr_lambda,
                mmr_top_k=mmr_top_k,
                use_graph=use_graph,
                graph_depth=graph_depth,
                file_name=file_name,
                file_path=file_path,
                file_type=file_type,
                page_number=page_number,
                scoring=scoring,
            )
            if cached_results is not None:
                # キャッシュから取得した結果をHybridSearchResultに変換
                results = [
                    HybridSearchResult(
                        chunk_id=r["chunk_id"],
                        text=r["text"],
                        metadata=r["metadata"],
                        score_vector=r.get("score_vector", 0.0),
                        score_meta=r.get("score_meta", 0.0),
                        score_hybrid=r.get("score_hybrid", 0.0),
                        score_rerank=r.get("score_rerank", 0.0),
                    )
                    for r in cached_results
                ]
                duration_ms = int((time.perf_counter() - started) * 1000)
                
                # キャッシュヒット時のタイミング情報（簡易版）
                cache_timing_info = {
                    "ms_query_expand": 0,
                    "ms_vector": 0,
                    "ms_semantic": 0,
                    "ms_dedupe": 0,
                    "ms_filter": 0,
                    "ms_combine": 0,
                    "ms_graph_expand": 0,
                    "ms_evidence_extraction": 0,
                    "ms_diversity": 0,
                    "ms_mmr": 0,
                    "ms_rerank": 0,
                    "ms_graph_rerank": 0,
                    "ms_graph_summary": 0,
                    "ms_context": 0,
                    "duration_ms": duration_ms,
                    "n_vec": 0,
                    "n_semantic": 0,
                    "n_results": len(results),
                    "cache_hit": True,
                }
                self.last_timing_info = cache_timing_info
                
                # キャッシュ統計を取得
                cache_stats = None
                if self.search_cache:
                    cache_stats = self.search_cache.get_stats()

                logger.info(
                    "search_hybrid.cache_hit",
                    extra={
                        "event": "search_hybrid.cache_hit",
                        "query_len": query_len,
                        "n_results": len(results),
                        "duration_ms": duration_ms,
                        "cache_stats": cache_stats,
                    },
                )
                
                # キャッシュヒット時もメトリクスを記録（フェーズ5: メトリクス収集・可視化）
                if self.metrics_collector and _METRICS_COLLECTOR_AVAILABLE:
                    try:
                        # キャッシュヒット時はMRR/NDCGは計算しない（relevant_chunk_idsが提供されても、キャッシュ結果のため）
                        search_metrics = SearchMetrics(
                            query=query[:100],  # クエリは100文字までに制限（プライバシー保護）
                            query_type=query_type,
                            use_graph=use_graph,
                            use_rerank=use_rerank,
                            use_mmr=use_mmr,
                            use_query_expansion=use_query_expansion,
                            duration_ms=duration_ms,
                            num_results=len(results),
                            mrr=None,  # キャッシュヒット時は計算しない
                            ndcg_at_10=None,
                            precision_at_10=None,
                            recall_at_10=None,
                            relevant_chunk_ids=relevant_chunk_ids,
                        )
                        self.metrics_collector.record_search(search_metrics)
                    except Exception as e:
                        # メトリクス収集の失敗は検索自体には影響しない
                        logger.warning(
                            "search_hybrid.metrics_collection_failed",
                            extra={
                                "event": "search_hybrid.metrics_collection_failed",
                                "error": str(e),
                            },
                            exc_info=True,
                        )
                
                return results
        
        # キャッシュミスの場合、ログに記録
        cache_stats_before = None
        if self.search_cache is not None:
            cache_stats_before = self.search_cache.get_stats()
            logger.info(
                "search_hybrid.cache_check",
                extra={
                    "event": "search_hybrid.cache_check",
                    "query_len": query_len,
                    "cache_enabled": True,
                    "cache_stats_before": cache_stats_before,
                },
            )
        
        # 機密/PII混入リスク低減のため、クエリ全文はログに出さない（長さなどのメタのみ）
        logger.info(
            "search_hybrid.start",
            extra={
                "event": "search_hybrid.start",
                "query_len": query_len,
                "cache_enabled": self.search_cache is not None,
                "k_vector": top_k_vector,
                "k_semantic": limit_meta,
                "scoring": scoring,
                "dynamic_weight": dynamic_weight,
                "diversity_max_per_file": max_chunks_per_file,
                "context_window": context_window,
                "parallel": parallel,
                "use_query_expansion": use_query_expansion,
                "use_rerank": use_rerank,
                "rerank_top_k": rerank_top_k,
                "use_mmr": use_mmr,
                "mmr_lambda": mmr_lambda,
                "mmr_top_k": mmr_top_k,
                "use_graph": use_graph,
                "graph_depth": graph_depth,
                "graph_seed_k": graph_seed_k,
                "graph_max_neighbors": graph_max_neighbors,
                "filter_file_name": file_name,
                "filter_document_id": file_path,
                "filter_file_type": file_type,
                "filter_page_number": page_number,
            },
        )

        ms_query_expand = 0
        ms_vector = 0
        ms_semantic = 0
        ms_dedupe = 0
        ms_filter = 0
        ms_combine = 0
        ms_graph_expand = 0
        ms_evidence_extraction = 0
        ms_diversity = 0
        ms_mmr = 0
        ms_rerank = 0
        ms_context = 0

        if dynamic_weight:
            weight_vector, weight_meta = choose_weights_for_query(query)

        # 1. クエリ拡張
        t0 = time.perf_counter()
        if use_query_expansion:
            queries = expand_query_with_llm(query)
        else:
            queries = [query]
        ms_query_expand = int((time.perf_counter() - t0) * 1000)

        # 2. 各クエリでベクトル検索 / セマンティック検索を実行し、結果をマージ
        vec_all: List[VectorRecord] = []
        semantic_all: List[ChunkMetadata] = []

        if parallel:
            # 並列時もステップ別時間を取るため、計測して返す関数で包む
            def _timed_vector(q: str) -> Tuple[int, List[VectorRecord]]:
                _t = time.perf_counter()
                out = self.search_vector(q, top_k=top_k_vector)
                return int((time.perf_counter() - _t) * 1000), out

            def _timed_semantic(q: str) -> Tuple[int, List[ChunkMetadata]]:
                _t = time.perf_counter()
                out = self.search_semantic(q, limit=limit_meta)
                return int((time.perf_counter() - _t) * 1000), out

            with ThreadPoolExecutor(max_workers=2) as ex:
                for q in queries:
                    fut_vec = ex.submit(_timed_vector, q)
                    fut_sem = ex.submit(_timed_semantic, q)
                    vec_ms, vec_out = fut_vec.result()
                    sem_ms, sem_out = fut_sem.result()
                    ms_vector += vec_ms
                    ms_semantic += sem_ms
                    vec_all.extend(vec_out)
                    semantic_all.extend(sem_out)

                    # クエリ拡張を行っている場合、十分な件数が集まったら以降の拡張クエリを省略する。
                    if use_query_expansion:
                        if len(vec_all) >= top_k_vector and len(semantic_all) >= limit_meta:
                            break
        else:
            for q in queries:
                t_vec = time.perf_counter()
                vec_all.extend(self.search_vector(q, top_k=top_k_vector))
                ms_vector += int((time.perf_counter() - t_vec) * 1000)

                t_sem = time.perf_counter()
                semantic_all.extend(self.search_semantic(q, limit=limit_meta))
                ms_semantic += int((time.perf_counter() - t_sem) * 1000)

                # クエリ拡張を行っている場合、十分な件数が集まったら以降の拡張クエリを省略する。
                if use_query_expansion:
                    if len(vec_all) >= top_k_vector and len(semantic_all) >= limit_meta:
                        break

        t0 = time.perf_counter()
        vec_results = _dedupe_vector_results(vec_all)
        semantic_results = _dedupe_meta_results(semantic_all)
        ms_dedupe = int((time.perf_counter() - t0) * 1000)

        # 2.4 メタデータフィルタリング
        t0 = time.perf_counter()
        vec_results = _apply_metadata_filter_to_vector(
            vec_results,
            file_name=file_name,
            file_path=file_path,
            file_type=file_type,
            page_number=page_number,
        )
        semantic_results = _apply_metadata_filter_to_meta(
            semantic_results,
            file_name=file_name,
            file_path=file_path,
            file_type=file_type,
            page_number=page_number,
        )
        ms_filter = int((time.perf_counter() - t0) * 1000)

        # 2.5 動的重み（結果が片方ゼロのときの安全策）
        if dynamic_weight:
            if not vec_results and semantic_results:
                weight_vector, weight_meta = 0.0, 1.0
            if vec_results and not semantic_results:
                weight_vector, weight_meta = 1.0, 0.0

        # 3. ハイブリッド統合
        t0 = time.perf_counter()
        if scoring == "score":
            results = combine_for_hybrid_with_scores(
                vector_results=vec_results,
                meta_results=semantic_results,
                weight_vector=weight_vector,
                weight_meta=weight_meta,
            )
        elif scoring == "rrf":
            results = combine_for_hybrid_rrf(
                vector_results=vec_results,
                meta_results=semantic_results,
                weight_vector=weight_vector,
                weight_meta=weight_meta,
            )
        else:
            results = combine_for_hybrid(
                vector_results=vec_results,
                meta_results=semantic_results,
                weight_vector=weight_vector,
                weight_meta=weight_meta,
            )
        ms_combine = int((time.perf_counter() - t0) * 1000)

        # 3.2 GraphRAG（軽量版）: 近傍候補の追加（任意）
        t0 = time.perf_counter()
        results = _apply_graph_expansion(
            results,
            graph_store=self.graph_store,
            metadata_store=self.metadata_store,
            use_graph=use_graph,
            graph_depth=graph_depth,
            graph_seed_k=graph_seed_k,
            graph_max_neighbors=graph_max_neighbors,
            graph_neighbor_weight=graph_neighbor_weight,
            file_name=file_name,
            file_path=file_path,
            file_type=file_type,
            page_number=page_number,
        )
        ms_graph_expand = int((time.perf_counter() - t0) * 1000)

        # 3.3 GraphRAG拡張: 根拠情報の抽出（仕様書検証向け）
        # Graph拡張後の結果を起点に、関連エンティティ（Constraint, SyntaxRule, SpecClause）を取得
        ms_evidence_extraction = 0
        evidence_info: Dict[str, Any] = {}
        if use_evidence_extraction and self.graph_store:
            t0 = time.perf_counter()
            try:
                evidence_info = _extract_evidence_from_results(
                    results,
                    graph_store=self.graph_store,
                    max_depth=evidence_max_depth,
                )
                # 根拠情報をメタデータに追加（LLMへの入力用）
                # 注意: 各結果に個別に追加するのではなく、検索結果全体のメタデータとして扱う
                # 実際のLLM呼び出し時には、evidence_info["evidence_text"]を使用
            except Exception as e:
                logger.warning(
                    "search_hybrid.evidence_extraction_failed",
                    extra={
                        "event": "search_hybrid.evidence_extraction_failed",
                        "error": str(e),
                    },
                    exc_info=True,
                )
            ms_evidence_extraction = int((time.perf_counter() - t0) * 1000)

        # 3.5 後処理（多様性）
        t0 = time.perf_counter()
        results = _apply_diversity_limit(results, max_chunks_per_file=max_chunks_per_file)
        ms_diversity = int((time.perf_counter() - t0) * 1000)

        # 3.6 MMR (Maximal Marginal Relevance) による多様性確保（任意）
        # リランキングの前に適用することで、リランキングの計算コストを削減
        if use_mmr and results:
            t0 = time.perf_counter()
            results = _apply_mmr(
                results,
                query=query,
                lambda_param=mmr_lambda,
                top_k=mmr_top_k,
            )
            ms_mmr = int((time.perf_counter() - t0) * 1000)

        # 4. Cross-Encoder によるリランキング（任意）
        if use_rerank and results:
            # 未ロードのまま MCP のワーカースレッドでロードするとデッドロックする
            # （preload_reranker のドキュメント参照）。ロード済みのときだけ実行し、
            # 未ロードならリランクを飛ばす。無反応になるより落として進めるほうがよい。
            if self._reranker is None and not is_reranker_ready():
                logger.warning(
                    "search_hybrid.rerank_skipped_not_preloaded",
                    extra={"event": "search_hybrid.rerank_skipped_not_preloaded"},
                )
            else:
                t0 = time.perf_counter()
                reranker = self._get_reranker()
                results = reranker.rerank(
                    query=query,
                    candidates=results,
                    top_k=rerank_top_k,
                )
                ms_rerank = int((time.perf_counter() - t0) * 1000)

        # 4.6 Graph-aware再ランキング（GraphRAG強化: フェーズ6）
        # Graph拡張された結果に対して、グラフの特徴量（距離、次数、中心性）を考慮してスコアを調整
        if use_graph and self.graph_store and results:
            t0 = time.perf_counter()
            results = _apply_graph_aware_rerank(
                results,
                graph_store=self.graph_store,
                graph_seed_k=graph_seed_k,
            )
            ms_graph_rerank = int((time.perf_counter() - t0) * 1000)
        else:
            ms_graph_rerank = 0

        # 4.7 局所グラフサマリ（GraphRAG強化: フェーズ6）
        # 近傍チャンク集合をLLMで要約し、説明力を向上
        if use_local_graph_summary and use_graph and self.graph_store and results:
            t0 = time.perf_counter()
            results = _apply_local_graph_summary(
                results,
                graph_store=self.graph_store,
                metadata_store=self.metadata_store,
                summary_depth=graph_depth,
                summary_max_neighbors=graph_max_neighbors,
                use_llm=True,
            )
            ms_graph_summary = int((time.perf_counter() - t0) * 1000)
        else:
            ms_graph_summary = 0

        # 4.5 文脈補完（前後チャンク）
        t0 = time.perf_counter()
        results = _apply_context_window(
            results,
            metadata_store=self.metadata_store,
            context_window=context_window,
            top_k=rerank_top_k,
        )
        ms_context = int((time.perf_counter() - t0) * 1000)

        duration_ms = int((time.perf_counter() - started) * 1000)
        
        # タイミング情報をメタデータとして結果に付与（デバッグ用）
        # 注意: この情報は大量の結果を返す場合にメモリを消費する可能性があるため、
        # 本番環境では無効化することを推奨
        timing_info = {
            "ms_query_expand": ms_query_expand,
            "ms_vector": ms_vector,
            "ms_semantic": ms_semantic,
            "ms_dedupe": ms_dedupe,
            "ms_filter": ms_filter,
            "ms_combine": ms_combine,
            "ms_graph_expand": ms_graph_expand,
            "ms_evidence_extraction": ms_evidence_extraction,
            "ms_diversity": ms_diversity,
            "ms_mmr": ms_mmr,
            "ms_rerank": ms_rerank,
            "ms_graph_rerank": ms_graph_rerank,
            "ms_graph_summary": ms_graph_summary,
            "ms_context": ms_context,
            "duration_ms": duration_ms,
            # 各検索手法の獲得件数（パフォーマンス測定用）
            "n_vec_raw": len(vec_all),
            "n_semantic_raw": len(semantic_all),
            "n_vec": len(vec_results),
            "n_semantic": len(semantic_results),
            "n_results": len(results),
        }
        
        # 最後の検索のタイミング情報を保存（パフォーマンス測定用）
        self.last_timing_info = timing_info
        
        logger.info(
            "search_hybrid.done",
            extra={
                "event": "search_hybrid.done",
                "query_len": query_len,
                "n_queries": len(queries),
                "n_vec_raw": len(vec_all),
                "n_semantic_raw": len(semantic_all),
                "n_vec": len(vec_results),
                "n_semantic": len(semantic_results),
                "n_results": len(results),
                "weight_vector": weight_vector,
                "weight_meta": weight_meta,
                **timing_info,
            },
        )

        # メトリクス収集（フェーズ5: メトリクス収集・可視化）
        if self.metrics_collector and _METRICS_COLLECTOR_AVAILABLE:
            try:
                # MRR/NDCGを計算（relevant_chunk_idsが提供された場合のみ）
                mrr_score = None
                ndcg_at_10 = None
                precision_at_10 = None
                recall_at_10 = None
                
                if relevant_chunk_ids:
                    from .eval import (
                        EvalCase,
                        mean_ndcg_at_k,
                        mean_precision_at_k,
                        mean_recall_at_k,
                        mrr,
                    )
                    
                    ranked_ids = [r.chunk_id for r in results]
                    relevant_set = set(relevant_chunk_ids)
                    
                    # MRRを計算
                    eval_case = EvalCase(query=query, relevant_chunk_ids=relevant_set)
                    mrr_score = mrr([eval_case], [ranked_ids])
                    
                    # NDCG@10を計算
                    ndcg_at_10 = mean_ndcg_at_k([eval_case], [ranked_ids], k=10)
                    
                    # Precision@10を計算
                    precision_at_10 = mean_precision_at_k([eval_case], [ranked_ids], k=10)
                    
                    # Recall@10を計算
                    recall_at_10 = mean_recall_at_k([eval_case], [ranked_ids], k=10)
                
                # メトリクスを記録
                search_metrics = SearchMetrics(
                    query=query[:100],  # クエリは100文字までに制限（プライバシー保護）
                    query_type=query_type,
                    use_graph=use_graph,
                    use_rerank=use_rerank,
                    use_mmr=use_mmr,
                    use_query_expansion=use_query_expansion,
                    use_evidence_extraction=use_evidence_extraction,
                    duration_ms=duration_ms,
                    num_results=len(results),
                    mrr=mrr_score,
                    ndcg_at_10=ndcg_at_10,
                    precision_at_10=precision_at_10,
                    recall_at_10=recall_at_10,
                    relevant_chunk_ids=relevant_chunk_ids,
                    # 段階別の所要時間も保存する。合計値だけでは、遅い検索が
                    # どの段階（ベクトル検索 / リランク / グラフ拡張など）で
                    # 時間を使ったのかを後から追跡できないため。
                    timing_breakdown=timing_info,
                )
                self.metrics_collector.record_search(search_metrics)
            except Exception as e:
                # メトリクス収集の失敗は検索自体には影響しない
                logger.warning(
                    "search_hybrid.metrics_collection_failed",
                    extra={
                        "event": "search_hybrid.metrics_collection_failed",
                        "error": str(e),
                    },
                    exc_info=True,
                )

        # 根拠情報を結果のメタデータに追加（後方互換性のため、オプション）
        # 注意: 根拠抽出はGraph拡張の直後（3.3）で実行済み
        if evidence_info and evidence_info.get("evidence_text"):
            # 検索結果のメタデータに根拠情報を追加
            for result in results[:10]:  # 上位10件にのみ追加
                result.metadata["evidence_text"] = evidence_info["evidence_text"]
                result.metadata["evidence_constraints"] = evidence_info.get("constraints", [])
                result.metadata["evidence_syntax_rules"] = evidence_info.get("syntax_rules", [])
                result.metadata["evidence_spec_clauses"] = evidence_info.get("spec_clauses", [])

        # キャッシュに保存（キャッシュが有効な場合）
        if self.search_cache is not None:
            try:
                # HybridSearchResultを辞書形式に変換
                results_dict = [
                    {
                        "chunk_id": r.chunk_id,
                        "text": r.text,
                        "metadata": r.metadata,
                        "score_vector": r.score_vector,
                        "score_meta": r.score_meta,
                        "score_hybrid": r.score_hybrid,
                        "score_rerank": r.score_rerank,
                    }
                    for r in results
                ]
                self.search_cache.set(
                    query,
                    results_dict,
                    top_k_vector=top_k_vector,
                    limit_meta=limit_meta,
                    use_rerank=use_rerank,
                    use_mmr=use_mmr,
                    mmr_lambda=mmr_lambda,
                    mmr_top_k=mmr_top_k,
                    use_graph=use_graph,
                    graph_depth=graph_depth,
                    file_name=file_name,
                    file_path=file_path,
                    file_type=file_type,
                    page_number=page_number,
                    scoring=scoring,
                )
                # キャッシュ保存後の統計を取得
                cache_stats_after = self.search_cache.get_stats()
                logger.info(
                    "search_hybrid.cache_saved",
                    extra={
                        "event": "search_hybrid.cache_saved",
                        "query_len": query_len,
                        "n_results": len(results),
                        "cache_stats_after": cache_stats_after,
                    },
                )
            # キャッシュ保存はベストエフォート。結果の直列化やDB書き込みで
            # 何が起きても検索結果自体は返したいため、失敗種別を問わず
            # 警告ログのみに留めてsearch_hybrid全体をクラッシュさせない。
            except Exception as e:  # noqa: BLE001
                logger.warning(f"キャッシュへの保存に失敗: {e}")

        return results



