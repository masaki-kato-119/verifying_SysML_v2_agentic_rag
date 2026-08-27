"""eval/qa_golden_set.json を使って検索精度(無料)を測定する。

LLM を一切呼ばず、HybridRAG の ``RAGSearcher.search_hybrid`` と GraphRAG の
``GraphQueryEngine`` を直接（インプロセスで）呼び出して評価する。

**設計メモ:** 当初案では ``HybridRAG/mcp_server.py`` を FastMCP クライアント経由の
サブプロセスとして起動し、実際の MCP ツール呼び出しを再現する予定だった。しかし
``mcp_server.py`` はモジュール読み込み時に ``preload_reranker()`` を無条件に呼び、
Cross-Encoder モデルを HuggingFace から取得しようとするため、起動のたびに
数十秒〜のネットワーク依存の遅延が発生する（``use_rerank=False`` がデフォルトでも
発生する）。「無料・即実行可」というこのスクリプトの目的に反するため、
``RAGSearcher``/``GraphQueryEngine`` を直接 import して呼び出す方式にしている。
呼び出しているのは MCP ツールが薄くラップしている実体そのものであり、
検索ロジック自体は同一である。

使い方::

    python scripts/run_retrieval_eval.py                  # 全ケース実行
    python scripts/run_retrieval_eval.py --only qa-hybrid-01,qa-graph-01
    python scripts/run_retrieval_eval.py --with-rerank              # Cross-Encoderリランキングを有効化(無料)
    python scripts/run_retrieval_eval.py --with-query-expansion     # LLMクエリ拡張を有効化(実APIコストあり)

``--with-rerank``/``--with-query-expansion`` は Hybrid検索ケースにのみ影響する
（GraphRAGの経路・近傍探索には影響しない）。
"""

from __future__ import annotations

import argparse
import json
import pickle
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "HybridRAG"))
sys.path.insert(0, str(REPO_ROOT / "GraphRAG"))

DEFAULT_GOLDEN = REPO_ROOT / "eval" / "qa_golden_set.json"
DEFAULT_RESULTS_DIR = REPO_ROOT / "eval" / "results"
K_VALUES = (3, 5, 10)


def chunk_index_of(metadata: dict) -> str | None:
    """検索結果の metadata から chunk_index を文字列で取り出す。"""
    idx = (metadata or {}).get("chunk_index")
    return str(idx) if idx is not None else None


def load_golden_set(path: Path, only: set[str] | None) -> list[dict]:
    spec = json.loads(path.read_text(encoding="utf-8"))
    cases = spec["cases"]
    if only:
        cases = [c for c in cases if c["id"] in only]
    return cases


def eval_hybrid_case(searcher, case: dict, *, use_rerank: bool = False, use_query_expansion: bool = False) -> dict:
    from rag.eval import mrr as _mrr  # noqa: F401  (使わないが将来の一括集計用に残す)
    from rag.eval import ndcg_at_k, precision_at_k, recall_at_k, reciprocal_rank

    results = searcher.search_hybrid(
        case["query"],
        top_k_vector=40,
        limit_meta=40,
        use_rerank=use_rerank,
        use_query_expansion=use_query_expansion,
    )
    ranked = [chunk_index_of(r.metadata) for r in results]
    ranked = [c for c in ranked if c is not None]
    relevant = {str(c) for c in case["relevant_chunk_ids"]}

    metrics = {"rr": reciprocal_rank(ranked, relevant)}
    for k in K_VALUES:
        metrics[f"recall@{k}"] = recall_at_k(ranked, relevant, k=k)
        metrics[f"precision@{k}"] = precision_at_k(ranked, relevant, k=k)
        metrics[f"ndcg@{k}"] = ndcg_at_k(ranked, relevant, k=k)
    return {
        "id": case["id"],
        "type": "hybrid",
        "query": case["query"],
        "relevant_chunk_ids": sorted(relevant),
        "ranked_top10": ranked[:10],
        "metrics": metrics,
    }


