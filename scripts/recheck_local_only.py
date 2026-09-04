"""ローカルのチェッカーだけを730件コーパスへ流し直し、参照実装との agreement を
再計算する（参照実装は動かさない）。文法・lintルールを変更したときの回帰確認用。

## なぜ参照実装を動かさなくてよいのか

`eval/sysml_results/<sha>.json` の `reference` フィールドは、参照実装（jar 0.61.0）を
そのサンプルに対して実行した結果である。**参照実装の判定はローカルのコードを変えても
変わらない**（jar のバージョンとサンプルの内容が固定されている限り決定的）。したがって
ローカル側の変更に対する回帰確認では、保存済みの `reference` を固定基準として使い、
`local` 側だけ再実行すればよい。

これにより、`scripts/run_reference_comparison_eval.py` のフル実行（逐次730件で2時間強）を
**数分**に置き換えられる。参照実装込みのフル実行が本当に必要なのは次の場合だけ:

- 参照実装の jar のバージョンを変えたとき
- `eval/sysml_samples/` のサンプルを追加・変更したとき
- ハーネス（`eval/sysml_reference/`）の呼び出し方を変えたとき

## 使い方

    python scripts/recheck_local_only.py                    # 全件、表を表示
    python scripts/recheck_local_only.py --json out.json    # 機械可読でも書き出す
    python scripts/recheck_local_only.py --list-regressions # 悪化したファイルを全件表示

出力は「保存済みの agreement」と「今のコードでの agreement」の突き合わせで、
`scripts/compare_reference_eval_runs.py` の遷移表と同じ読み方ができる。

## 注意

このスクリプトは `eval/sysml_results/` を**書き換えない**。したがって同ディレクトリの
`local` フィールドは「最後にフル実行した時点」のものであり、ローカルを変更した後は
実際の挙動と食い違う。食い違いを解消したい（＝新しい正式な記録にしたい）ときだけ
`run_reference_comparison_eval.py --force` を回すこと。日々の回帰確認では不要。
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
import traceback
from collections import Counter
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

RESULTS_DIR = REPO_ROOT / "eval" / "sysml_results"

_QUOTED_RE = re.compile(r"'[^']*'")
_NUMBER_RE = re.compile(r"\b\d+\b")
_RULE_ID_RE = re.compile(r"\[[0-9.]+\]")

# 一致しているとみなす agreement（compare_reference_eval_runs.py と同じ定義）。
_AGREEING = {"both_clean", "both_error"}


def run_local(text: str) -> dict:
    """`run_reference_comparison_eval.py` の run_local_check と同じ正規化を行う。

    `parse_sysml` は例外を投げず error dict を返す契約なので、戻り値を見て分岐する
    （try/except で捕まえようとしても構文エラーは捕まらない）。
    """
    from sysml_v2_checker_advanced.parser import lint_sysml, parse_sysml

    try:
        ast = parse_sysml(text)
    except Exception as exc:  # noqa: BLE001 -- 回帰確認ハーネスなのでクラッシュも記録対象
        return {"parsed": False, "crashed": True, "diagnostics": [],
                "crash_message": f"parse_sysml crashed: {type(exc).__name__}: {exc}"}

    if isinstance(ast, dict) and ast.get("type") == "error":
        message = ast.get("message", "parse error")
        return {"parsed": False, "crashed": False, "crash_message": None,
                "diagnostics": [{"severity": "error", "message": seg} for seg in message.split("; ")]}

    try:
        issues = lint_sysml(ast)
    except Exception as exc:  # noqa: BLE001 -- lintのクラッシュそのものが回帰対象
        return {"parsed": True, "crashed": True, "diagnostics": [],
                "crash_message": f"lint_sysml crashed: {type(exc).__name__}: {exc}\n{traceback.format_exc()}"}

    diagnostics = []
    for issue in issues:
        as_dict = issue.to_dict() if hasattr(issue, "to_dict") else dict(issue)
        diagnostics.append({
            "severity": str(as_dict.get("severity", "")).lower(),
            "message": str(as_dict.get("message", "")),
        })
    return {"parsed": True, "crashed": False, "crash_message": None, "diagnostics": diagnostics}


def has_error(side: dict) -> bool:
    return any(d.get("severity") == "error" for d in side.get("diagnostics", []))


def classify(local: dict, reference: dict) -> str:
    if reference.get("crashed"):
        return "reference_crash"
    if local["crashed"]:
        return "local_crash"
    local_error, ref_error = has_error(local), has_error(reference)
    if local_error and ref_error:
        return "both_error"
    if local_error:
        return "local_only_error"
    if ref_error:
        return "reference_only_error"
    return "both_clean"


def normalize(message: str, width: int = 70) -> str:
    return _NUMBER_RE.sub("<N>", _QUOTED_RE.sub("<X>", _RULE_ID_RE.sub("", message))).strip()[:width]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--results-dir", type=Path, default=RESULTS_DIR,
                        help="参照実装の判定を読む結果ディレクトリ（既定 eval/sysml_results）")
    parser.add_argument("--list-regressions", action="store_true", help="悪化したファイルを全件表示する")
    parser.add_argument("--top", type=int, default=12, help="頻出クラスタの表示件数")
    parser.add_argument("--json", type=Path, help="集計をJSONでも書き出す")
    args = parser.parse_args()

    files = sorted(args.results_dir.glob("*.json"))
    if not files:
        raise SystemExit(f"{args.results_dir} に結果JSONがありません。"
                         "先に scripts/run_reference_comparison_eval.py を実行してください。")

    before: Counter[str] = Counter()
    after: Counter[str] = Counter()
    transitions: Counter[tuple[str, str]] = Counter()
    by_category: dict[str, Counter] = {}
    regressions: list[dict] = []
    local_only_messages: Counter[str] = Counter()
    parse_failures: list[str] = []
    missing = 0

    started = time.time()
    for index, path in enumerate(files, 1):
        record = json.loads(path.read_text(encoding="utf-8"))
        sample = record["sample"]
        source = REPO_ROOT / sample["path"]
        if not source.exists():
            missing += 1
            continue

        local = run_local(source.read_text(encoding="utf-8", errors="replace"))
        agreement = classify(local, record["reference"])
        recorded = record["agreement"]

        before[recorded] += 1
        after[agreement] += 1
        transitions[(recorded, agreement)] += 1
        by_category.setdefault(sample.get("category", "?"), Counter())[agreement] += 1

        if agreement == "local_only_error":
            for diagnostic in local["diagnostics"]:
                if diagnostic["severity"] == "error":
                    local_only_messages[normalize(diagnostic["message"])] += 1
            if not local["parsed"]:
                parse_failures.append(sample["path"])
        if recorded in _AGREEING and agreement not in _AGREEING:
            regressions.append({
                "path": sample["path"],
                "category": sample.get("category", "?"),
                "before": recorded,
                "after": agreement,
                "local_first_error": next(
                    (d["message"] for d in local["diagnostics"] if d["severity"] == "error"), None
                ),
            })

        if index % 100 == 0:
            print(f"  {index}/{len(files)} ({time.time() - started:.0f}秒)", flush=True)

    total = sum(after.values())
    print(f"\n# ローカル側のみ再実行: {total}件"
          f"（サンプル欠落 {missing}件を除外、{time.time() - started:.0f}秒）")
    print("# 参照実装の判定は保存済みのものを使用（ローカル変更では変わらないため）\n")

    print("## agreement")
    print(f"{'agreement':24s} {'記録済み':>12s} {'現行コード':>12s} {'diff':>7s}")
    for key in sorted(set(before) | set(after), key=lambda k: -after.get(k, 0)):
        b, a = before.get(key, 0), after.get(key, 0)
        print(f"{key:24s} {b:12d} {a:12d} {a - b:+7d}")

    changed = [(k, v) for k, v in transitions.most_common() if k[0] != k[1]]
    print(f"\n## 変化したファイル: {sum(v for _, v in changed)}件")
    for (b, a), count in changed:
        marker = "  <<< 悪化" if b in _AGREEING and a not in _AGREEING else "  <<< 改善"
        print(f"  {b:22s} -> {a:22s} {count:4d}{marker}")

    print("\n## カテゴリ別（現行コード）")
    for category, counter in sorted(by_category.items(), key=lambda kv: -sum(kv[1].values())):
        subtotal = sum(counter.values())
        breakdown = " ".join(f"{k}={v}" for k, v in sorted(counter.items(), key=lambda x: -x[1]))
        print(f"  {category:20s} n={subtotal:4d}  {breakdown}")

    print(f"\n## local_only_error のうちパースエラー: {len(parse_failures)}件")
    for path in parse_failures[: args.top]:
        print(f"  {path}")

    if local_only_messages:
        print("\n## local_only_error の症状（頻出順、パースエラーも含む）")
        for message, count in local_only_messages.most_common(args.top):
            print(f"  {count:4d}  {message}")

    print(f"\n## 悪化（一致 -> 不一致）: {len(regressions)}件")
    if not args.list_regressions and regressions:
        print("  （--list-regressions で全件表示）")
    for item in regressions if args.list_regressions else regressions[: args.top]:
        print(f"  [{item['category']}] {item['path']}")
        print(f"      {item['before']} -> {item['after']}: {(item['local_first_error'] or '')[:100]}")

    if args.json:
        args.json.write_text(json.dumps({
            "total": total,
            "before": dict(before),
            "after": dict(after),
            "transitions": [{"before": b, "after": a, "count": c} for (b, a), c in transitions.most_common()],
            "by_category": {k: dict(v) for k, v in by_category.items()},
            "local_only_parse_failures": parse_failures,
            "local_only_messages": dict(local_only_messages),
            "regressions": regressions,
        }, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"\n# JSONを書き出した: {args.json}")

    return 1 if regressions else 0


if __name__ == "__main__":
    raise SystemExit(main())
