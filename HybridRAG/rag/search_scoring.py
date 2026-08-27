"""検索結果のランク融合・スコア結合ロジック(RRF/rank-based/正規化)。

search.pyのRAGSearcherから利用される、ベクトル検索とメタ検索の結果を
統合するための純粋関数群。
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from .metadata_store import ChunkMetadata
from .search_result import HybridSearchResult
from .vector_store import VectorRecord


def _rank_based_scores(ids: Sequence[str]) -> Dict[str, float]:
    """シンプルな順位ベースのスコア付け。

    先頭を1.0とし、末尾に向けて線形に減少させます。

    Args:
        ids: IDのシーケンス（順位が重要）。

    Returns:
        Dict[str, float]: IDをキー、スコアを値とする辞書。
            先頭のIDが1.0、末尾が最小値になります。
    """
    n = len(ids)
    if n == 0:
        return {}
    return {cid: float(n - idx) / float(n) for idx, cid in enumerate(ids)}
def _rrf_scores(ids: Sequence[str], *, k: int = 60) -> Dict[str, float]:
    """Reciprocal Rank Fusion (RRF) のスコアを計算する。

    RRFは複数のランキング結果を統合する手法で、順位に基づいてスコアを計算します。
    距離やスケールの違いに左右されにくく、実務で安定しやすい特徴があります。

    Args:
        ids: IDのシーケンス（順位が重要）。先頭のIDが最も高いスコアを得ます。
        k: RRFのパラメータ（デフォルト: 60）。値が大きいほど順位の差が小さくなります。

    Returns:
        Dict[str, float]: IDをキー、RRFスコアを値とする辞書。
            スコアは `1 / (k + rank)` の形式で計算されます。

    Formula:
        score = sum(1 / (k + rank))
    """
    scores: Dict[str, float] = {}
    for rank, cid in enumerate(ids, start=1):
        scores[cid] = scores.get(cid, 0.0) + (1.0 / float(k + rank))
    return scores
def _dedupe_vector_results(results: Iterable[VectorRecord]) -> List[VectorRecord]:
    """ベクトル検索結果を重複除去する。

    chunk_id（VectorRecord.id）単位で重複除去します。
    最初に出現したレコードを優先します。

    Args:
        results: ベクトル検索結果のイテラブル。

    Returns:
        List[VectorRecord]: 重複除去された結果のリスト。
    """
    index: Dict[str, VectorRecord] = {}
    for r in results:
        if r.id not in index:
            index[r.id] = r
    return list(index.values())
def _dedupe_meta_results(results: Iterable[ChunkMetadata]) -> List[ChunkMetadata]:
    """メタ検索結果を重複除去する。

    chunk_id 単位で重複除去します。
    最初に出現したレコードを優先します。

    Args:
        results: メタ検索結果のイテラブル。

    Returns:
        List[ChunkMetadata]: 重複除去された結果のリスト。
    """
    index: Dict[str, ChunkMetadata] = {}
    for r in results:
        if r.chunk_id not in index:
            index[r.chunk_id] = r
    return list(index.values())
def _apply_metadata_filter_to_vector(
    results: List[VectorRecord],
    *,
    file_name: Optional[str] = None,
    file_path: Optional[str] = None,
    file_type: Optional[str] = None,
    page_number: Optional[int] = None,
) -> List[VectorRecord]:
    """ベクトル検索結果にメタデータフィルタを適用する。

    Args:
        results: ベクトル検索結果のリスト。
        file_name: ファイル名でフィルタ（完全一致）。
        file_path: ファイルパスでフィルタ（完全一致）。
        file_type: ファイル種別でフィルタ（"txt", "md", "pdf"）。
        page_number: ページ番号でフィルタ（PDFの場合）。

    Returns:
        List[VectorRecord]: フィルタ適用後の結果のリスト。
    """
    if not any([file_name, file_path, file_type, page_number is not None]):
        return results

    filtered: List[VectorRecord] = []
    for r in results:
        meta = r.metadata

        if file_name and meta.get("file_name") != file_name:
            continue
        if file_path and meta.get("file_path") != file_path:
            continue
        if file_type and meta.get("file_type") != file_type:
            continue
        if page_number is not None:
            meta_page = meta.get("page_number")
            if meta_page is None or meta_page != page_number:
                continue

        filtered.append(r)

    return filtered
def _apply_metadata_filter_to_meta(
    results: List[ChunkMetadata],
    *,
    file_name: Optional[str] = None,
    file_path: Optional[str] = None,
    file_type: Optional[str] = None,
    page_number: Optional[int] = None,
) -> List[ChunkMetadata]:
    """メタ検索結果にメタデータフィルタを適用する。

    Args:
        results: メタ検索結果のリスト。
        file_name: ファイル名でフィルタ（完全一致）。
        file_path: ファイルパスでフィルタ（完全一致）。
        file_type: ファイル種別でフィルタ（"txt", "md", "pdf"）。
        page_number: ページ番号でフィルタ（PDFの場合）。

    Returns:
        List[ChunkMetadata]: フィルタ適用後の結果のリスト。
    """
    if not any([file_name, file_path, file_type, page_number is not None]):
        return results

    filtered: List[ChunkMetadata] = []
    for r in results:
        if file_name and r.file_name != file_name:
            continue
        if file_path and r.file_path != file_path:
            continue
        if file_type and r.file_type != file_type:
            continue
        if page_number is not None:
            if r.page_number is None or r.page_number != page_number:
                continue

        filtered.append(r)

    return filtered
def combine_for_hybrid(
    vector_results: Sequence[VectorRecord],
    meta_results: Sequence[ChunkMetadata],
    *,
    weight_vector: float = 0.7,
    weight_meta: float = 0.3,
) -> List[HybridSearchResult]:
    """ベクトル検索結果とメタ検索結果を統合し、ハイブリッドスコアを計算する。

    ベクトル検索結果: VectorRecord.id を chunk_id とみなします。
    メタ検索結果: ChunkMetadata.chunk_id を chunk_id とみなします。
    ランクベースで 0〜1 に正規化し、重み付き和で最終スコアを算出します。

    Args:
        vector_results: ベクトル検索結果のシーケンス。
        meta_results: メタ検索結果のシーケンス。
        weight_vector: ベクトル検索スコアの重み（デフォルト: 0.7）。
        weight_meta: メタ検索スコアの重み（デフォルト: 0.3）。

    Returns:
        List[HybridSearchResult]: ハイブリッドスコアでソートされた結果のリスト。
    """
    # ベクトル検索側の順位スコア
    vec_ids = [r.id for r in vector_results]
    vec_rank_scores = _rank_based_scores(vec_ids)

    # メタ検索側の順位スコア
    meta_ids = [m.chunk_id for m in meta_results]
    meta_rank_scores = _rank_based_scores(meta_ids)

    # インデックスを作っておく
    vec_index: Dict[str, VectorRecord] = {r.id: r for r in vector_results}
    meta_index: Dict[str, ChunkMetadata] = {m.chunk_id: m for m in meta_results}

    all_ids = set(vec_ids) | set(meta_ids)
    results: List[HybridSearchResult] = []

    for cid in all_ids:
        sv = vec_rank_scores.get(cid, 0.0)
        sm = meta_rank_scores.get(cid, 0.0)
        hybrid_score = sv * weight_vector + sm * weight_meta

        # 表示用テキストとメタデータは、ベクトル側を優先しつつ、なければメタ側から取得
        text = ""
        metadata: Dict[str, Any] = {}

        if cid in vec_index:
            vr = vec_index[cid]
            text = vr.text
            metadata.update(vr.metadata)

        if cid in meta_index:
            mr = meta_index[cid]
            # メタデータテーブルの情報を追加
            if not text:
                text = mr.chunk_text
            metadata.setdefault("file_name", mr.file_name)
            metadata.setdefault("file_path", mr.file_path)
            metadata.setdefault("file_type", mr.file_type)
            metadata.setdefault("chunk_index", mr.chunk_index)
            if mr.page_number is not None:
                metadata.setdefault("page_number", mr.page_number)

        results.append(
            HybridSearchResult(
                chunk_id=cid,
                text=text,
                metadata=metadata,
                score_vector=sv,
                score_meta=sm,
                score_hybrid=hybrid_score,
            )
        )

    # ハイブリッドスコアの降順でソート
    results.sort(key=lambda r: r.score_hybrid, reverse=True)
    return results
def combine_for_hybrid_rrf(
    vector_results: Sequence[VectorRecord],
    meta_results: Sequence[ChunkMetadata],
    *,
    weight_vector: float = 0.7,
    weight_meta: float = 0.3,
    rrf_k: int = 60,
) -> List[HybridSearchResult]:
    """RRF（Reciprocal Rank Fusion）で統合し、重み付き和でスコア化する。

    ベクトル検索とFTS検索の結果をRRFスコアで統合します。
    距離やBM25スコアのスケール差に左右されにくく、実務で安定しやすい特徴があります。

    Args:
        vector_results: ベクトル検索結果のシーケンス。
        meta_results: メタ検索結果のシーケンス。
        weight_vector: ベクトル検索スコアの重み（デフォルト: 0.7）。
        weight_meta: メタ検索スコアの重み（デフォルト: 0.3）。
        rrf_k: RRFのパラメータ（デフォルト: 60）。

    Returns:
        List[HybridSearchResult]: RRFスコアで統合された結果のリスト。
            ハイブリッドスコアの降順でソートされます。
    """
    vec_ids = [r.id for r in vector_results]
    meta_ids = [m.chunk_id for m in meta_results]
    vec_rrf = _rrf_scores(vec_ids, k=rrf_k)
    meta_rrf = _rrf_scores(meta_ids, k=rrf_k)

    vec_index: Dict[str, VectorRecord] = {r.id: r for r in vector_results}
    meta_index: Dict[str, ChunkMetadata] = {m.chunk_id: m for m in meta_results}

    all_ids = set(vec_ids) | set(meta_ids)
    results: List[HybridSearchResult] = []
    for cid in all_ids:
        sv = vec_rrf.get(cid, 0.0)
        sm = meta_rrf.get(cid, 0.0)
        hybrid_score = sv * weight_vector + sm * weight_meta

        text = ""
        metadata: Dict[str, Any] = {}
        if cid in vec_index:
            vr = vec_index[cid]
            text = vr.text
            metadata.update(vr.metadata)
        if cid in meta_index:
            mr = meta_index[cid]
            if not text:
                text = mr.chunk_text
            metadata.setdefault("file_name", mr.file_name)
            metadata.setdefault("file_path", mr.file_path)
            metadata.setdefault("file_type", mr.file_type)
            metadata.setdefault("chunk_index", mr.chunk_index)
            if mr.page_number is not None:
                metadata.setdefault("page_number", mr.page_number)

        results.append(
            HybridSearchResult(
                chunk_id=cid,
                text=text,
                metadata=metadata,
                score_vector=sv,
                score_meta=sm,
                score_hybrid=hybrid_score,
            )
        )

    results.sort(key=lambda r: r.score_hybrid, reverse=True)
    return results
def _min_max_normalize(values: Sequence[float], *, smaller_is_better: bool) -> List[float]:
    """min-max正規化で値を0.0〜1.0の範囲に変換する。

    最小値を0.0、最大値を1.0にマッピングし、その間の値を線形補間します。
    距離やスコアなどの異なるスケールの値を統一的に扱うために使用します。

    Args:
        values: 正規化する値のシーケンス。
        smaller_is_better: Trueの場合、値が小さいほど1.0に近づくよう反転します。
            距離など「小さいほど良い」指標に使用します。

    Returns:
        List[float]: 正規化された値のリスト（0.0〜1.0の範囲）。
            すべての値が同じ場合は[1.0, 1.0, ...]を返します。

    Example:
        >>> _min_max_normalize([1.0, 2.0, 3.0], smaller_is_better=False)
        [0.0, 0.5, 1.0]
        >>> _min_max_normalize([1.0, 2.0, 3.0], smaller_is_better=True)
        [1.0, 0.5, 0.0]
    """
    if not values:
        return []
    vmin = min(values)
    vmax = max(values)
    if vmax == vmin:
        return [1.0 for _ in values]
    out = [(v - vmin) / (vmax - vmin) for v in values]  # 0..1（小さいほど0）
    if smaller_is_better:
        out = [1.0 - x for x in out]
    return out
def combine_for_hybrid_with_scores(
    vector_results: Sequence[VectorRecord],
    meta_results: Sequence[ChunkMetadata],
    *,
    weight_vector: float = 0.7,
    weight_meta: float = 0.3,
) -> List[HybridSearchResult]:
    """距離/BM25スコアを正規化して統合する。

    ベクトル検索の距離とFTS検索のBM25スコアをmin-max正規化で0.0〜1.0の範囲に変換し、
    重み付き和でハイブリッドスコアを計算します。

    Args:
        vector_results: ベクトル検索結果のシーケンス。
            VectorRecord.distanceが使用されます（小さいほど良い）。
        meta_results: メタ検索結果のシーケンス。
            ChunkMetadata.bm25_scoreが使用されます（小さいほど良い）。
        weight_vector: ベクトル検索スコアの重み（デフォルト: 0.7）。
        weight_meta: メタ検索スコアの重み（デフォルト: 0.3）。

    Returns:
        List[HybridSearchResult]: 正規化スコアで統合された結果のリスト。
            ハイブリッドスコアの降順でソートされます。

    Note:
        - 距離やBM25スコアが取得できない場合は、順位ベースの統合（combine_for_hybrid）にフォールバックします。
        - vector: distance（小さいほど良い）を0.0〜1.0に正規化してscore_vectorにします。
        - meta: bm25_score（小さいほど良い）を0.0〜1.0に正規化してscore_metaにします。
    """
    vec_results = list(vector_results)
    meta_results_list = list(meta_results)

    vec_ids = [r.id for r in vec_results]
    meta_ids = [m.chunk_id for m in meta_results_list]

    # 距離が取れない場合は順位ベースへフォールバック
    if any(r.distance is None for r in vec_results) or not vec_results:
        return combine_for_hybrid(
            vector_results=vector_results,
            meta_results=meta_results,
            weight_vector=weight_vector,
            weight_meta=weight_meta,
        )

    # bm25_score が無い場合も順位ベースへフォールバック
    if not meta_results_list or any(m.bm25_score is None for m in meta_results_list):
        return combine_for_hybrid(
            vector_results=vector_results,
            meta_results=meta_results,
            weight_vector=weight_vector,
            weight_meta=weight_meta,
        )

    vec_scores = _min_max_normalize([float(r.distance) for r in vec_results], smaller_is_better=True)
    meta_scores = _min_max_normalize([float(m.bm25_score) for m in meta_results_list], smaller_is_better=True)

    vec_score_map = {rid: score for rid, score in zip(vec_ids, vec_scores)}
    meta_score_map = {cid: score for cid, score in zip(meta_ids, meta_scores)}

    vec_index: Dict[str, VectorRecord] = {r.id: r for r in vec_results}
    meta_index: Dict[str, ChunkMetadata] = {m.chunk_id: m for m in meta_results_list}

    all_ids = set(vec_ids) | set(meta_ids)
    results: List[HybridSearchResult] = []
    for cid in all_ids:
        sv = vec_score_map.get(cid, 0.0)
        sm = meta_score_map.get(cid, 0.0)
        hybrid_score = sv * weight_vector + sm * weight_meta

        text = ""
        metadata: Dict[str, Any] = {}
        if cid in vec_index:
            vr = vec_index[cid]
            text = vr.text
            metadata.update(vr.metadata)
        if cid in meta_index:
            mr = meta_index[cid]
            if not text:
                text = mr.chunk_text
            metadata.setdefault("file_name", mr.file_name)
            metadata.setdefault("file_path", mr.file_path)
            metadata.setdefault("file_type", mr.file_type)
            metadata.setdefault("chunk_index", mr.chunk_index)
            if mr.page_number is not None:
                metadata.setdefault("page_number", mr.page_number)

        results.append(
            HybridSearchResult(
                chunk_id=cid,
                text=text,
                metadata=metadata,
                score_vector=sv,
                score_meta=sm,
                score_hybrid=hybrid_score,
            )
        )

    results.sort(key=lambda r: r.score_hybrid, reverse=True)
    return results
def detect_query_type(query: str) -> str:
    """クエリの種類を推定する（動的重み用）。

    クエリの特徴から「キーワード検索向き」か「セマンティック検索向き」かを判定します。
    この判定結果は、動的重み調整（choose_weights_for_query）で使用されます。

    Args:
        query: 検索クエリ文字列。

    Returns:
        str: クエリの種類。
            - "keyword": 短い、数字や記号が多い、ファイル名っぽい
            - "semantic": 自然文寄り

    Note:
        この関数は簡易的なヒューリスティックに基づいており、
        完全に正確な分類を保証するものではありません。
    """
    q = query.strip()
    if not q:
        return "semantic"
    if len(q) <= 10:
        return "keyword"
    if any(ch.isdigit() for ch in q):
        return "keyword"
    if any(ch in {":", "/", "\\", ".", "_", "-"} for ch in q):
        return "keyword"
    return "semantic"
def choose_weights_for_query(query: str) -> Tuple[float, float]:
    """クエリの種類に応じてベクトル検索とメタ検索の重みを選択する。

    動的重み調整機能で使用されます。キーワード検索向きのクエリでは
    メタ検索（FTS）の重みを高く、セマンティック検索向きのクエリでは
    ベクトル検索の重みを高く設定します。

    Args:
        query: 検索クエリ文字列。

    Returns:
        Tuple[float, float]: (weight_vector, weight_meta)のタプル。
            - キーワード検索向き: (0.45, 0.55)
            - セマンティック検索向き: (0.8, 0.2)
    """
    qt = detect_query_type(query)
    if qt == "keyword":
        return 0.45, 0.55
    return 0.8, 0.2
def _extract_file_key(result: HybridSearchResult) -> str:
    """検索結果からファイルキー（ファイルパスまたはドキュメントID）を抽出する。

    メタデータからfile_pathまたはdocument_idを取得し、それらが存在しない場合は
    chunk_idからドキュメントIDを抽出します。

    Args:
        result: ハイブリッド検索結果。

    Returns:
        str: ファイルキー（ファイルパスまたはドキュメントID）。
            chunk_idの形式が"{document_id}::chunk-{i}"の場合、document_id部分を返します。
    """
    fp = result.metadata.get("file_path") or result.metadata.get("document_id")
    if isinstance(fp, str) and fp:
        return fp
    # chunk_id: "{document_id}::chunk-{i}"
    return result.chunk_id.split("::chunk-")[0]
def _extract_chunk_index(result: HybridSearchResult) -> Optional[int]:
    """検索結果からチャンクインデックスを抽出する。

    メタデータからchunk_indexを取得し、それらが存在しない場合は
    chunk_idからインデックスを抽出します。

    Args:
        result: ハイブリッド検索結果。

    Returns:
        Optional[int]: チャンクインデックス。取得できない場合はNone。
            chunk_idの形式が"{document_id}::chunk-{i}"の場合、i部分を返します。
    """
    v = result.metadata.get("chunk_index")
    if isinstance(v, int):
        return v
    if isinstance(v, str) and v.isdigit():
        return int(v)
    # chunk_id から推定
    if "::chunk-" in result.chunk_id:
        try:
            return int(result.chunk_id.split("::chunk-")[-1])
        except ValueError:
            return None
    return None