def eval_graph_path_case(query_engine, case: dict) -> dict:
    from graphrag.eval import (
        path_exact_match,
        path_node_overlap,
        relation_sequence_match,
    )

    expected = case["expected_graph_path"]
    result = query_engine.find_path(expected["start_node"], expected["end_node"])
    success = bool(result.get("success"))
    actual_nodes = result.get("path", []) if success else []
    actual_relations = [e.get("relation", "") for e in result.get("edges", [])] if success else []

    return {
        "id": case["id"],
        "type": "graph_path",
        "query": case["query"],
        "success": success,
        "error": result.get("error") if not success else None,
        "expected_nodes": list(expected["nodes"]),
        "actual_nodes": actual_nodes,
        "metrics": {
            "exact_match": path_exact_match(actual_nodes, expected["nodes"]),
            "node_overlap": path_node_overlap(actual_nodes, expected["nodes"]),
            "relation_sequence_match": relation_sequence_match(
                actual_relations, expected["relations"]
            ),
        },
    }


def eval_graph_neighbor_case(graph, case: dict) -> dict:
    from graphrag.eval import neighbor_precision_recall

    spec = case["expected_neighbors"]
    node = spec["node"]
    if node not in graph:
        return {
            "id": case["id"],
            "type": "graph_neighbors",
            "query": case["query"],
            "success": False,
            "error": f"ノード '{node}' がグラフに存在しません",
            "metrics": {},
        }

    actual_out = {(d.get("relation", ""), v) for _, v, d in graph.out_edges(node, data=True)}
    actual_in = {(d.get("relation", ""), u) for u, _, d in graph.in_edges(node, data=True)}
    expected_out = {(e["relation"], e["target"]) for e in spec.get("outgoing", [])}
    expected_in = {(e["relation"], e["source"]) for e in spec.get("incoming", [])}

    out_p, out_r = neighbor_precision_recall(actual_out, expected_out)
    in_p, in_r = neighbor_precision_recall(actual_in, expected_in)

    return {
        "id": case["id"],
        "type": "graph_neighbors",
        "query": case["query"],
        "success": True,
        "actual_outgoing": sorted(actual_out),
        "actual_incoming": sorted(actual_in),
        "metrics": {
            "outgoing_precision": out_p,
            "outgoing_recall": out_r,
            "incoming_precision": in_p,
            "incoming_recall": in_r,
        },
    }


def find_default_graph_path() -> Path | None:
    from graphrag.config import GRAPHS_DIR

    if not GRAPHS_DIR.exists():
        return None
    candidates = sorted(GRAPHS_DIR.glob("*.pkl"))
    return candidates[0] if candidates else None


