"""参照実装比較評価（`scripts/run_reference_comparison_eval.py`）の2つの実行結果を
突き合わせ、agreementの変化と、変化したバケットの内訳を集計する。

`run_reference_comparison_eval.py --force` で結果を作り直す前に旧結果を
ディレクトリごと退避しておけば、このスクリプトで「修正によって何がどう変わったか」を
機械的に出せる。比較レポートを更新する際の差分表の生成元。

LLMは一切使わない決定的な集計。

使い方::

    # 旧結果を退避してから再実行する
    cp -r eval/sysml_results eval/sysml_results_baseline_20260828
    python scripts/run_reference_comparison_eval.py --force

    # 差分を見る
    python scripts/compare_reference_eval_runs.py \
        --baseline eval/sysml_results_baseline_20260828 \
        --current  eval/sysml_results

    # 悪化したファイル（両実装一致 → 不一致）を全部挙げる
    python scripts/compare_reference_eval_runs.py --list-regressions

`--json <path>` を付けると、集計結果を機械可読な形でも書き出す。

## reference_only_error の3分類について

`reference_only_error`（参照実装だけがエラーを検出）は、そのままでは
「ローカルの偽陰性」と読めてしまうが、実際には性質の異なる3つが混在している
（2026-08-28の比較レポート §4.1/§4.2/§4.3）。このスクリプトは参照実装側の
診断メッセージから3つを機械的に振り分ける:

- ``type_resolution``: `Couldn't resolve reference to ...` / `... must be typed by ...`。
  単一ファイル解析では原理的に解決できない他ファイル・標準ライブラリ型への参照。
  **設計上のスコープ外であり、偽陰性として数えるべきではない**（レポート §4.2）。
- ``reference_syntax``: `mismatched input 'import'` / `missing EOF at 'import'` 等。
  参照実装（jar v0.61.0 の `SysMLInteractive.process()`）がビジビリティ修飾子なしの
  裸の `import` を位置に関わらず拒否する挙動に由来する疑いが濃い
  （レポート §4.3 に再現手順あり）。**参照実装側のアーティファクトの可能性が高い**。
- ``semantic_rule``: 上記以外。`Only one return parameter is allowed` のような
  意味制約の検証ルールで、**ローカルに未実装の真の偽陰性候補**（レポート §4.1）。
  ここに出てくるものだけが「lintルールを足すべき候補」。
"""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_BASELINE = REPO_ROOT / "eval" / "sysml_results_baseline_20260828"
DEFAULT_CURRENT = REPO_ROOT / "eval" / "sysml_results"

# 一致しているとみなすagreement（どちらの実装も同じ結論に達している状態）。
_AGREEING = {"both_clean", "both_error"}

# reference_only_error の3分類（docstring参照）。判定は参照実装側の
# エラーメッセージ全体に対して行い、上から順に最初にマッチした分類を採る。
_REFERENCE_SYNTAX_RE = re.compile(
    r"mismatched input|no viable alternative|missing EOF|extraneous input|token recognition"
)
_TYPE_RESOLUTION_RE = re.compile(r"Couldn't resolve|must be typed by")

# メッセージのクラスタリング用。引用符付き識別子と数値を潰して同型のものを束ねる
# （analyze_reference_comparison.py と同じ考え方）。
_QUOTED_RE = re.compile(r"'[^']*'")
_NUMBER_RE = re.compile(r"\b\d+\b")


