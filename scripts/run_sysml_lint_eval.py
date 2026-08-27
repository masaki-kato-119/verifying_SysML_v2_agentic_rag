"""eval/sysml_lint_golden_set.json を使って SysML v2 Checker の精度を測定する。

LLM を一切使わない決定的な評価（`sysml_v2_checker_advanced.parser.parse_sysml`/
`lint_sysml` を直接呼び出すだけ）のため、APIコストは発生しない。

- `clean` ケース: 診断が0件であることを期待する（誤検出=false positiveの回帰検知）。
- `broken` ケース: 特定の診断が出ることを期待する（見逃し=false negativeの回帰検知）。
- `known_bug` ケース: 既知の未修正バグの現在の挙動を記録するだけで、pass/fail集計には
  含めない。挙動が記録時と変わっていれば警告として表示する（直った/悪化した可能性）。

`--corpus` を付けると `tests/fixtures/sysml_corpus/working/` 全件も走査し、
診断が出たファイルの一覧を参考情報として表示する（golden setには含まれない
実ファイルでの傾向を見るため。pass/fail判定はしない）。

使い方::

    python scripts/run_sysml_lint_eval.py
    python scripts/run_sysml_lint_eval.py --corpus
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

DEFAULT_GOLDEN = REPO_ROOT / "eval" / "sysml_lint_golden_set.json"
DEFAULT_RESULTS_DIR = REPO_ROOT / "eval" / "results"
CORPUS_DIR = REPO_ROOT / "tests" / "fixtures" / "sysml_corpus" / "working"


def load_golden_set(path: Path) -> list[dict]:
    spec = json.loads(path.read_text(encoding="utf-8"))
    return spec["cases"]


def run_lint(sysml_text: str):
    from sysml_v2_checker_advanced.parser import lint_sysml, parse_sysml

    ast = parse_sysml(sysml_text)
    if isinstance(ast, dict) and ast.get("type") == "error":
        return None, ast.get("message", "parse error")
    issues = lint_sysml(ast)
    return issues, None


def match_expected_issues(actual, expected_issues: list[dict]) -> dict:
    """期待される診断が実際の結果に含まれるかを severity + 部分一致で照合する。"""
    remaining = list(actual)
    matched = []
    unmatched_expected = []
    for exp in expected_issues:
        hit_idx = None
        for i, a in enumerate(remaining):
            if a.severity == exp["severity"] and exp["message_contains"] in a.message:
                hit_idx = i
                break
        if hit_idx is not None:
            matched.append(exp)
            remaining.pop(hit_idx)
        else:
            unmatched_expected.append(exp)
    return {
        "matched": len(matched),
        "false_negatives": unmatched_expected,  # 期待したが出なかった
        "unaccounted_actual": remaining,  # 実際に出たが期待リストに無かった（超過分）
    }


def eval_case(case: dict) -> dict:
    actual, parse_error = run_lint(case["sysml"])
    result = {"id": case["id"], "category": case["category"]}
    if parse_error:
        result["error"] = f"parse error: {parse_error}"
        result["pass"] = False
        return result

    if case["category"] == "known_bug":
        # キー名は日付非依存の "_recorded" 系を正とする。過去の日付付きキー名
        # （"_as_of_2026-08-11"）のケースが将来追加された場合のフォールバックも残す。
        recorded = case.get("actual_issues_recorded", case.get("actual_issues_as_of_2026-08-11", []))
        actual_msgs = [(a.severity, a.message) for a in actual]
        recorded_msgs = [(r["severity"], r["message_contains"]) for r in recorded]
        recorded_count = case.get(
            "actual_issue_count_recorded", case.get("actual_issue_count_as_of_2026-08-11", -1)
        )
        drifted = len(actual) != recorded_count
        result.update(
            {
                "actual_issue_count": len(actual),
                "actual_issues": [{"severity": s, "message": m} for s, m in actual_msgs],
                "recorded_issue_count": len(recorded_msgs),
                "drifted_from_recorded": drifted,
            }
        )
        return result

    n = len(actual)
    expected_n = case["expected_issue_count"]
    count_ok = n == expected_n

    if case["category"] == "clean":
        result.update(
            {
                "expected_issue_count": expected_n,
                "actual_issue_count": n,
                "actual_issues": [{"severity": a.severity, "message": a.message} for a in actual],
                "pass": count_ok,
            }
        )
        return result

    # broken: 期待される診断がすべて含まれているかを照合
    match = match_expected_issues(actual, case.get("expected_issues", []))
    result.update(
        {
            "expected_issue_count": expected_n,
            "actual_issue_count": n,
            "actual_issues": [{"severity": a.severity, "message": a.message} for a in actual],
            "matched_expected": match["matched"],
            "false_negatives": match["false_negatives"],
            "unaccounted_actual": [
                {"severity": a.severity, "message": a.message} for a in match["unaccounted_actual"]
            ],
            "pass": count_ok and not match["false_negatives"],
        }
    )
    return result


def run_corpus_scan() -> list[dict]:
    files = sorted(CORPUS_DIR.glob("*.sysml"))
    out = []
    for f in files:
        text = f.read_text(encoding="utf-8")
        actual, parse_error = run_lint(text)
        if parse_error:
            out.append({"file": f.name, "error": parse_error})
            continue
        out.append(
            {
                "file": f.name,
                "issue_count": len(actual),
                "issues": [{"severity": a.severity, "message": a.message} for a in actual],
            }
        )
    return out


def print_summary(results: list[dict]) -> None:
    clean = [r for r in results if r["category"] == "clean"]
    broken = [r for r in results if r["category"] == "broken"]
    known_bugs = [r for r in results if r["category"] == "known_bug"]

    print(f"\n== clean ({len(clean)}件、誤検出が無ければ0件のはず) ==")
    for r in clean:
        mark = "OK" if r.get("pass") else "NG"
        print(f"  [{mark}] {r['id']:<18} actual={r.get('actual_issue_count', '-')}")
        if not r.get("pass"):
            for i in r.get("actual_issues", []):
                print(f"        unexpected: [{i['severity']}] {i['message'][:80]}")

    print(f"\n== broken ({len(broken)}件、期待した診断が出るはず） ==")
    for r in broken:
        mark = "OK" if r.get("pass") else "NG"
        print(f"  [{mark}] {r['id']:<18} expected={r.get('expected_issue_count')} actual={r.get('actual_issue_count')}")
        for fn in r.get("false_negatives", []):
            print(f"        MISSED: [{fn['severity']}] {fn['message_contains'][:80]}")
        for ua in r.get("unaccounted_actual", []):
            print(f"        extra:  [{ua['severity']}] {ua['message'][:80]}")

    clean_pass = sum(1 for r in clean if r.get("pass"))
    broken_pass = sum(1 for r in broken if r.get("pass"))
    print(f"\n== 集計 == clean {clean_pass}/{len(clean)} 通過（誤検出なし） / broken {broken_pass}/{len(broken)} 通過（見逃しなし）")

    if known_bugs:
        print(f"\n== known_bug ({len(known_bugs)}件、pass/failには含めない） ==")
        for r in known_bugs:
            drift = " [挙動が変化！要確認]" if r.get("drifted_from_recorded") else ""
            print(f"  {r['id']:<18} 実際の診断数={r.get('actual_issue_count')} 記録時={r.get('recorded_issue_count')}{drift}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--golden", default=str(DEFAULT_GOLDEN))
    parser.add_argument("--corpus", action="store_true", help="tests/fixtures/sysml_corpus/working/ 全件も走査する")
    parser.add_argument("--output-dir", default=str(DEFAULT_RESULTS_DIR))
    args = parser.parse_args()

    cases = load_golden_set(Path(args.golden))
    results = [eval_case(c) for c in cases]
    print_summary(results)

    corpus_results = run_corpus_scan() if args.corpus else None
    if corpus_results is not None:
        with_issues = [r for r in corpus_results if r.get("issue_count", 0) > 0]
        total_issues = sum(r.get("issue_count", 0) for r in corpus_results)
        print(f"\n== corpus scan ({len(corpus_results)}ファイル) ==")
        print(f"  診断ありファイル: {len(with_issues)} / 総診断数: {total_issues}")
        for r in with_issues:
            print(f"    {r['file']:<35} issues={r['issue_count']}")

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_path = output_dir / f"sysml_lint_{ts}.json"
    out_path.write_text(
        json.dumps({"golden_results": results, "corpus_scan": corpus_results}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"\n結果を保存しました: {out_path}")

    clean = [r for r in results if r["category"] == "clean"]
    broken = [r for r in results if r["category"] == "broken"]
    all_pass = all(r.get("pass") for r in clean + broken)
    return 0 if all_pass else 1


if __name__ == "__main__":
    raise SystemExit(main())