def print_summary(results: list[dict]) -> None:
    hybrid = [r for r in results if r["type"] == "hybrid"]
    graph_paths = [r for r in results if r["type"] == "graph_path"]
    graph_neighbors = [r for r in results if r["type"] == "graph_neighbors"]
    skipped = [r for r in results if r["type"] == "skipped"]

    if hybrid:
        print(f"\n== Hybrid検索 ({len(hybrid)}件) ==")
        for k in K_VALUES:
            mean_recall = sum(r["metrics"][f"recall@{k}"] for r in hybrid) / len(hybrid)
            mean_prec = sum(r["metrics"][f"precision@{k}"] for r in hybrid) / len(hybrid)
            mean_ndcg = sum(r["metrics"][f"ndcg@{k}"] for r in hybrid) / len(hybrid)
            print(
                f"  k={k:<2} Recall={mean_recall:.3f} Precision={mean_prec:.3f} nDCG={mean_ndcg:.3f}"
            )
        mean_rr = sum(r["metrics"]["rr"] for r in hybrid) / len(hybrid)
        print(f"  MRR={mean_rr:.3f}")
        for r in hybrid:
            print(f"    {r['id']:<20} RR={r['metrics']['rr']:.2f} Recall@5={r['metrics']['recall@5']:.2f}")

    if graph_paths:
        print(f"\n== Graph経路探索 ({len(graph_paths)}件) ==")
        exact = sum(1 for r in graph_paths if r["metrics"].get("exact_match")) if all(
            "metrics" in r and r["metrics"] for r in graph_paths
        ) else 0
        overlaps = [r["metrics"].get("node_overlap", 0.0) for r in graph_paths if r.get("success")]
        mean_overlap = sum(overlaps) / len(overlaps) if overlaps else 0.0
        print(f"  完全一致: {exact}/{len(graph_paths)}  平均ノード重なり(Jaccard): {mean_overlap:.3f}")
        for r in graph_paths:
            if not r.get("success"):
                print(f"    {r['id']:<20} FAILED: {r.get('error')}")
            else:
                print(
                    f"    {r['id']:<20} exact={r['metrics']['exact_match']} "
                    f"overlap={r['metrics']['node_overlap']:.2f} "
                    f"relations_match={r['metrics']['relation_sequence_match']}"
                )

    if graph_neighbors:
        print(f"\n== Graph近傍探索 ({len(graph_neighbors)}件) ==")
        for r in graph_neighbors:
            if not r.get("success"):
                print(f"    {r['id']:<20} FAILED: {r.get('error')}")
                continue
            m = r["metrics"]
            print(
                f"    {r['id']:<20} out P={m['outgoing_precision']:.2f} R={m['outgoing_recall']:.2f} "
                f"in P={m['incoming_precision']:.2f} R={m['incoming_recall']:.2f}"
            )

    if skipped:
        print(f"\n== スキップ ({len(skipped)}件、answerable=false のため対象外) ==")
        for r in skipped:
            print(f"    {r['id']}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--golden", default=str(DEFAULT_GOLDEN))
    parser.add_argument("--graph-path", default="", help="GraphRAGのpklパス（省略時は自動検出）")
    parser.add_argument("--only", default="", help="カンマ区切りのcase idで絞り込む")
    parser.add_argument("--output-dir", default=str(DEFAULT_RESULTS_DIR))
    parser.add_argument(
        "--with-rerank",
        action="store_true",
        help="Hybrid検索でCross-Encoderリランキングを有効化する(無料・ローカル。初回はHuggingFaceからモデル取得が発生)",
    )
    parser.add_argument(
        "--with-query-expansion",
        action="store_true",
        help="Hybrid検索でLLMクエリ拡張を有効化する(ケースごとに実APIコストが発生。OPENAI_API_KEYが必要)",
    )
    args = parser.parse_args()

    if args.with_rerank:
        from rag.search import preload_reranker

        print("Cross-Encoderリランカーを先読み中...")
        preload_reranker()

    only = {c.strip() for c in args.only.split(",") if c.strip()} or None
    cases = load_golden_set(Path(args.golden), only)
    if not cases:
        print("対象ケースがありません。")
        return 1

    hybrid_cases = [c for c in cases if c.get("relevant_chunk_ids") and c.get("answerable", True)]
    graph_path_cases = [c for c in cases if c.get("expected_graph_path")]
    graph_neighbor_cases = [c for c in cases if c.get("expected_neighbors")]
    skipped_cases = [
        c
        for c in cases
        if not c.get("answerable", True)
        or c["id"] not in {x["id"] for x in hybrid_cases + graph_path_cases + graph_neighbor_cases}
    ]

    results: list[dict] = []

    if hybrid_cases:
        from rag.search import RAGSearcher

        print(f"HybridRAG インデックスを読み込み中... ({len(hybrid_cases)}件を評価)")
        searcher = RAGSearcher()
        for case in hybrid_cases:
            results.append(
                eval_hybrid_case(
                    searcher,
                    case,
                    use_rerank=args.with_rerank,
                    use_query_expansion=args.with_query_expansion,
                )
            )

    if graph_path_cases or graph_neighbor_cases:
        graph_path = Path(args.graph_path) if args.graph_path else find_default_graph_path()
        if graph_path is None or not graph_path.exists():
            print(f"警告: GraphRAGのグラフファイルが見つかりません（{graph_path}）。グラフ系ケースをスキップします。")
        else:
            from graphrag.query_engine import GraphQueryEngine

            print(f"GraphRAG グラフを読み込み中... ({graph_path.name})")
            # セキュリティ注意: pickle.load()は逆シリアライズ時に任意コードを実行し得る。
            # --graph-pathはこのスクリプトを実行する開発者自身が指定するローカルCLI引数
            # であり、リモートやLLM経由で到達可能な入力ではないため許容しているが、
            # 信頼できない相手から受け取ったグラフファイルを指定してはならない。
            with open(graph_path, "rb") as f:
                graph = pickle.load(f)
            query_engine = GraphQueryEngine(graph)
            for case in graph_path_cases:
                results.append(eval_graph_path_case(query_engine, case))
            for case in graph_neighbor_cases:
                results.append(eval_graph_neighbor_case(graph, case))

    for case in skipped_cases:
        results.append({"id": case["id"], "type": "skipped", "reason": "answerable=false or no ground truth for retrieval"})

    print_summary(results)

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_path = output_dir / f"retrieval_{ts}.json"
    out_path.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n結果を保存しました: {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
