"""MMR(最大マージナル関連性)による多様性確保・コンテキストウィンドウ結合。"""

from __future__ import annotations

import logging
from typing import Dict, List, Optional

from .embedding import embed_text, embed_texts
from .metadata_store import MetadataStore
from .search_result import HybridSearchResult
from .search_scoring import _extract_chunk_index, _extract_file_key

logger = logging.getLogger(__name__)


def _apply_mmr(
    results: List[HybridSearchResult],
    query: str,
    *,
    lambda_param: float = 0.5,
    top_k: Optional[int] = None,
) -> List[HybridSearchResult]:
    """Maximal Marginal Relevance (MMR) を適用して多様性を確保する。
    
    MMRは、関連性と多様性のバランスを取るアルゴリズムです。
    類似した結果の重複を減らし、多様性を向上させます。
    
    Args:
        results: ハイブリッド検索結果のリスト（スコア降順でソート済み）。
        query: 検索クエリ。
        lambda_param: 関連性と多様性のバランス（0.0=多様性優先、1.0=関連性優先、デフォルト: 0.5）。
        top_k: 返す結果の最大数。Noneの場合はすべて返します。
    
    Returns:
        List[HybridSearchResult]: MMR適用後の結果リスト（関連性と多様性のバランスが取れた順序）。
    
    Algorithm:
        1. 最初の結果は最も関連性の高いものを選択
        2. 以降は (lambda * relevance) - ((1-lambda) * max_similarity_to_selected) で選択
        3. 選択された結果をselectedに追加し、繰り返す
    """
    if not results:
        return results
    
    if top_k is None:
        top_k = len(results)
    
    if top_k <= 0:
        return []
    
    # クエリの埋め込みを取得
    # embed_text は外部API呼び出しであり、ネットワークエラーやAPI側の
    # 一時的な障害など多様な例外を送出しうる。MMRは検索結果の並び替えを
    # 補助する機能に過ぎないため、失敗時は元の結果をそのまま返して
    # 検索全体を落とさないようにする。
    try:
        query_embedding = embed_text(query)
    except Exception as e:  # noqa: BLE001
        logger.warning(
            "mmr.query_embedding_failed",
            extra={"event": "mmr.query_embedding_failed", "error": str(e)},
        )
        # 埋め込み取得に失敗した場合は、元の結果を返す
        return results[:top_k]
    
    # 各結果のテキストの埋め込みをバッチAPIで一括取得する。
    #
    # 以前は候補ごとに embed_text を呼んでいたため、候補 40 件で 41 回の
    # 逐次 API 往復が発生し、MMR だけで 10 秒以上（検索全体の 93%）を
    # 消費していた。embed_texts は同じ内容を 1 リクエストで取得する。
    result_embeddings: List[List[float]] = []
    try:
        result_embeddings = embed_texts([result.text for result in results])
    except Exception as e:  # noqa: BLE001
        # 外部APIの呼び出しであり例外の種類を限定できない。
        # バッチは全件失敗になるため、1 件ずつの取得へフォールバックする。
        # 単一テキストの不具合で MMR 全体が落ちるのを避けるため、
        # 個別失敗はゼロベクトル（類似度 0）として扱う従来の挙動を維持する。
        logger.warning(
            "mmr.batch_embedding_failed",
            extra={
                "event": "mmr.batch_embedding_failed",
                "num_results": len(results),
                "error": str(e),
            },
        )
        result_embeddings = []
        for result in results:
            # 個別フォールバックも外部API呼び出しのため、例外種別を限定せず、
            # 失敗した1件だけをゼロベクトル扱いにしてループを継続する。
            try:
                result_embeddings.append(embed_text(result.text))
            except Exception as inner:  # noqa: BLE001
                logger.warning(
                    "mmr.result_embedding_failed",
                    extra={
                        "event": "mmr.result_embedding_failed",
                        "chunk_id": result.chunk_id,
                        "error": str(inner),
                    },
                )
                result_embeddings.append([0.0] * len(query_embedding))
    
    # コサイン類似度を計算する関数
    def cosine_similarity(a: List[float], b: List[float]) -> float:
        """コサイン類似度を計算する。"""
        if not a or not b or len(a) != len(b):
            return 0.0
        dot_product = sum(x * y for x, y in zip(a, b))
        norm_a = sum(x * x for x in a) ** 0.5
        norm_b = sum(x * x for x in b) ** 0.5
        if norm_a == 0.0 or norm_b == 0.0:
            return 0.0
        return dot_product / (norm_a * norm_b)
    
    # クエリとの関連性スコアを計算（既存のスコアを使用）
    # スコアが高いほど関連性が高い
    relevance_scores = [
        result.score_rerank if result.score_rerank > 0.0 else result.score_hybrid
        for result in results
    ]
    
    # 正規化（0.0〜1.0の範囲に）
    max_relevance = max(relevance_scores) if relevance_scores else 1.0
    if max_relevance > 0.0:
        relevance_scores = [s / max_relevance for s in relevance_scores]
    
    # MMRアルゴリズム
    selected: List[int] = []
    remaining = set(range(len(results)))
    
    # 最初の結果は最も関連性の高いものを選択
    if remaining:
        best_idx = max(remaining, key=lambda i: relevance_scores[i])
        selected.append(best_idx)
        remaining.remove(best_idx)
    
    # 以降はMMRスコアで選択
    while remaining and len(selected) < top_k:
        best_mmr_score = float("-inf")
        best_idx = None
        
        for candidate_idx in remaining:
            # 関連性スコア
            relevance = relevance_scores[candidate_idx]
            
            # 選択済み結果との最大類似度
            max_similarity = 0.0
            if selected:
                candidate_embedding = result_embeddings[candidate_idx]
                for selected_idx in selected:
                    selected_embedding = result_embeddings[selected_idx]
                    similarity = cosine_similarity(candidate_embedding, selected_embedding)
                    max_similarity = max(max_similarity, similarity)
            
            # MMRスコア: (lambda * relevance) - ((1-lambda) * max_similarity)
            mmr_score = (lambda_param * relevance) - ((1.0 - lambda_param) * max_similarity)
            
            if mmr_score > best_mmr_score:
                best_mmr_score = mmr_score
                best_idx = candidate_idx
        
        if best_idx is not None:
            selected.append(best_idx)
            remaining.remove(best_idx)
        else:
            # これ以上選択できない場合は終了
            break
    
    # 選択された結果を返す
    return [results[i] for i in selected]
