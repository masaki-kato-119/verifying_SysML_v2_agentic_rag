"""eval/backend_selection_queries.json を実行し、バックエンド選択率を実測する。

``openai_call_mcp`` と同じ経路（全サーバのツールを同時提示 → LLM が選択）で
各クエリを 1 ターン実行し、実際に呼ばれたバックエンドを期待値と突き合わせる。

**実 API を呼ぶためコストが発生します。** 実行前に対象クエリ数を表示し、
``--yes`` が無ければ確認を求めます。

使い方::

    python scripts/run_backend_eval.py --dry-run     # 何を実行するかだけ表示
    python scripts/run_backend_eval.py --yes         # 実行
    python scripts/run_backend_eval.py --yes --only graph-01,hybrid-01
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections import Counter
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

DEFAULT_QUERIES = REPO_ROOT / "eval" / "backend_selection_queries.json"

# 期待値のキー -> 実際のサーバ名
BACKEND_TO_SERVER = {
    "hybrid": "Hybrid RAG MCP Server",
    "graph": "Graph RAG MCP Server",
}


# execute_tool_calls_and_append がツール失敗時に返す文言
TOOL_ERROR_MARKERS = (
    "ツール実行中にエラーが発生しました",
    "ツール実行時に例外が発生しました",
    "は登録されていません",
    "ツール結果のシリアライズに失敗しました",
)


def is_tool_error(content: str) -> bool:
    """ツール結果がエラーかどうかを判定する。

    「どのバックエンドが呼ばれたか」だけを数えると、失敗した呼び出しも
    成功として集計してしまう。実際、環境変数が子プロセスへ渡らず
    HybridRAG が全滅していたのに選択率だけは記録されていた。
    """
    return any(marker in (content or "") for marker in TOOL_ERROR_MARKERS)


def classify(expected: str, servers_used: set[str]) -> str:
    """期待バックエンドと実際に呼ばれたサーバを突き合わせる。"""
    if not servers_used:
        return "no-tool-call"
    if expected == "either":
        return "ok(both)" if len(servers_used) >= 2 else "ok"
    wanted = BACKEND_TO_SERVER.get(expected)
    if wanted in servers_used:
        return "ok(+other)" if len(servers_used) > 1 else "ok"
    return "miss"


async def run(args) -> int:
    spec = json.loads(Path(args.queries).read_text(encoding="utf-8"))
    cases = spec["cases"]
    if args.only:
        wanted = {c.strip() for c in args.only.split(",")}
        cases = [c for c in cases if c["id"] in wanted]
    if not cases:
        print("対象クエリがありません。")
        return 1

    print(f"対象クエリ: {len(cases)} 件 / モデル: {args.model}")
    for c in cases:
        print(f"  {c['id']:<12} expected={c['expected_backend']:<7} {c['query'][:48]}")
    if args.dry_run:
        return 0
    if not args.yes:
        print("\n実 API を呼びます。実行するには --yes を付けてください。")
        return 1

    # openai_call_mcp はimport時にOPENAI_API_KEYの存在確認とOpenAIクライアント生成を
    # 行うため、--dry-run（APIキー不要のはず）でも失敗しないよう実行直前まで遅延させる。
    import openai_call_mcp as ocm

    system_prompt = Path(args.system_prompt_file).read_text(encoding="utf-8").strip()

    # 使用トークンを集計するため create をラップする
    usage = Counter()
    original_create = ocm.client.responses.create

    def counting_create(**kwargs):
        response = original_create(**kwargs)
        u = getattr(response, "usage", None)
        if u:
            usage["prompt"] += u.input_tokens
            usage["cached"] += getattr(
                getattr(u, "input_tokens_details", None), "cached_tokens", 0
            )
            usage["completion"] += u.output_tokens
            usage["reasoning"] += getattr(
                getattr(u, "output_tokens_details", None), "reasoning_tokens", 0
            )
            usage["calls"] += 1
        return response

    ocm.client.responses.create = counting_create

    servers = await ocm.load_mcp_servers_from_file(args.servers_file)
    if not servers:
        print("MCP サーバに接続できませんでした。")
        return 1
    tools, routing = ocm.build_tool_registry(servers)
    print(f"\n提示ツール数: {len(tools)}（{', '.join(servers)}）\n")

    results = []
    try:
        for case in cases:
            history = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": case["query"]},
            ]
            try:
                await ocm.resolve_with_history(
                    history, args.model, routing, tools, args.reasoning_effort
                )
                error = ""
            except Exception as e:  # 1 件の失敗で全体を止めない  # noqa: BLE001
                error = f"{type(e).__name__}: {e}"

            # ツール結果を call_id で引けるようにする（Responses API の入力アイテム）
            outcomes = {
                item["call_id"]: item.get("output", "")
                for item in history
                if isinstance(item, dict) and item.get("type") == "function_call_output"
            }
            called = []
            failed = []
            for item in history:
                if getattr(item, "type", None) != "function_call":
                    continue
                server = routing.get(item.name, {}).get("server", "(unknown)")
                called.append(server)
                if is_tool_error(outcomes.get(item.call_id, "")):
                    failed.append(server)
            verdict = "error" if error else classify(case["expected_backend"], set(called))
            results.append((case, verdict, called, failed, error))
            fail_note = f" 失敗={Counter(failed)}" if failed else ""
            print(
                f"  {case['id']:<12} expected={case['expected_backend']:<7} "
                f"-> {verdict:<12} calls={Counter(called) or '-'}{fail_note}"
            )
            if error:
                print(f"      {error[:150]}")
    finally:
        ocm.client.responses.create = original_create
        for s in servers.values():
            await ocm.close_mcp_client(s.get("mcp"), timeout=2.0)

    verdicts = Counter(v for _, v, _, _, _ in results)
    ok = sum(n for v, n in verdicts.items() if v.startswith("ok"))
    print(f"\n== 結果 == {ok}/{len(results)} が期待どおり")
    for v, n in verdicts.most_common():
        print(f"  {v:<12} {n}")

    server_calls = Counter(s for _, _, calls, _, _ in results for s in calls)
    server_fails = Counter(s for _, _, _, fails, _ in results for s in fails)
    total_calls = sum(server_calls.values())
    total_fails = sum(server_fails.values())
    print(f"\n== バックエンド選択率（総 {total_calls} 呼び出し / うち失敗 {total_fails}）==")
    for s, n in server_calls.most_common():
        f = server_fails.get(s, 0)
        note = f"  失敗 {f}" if f else ""
        print(f"  {s:<28} {n:>4} ({n / max(total_calls, 1):6.1%}){note}")
    if total_fails:
        print(
            "\n注意: 失敗した呼び出しが含まれています。"
            "選択率は「選ばれた」ことしか示しません。"
        )

    print(
        f"\n== トークン == LLM 呼び出し {usage['calls']} 回 / "
        f"入力 {usage['prompt']:,}（キャッシュ {usage['cached']:,}）/ "
        f"出力 {usage['completion']:,}（推論 {usage['reasoning']:,}）"
    )
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--queries", default=str(DEFAULT_QUERIES))
    p.add_argument("--servers-file", default=str(REPO_ROOT / "mcp_servers.json"))
    p.add_argument("--system-prompt-file", default=str(REPO_ROOT / "openai.md"))
    p.add_argument("--model", default="gpt-5.6-terra")
    p.add_argument("--reasoning-effort", default="low")
    p.add_argument("--only", default="", help="カンマ区切りの case id で絞り込む")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--yes", action="store_true", help="実 API 呼び出しを承認する")
    return asyncio.run(run(p.parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
