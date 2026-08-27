"""軽量GraphRAGによる検索結果の拡張(グラフ近傍を用いたリランク・要約・根拠抽出)。"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Tuple

from .config import LLM_MODEL
from .graph_store import GraphStore, Neighbor
from .metadata_store import MetadataStore
from .query_expansion import _get_openai_client
from .search_result import HybridSearchResult
from .search_scoring import _apply_metadata_filter_to_meta

logger = logging.getLogger(__name__)


def _apply_graph_aware_rerank(
    results: List[HybridSearchResult],
    *,
    graph_store: GraphStore,
    graph_seed_k: int = 3,
    distance_weight: float = 0.3,
    degree_weight: float = 0.2,
    centrality_weight: float = 0.1,
) -> List[HybridSearchResult]:
    """Graph-aware再ランキングを適用する（GraphRAG強化: フェーズ6）。

    グラフの特徴量（距離、次数、中心性）を考慮してスコアを調整し、
    Graphで拾った候補の中から、本当に重要なノードを前に出します。

    Args:
        results: 検索結果のリスト（Graph拡張後）。
        graph_store: グラフストアインスタンス。
        graph_seed_k: 起点となる上位候補数（距離計算用）。
        distance_weight: 距離による加点の重み（デフォルト: 0.3）。
        degree_weight: 次数による加点の重み（デフォルト: 0.2）。
        centrality_weight: 中心性による加点の重み（デフォルト: 0.1）。

    Returns:
        List[HybridSearchResult]: Graph-aware再ランキング後の検索結果。
    """
    if not results:
        return results
    if graph_store.num_nodes() == 0:
        return results

    # 起点となる上位候補を取得
    seed_k = min(graph_seed_k, len(results))
    seed_ids = [r.chunk_id for r in results[:seed_k]]

    # 各結果に対してグラフ特徴量を計算
    for result in results:
        chunk_id = result.chunk_id

        # 1. 距離による加点（近いほど高スコア）
        distance_bonus = 0.0
        min_distance = graph_store.get_min_distance_to_seeds(chunk_id, seed_ids, max_depth=3)
        if min_distance is not None:
            # 距離が近いほど高スコア（距離1=1.0, 距離2=0.5, 距離3=0.25）
            distance_bonus = (1.0 / (min_distance + 1)) * distance_weight

        # 2. 次数による加点（接続が多いほど高スコア）
        degree = graph_store.get_node_degree(chunk_id)
        max_degree = max(
            (graph_store.get_node_degree(r.chunk_id) for r in results if graph_store.has_node(r.chunk_id)),
            default=1,
        )
        degree_bonus = 0.0
        if max_degree > 0:
            normalized_degree = degree / max_degree
            degree_bonus = normalized_degree * degree_weight

        # 3. 中心性による加点（中心性が高いほど高スコア）
        centrality = graph_store.get_node_centrality(chunk_id)
        centrality_bonus = centrality * centrality_weight

        # スコアに加点（既存のscore_hybridに加算）
        graph_bonus = distance_bonus + degree_bonus + centrality_bonus
        result.score_hybrid += graph_bonus

        # メタデータにグラフ特徴量を記録（デバッグ用）
        result.metadata["graph_distance"] = min_distance
        result.metadata["graph_degree"] = degree
        result.metadata["graph_centrality"] = centrality
        result.metadata["graph_bonus"] = graph_bonus

    # スコアの降順で再ソート
    results.sort(key=lambda r: r.score_hybrid, reverse=True)

    return results
def _apply_local_graph_summary(
    results: List[HybridSearchResult],
    *,
    graph_store: GraphStore,
    metadata_store: MetadataStore,
    summary_depth: int = 2,
    summary_max_neighbors: int = 10,
    use_llm: bool = True,
) -> List[HybridSearchResult]:
    """局所グラフサマリを適用する（GraphRAG強化: フェーズ6）。

    近傍チャンク集合をLLMで要約し、「この手順ブロック全体」「この要件ブロック全体」
    の説明を生成して回答コンテキストに統合します。

    Args:
        results: 検索結果のリスト。
        graph_store: グラフストアインスタンス。
        metadata_store: メタデータストア（近傍チャンクの実体取得用）。
        summary_depth: サマリに含める近傍の深さ（hop数、デフォルト: 2）。
        summary_max_neighbors: サマリに含める近傍の最大数（デフォルト: 10）。
        use_llm: Trueの場合、LLMで要約を生成（デフォルト: True）。

    Returns:
        List[HybridSearchResult]: 局所グラフサマリが追加された検索結果。
    """
    if not results:
        return results
    if graph_store.num_nodes() == 0:
        return results
    if not use_llm:
        return results

    # クライアント初期化は設定不備（APIキー未設定など）以外にも実装依存の
    # 例外を送出しうる。サマリ生成はオプション機能であり、失敗しても
    # 検索結果自体は返したいため広く捕捉してスキップする。
    try:
        client = _get_openai_client()
    except Exception as e:  # noqa: BLE001
        logger.warning(f"局所グラフサマリの生成に失敗（OpenAI API未設定）: {e}")
        return results

    # 上位結果に対してのみサマリを生成（コスト削減）
    top_results = results[:5]  # 上位5件のみ

    for result in top_results:
        chunk_id = result.chunk_id

        # 近傍チャンクを取得
        neighbors = graph_store.neighbors_with_distance(
            [chunk_id],
            max_depth=summary_depth,
            limit=summary_max_neighbors,
            include_start=True,  # 自身も含める
            only_chunk_ids=True,
        )

        if len(neighbors) <= 1:
            # 近傍がない場合はスキップ
            continue

        # 近傍チャンクのテキストを取得
        neighbor_ids = [n.chunk_id for n in neighbors]
        neighbor_metas = metadata_store.get_chunks_by_chunk_ids(neighbor_ids)

        if not neighbor_metas:
            continue

        # 近傍チャンクのテキストを結合
        neighbor_texts = [m.chunk_text for m in neighbor_metas if m.chunk_text]
        if not neighbor_texts:
            continue

        combined_text = "\n\n".join(neighbor_texts)

        # LLMで要約を生成
        try:
            prompt = f"""以下のチャンク集合を要約してください。このチャンク集合は、関連する手順ブロック、要件ブロック、または概念のグループを表しています。

