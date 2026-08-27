"""MCPサーバーモジュール。

このモジュールは、FastMCPを使用してハイブリッドRAGシステムを
MCP（Model Context Protocol）サーバーとして公開します。
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path
from time import perf_counter
from typing import Any, Dict, List, Optional

from fastmcp import FastMCP
from rag.cache import SearchCache
from rag.config import (
    ALLOWED_BASE_DIR,
    ALLOWED_INDEX_EXTENSIONS,
    CACHE_DB_PATH,
    CHROMA_DIR,
    DATA_DIR,
    GRAPH_PATH,
    MAX_INDEX_FILE_BYTES,
    SEARCH_GRAPH_DEPTH,
    SEARCH_GRAPH_MAX_NEIGHBORS,
    SEARCH_GRAPH_NEIGHBOR_WEIGHT,
    SEARCH_GRAPH_SEED_K,
    SEARCH_LIMIT_META,
    SEARCH_RERANK_TOP_K,
    SEARCH_TOP_K_VECTOR,
    configure_logging,
    env_flag,
)
from rag.graph_store import GraphStore
from rag.indexer import index_document
from rag.metrics_collector import MetricsCollector
from rag.search import (
    RAGSearcher,
    annotate_evidence_status,
    preload_reranker,
)

mcp = FastMCP("Hybrid RAG MCP Server")

configure_logging()
logger = logging.getLogger(__name__)

# 単一のRAGSearcherインスタンスを使い回す
# ChromaDBが破損している場合のエラーハンドリング
try:
    # キャッシュを有効化
    search_cache = SearchCache(
        max_size=1000,
        persist_path=CACHE_DB_PATH,
    )
    logger.info(f"検索結果キャッシュを有効化: {CACHE_DB_PATH}")
    
    # メトリクス収集を有効化（web_app.pyと同じDBを使用して累積）
    METRICS_DB_PATH = DATA_DIR / "metrics_web_app.db"
    metrics_collector = MetricsCollector(db_path=METRICS_DB_PATH)
    logger.info(f"メトリクス収集を有効化: {METRICS_DB_PATH}")
    
    searcher = RAGSearcher(
        graph_store=GraphStore(persist_path=GRAPH_PATH),
        search_cache=search_cache,
        metrics_collector=metrics_collector,
    )
# chromadb の Rust バインディングが投げる PanicException は BaseException 由来で、
# except Exception では捕まらない。ここは「壊れた ChromaDB を分かりやすく報告する」
# のが目的なので BaseException で受け、制御用の例外だけ素通しする。
except BaseException as e:
    if isinstance(e, (KeyboardInterrupt, SystemExit)):
        raise

    error_msg = str(e)
    error_type = type(e).__name__

    # ChromaDB関連のエラー（Rustパニック含む）を検出
    if (
        "chromadb" in error_type.lower()
        or "panic" in error_type.lower()
        or "panic" in error_msg.lower()
        or "range start index" in error_msg.lower()
        or "sqlite" in error_msg.lower()
    ):
        logger.error(
            "chromadb.init_failed",
            extra={
                "event": "chromadb.init_failed",
                "error_type": error_type,
                "error_msg": error_msg,
                "chroma_dir": str(CHROMA_DIR),
            },
        )
        # stdio トランスポートでは stdout が MCP のプロトコル channel なので、
        # 診断メッセージは必ず stderr に出す（stdout に書くと接続が壊れる）。
        print("=" * 60, file=sys.stderr)
        print("ChromaDB初期化エラー", file=sys.stderr)
        print("=" * 60, file=sys.stderr)
        print(f"\nエラー: {error_type}: {error_msg}", file=sys.stderr)
        print(f"対象: {CHROMA_DIR}", file=sys.stderr)
        print("\nChromaDBのデータベースが破損している可能性があります。", file=sys.stderr)
        print("上記ディレクトリを退避（またはリネーム）してから、", file=sys.stderr)
        print("index_path ツールでドキュメントを再インデックスしてください。", file=sys.stderr)
        print("※ 再インデックスには OpenAI Embedding API の呼び出しが発生します。", file=sys.stderr)
        print("=" * 60, file=sys.stderr)
        raise SystemExit(1) from e
    else:
        # その他のエラーはそのまま再発生
        raise


# Cross-Encoder はイベントループが動き出す前に、メインスレッドで読み込む。
# FastMCP のワーカースレッド内で初回ロードするとデッドロックし、
# use_rerank=True の呼び出しが永久に返らない（rag.search の preload_reranker 参照）。
# ロードに 25 秒ほどかかるため、リランクを使わない運用では
# RAG_PRELOAD_RERANKER=0 で省略できる（その場合 use_rerank は無視される）。
if env_flag("RAG_PRELOAD_RERANKER"):
    preload_reranker()
else:
    logger.info(
        "reranker.preload_skipped",
        extra={"event": "reranker.preload_skipped"},
    )


def _validate_index_target(path: str) -> Path:
    p = Path(path).resolve()
    if not p.exists():
        raise FileNotFoundError(f"ファイルが存在しません: {p}")
    if not p.is_file():
        raise ValueError(f"ファイルではありません: {p}")

    ext = p.suffix.lower()
    if ext not in ALLOWED_INDEX_EXTENSIONS:
        raise ValueError(f"許可されていない拡張子です: {ext} (allowed={sorted(ALLOWED_INDEX_EXTENSIONS)})")

    if ALLOWED_BASE_DIR:
        base = Path(ALLOWED_BASE_DIR).resolve()
        try:
            p.relative_to(base)
        except ValueError as e:
            raise ValueError(f"許可されていないパスです: {p} (base={base})") from e

    size = p.stat().st_size
    if size > MAX_INDEX_FILE_BYTES:
        raise ValueError(f"ファイルサイズが上限を超えています: {size} bytes (max={MAX_INDEX_FILE_BYTES})")

    return p


@mcp.tool()
def index_path(path: str) -> Dict[str, Any]:
    """指定パスのファイルをインデックス化する。

    テキスト/Markdown/PDF/Word/Excel/PowerPointファイルを読み込み、チャンク分割して
    ベクトルDBおよびメタDBの両方に登録します。
    さらに、軽量GraphRAGとして同一ファイル内の隣接チャンク間の関係（next/prev）を
    グラフ化し、`data/graph.pkl` に永続化します。

    対応ファイル形式:
    - テキスト: .txt
    - Markdown: .md, .markdown
    - PDF: .pdf
    - Word: .docx
    - Excel: .xlsx, .xls
    - PowerPoint: .pptx
    - SysML: .sysml

    Args:
        path: インデックス化するファイルの絶対パス。

    Returns:
        Dict[str, Any]: インデックス化結果の辞書。以下のキーを含みます:
            - document_id: ドキュメントID（絶対パス）
            - file_name: ファイル名
            - file_type: ファイル種別（"txt", "md", "pdf", "docx", "xlsx", "pptx" など）
            - num_chunks: チャンク数

    Raises:
        FileNotFoundError: ファイルが存在しない場合。
        ImportError: 必要なライブラリ（python-docx, openpyxl, python-pptx）がインストールされていない場合。

    Example:
        >>> result = index_path("E:/documents/example.pdf")
        >>> print(result["num_chunks"])
        50
        >>> result = index_path("E:/documents/document.docx")
        >>> print(result["file_type"])
        docx
    """
    started = perf_counter()
    t0 = perf_counter()
    p = _validate_index_target(path)
    ms_validate = int((perf_counter() - t0) * 1000)
    document_id = str(p)
    logger.info(
        "index_path.start",
        extra={"event": "index_path.start", "document_id": document_id, "ms_validate": ms_validate},
    )
    try:
        result = index_document(
            p,
            vector_store=searcher.vector_store,
            metadata_store=searcher.metadata_store,
            graph_store=searcher.graph_store,
        )
        # 返り値にツール側の計測も付与（UI/運用で追跡しやすくする）
        result["validate_ms"] = ms_validate
        logger.info(
            "index_path.done",
            extra={
                "event": "index_path.done",
                "document_id": document_id,
                "file_name": result.get("file_name"),
                "file_type": result.get("file_type"),
                "n_chunks": result.get("num_chunks"),
                "ms_validate": ms_validate,
                "ms_load": result.get("load_ms"),
                "ms_vector": result.get("vector_ms"),
                "ms_meta": result.get("meta_ms"),
                "ms_graph": result.get("graph_ms"),
                "duration_ms": int((perf_counter() - started) * 1000),
            },
        )
        return result
    except Exception:
        logger.exception(
            "index_path.error",
            extra={
                "event": "index_path.error",
                "document_id": document_id,
                "ms_validate": ms_validate,
                "duration_ms": int((perf_counter() - started) * 1000),
            },
        )
        raise


@mcp.tool()
def vector_search(query: str, top_k: int = 5) -> List[Dict[str, Any]]:
    """ベクトル検索を実行する。

    クエリに対してベクトル検索を行い、類似チャンクを返します。

    Args:
        query: 検索クエリ。
        top_k: 返す結果の最大件数（デフォルト: 5）。

    Returns:
        List[Dict[str, Any]]: 検索結果のリスト。各要素は以下のキーを含みます:
            - id: チャンクID
            - text: チャンクテキスト
            - metadata: メタデータ
            - distance: 類似度距離
    """
    started = perf_counter()
    logger.info(
        "vector_search.start",
        extra={
            "event": "vector_search.start",
            "query_len": len(query or ""),
            "k": top_k,
        },
    )
    try:
        results = searcher.search_vector(query, top_k=top_k)
        logger.info(
            "vector_search.done",
            extra={
                "event": "vector_search.done",
                "query_len": len(query or ""),
                "k": top_k,
                "n_results": len(results),
                "duration_ms": int((perf_counter() - started) * 1000),
            },
        )
        return [
            {
                "id": r.id,
                "text": r.text,
                "metadata": r.metadata,
                "distance": r.distance,
            }
            for r in results
        ]
    except Exception:
        logger.exception(
            "vector_search.error",
            extra={
                "event": "vector_search.error",
                "query_len": len(query or ""),
                "k": top_k,
                "duration_ms": int((perf_counter() - started) * 1000),
            },
        )
        raise


@mcp.tool()
def meta_search(
    file_name: str | None = None,
    file_path: str | None = None,
    file_type: str | None = None,
    page_number: int | None = None,
    limit: int = 10,
) -> List[Dict[str, Any]]:
    """メタ情報検索を実行する。

    メタ情報（ファイル名・パス・種別など）に基づいてチャンクを検索します。

    Args:
        file_name: ファイル名でフィルタ。
        file_path: ファイルパスでフィルタ。
        file_type: ファイル種別でフィルタ（"txt", "md", "pdf"）。
        page_number: ページ番号でフィルタ（PDFの場合）。
        limit: 返す結果の最大件数（デフォルト: 10）。

    Returns:
        List[Dict[str, Any]]: 検索結果のリスト。各要素は以下のキーを含みます:
            - chunk_id: チャンクID
            - file_name: ファイル名
            - file_path: ファイルパス
            - file_type: ファイル種別
            - chunk_index: チャンクインデックス
            - page_number: ページ番号
            - chunk_text: チャンクテキスト
    """
    started = perf_counter()
    logger.info(
        "meta_search.start",
        extra={
            "event": "meta_search.start",
            "k": limit,
            "filter_file_name": file_name,
            "filter_document_id": file_path,
            "filter_file_type": file_type,
            "filter_page_number": page_number,
        },
    )
    try:
        results = searcher.search_meta(
            file_name=file_name,
            file_path=file_path,
            file_type=file_type,
            page_number=page_number,
            limit=limit,
        )
        logger.info(
            "meta_search.done",
            extra={
                "event": "meta_search.done",
                "k": limit,
                "n_results": len(results),
                "filter_file_name": file_name,
                "filter_document_id": file_path,
                "filter_file_type": file_type,
                "filter_page_number": page_number,
                "duration_ms": int((perf_counter() - started) * 1000),
            },
        )
        return [
            {
                "chunk_id": r.chunk_id,
                "file_name": r.file_name,
                "file_path": r.file_path,
                "file_type": r.file_type,
                "chunk_index": r.chunk_index,
                "page_number": r.page_number,
                "chunk_text": r.chunk_text,
            }
            for r in results
        ]
    except Exception:
        logger.exception(
            "meta_search.error",
            extra={
                "event": "meta_search.error",
                "k": limit,
                "filter_file_name": file_name,
                "filter_document_id": file_path,
                "filter_file_type": file_type,
                "filter_page_number": page_number,
                "duration_ms": int((perf_counter() - started) * 1000),
            },
        )
        raise


@mcp.tool()
def semantic_search(query: str, limit: int = 10) -> List[Dict[str, Any]]:
    """セマンティック検索を実行する。

    SQLite FTS5 を用いて、全文検索（セマンティック検索）を行います。

    Args:
        query: 検索クエリ。
        limit: 返す結果の最大件数（デフォルト: 10）。

    Returns:
        List[Dict[str, Any]]: 検索結果のリスト。各要素は以下のキーを含みます:
            - chunk_id: チャンクID
            - file_name: ファイル名
            - file_path: ファイルパス
            - file_type: ファイル種別
            - chunk_index: チャンクインデックス
            - page_number: ページ番号
            - chunk_text: チャンクテキスト
    """
    started = perf_counter()
    logger.info(
        "semantic_search.start",
        extra={
            "event": "semantic_search.start",
            "query_len": len(query or ""),
            "k": limit,
        },
    )
    try:
        results = searcher.search_semantic(query, limit=limit)
        logger.info(
            "semantic_search.done",
            extra={
                "event": "semantic_search.done",
                "query_len": len(query or ""),
                "k": limit,
                "n_results": len(results),
                "duration_ms": int((perf_counter() - started) * 1000),
            },
        )
        return [
            {
                "chunk_id": r.chunk_id,
                "file_name": r.file_name,
                "file_path": r.file_path,
                "file_type": r.file_type,
                "chunk_index": r.chunk_index,
                "page_number": r.page_number,
                "chunk_text": r.chunk_text,
            }
            for r in results
        ]
    except Exception:
        logger.exception(
            "semantic_search.error",
            extra={
                "event": "semantic_search.error",
                "query_len": len(query or ""),
                "k": limit,
                "duration_ms": int((perf_counter() - started) * 1000),
            },
        )
        raise


@mcp.tool()
def hybrid_search(
    query: str,
    top_k_vector: int = SEARCH_TOP_K_VECTOR,
    limit_meta: int = SEARCH_LIMIT_META,
    scoring: str = "rank",
    dynamic_weight: bool = False,
    max_chunks_per_file: Optional[int] = None,
    context_window: int = 0,
    parallel: bool = True,
    # パフォーマンス優先のため、デフォルトではクエリ拡張とリランキングを無効化
    # 精度が必要な場合は明示的に True を指定してください
    use_query_expansion: bool = False,
    use_rerank: bool = False,
    rerank_top_k: Optional[int] = SEARCH_RERANK_TOP_K,
    use_graph: bool = False,
    graph_depth: int = SEARCH_GRAPH_DEPTH,
    graph_seed_k: int = SEARCH_GRAPH_SEED_K,
    graph_max_neighbors: int = SEARCH_GRAPH_MAX_NEIGHBORS,
    graph_neighbor_weight: float = SEARCH_GRAPH_NEIGHBOR_WEIGHT,
    use_mmr: bool = False,
    mmr_lambda: float = 0.5,
    mmr_top_k: Optional[int] = None,
    use_evidence_extraction: bool = False,
    evidence_max_depth: int = 2,
    file_name: Optional[str] = None,
    file_path: Optional[str] = None,
    file_type: Optional[str] = None,
    page_number: Optional[int] = None,
) -> List[Dict[str, Any]]:
    """ハイブリッド検索を実行する。

    ベクトル検索とセマンティック検索を組み合わせたハイブリッド検索を行い、
    スコア順にチャンクを返します。

    Args:
        query: 検索クエリ。
        top_k_vector: ベクトル検索で取得する最大件数（デフォルト: config.pyのSEARCH_TOP_K_VECTOR、通常40）。
        limit_meta: セマンティック検索で取得する最大件数（デフォルト: config.pyのSEARCH_LIMIT_META、通常40）。
        scoring: 統合方式（"rank" | "score" | "rrf"）。
        dynamic_weight: Trueの場合、クエリ種別に応じて重みを調整する。
        max_chunks_per_file: 1ファイルから返す最大チャンク数（多様性確保）。Noneで無効。
        context_window: 前後何チャンクを結合して返すか（0で無効）。
        parallel: Trueの場合、ベクトル検索とFTS検索を並列実行する（デフォルト: True）。
        use_query_expansion: Trueの場合、LLMによるクエリ拡張を行う（デフォルト: False）。
        use_rerank: Trueの場合、Cross-Encoderによるリランキングを行う（デフォルト: False）。
            **注意**: リランキングは処理時間が大幅に増加します（約800ms/回）。高精度が必要な場合のみ使用を推奨します。
        rerank_top_k: リランキング後の返却件数。Noneの場合はすべて返します。
        use_graph: Trueの場合、Graph近傍を用いて候補を拡張する（軽量GraphRAG、デフォルト: False）。
        graph_depth: Graph探索の深さ（hop数、デフォルト: config.pyのSEARCH_GRAPH_DEPTH、通常2）。
        graph_seed_k: 既存結果の上位何件を起点にするか（デフォルト: config.pyのSEARCH_GRAPH_SEED_K、通常4）。
        graph_max_neighbors: Graphから追加する近傍候補の最大数（デフォルト: config.pyのSEARCH_GRAPH_MAX_NEIGHBORS、通常40）。
        graph_neighbor_weight: 近傍候補のスコア付与係数（距離減衰、デフォルト: config.pyのSEARCH_GRAPH_NEIGHBOR_WEIGHT、通常0.5）。
        use_mmr: Trueの場合、MMR (Maximal Marginal Relevance) を適用して多様性を確保する（デフォルト: False）。
        mmr_lambda: MMRの関連性と多様性のバランス（0.0=多様性優先、1.0=関連性優先、デフォルト: 0.5）。
        mmr_top_k: MMR適用後の返却件数。Noneの場合はすべて返します。
        use_evidence_extraction: Trueの場合、根拠情報（Constraint, SyntaxRule, SpecClause）を抽出する（GraphRAG拡張、デフォルト: False）。
            仕様書検証タスクで根拠情報が必要な場合に有効です。
        evidence_max_depth: 根拠抽出時のGraph探索の最大深さ（hop数、デフォルト: 2）。
        file_name: ファイル名でフィルタ（完全一致）。Noneで無効。
        file_path: ファイルパスでフィルタ（完全一致）。Noneで無効。
        file_type: ファイル種別でフィルタ（"txt", "md", "pdf"）。Noneで無効。
        page_number: ページ番号でフィルタ（PDFの場合）。Noneで無効。

    Returns:
        List[Dict[str, Any]]: 検索結果のリスト。各要素は以下のキーを含みます:
            - chunk_id: チャンクID
            - text: チャンクテキスト
            - metadata: メタデータ
            - score_vector: ベクトル検索スコア
            - score_meta: メタ検索スコア
            - score_hybrid: ハイブリッドスコア
            - score_rerank: リランキングスコア

        use_evidence_extraction=True の場合、各要素の metadata に
        evidence_status（"found" | "no_evidence_nodes"）が付与されます。
        "no_evidence_nodes" は Constraint / SyntaxRule / SpecClause を
        1件も取得できなかったことを意味し、これらを出典として引用してはいけません。
    """
    started = perf_counter()
    # パフォーマンス警告: rerankが有効な場合、処理時間が大幅に増加する可能性がある
    if use_rerank:
        logger.warning(
            "hybrid_search.performance_warning: use_rerank=True is enabled. This may significantly increase processing time.",
            extra={
                "event": "hybrid_search.performance_warning",
                "top_k_vector": top_k_vector,
                "limit_meta": limit_meta,
                "estimated_candidates": top_k_vector + limit_meta,
            },
        )
    logger.info(
        "hybrid_search.start",
        extra={
            "event": "hybrid_search.start",
            "query_len": len(query or ""),
            "k_vector": top_k_vector,
            "k_semantic": limit_meta,
            "scoring": scoring,
            "dynamic_weight": dynamic_weight,
            "diversity_max_per_file": max_chunks_per_file,
            "context_window": context_window,
            "use_query_expansion": use_query_expansion,
            "use_rerank": use_rerank,
            "rerank_top_k": rerank_top_k,
            "parallel": parallel,
            "use_graph": use_graph,
            "graph_depth": graph_depth,
            "graph_seed_k": graph_seed_k,
            "graph_max_neighbors": graph_max_neighbors,
            "graph_neighbor_weight": graph_neighbor_weight,
            "use_evidence_extraction": use_evidence_extraction,
            "evidence_max_depth": evidence_max_depth,
            "filter_file_name": file_name,
            "filter_document_id": file_path,
            "filter_file_type": file_type,
            "filter_page_number": page_number,
        },
    )
    try:
        # query_typeを設定（SysML検証の場合は"procedural"、その他は"factual"）
        query_type = "procedural"  # MCP経由の検索は主にSysML検証で使用されるため
        results = searcher.search_hybrid(
            query,
            top_k_vector=top_k_vector,
            limit_meta=limit_meta,
            scoring=scoring,
            dynamic_weight=dynamic_weight,
            max_chunks_per_file=max_chunks_per_file,
            context_window=context_window,
            parallel=parallel,
            use_query_expansion=use_query_expansion,
            use_rerank=use_rerank,
            rerank_top_k=rerank_top_k,
            use_graph=use_graph,
            graph_depth=graph_depth,
            graph_seed_k=graph_seed_k,
            graph_max_neighbors=graph_max_neighbors,
            graph_neighbor_weight=graph_neighbor_weight,
            use_mmr=use_mmr,
            mmr_lambda=mmr_lambda,
            mmr_top_k=mmr_top_k,
            use_evidence_extraction=use_evidence_extraction,
            evidence_max_depth=evidence_max_depth,
            file_name=file_name,
            file_path=file_path,
            file_type=file_type,
            page_number=page_number,
            query_type=query_type,  # メトリクス収集用
        )
        # search_hybrid内部の詳細タイミング情報を取得するため、
        # 最後のログメッセージから情報を抽出（暫定対応）
        # 本来は search_hybrid の返り値にタイミング情報を含めるべきだが、
        # 現状はログから取得する必要がある
        duration_ms = int((perf_counter() - started) * 1000)
        
        # キャッシュ統計を取得
        cache_stats = None
        if searcher.search_cache:
            cache_stats = searcher.search_cache.get_stats()
        
        # 検索結果の詳細をログに記録（デバッグ用）
        result_summary = []
        if results:
            for i, r in enumerate(results[:5]):  # 上位5件のサマリー
                result_summary.append({
                    "rank": i + 1,
                    "chunk_id": r.chunk_id[:100] if len(r.chunk_id) > 100 else r.chunk_id,
                    "file_name": r.metadata.get("file_name", "N/A")[:50],
                    "text_preview": r.text[:100] if len(r.text) > 100 else r.text,
                    "score_hybrid": round(r.score_hybrid, 4) if r.score_hybrid else None,
                })
        
        logger.info(
            "hybrid_search.done",
            extra={
                "event": "hybrid_search.done",
                "query_len": len(query or ""),
                "k_vector": top_k_vector,
                "k_semantic": limit_meta,
                "n_results": len(results),
                "scoring": scoring,
                "dynamic_weight": dynamic_weight,
                "diversity_max_per_file": max_chunks_per_file,
                "context_window": context_window,
                "duration_ms": duration_ms,
                "use_query_expansion": use_query_expansion,
                "use_rerank": use_rerank,
                "use_graph": use_graph,
                "use_mmr": use_mmr,
                "mmr_lambda": mmr_lambda,
                "mmr_top_k": mmr_top_k,
                "use_evidence_extraction": use_evidence_extraction,
                "evidence_max_depth": evidence_max_depth,
                "filter_file_name": file_name,
                "filter_document_id": file_path,
                "filter_file_type": file_type,
                "filter_page_number": page_number,
                "result_summary": result_summary,  # 検索結果のサマリー
                "cache_stats": cache_stats,  # キャッシュ統計
            },
        )
        
        # キャッシュ統計をログに出力（INFOレベル）
        if cache_stats:
            logger.info(
                "hybrid_search.cache_stats",
                extra={
                    "event": "hybrid_search.cache_stats",
                    "cache_hits": cache_stats.get("hits", 0),
                    "cache_misses": cache_stats.get("misses", 0),
                    "cache_hit_rate": f"{cache_stats.get('hit_rate', 0.0):.2%}",
                    "memory_cache_size": cache_stats.get("memory_cache_size", 0),
                    "persistent_cache_size": cache_stats.get("persistent_cache_size", 0),
                },
            )
        
        # 検索結果が空の場合、警告をログに記録
        if not results:
            logger.warning(
                "hybrid_search.no_results",
                extra={
                    "event": "hybrid_search.no_results",
                    "query": query[:200] if query else "",
                    "query_len": len(query or ""),
                    "k_vector": top_k_vector,
                    "k_semantic": limit_meta,
                    "filters": {
                        "file_name": file_name,
                        "file_path": file_path,
                        "file_type": file_type,
                        "page_number": page_number,
                    },
                },
            )
        
        # 処理時間が長い場合、警告をログに記録
        if duration_ms > 30000:  # 30秒以上
            logger.warning(
                "hybrid_search.slow",
                extra={
                    "event": "hybrid_search.slow",
                    "duration_ms": duration_ms,
                    "query_len": len(query or ""),
                    "use_query_expansion": use_query_expansion,
                    "use_rerank": use_rerank,
                    "n_results": len(results),
                },
            )
        
        # 検索結果を辞書形式に変換（LLMに渡すため）
        formatted_results = [
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
        
        # 根拠抽出が要求された場合、根拠ノードが取れたかどうかを結果に明示する
        # （空のまま黙って返すと LLM が実在しない出典を名乗る原因になる）
        if use_evidence_extraction:
            status = annotate_evidence_status(formatted_results)
            if status == "no_evidence_nodes":
                logger.warning(
                    "hybrid_search.no_evidence_nodes",
                    extra={
                        "event": "hybrid_search.no_evidence_nodes",
                        "query_len": len(query or ""),
                        "evidence_max_depth": evidence_max_depth,
                        "n_results": len(formatted_results),
                    },
                )

        # 検索結果のテキスト長の合計をログに記録（LLMへのコンテキストサイズ確認用）
        total_text_length = sum(len(r["text"]) for r in formatted_results)
        if formatted_results:
            logger.info(
                "hybrid_search.result_details",
                extra={
                    "event": "hybrid_search.result_details",
                    "n_results": len(formatted_results),
                    "total_text_length": total_text_length,
                    "avg_text_length": total_text_length / len(formatted_results),
                    "file_types": list(set(r["metadata"].get("file_type", "unknown") for r in formatted_results)),
                },
            )
        
        return formatted_results
    except Exception:
        logger.exception(
            "hybrid_search.error",
            extra={
                "event": "hybrid_search.error",
                "query_len": len(query or ""),
                "k_vector": top_k_vector,
                "k_semantic": limit_meta,
                "duration_ms": int((perf_counter() - started) * 1000),
                "use_query_expansion": use_query_expansion,
                "use_rerank": use_rerank,
                "use_graph": use_graph,
                "use_mmr": use_mmr,
                "mmr_lambda": mmr_lambda,
                "mmr_top_k": mmr_top_k,
                "use_evidence_extraction": use_evidence_extraction,
                "evidence_max_depth": evidence_max_depth,
                "filter_file_name": file_name,
                "filter_document_id": file_path,
                "filter_file_type": file_type,
                "filter_page_number": page_number,
            },
        )
        raise


@mcp.tool()
def delete_document(file_path: str) -> Dict[str, Any]:
    """指定したファイルパスのドキュメントを削除する。

    ベクトルDB、メタDB、Graphストアから該当ドキュメントの全チャンクを削除します。

    Args:
        file_path: 削除対象のファイルの絶対パス（document_id）。

    Returns:
        Dict[str, Any]: 削除結果の辞書。以下のキーを含みます:
            - file_path: 削除対象のファイルパス
            - num_chunks_deleted: 削除されたチャンク数

    Raises:
        ValueError: ファイルパスが指定されていない場合、または該当ドキュメントが見つからない場合。

    Example:
        >>> result = delete_document("E:/documents/example.pdf")
        >>> print(result["num_chunks_deleted"])
        50
    """
    started = perf_counter()
    if not file_path:
        raise ValueError("file_pathが指定されていません")

    logger.info(
        "delete_document.start",
        extra={"event": "delete_document.start", "document_id": file_path},
    )
    try:
        # 1. 該当ドキュメントの全チャンクIDを取得
        t0 = perf_counter()
        chunks = searcher.metadata_store.meta_search(
            file_path=file_path,
            limit=1000000,  # 大きな値を指定して全件取得
        )
        ms_meta_lookup = int((perf_counter() - t0) * 1000)
        if not chunks:
            raise ValueError(f"指定されたファイルパスのドキュメントが見つかりません: {file_path}")

        chunk_ids = [chunk.chunk_id for chunk in chunks]
        n_chunks_deleted = len(chunk_ids)

        # 2. ベクトルストアから削除
        t0 = perf_counter()
        searcher.vector_store.delete(chunk_ids)
        ms_vector_delete = int((perf_counter() - t0) * 1000)

        # 3. メタデータストアから削除
        t0 = perf_counter()
        searcher.metadata_store.delete_by_chunk_ids(chunk_ids)
        ms_meta_delete = int((perf_counter() - t0) * 1000)

        # 4. Graphストアから削除（ノードとエッジを削除）
        ms_graph_delete = 0
        ms_graph_save = 0
        if searcher.graph_store is not None:
            t0 = perf_counter()
            for chunk_id in chunk_ids:
                if searcher.graph_store.has_node(chunk_id):
                    searcher.graph_store._graph.remove_node(chunk_id)
            ms_graph_delete = int((perf_counter() - t0) * 1000)
            # Graphストアを永続化
            if searcher.graph_store.persist_path is not None:
                t0 = perf_counter()
                try:
                    searcher.graph_store.save()
                    ms_graph_save = int((perf_counter() - t0) * 1000)
                except Exception:  # noqa: BLE001
                    # pickle.dump対象のグラフノード/エッジには任意のメタデータが
                    # 含まれ得るため、送出され得る例外を特定の型に絞り込めない。
                    # 保存失敗はドキュメント削除の成否に影響しない補助情報のため、
                    # 意図的に広く捕捉して警告ログのみに留める。
                    logger.warning(
                        "delete_document.graph_save_failed",
                        extra={"event": "delete_document.graph_save_failed", "document_id": file_path},
                    )

        result = {
            "file_path": file_path,
            "num_chunks_deleted": n_chunks_deleted,
            # Observability
            "meta_lookup_ms": ms_meta_lookup,
            "vector_delete_ms": ms_vector_delete,
            "meta_delete_ms": ms_meta_delete,
            "graph_delete_ms": ms_graph_delete,
            "graph_save_ms": ms_graph_save,
        }

        logger.info(
            "delete_document.done",
            extra={
                "event": "delete_document.done",
                "document_id": file_path,
                "n_chunks_deleted": n_chunks_deleted,
                "ms_meta_lookup": ms_meta_lookup,
                "ms_vector_delete": ms_vector_delete,
                "ms_meta_delete": ms_meta_delete,
                "ms_graph_delete": ms_graph_delete,
                "ms_graph_save": ms_graph_save,
                "duration_ms": int((perf_counter() - started) * 1000),
            },
        )
        return result
    except Exception:
        logger.exception(
            "delete_document.error",
            extra={
                "event": "delete_document.error",
                "document_id": file_path,
                "duration_ms": int((perf_counter() - started) * 1000),
            },
        )
        raise


@mcp.tool()
def list_documents() -> List[Dict[str, Any]]:
    """RAGシステムに登録されているドキュメント（ファイル）の一覧を取得する。

    メタデータストアから登録済みの全ドキュメントを取得し、
    ファイルパスごとにグループ化して返します。

    Returns:
        List[Dict[str, Any]]: ドキュメント一覧のリスト。各要素は以下のキーを含みます:
            - file_path: ファイルの絶対パス
            - file_name: ファイル名
            - file_type: ファイル種別（"txt", "md", "pdf", "docx", "xlsx", "pptx", "sysml" など）
            - num_chunks: そのドキュメントに含まれるチャンク数

    Example:
        >>> documents = list_documents()
        >>> print(f"登録されているドキュメント数: {len(documents)}")
        >>> for doc in documents[:5]:
        ...     print(f"{doc['file_name']} ({doc['file_type']}): {doc['num_chunks']} chunks")
    """
    started = perf_counter()
    logger.info(
        "list_documents.start",
        extra={"event": "list_documents.start"},
    )
    try:
        # すべてのドキュメントを取得（file_pathでグループ化）
        # 大きなlimitを指定して全チャンクを取得
        all_chunks = searcher.metadata_store.meta_search(limit=1000000)
        
        # ファイルパスごとにグループ化（データベースに保存されているパスをそのまま使用）
        documents_map: Dict[str, Dict[str, Any]] = {}
        for chunk in all_chunks:
            file_path = chunk.file_path
            if file_path not in documents_map:
                documents_map[file_path] = {
                    "file_path": file_path,
                    "file_name": chunk.file_name,
                    "file_type": chunk.file_type,
                    "num_chunks": 0,
                }
            documents_map[file_path]["num_chunks"] += 1
        
        documents = list(documents_map.values())
        documents.sort(key=lambda x: x["file_name"])
        
        logger.info(
            "list_documents.done",
            extra={
                "event": "list_documents.done",
                "n_documents": len(documents),
                "total_chunks": sum(d["num_chunks"] for d in documents),
                "duration_ms": int((perf_counter() - started) * 1000),
            },
        )
        
        return documents
    except Exception:
        logger.exception(
            "list_documents.error",
            extra={
                "event": "list_documents.error",
                "duration_ms": int((perf_counter() - started) * 1000),
            },
        )
        raise


@mcp.tool()
def update_document(path: str) -> Dict[str, Any]:
    """指定パスのファイルを更新（再インデックス）する。

    既存のドキュメントを削除してから、新しいファイルをインデックス化します。
    ファイルが存在しない場合はエラーになります。

    Args:
        path: 更新対象のファイルの絶対パス。

    Returns:
        Dict[str, Any]: 更新結果の辞書。以下のキーを含みます:
            - document_id: ドキュメントID（絶対パス）
            - file_name: ファイル名
            - file_type: ファイル種別
            - num_chunks: チャンク数
            - num_chunks_deleted: 削除されたチャンク数（既存ドキュメントがあった場合）

    Raises:
        FileNotFoundError: ファイルが存在しない場合。

    Example:
        >>> result = update_document("E:/documents/example.pdf")
        >>> print(result["num_chunks"])
        50
    """
    started = perf_counter()
    t0 = perf_counter()
    p = _validate_index_target(path)
    ms_validate = int((perf_counter() - t0) * 1000)
    document_id = str(p)

    logger.info(
        "update_document.start",
        extra={"event": "update_document.start", "document_id": document_id, "ms_validate": ms_validate},
    )
    try:
        # 1. 既存ドキュメントを削除（存在する場合）
        num_chunks_deleted = 0
        ms_delete_existing = 0
        try:
            t0 = perf_counter()
            delete_result = delete_document(document_id)
            num_chunks_deleted = delete_result.get("num_chunks_deleted", 0)
            ms_delete_existing = int((perf_counter() - t0) * 1000)
        except ValueError:
            # 既存ドキュメントが存在しない場合はスキップ
            pass

        # 2. 新しいファイルをインデックス化
        t0 = perf_counter()
        result = index_document(
            p,
            vector_store=searcher.vector_store,
            metadata_store=searcher.metadata_store,
            graph_store=searcher.graph_store,
        )
        ms_index = int((perf_counter() - t0) * 1000)
        result["num_chunks_deleted"] = num_chunks_deleted
        result["validate_ms"] = ms_validate
        result["delete_existing_ms"] = ms_delete_existing
        result["index_ms"] = ms_index

        logger.info(
            "update_document.done",
            extra={
                "event": "update_document.done",
                "document_id": document_id,
                "file_name": result.get("file_name"),
                "file_type": result.get("file_type"),
                "n_chunks": result.get("num_chunks"),
                "n_chunks_deleted": num_chunks_deleted,
                "ms_validate": ms_validate,
                "ms_delete_existing": ms_delete_existing,
                "ms_index": ms_index,
                "ms_load": result.get("load_ms"),
                "ms_vector": result.get("vector_ms"),
                "ms_meta": result.get("meta_ms"),
                "ms_graph": result.get("graph_ms"),
                "duration_ms": int((perf_counter() - started) * 1000),
            },
        )
        return result
    except Exception:
        logger.exception(
            "update_document.error",
            extra={
                "event": "update_document.error",
                "document_id": document_id,
                "ms_validate": ms_validate,
                "duration_ms": int((perf_counter() - started) * 1000),
            },
        )
        raise


if __name__ == "__main__":
    mcp.run()