def _apply_diversity_limit(
    results: List[HybridSearchResult],
    *,
    max_chunks_per_file: Optional[int],
) -> List[HybridSearchResult]:
    """ファイル単位で結果の多様性を確保するための制限を適用する。

    1つのファイルから返すチャンク数を制限することで、複数のファイルからの
    結果を含めることができ、検索結果の多様性が向上します。

    Args:
        results: 検索結果のリスト（スコア降順でソート済み）。
        max_chunks_per_file: 1ファイルから返す最大チャンク数。
            Noneの場合は制限なし。0以下の場合は空リストを返します。

    Returns:
        List[HybridSearchResult]: 多様性制限適用後の結果リスト。
            各ファイルから最大max_chunks_per_file件まで含まれます。
    """
    if max_chunks_per_file is None:
        return results
    if max_chunks_per_file <= 0:
        return []
    counts: Dict[str, int] = {}
    out: List[HybridSearchResult] = []
    for r in results:
        key = _extract_file_key(r)
        n = counts.get(key, 0)
        if n >= max_chunks_per_file:
            continue
        counts[key] = n + 1
        out.append(r)
    return out
def _apply_context_window(
    results: List[HybridSearchResult],
    *,
    metadata_store: MetadataStore,
    context_window: int,
    top_k: Optional[int],
) -> List[HybridSearchResult]:
    """コンテキストウィンドウを適用して、前後のチャンクを結合する。

    検索結果の各チャンクについて、前後context_window個のチャンクを取得し、
    それらのテキストを結合して結果のtextフィールドを拡張します。
    これにより、単一のチャンクだけでなく、周辺のコンテキストも含めた
    より完全な情報を提供できます。

    Args:
        results: 検索結果のリスト。
        metadata_store: メタデータストア（近傍チャンクの取得用）。
        context_window: 前後何チャンクを結合するか。
            0以下の場合は何もせずに結果をそのまま返します。
        top_k: コンテキストウィンドウを適用する上位結果数。
            Noneの場合はすべての結果に適用します。

    Returns:
        List[HybridSearchResult]: コンテキストウィンドウ適用後の結果リスト。
            各結果のtextフィールドは、前後のチャンクを含む拡張されたテキストになります。
            メタデータに"context_expanded": Trueが追加されます。
    """
    if context_window <= 0:
        return results
    if not results:
        return results

    limit = top_k if top_k is not None else len(results)
    limit = min(limit, len(results))

    for r in results[:limit]:
        fp = _extract_file_key(r)
        idx = _extract_chunk_index(r)
        if idx is None:
            continue
        start = max(0, idx - context_window)
        end = idx + context_window
        neighbors = metadata_store.get_chunks_by_file_and_index_range(
            file_path=fp,
            start_index=start,
            end_index=end,
        )
        if not neighbors:
            continue
        expanded = "\n".join(n.chunk_text for n in neighbors)
        r.metadata.setdefault("hit_chunk_index", idx)
        r.metadata["context_window"] = context_window
        r.metadata["context_expanded"] = True
        r.text = expanded
    return results
