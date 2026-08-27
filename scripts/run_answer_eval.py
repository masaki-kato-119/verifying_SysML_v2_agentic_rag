"""eval/qa_golden_set.json を使って回答精度(実APIコスト・予算上限あり)を測定する。

``scripts/run_backend_eval.py`` と同じ経路（``openai_call_mcp.resolve_with_history``、
全MCPサーバー同時提示）で各ケースを実行し、次を測定する。

- 引用整合性: 回答文中の ``chunk-\\d+`` 引用が、実際にそのターンのツール出力に
  含まれていたかをルールベースで照合する（追加コストなし）。
- 正確性・完全性: ``expected_answer`` を持つケースについて、安価なモデルに
  1-5点で採点させる（LLM-as-judge、追加コスト発生）。
- 棄却率: ``answerable: false`` のケースで、規定の「検証不能」宣言が
  含まれているかを確認する。含まれなければ最重要度の失敗として報告する。

**予算上限**: 実行前にケース数・モデルから概算コストを表示し、``--budget-usd``
（デフォルト $5）を超える場合は実行しない。実行中も実測コストを積算し、
上限を超えたら打ち切る。``--dry-run`` は ``openai_call_mcp`` を import しない
（=API キー・openai パッケージ不要）ため、コスト見積もりだけなら誰でも実行できる。

使い方::

    python scripts/run_answer_eval.py --dry-run
    python scripts/run_answer_eval.py --only qa-hybrid-01,qa-negative-01 --yes --budget-usd 1
    python scripts/run_answer_eval.py --yes --budget-usd 5
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

DEFAULT_GOLDEN = REPO_ROOT / "eval" / "qa_golden_set.json"
DEFAULT_RESULTS_DIR = REPO_ROOT / "eval" / "results"

# 2026-08時点の実勢価格（概算、$/1Mトークン）。正確な値は都度公式サイトで確認すること。
# 実測コストは実行中にレスポンスのusageから積算するため、ここは事前見積もり専用。
PRICING = {
    "gpt-5.6-terra": {"input": 2.50, "output": 15.0},
    "gpt-5.6-luna": {"input": 0.20, "output": 1.20},
    "gpt-5.6-sol": {"input": 5.0, "output": 20.0},
}
DEFAULT_PRICING = {"input": 2.50, "output": 15.0}

# 1ケースあたりのラフな平均トークン数（事前見積もり専用、実測ではない）。
# ツール結果込みの履歴を毎ターン再送するうえ、1ケースがtool-callループで
# 複数回のLLM往復になることがあるため入力トークンが支配的になる。
# 2026-08-11の実測（qa-hybrid-01/qa-graph-01/qa-negative-01、3ケース10LLM呼び出し）では
# 1ケースあたり平均 入力=34,948 / 出力=1,380 トークンだった。安全側に見て少し高めに設定している。
EST_TOKENS_PER_GENERATION = {"input": 35000, "output": 1500}
EST_TOKENS_PER_JUDGE = {"input": 500, "output": 150}

# openai.md が規定する語彙（検証不能／根拠不在）に加え、2026-08-11の実行で
# 実際に観測された同義の言い回しを含める。qa-negative-03 では「該当条文は
# 検出されませんでした」「非準拠（そのような仕様記載は確認できません）」という
# 表現で正しく棄却できていたにもかかわらず、旧版（検証不能／根拠不在の厳密一致のみ）
# では false negative になっていた。それでも語彙ベースなので万能ではない——
# `refusal_ok: false` のケースは `final_text` を必ず目視確認すること。
REQUIRED_REFUSAL_MARKERS = (
    "検証不能",
    "根拠不在",
    "確認できません",
    "検出されませんでした",
    "見当たりません",
    "該当箇所は提示できません",
    "存在しません",
    "示す条文はありません",
    "規定する条文は検出",
)
CHUNK_CITATION_RE = re.compile(r"chunk-(\d+)")

JUDGE_PROMPT_TEMPLATE = """あなたはRAGシステムの回答品質を採点する評価者です。
以下の質問・参照回答・生成回答を比較し、JSON形式のみで採点してください。

質問: {query}

参照回答:
{expected_answer}

生成回答:
{generated_answer}

次のJSON形式で出力してください（他のテキストは一切含めないこと）:
{{"correctness": <1-5の整数>, "completeness": <1-5の整数>, "rationale": "<採点理由を1文で>"}}