def load_run(results_dir: Path) -> dict[str, dict]:
    """結果ディレクトリを `sample.path -> 結果dict` の索引として読む。

    ファイル名（sha256の先頭16文字）ではなく `sample.path` をキーにするのは、
    サンプルの内容が変わってsha256が変わっても同じファイルとして突き合わせたいため。
    """
    if not results_dir.is_dir():
        raise SystemExit(f"{results_dir} が見つかりません（先に退避・再実行が必要）")
    runs: dict[str, dict] = {}
    for path in sorted(results_dir.glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        runs[data["sample"]["path"]] = data
    if not runs:
        raise SystemExit(f"{results_dir} に結果JSONがありません")
    return runs


def error_messages(side: dict) -> list[str]:
    return [d["message"] for d in side.get("diagnostics", []) if d.get("severity") == "error"]


def classify_reference_only(result: dict) -> str:
    """reference_only_error を3分類のいずれかへ振り分ける（docstring参照）。"""
    joined = " | ".join(error_messages(result["reference"]))
    if _REFERENCE_SYNTAX_RE.search(joined):
        return "reference_syntax"
    if _TYPE_RESOLUTION_RE.search(joined):
        return "type_resolution"
    return "semantic_rule"


def normalize(message: str, width: int = 90) -> str:
    return _NUMBER_RE.sub("<N>", _QUOTED_RE.sub("<X>", message))[:width]


def _percent(count: int, total: int) -> str:
    return f"{count / total * 100:.1f}%" if total else "-"


def build_summary(baseline: dict[str, dict], current: dict[str, dict]) -> dict:
    shared = sorted(set(baseline) & set(current))
    only_baseline = sorted(set(baseline) - set(current))
    only_current = sorted(set(current) - set(baseline))

    overall_before = Counter(baseline[p]["agreement"] for p in shared)
    overall_after = Counter(current[p]["agreement"] for p in shared)
    transitions = Counter((baseline[p]["agreement"], current[p]["agreement"]) for p in shared)

    by_category: dict[str, Counter] = {}
    for path in shared:
        category = current[path]["sample"].get("category", "?")
        by_category.setdefault(category, Counter())[current[path]["agreement"]] += 1

    # 悪化したファイル: 一致していたのに一致しなくなったもの。
    regressions = [
        {
            "path": path,
            "category": current[path]["sample"].get("category", "?"),
            "before": baseline[path]["agreement"],
            "after": current[path]["agreement"],
            "reference_only_bucket": (
                classify_reference_only(current[path])
                if current[path]["agreement"] == "reference_only_error"
                else None
            ),
            "reference_first_error": next(iter(error_messages(current[path]["reference"])), None),
            "local_first_error": next(iter(error_messages(current[path]["local"])), None),
        }
        for path in shared
        if baseline[path]["agreement"] in _AGREEING
        and current[path]["agreement"] not in _AGREEING
    ]

    # reference_only_error の3分類（現行のみ。偽陰性候補の絞り込みに使う）。
    reference_only_buckets: Counter = Counter()
    semantic_rule_messages: Counter = Counter()
    for path in shared:
        if current[path]["agreement"] != "reference_only_error":
            continue
        bucket = classify_reference_only(current[path])
        reference_only_buckets[bucket] += 1
        if bucket == "semantic_rule":
            for message in error_messages(current[path]["reference"]):
                semantic_rule_messages[normalize(message)] += 1

    # local_only_error に残っている症状のクラスタ（偽陽性の残りを潰す優先順位付け用）。
    local_only_messages: Counter = Counter()
    for path in shared:
        if current[path]["agreement"] != "local_only_error":
            continue
        for message in error_messages(current[path]["local"]):
            local_only_messages[normalize(message)] += 1

    return {
        "counts": {"shared": len(shared), "only_baseline": len(only_baseline), "only_current": len(only_current)},
        "only_baseline": only_baseline,
        "only_current": only_current,
        "overall_before": overall_before,
        "overall_after": overall_after,
        "transitions": transitions,
        "by_category": by_category,
        "regressions": regressions,
        "reference_only_buckets": reference_only_buckets,
        "semantic_rule_messages": semantic_rule_messages,
        "local_only_messages": local_only_messages,
    }


def print_summary(summary: dict, list_regressions: bool, top: int) -> None:
    shared = summary["counts"]["shared"]
    print(f"# 突き合わせ対象: {shared}件"
          f"（baselineのみ {summary['counts']['only_baseline']}件 /"
          f" currentのみ {summary['counts']['only_current']}件は除外）\n")

    print("## agreement の変化")
    before, after = summary["overall_before"], summary["overall_after"]
    keys = sorted(set(before) | set(after), key=lambda k: -after.get(k, 0))
    print(f"{'agreement':24s} {'before':>14s} {'after':>14s} {'diff':>7s}")
    for key in keys:
        b, a = before.get(key, 0), after.get(key, 0)
        print(f"{key:24s} {b:6d} ({_percent(b, shared):>5s}) {a:6d} ({_percent(a, shared):>5s}) {a - b:+7d}")

    print("\n## 遷移（before -> after）")
    for (b, a), count in summary["transitions"].most_common():
        marker = "" if b == a else ("  <<< 悪化" if b in _AGREEING and a not in _AGREEING else "  <<< 改善")
        print(f"  {b:22s} -> {a:22s} {count:4d}{marker}")

    print("\n## カテゴリ別（after）")
    for category, counter in sorted(summary["by_category"].items(), key=lambda kv: -sum(kv[1].values())):
        total = sum(counter.values())
        breakdown = " ".join(
            f"{k}={v}({_percent(v, total)})" for k, v in sorted(counter.items(), key=lambda x: -x[1])
        )
        print(f"  {category:20s} n={total:4d}  {breakdown}")

    print("\n## reference_only_error の3分類（after）")
    total_ro = sum(summary["reference_only_buckets"].values())
    labels = {
        "type_resolution": "型解決カスケード（設計上スコープ外。偽陰性として数えない）",
        "reference_syntax": "参照実装側の構文エラー（裸import artifact 疑い）",
        "semantic_rule": "意味検証ルール未実装（真の偽陰性候補）",
    }
    for bucket in ("semantic_rule", "type_resolution", "reference_syntax"):
        count = summary["reference_only_buckets"].get(bucket, 0)
        print(f"  {count:4d} ({_percent(count, total_ro):>5s})  {labels[bucket]}")

    if summary["semantic_rule_messages"]:
        print("\n### 未実装の意味検証ルール候補（頻出順）")
        for message, count in summary["semantic_rule_messages"].most_common(top):
            print(f"  {count:4d}  {message}")

    if summary["local_only_messages"]:
        print("\n## local_only_error に残る症状（偽陽性の残り、頻出順）")
        for message, count in summary["local_only_messages"].most_common(top):
            print(f"  {count:4d}  {message}")

    regressions = summary["regressions"]
    print(f"\n## 悪化したファイル: {len(regressions)}件")
    if not list_regressions:
        print("  （--list-regressions で全件表示）")
    for item in regressions if list_regressions else regressions[:top]:
        bucket = f" [{item['reference_only_bucket']}]" if item["reference_only_bucket"] else ""
        print(f"  [{item['category']}] {item['path']}")
        print(f"      {item['before']} -> {item['after']}{bucket}")
        if item["reference_first_error"]:
            print(f"      reference: {item['reference_first_error'][:110]}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--baseline", type=Path, default=DEFAULT_BASELINE,
                        help="比較元（退避しておいた旧結果ディレクトリ）")
    parser.add_argument("--current", type=Path, default=DEFAULT_CURRENT, help="比較先（再実行後の結果ディレクトリ）")
    parser.add_argument("--list-regressions", action="store_true", help="悪化したファイルを全件表示する")
    parser.add_argument("--top", type=int, default=15, help="頻出クラスタ・抜粋の表示件数")
    parser.add_argument("--json", type=Path, help="集計結果をJSONでも書き出す")
    args = parser.parse_args()

    summary = build_summary(load_run(args.baseline), load_run(args.current))
    print_summary(summary, args.list_regressions, args.top)

    if args.json:
        serializable = {
            "counts": summary["counts"],
            "overall_before": dict(summary["overall_before"]),
            "overall_after": dict(summary["overall_after"]),
            "transitions": [
                {"before": b, "after": a, "count": c} for (b, a), c in summary["transitions"].most_common()
            ],
            "by_category": {k: dict(v) for k, v in summary["by_category"].items()},
            "reference_only_buckets": dict(summary["reference_only_buckets"]),
            "semantic_rule_messages": dict(summary["semantic_rule_messages"]),
            "local_only_messages": dict(summary["local_only_messages"]),
            "regressions": summary["regressions"],
        }
        args.json.write_text(json.dumps(serializable, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"\n# JSONを書き出した: {args.json}")


if __name__ == "__main__":
    main()