チャンク集合:
{combined_text[:2000]}  # 長すぎる場合は切り詰め

要約:
- このチャンク集合の主要な内容を簡潔に説明してください（2-3文程度）
- 手順の場合は、全体の流れを説明してください
- 要件の場合は、主要な要件を列挙してください
"""

            response = client.chat.completions.create(
                model=LLM_MODEL,
                messages=[
                    {
                        "role": "system",
                        "content": "あなたは技術文書の要約エキスパートです。提供されたチャンク集合を簡潔に要約してください。",
                    },
                    {"role": "user", "content": prompt},
                ],
                # reasoning モデルは temperature 非対応。max_tokens も使えない。
                # reasoning トークンも max_completion_tokens を食うため、
                # 可視出力（2-3文）に対して余裕を持たせている。
                reasoning_effort="low",
                max_completion_tokens=600,
            )

            summary = response.choices[0].message.content or ""
            if summary:
                # メタデータにサマリを追加
                result.metadata["local_graph_summary"] = summary
                # テキストの先頭にサマリを追加（オプション）
                # result.text = f"[要約] {summary}\n\n{result.text}"

        # LLM呼び出し（外部API）はネットワークエラー、レート制限、
        # レスポンス形式の変化など多様な例外を送出しうる。1件のチャンクの
        # サマリ生成失敗で検索全体を落とさないよう、広く捕捉してスキップする。
        except Exception as e:  # noqa: BLE001
            logger.warning(f"局所グラフサマリの生成に失敗（chunk_id={chunk_id}）: {e}")
            continue

    return results
def _apply_graph_expansion(
    results: List[HybridSearchResult],
    *,
    graph_store: Optional[GraphStore],
    metadata_store: MetadataStore,
    use_graph: bool,
    graph_depth: int,
    graph_seed_k: int,
    graph_max_neighbors: int,
    graph_neighbor_weight: float,
    # metadata filters (same as hybrid_search)
    file_name: Optional[str],
    file_path: Optional[str],
    file_type: Optional[str],
    page_number: Optional[int],
) -> List[HybridSearchResult]:
    """Graph近傍を用いて候補を拡張する（軽量GraphRAG）。

    検索結果の上位候補（seed）から近傍チャンクをBFSで探索し、
    候補リストに追加することで回収率を向上させます。

    方針（最小実装）:
    - 既存の上位候補（seed）から近傍ノードをBFSで辿り、近傍チャンクを候補に追加する。
    - 近傍チャンクのテキストは MetadataStore から取得する（Graphに全文は保持しない）。
    - 近傍のスコアは seed の最大スコアを基準に距離減衰で付与する（重い再計算はしない）。
    - 既存候補と重複する場合は、スコアを上げる（下げない）方向で統合する。

    Args:
        results: 既存の検索結果（ハイブリッドスコアでソート済み）。
        graph_store: グラフストアインスタンス。Noneの場合は何もしない。
        metadata_store: メタデータストア（近傍チャンクの実体取得用）。
        use_graph: Graph拡張を有効にするか。
        graph_depth: Graph探索の深さ（hop数）。
        graph_seed_k: 既存結果の上位何件を起点（seed）にするか。
        graph_max_neighbors: Graphから追加する近傍候補の最大数。
        graph_neighbor_weight: 近傍候補のスコア付与係数（距離減衰の基準値）。
        file_name: メタデータフィルタ（ファイル名）。
        file_path: メタデータフィルタ（ファイルパス）。
        file_type: メタデータフィルタ（ファイル種別）。
        page_number: メタデータフィルタ（ページ番号）。

    Returns:
        List[HybridSearchResult]: Graph拡張後の検索結果（ハイブリッドスコアで再ソート済み）。
            Graph拡張されたチャンクには `metadata["graph_expanded"]=True` が付与されます。
    """
    if not use_graph:
        return results
    if graph_store is None:
        return results
    if graph_depth <= 0:
        return results
    if graph_seed_k <= 0:
        return results
    if graph_max_neighbors <= 0:
        return results
    if not results:
        return results

    seed_k = min(graph_seed_k, len(results))
    seeds = results[:seed_k]
    seed_ids = [r.chunk_id for r in seeds]
    base_score = max((r.score_hybrid for r in seeds), default=0.0)
    if base_score <= 0.0:
        return results

    neighbors: List[Neighbor] = graph_store.neighbors_with_distance(
        seed_ids,
        max_depth=graph_depth,
        limit=graph_max_neighbors,
        include_start=False,
        only_chunk_ids=True,
    )
    if not neighbors:
        return results

    # chunk_id -> (min_distance, relation)
    dist_map: Dict[str, Tuple[int, Optional[str]]] = {}
    for n in neighbors:
        prev = dist_map.get(n.chunk_id)
        if prev is None or n.distance < prev[0]:
            dist_map[n.chunk_id] = (n.distance, n.relation)

    neighbor_ids = list(dist_map.keys())
    meta_records = metadata_store.get_chunks_by_chunk_ids(neighbor_ids)
    if not meta_records:
        return results

    # metadata filter を適用
    meta_records = _apply_metadata_filter_to_meta(
        meta_records,
        file_name=file_name,
        file_path=file_path,
        file_type=file_type,
        page_number=page_number,
    )
    if not meta_records:
        return results

    existing_by_id: Dict[str, HybridSearchResult] = {r.chunk_id: r for r in results}

    # 近傍候補を追加（重複は max で統合）
    for m in meta_records:
        if m.chunk_id not in dist_map:
            continue
        distance, relation = dist_map[m.chunk_id]
        # 距離減衰（distance=1で neighbor_weight、distance=2で neighbor_weight/2 ...）
        decay = graph_neighbor_weight / float(max(1, distance))
        score = max(0.0, min(1.0, base_score * decay))

        if m.chunk_id in existing_by_id:
            # 既にある場合は、スコアを上げる（下げない）
            existing_by_id[m.chunk_id].score_hybrid = max(existing_by_id[m.chunk_id].score_hybrid, score)
            existing_by_id[m.chunk_id].metadata.setdefault("graph_expanded", True)
            continue

        md: Dict[str, Any] = {
            "file_name": m.file_name,
            "file_path": m.file_path,
            "file_type": m.file_type,
            "chunk_index": m.chunk_index,
            "page_number": m.page_number,
            "graph_expanded": True,
            "graph_distance": distance,
        }
        if relation is not None:
            md["graph_relation"] = relation

        existing_by_id[m.chunk_id] = HybridSearchResult(
            chunk_id=m.chunk_id,
            text=m.chunk_text,
            metadata=md,
            score_vector=0.0,
            score_meta=0.0,
            score_hybrid=score,
            score_rerank=0.0,
        )

    out = list(existing_by_id.values())
    out.sort(key=lambda r: r.score_hybrid, reverse=True)
    return out
def _extract_evidence_from_results(
    results: List[HybridSearchResult],
    *,
    graph_store: Optional[GraphStore],
    max_depth: int = 2,
    max_constraints: int = 10,
    max_syntax_rules: int = 10,
    max_spec_clauses: int = 10,
) -> Dict[str, Any]:
    """Hybrid RAG結果から根拠情報（Constraint, SyntaxRule, SpecClause）を抽出する。

    GraphRAG拡張: 仕様書検証向けの根拠情報を取得し、LLMへの入力に使用する。

    Args:
        results: Hybrid RAG検索結果のリスト。
        graph_store: グラフストアインスタンス。Noneの場合は空の根拠情報を返す。
        max_depth: Graph探索の最大深さ（hop数、デフォルト: 2）。
        max_constraints: 取得するConstraintの最大数（デフォルト: 10）。
        max_syntax_rules: 取得するSyntaxRuleの最大数（デフォルト: 10）。
        max_spec_clauses: 取得するSpecClauseの最大数（デフォルト: 10）。

    Returns:
        Dict[str, Any]: 根拠情報の辞書。以下のキーを含む:
            - constraints: Constraint情報のリスト
            - syntax_rules: SyntaxRule情報のリスト
            - spec_clauses: SpecClause情報のリスト
            - evidence_text: LLMへの入力用のテキスト形式
    """
    if graph_store is None or not results:
        return {
            "constraints": [],
            "syntax_rules": [],
            "spec_clauses": [],
            "evidence_text": "",
        }

    # 上位N件のチャンクIDを取得（根拠探索の起点）
    seed_chunk_ids = [r.chunk_id for r in results[:min(10, len(results))]]

    # 関連エンティティを取得
    related_entities = graph_store.get_related_entities(
        seed_chunk_ids,
        entity_types=["constraint", "syntax_rule", "spec_clause"],
        relations=["derived_from", "refers_to", "defined_in"],
        max_depth=max_depth,
    )

    # Constraint情報を整理
    constraints = related_entities.get("constraint", [])[:max_constraints]
    constraints_sorted = sorted(constraints, key=lambda x: (x["distance"], x["id"]))

    # SyntaxRule情報を整理
    syntax_rules = related_entities.get("syntax_rule", [])[:max_syntax_rules]
    syntax_rules_sorted = sorted(syntax_rules, key=lambda x: (x["distance"], x["id"]))

    # SpecClause情報を整理
    spec_clauses = related_entities.get("spec_clause", [])[:max_spec_clauses]
    spec_clauses_sorted = sorted(spec_clauses, key=lambda x: (x["distance"], x["id"]))

    # LLMへの入力用テキストを生成
    evidence_lines: List[str] = []

    if constraints_sorted:
        evidence_lines.append("Relevant Constraints:")
        for c in constraints_sorted:
            c_id = c["id"]
            c_meta = c["metadata"]
            c_name = c_meta.get("name", c_id)
            derived_from = None
            # derived_from関係を探す
            if "derived_from" in str(c.get("relation", "")):
                # 実際の実装では、エッジを辿ってSpecClauseを取得する必要がある
                pass
            if derived_from:
                evidence_lines.append(f"- {c_id} ({c_name}, derived from {derived_from})")
            else:
                evidence_lines.append(f"- {c_id} ({c_name})")
        evidence_lines.append("")

    if syntax_rules_sorted:
        evidence_lines.append("Related Syntax Rules:")
        for sr in syntax_rules_sorted:
            sr_id = sr["id"]
            sr_meta = sr["metadata"]
            sr_name = sr_meta.get("name", sr_id)
            defined_in = sr_meta.get("defined_in")
            if defined_in:
                evidence_lines.append(f"- {sr_id} ({sr_name}, defined in {defined_in})")
            else:
                evidence_lines.append(f"- {sr_id} ({sr_name})")
        evidence_lines.append("")

    if spec_clauses_sorted:
        evidence_lines.append("Spec Clauses:")
        for sc in spec_clauses_sorted:
            sc_id = sc["id"]
            sc_meta = sc["metadata"]
            clause_number = sc_meta.get("clause_number", sc_id)
            title = sc_meta.get("title", "")
            if title:
                evidence_lines.append(f"- {clause_number} ({title})")
            else:
                evidence_lines.append(f"- {clause_number}")
        evidence_lines.append("")

    evidence_text = "\n".join(evidence_lines)

    return {
        "constraints": constraints_sorted,
        "syntax_rules": syntax_rules_sorted,
        "spec_clauses": spec_clauses_sorted,
        "evidence_text": evidence_text,
    }
EVIDENCE_NOT_AVAILABLE_NOTE = (
    "根拠グラフに Constraint / SyntaxRule / SpecClause ノードが存在しないため、"
    "根拠情報は取得できませんでした。これらを出典として引用しないでください。"
)
def annotate_evidence_status(formatted_results: List[Dict[str, Any]]) -> str:
    """根拠情報が取得できたかどうかを各結果の metadata に明示する。

    根拠が空のまま黙って返すと、LLM が「Constraint / SyntaxRule から抽出した」と
    実在しない出典を名乗る原因になる。取得できなかったことを結果側から
    はっきり伝えるためのマーカーを付与する。

    ``metadata`` は検索キャッシュが保持する辞書と共有されている可能性があるため、
    コピーしてから書き換える。

    Args:
        formatted_results: ``metadata`` キーを持つ検索結果辞書のリスト（破壊的に更新）。

    Returns:
        str: 付与したステータス（``"found"`` または ``"no_evidence_nodes"``）。
    """
    has_evidence = any(r.get("metadata", {}).get("evidence_text") for r in formatted_results)
    status = "found" if has_evidence else "no_evidence_nodes"
    for r in formatted_results:
        meta = dict(r.get("metadata") or {})
        meta["evidence_status"] = status
        if status == "no_evidence_nodes":
            meta["evidence_note"] = EVIDENCE_NOT_AVAILABLE_NOTE
        r["metadata"] = meta
    return status