採点基準:
- correctness: 参照回答と矛盾する記述がないか（5=矛盾なし、1=事実誤認あり）
- completeness: 参照回答が触れている要点をどれだけ含むか（5=すべて含む、1=ほぼ欠落）
"""


class BudgetExceeded(Exception):
    pass


def load_golden_set(path: Path, only: set[str] | None) -> list[dict]:
    spec = json.loads(path.read_text(encoding="utf-8"))
    cases = spec["cases"]
    if only:
        cases = [c for c in cases if c["id"] in only]
    return cases


def estimate_cost(cases: list[dict], model: str, judge_model: str, repeat: int) -> dict:
    gen_price = PRICING.get(model, DEFAULT_PRICING)
    judge_price = PRICING.get(judge_model, DEFAULT_PRICING)

    n_gen = len(cases) * repeat
    n_judge = sum(1 for c in cases if c.get("expected_answer") and c.get("answerable", True)) * repeat

    gen_cost = (
        n_gen * EST_TOKENS_PER_GENERATION["input"] / 1_000_000 * gen_price["input"]
        + n_gen * EST_TOKENS_PER_GENERATION["output"] / 1_000_000 * gen_price["output"]
    )
    judge_cost = (
        n_judge * EST_TOKENS_PER_JUDGE["input"] / 1_000_000 * judge_price["input"]
        + n_judge * EST_TOKENS_PER_JUDGE["output"] / 1_000_000 * judge_price["output"]
    )
    return {
        "n_generation_calls": n_gen,
        "n_judge_calls": n_judge,
        "estimated_generation_usd": round(gen_cost, 4),
        "estimated_judge_usd": round(judge_cost, 4),
        "estimated_total_usd": round(gen_cost + judge_cost, 4),
    }


def print_dry_run(cases: list[dict], args) -> None:
    print(f"対象ケース: {len(cases)} 件（--repeat {args.repeat}）\n")
    for c in cases:
        judge = "judge対象" if c.get("expected_answer") and c.get("answerable", True) else "-"
        print(
            f"  {c['id']:<20} answerable={str(c.get('answerable', True)):<5} "
            f"backend={c.get('expected_backend', '?'):<7} {judge:<10} {c['query'][:40]}"
        )
    est = estimate_cost(cases, args.model, args.judge_model, args.repeat)
    print(
        f"\n概算コスト: 生成 {est['n_generation_calls']}回 (${est['estimated_generation_usd']}) + "
        f"judge {est['n_judge_calls']}回 (${est['estimated_judge_usd']}) "
        f"= 合計 約${est['estimated_total_usd']}（粗い事前見積もり、実測ではない）"
    )
    print(f"予算上限: ${args.budget_usd}")
    if est["estimated_total_usd"] > args.budget_usd:
        print("警告: 概算コストが予算上限を超えています。--yes を付けても実行を拒否します。")


def extract_tool_chunk_ids(history: list) -> set[str]:
    """会話履歴中の function_call_output から実際に登場したchunk番号を抽出する。"""
    ids: set[str] = set()
    for item in history:
        if isinstance(item, dict) and item.get("type") == "function_call_output":
            content = item.get("output", "") or ""
            ids.update(CHUNK_CITATION_RE.findall(content))
    return ids


def check_citation_faithfulness(final_text: str, tool_chunk_ids: set[str]) -> dict:
    cited = set(CHUNK_CITATION_RE.findall(final_text or ""))
    fabricated = cited - tool_chunk_ids
    return {
        "cited_chunk_ids": sorted(cited),
        "fabricated_chunk_ids": sorted(fabricated),
        "has_fabricated_citation": bool(fabricated),
    }


def check_refusal(final_text: str) -> bool:
    text = final_text or ""
    return any(marker in text for marker in REQUIRED_REFUSAL_MARKERS)


async def run_judge(ocm, judge_model: str, case: dict, final_text: str) -> dict:
    prompt = JUDGE_PROMPT_TEMPLATE.format(
        query=case["query"],
        expected_answer=case.get("expected_answer") or "(なし)",
        generated_answer=final_text or "(空)",
    )
    response = ocm.client.responses.create(
        model=judge_model,
        input=[{"role": "user", "content": prompt}],
        reasoning={"effort": "low"},
    )
    text = ocm.response_output_text(response)
    try:
        cleaned = text.strip()
        if cleaned.startswith("```"):
            cleaned = re.sub(r"^```(json)?", "", cleaned).rstrip("`").strip()
        parsed = json.loads(cleaned)
        return {
            "correctness": parsed.get("correctness"),
            "completeness": parsed.get("completeness"),
            "rationale": parsed.get("rationale"),
            "raw": text,
        }
    except (json.JSONDecodeError, AttributeError):
        return {"correctness": None, "completeness": None, "rationale": None, "raw": text, "parse_error": True}


async def run(args) -> int:
    import openai_call_mcp as ocm

    only = {c.strip() for c in args.only.split(",") if c.strip()} or None
    cases = load_golden_set(Path(args.golden), only)
    if not cases:
        print("対象ケースがありません。")
        return 1

    est = estimate_cost(cases, args.model, args.judge_model, args.repeat)
    print(f"概算コスト: 約${est['estimated_total_usd']}（予算上限 ${args.budget_usd}）")
    if est["estimated_total_usd"] > args.budget_usd:
        print("概算コストが予算上限を超えているため実行しません。--budget-usd で引き上げるか --only で絞り込んでください。")
        return 1

    usage = Counter()
    cost_state = {"usd": 0.0}
    original_create = ocm.client.responses.create

    def counting_create(**kwargs):
        response = original_create(**kwargs)
        u = getattr(response, "usage", None)
        if u:
            model = kwargs.get("model", "")
            price = PRICING.get(model, DEFAULT_PRICING)
            call_cost = (
                u.input_tokens / 1_000_000 * price["input"]
                + u.output_tokens / 1_000_000 * price["output"]
            )
            usage["prompt"] += u.input_tokens
            usage["completion"] += u.output_tokens
            usage["calls"] += 1
            cost_state["usd"] += call_cost
            if cost_state["usd"] > args.budget_usd:
                raise BudgetExceeded(
                    f"実測コストが予算上限 ${args.budget_usd} を超えました（現在 ${cost_state['usd']:.4f}）。"
                )
        return response

    ocm.client.responses.create = counting_create

    system_prompt_path = Path(args.system_prompt_file)
    system_prompt = system_prompt_path.read_text(encoding="utf-8").strip() if system_prompt_path.exists() else ""

    servers = await ocm.load_mcp_servers_from_file(args.servers_file)
    if not servers:
        print("MCP サーバに接続できませんでした。")
        return 1
    tools, routing = ocm.build_tool_registry(servers)

    results: list[dict] = []
    budget_hit = False
    try:
        for case in cases:
            for rep in range(args.repeat):
                history = [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": case["query"]},
                ]
                t0 = time.perf_counter()
                error = None
                final_text = ""
                try:
                    response = await ocm.resolve_with_history(
                        history, args.model, routing, tools, args.reasoning_effort
                    )
                    final_text = ocm.response_output_text(response)
                except BudgetExceeded as e:
                    budget_hit = True
                    error = str(e)
                except Exception as e:  # 1件の失敗で全体を止めない  # noqa: BLE001
                    error = f"{type(e).__name__}: {e}"
                latency_ms = int((time.perf_counter() - t0) * 1000)

                called_servers = [
                    routing.get(item.get("name") if isinstance(item, dict) else getattr(item, "name", None), {}).get("server", "(unknown)")
                    for item in history
                    if (isinstance(item, dict) and item.get("type") == "function_call")
                    or getattr(item, "type", None) == "function_call"
                ]
                tool_chunk_ids = extract_tool_chunk_ids(history)
                citation = check_citation_faithfulness(final_text, tool_chunk_ids)

                refusal_ok = None
                if not case.get("answerable", True):
                    refusal_ok = check_refusal(final_text)

                judge = None
                if not error and case.get("expected_answer") and case.get("answerable", True):
                    try:
                        judge = await run_judge(ocm, args.judge_model, case, final_text)
                    except BudgetExceeded as e:
                        budget_hit = True
                        error = str(e)

                result = {
                    "id": case["id"],
                    "repeat": rep,
                    "query": case["query"],
                    "answerable": case.get("answerable", True),
                    "expected_backend": case.get("expected_backend"),
                    "servers_called": called_servers,
                    "final_text": final_text,
                    "latency_ms": latency_ms,
                    "citation": citation,
                    "refusal_ok": refusal_ok,
                    "judge": judge,
                    "error": error,
                }
                results.append(result)

                flags = []
                if citation["has_fabricated_citation"]:
                    flags.append("捏造引用!")
                if refusal_ok is False:
                    flags.append("誤った断定回答!")
                if error:
                    flags.append(f"ERROR: {error[:80]}")
                flag_str = f" [{', '.join(flags)}]" if flags else ""
                judge_str = (
                    f" judge=correctness:{judge['correctness']} completeness:{judge['completeness']}"
                    if judge and not judge.get("parse_error")
                    else ""
                )
                print(f"  {case['id']:<20} rep={rep} {latency_ms:>6}ms{judge_str}{flag_str}")

                if budget_hit:
                    break
            if budget_hit:
                print("\n予算上限に達したため、残りのケースを中断しました。")
                break
    finally:
        ocm.client.responses.create = original_create
        for s in servers.values():
            await ocm.close_mcp_client(s.get("mcp"), timeout=2.0)

    print_answer_summary(results, usage, cost_state["usd"])

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_path = output_dir / f"answer_{ts}.json"
    out_path.write_text(
        json.dumps(
            {
                "results": results,
                "usage": dict(usage),
                "actual_cost_usd": round(cost_state["usd"], 4),
                "budget_usd": args.budget_usd,
                "budget_exceeded": budget_hit,
                "model": args.model,
                "judge_model": args.judge_model,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"\n結果を保存しました: {out_path}")
    return 0


def print_answer_summary(results: list[dict], usage: Counter, actual_cost: float) -> None:
    n = len(results)
    if n == 0:
        return
    fabricated = sum(1 for r in results if r["citation"]["has_fabricated_citation"])
    refusal_cases = [r for r in results if r["refusal_ok"] is not None]
    refusal_correct = sum(1 for r in refusal_cases if r["refusal_ok"])
    judged = [r for r in results if r.get("judge") and not r["judge"].get("parse_error") and r["judge"].get("correctness") is not None]
    errors = sum(1 for r in results if r["error"])

    print(f"\n== 結果サマリ ({n}件) ==")
    print(f"  捏造引用: {fabricated}/{n}")
    if refusal_cases:
        print(f"  棄却率（正しく『検証不能』と回答できた割合）: {refusal_correct}/{len(refusal_cases)}")
    if judged:
        mean_correctness = sum(r["judge"]["correctness"] for r in judged) / len(judged)
        mean_completeness = sum(r["judge"]["completeness"] for r in judged) / len(judged)
        print(f"  LLM-as-judge 平均: correctness={mean_correctness:.2f}/5 completeness={mean_completeness:.2f}/5 ({len(judged)}件)")
    if errors:
        print(f"  エラー: {errors}/{n}")
    print(
        f"  トークン: 入力 {usage['prompt']:,} / 出力 {usage['completion']:,} "
        f"（LLM呼び出し {usage['calls']}回） / 実測コスト ${actual_cost:.4f}"
    )


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--golden", default=str(DEFAULT_GOLDEN))
    p.add_argument("--servers-file", default=str(REPO_ROOT / "mcp_servers.json"))
    p.add_argument("--system-prompt-file", default=str(REPO_ROOT / "openai.md"))
    p.add_argument("--model", default="gpt-5.6-terra")
    p.add_argument("--judge-model", default="gpt-5.6-luna")
    p.add_argument("--reasoning-effort", default="low")
    p.add_argument("--only", default="", help="カンマ区切りのcase idで絞り込む")
    p.add_argument("--repeat", type=int, default=1, help="各ケースを繰り返す回数(再現性測定用)")
    p.add_argument("--budget-usd", type=float, default=5.0, help="このスクリプト実行あたりの予算上限(USD)")
    p.add_argument("--output-dir", default=str(DEFAULT_RESULTS_DIR))
    p.add_argument("--dry-run", action="store_true", help="コスト見積もりとケース一覧だけ表示する(API呼び出しなし)")
    p.add_argument("--yes", action="store_true", help="実API呼び出しを承認する")
    args = p.parse_args()

    only = {c.strip() for c in args.only.split(",") if c.strip()} or None
    cases = load_golden_set(Path(args.golden), only)
    if not cases:
        print("対象ケースがありません。")
        return 1

    if args.dry_run:
        print_dry_run(cases, args)
        return 0

    if not args.yes:
        print("実 API を呼びます。実行するには --yes を付けてください（先に --dry-run でコストを確認することを推奨）。")
        return 1

    return asyncio.run(run(args))


if __name__ == "__main__":
    raise SystemExit(main())
