"""eval/sysml_results/*.json（run_reference_comparison_eval.py の出力）を集計し、
ローカルlinter(sysml_v2_checker_advanced)と参照実装(OMG SysML v2 Pilot Implementation)
の相違をメッセージパターン単位でクラスタリングして頻度順に表示する。

主目的: local_only_error（ローカルだけがエラー報告＝偽陽性の疑い）と
reference_only_error（参照実装だけがエラー報告＝偽陰性の疑い）について、
「同じ根本原因で大量発生しているパターン」を見つけること。メッセージ中の
引用符付き識別子・数値を `<X>` に置換して正規化し、同一パターンをグルーピングする。

使い方::

    python scripts/analyze_reference_comparison.py                       # 概要
    python scripts/analyze_reference_comparison.py --bucket local_only_error --top 30
    python scripts/analyze_reference_comparison.py --bucket reference_only_error --show-examples 3
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
RESULTS_DIR = REPO_ROOT / "eval" / "sysml_results"

_NORMALIZE_PATTERNS = [
    (re.compile(r"'[^']*'"), "'<X>'"),
    (re.compile(r'"[^"]*"'), '"<X>"'),
    (re.compile(r"\b\d+\b"), "<N>"),
]


def normalize_message(msg: str) -> str:
    for pattern, repl in _NORMALIZE_PATTERNS:
        msg = pattern.sub(repl, msg)
    return msg.strip()


def load_results() -> list[dict]:
    return [json.loads(p.read_text(encoding="utf-8")) for p in sorted(RESULTS_DIR.glob("*.json"))]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--bucket",
        choices=[
            "local_only_error",
            "reference_only_error",
            "local_crash",
            "reference_crash",
            "both_crash",
            "both_error",
        ],
        default=None,
        help="このagreementバケットのメッセージパターンを集計する（省略時は全体サマリのみ）",
    )
    parser.add_argument("--top", type=int, default=25, help="表示するパターン数の上限")
    parser.add_argument("--show-examples", type=int, default=2, help="各パターンごとに表示するサンプルファイル数")
    parser.add_argument("--category", default=None, help="manifestのcategoryで絞り込む")
    args = parser.parse_args()

    results = load_results()
    if args.category:
        results = [r for r in results if r["sample"]["category"] == args.category]

    agreement_counts = Counter(r["agreement"] for r in results)
    category_x_agreement: dict[str, Counter] = defaultdict(Counter)
    for r in results:
        category_x_agreement[r["sample"]["category"]][r["agreement"]] += 1

    print(f"総サンプル数: {len(results)}")
    print("\n== agreementバケット別集計 ==")
    for label, count in agreement_counts.most_common():
        print(f"  {label:<22} {count:5d}件 ({count * 100 // len(results)}%)")

    print("\n== カテゴリ別のlocal_only_error / reference_only_error 比率 ==")
    for cat, counter in sorted(category_x_agreement.items(), key=lambda kv: -sum(kv[1].values())):
        total = sum(counter.values())
        loe = counter.get("local_only_error", 0)
        roe = counter.get("reference_only_error", 0)
        print(f"  {cat:<20} 総数={total:4d}  local_only_error={loe:4d} ({loe * 100 // total}%)  reference_only_error={roe:4d} ({roe * 100 // total}%)")

    if args.bucket is None:
        print("\n(--bucket <name> を指定するとメッセージパターンのクラスタリング結果を表示します)")
        return 0

    bucket_results = [r for r in results if r["agreement"] == args.bucket]
    print(f"\n== '{args.bucket}' ({len(bucket_results)}件) のメッセージパターン集計 ==")

    # local_only_error なら local 側の error 診断、reference_only_error なら reference 側、
    # crash系なら crash_message / raw_stderr を対象にする。
    pattern_to_samples: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for r in bucket_results:
        sample_path = r["sample"]["path"]
        if args.bucket == "local_only_error":
            msgs = [d["message"] for d in r["local"]["diagnostics"] if d["severity"] == "error"]
        elif args.bucket == "reference_only_error":
            msgs = [d["message"] for d in r["reference"]["diagnostics"] if d["severity"] == "error"]
        elif args.bucket in ("local_crash", "both_crash"):
            msgs = [r["local"].get("crash_message") or "(no message)"]
        elif args.bucket in ("reference_crash",):
            msgs = [(r["reference"].get("raw_stderr_excerpt") or "(no stderr)")[-200:]]
        else:
            msgs = [d["message"] for d in r["local"]["diagnostics"] if d["severity"] == "error"]

        for msg in msgs:
            pattern = normalize_message(msg)
            pattern_to_samples[pattern].append((sample_path, msg))

    pattern_counts = Counter({p: len(v) for p, v in pattern_to_samples.items()})
    for pattern, count in pattern_counts.most_common(args.top):
        print(f"\n  [{count:3d}件] {pattern[:160]}")
        for sample_path, original_msg in pattern_to_samples[pattern][: args.show_examples]:
            print(f"        例: {sample_path}")
            if original_msg != pattern:
                print(f"            {original_msg[:160]}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
