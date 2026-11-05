"""ルールごとの confidence（sysml_v2_checker_advanced/rule_confidence.json）を、Pilot との差分評価の
コーパスで測り直す（2026-11-05）。

以前の表（scripts/build_rule_confidence_table.py、2026-09-25）は 730 件コーパスで「そのルールだけが error を
出したファイルを、参照実装も不正と判定した割合」（ファイル単位の一致率の上限）だった。ファイル単位の一致は
違う箇所・違う理由の指摘も当たりに数えてしまう。ここでは compare.py と同じ「行 + 種類」で、各指摘について
Pilot が同じ行に同じ種類のエラーを出したかを数える（指摘単位の適合率）。構文エラー（rule が parse）は表に載せない。

コーパス: 開発（corpus）・held-out（heldout）・フォルダ単位（folders）・2 つ目〜4 つ目の held-out。
各コーパスの labels/pilot と labels/local を読むので、先に run_local*.py で自作の結果を作り直しておく。

    .venv\\Scripts\\python.exe -I eval\\pilot_parity\\build_rule_confidence.py
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
sys.path.insert(0, str(HERE))

from compare import category, is_error  # noqa: E402

TARGET = REPO / "sysml_v2_checker_advanced" / "rule_confidence.json"
CORPORA = {"dev": HERE, "heldout": HERE / "heldout", "folders": HERE / "folders",
           "heldout2": HERE / "heldout2", "heldout3": HERE / "heldout3", "heldout4": HERE / "heldout4"}
MIN_SAMPLES = 5
BASIS = "pilot_line_kind_precision"
CAVEAT = ("このルールの指摘のうち、参照実装（Pilot）が同じ行に同じ種類のエラー（未解決参照・型の種類など）を出した"
          "割合。文言まで同じとは限らない。Pilot に構文エラーのあるファイルも含む（エラー回復の違いで下がる）。")


def corpus_ids(root: Path) -> list[str]:
    manifest = root / "corpus" / "manifest.json"
    return [m["id"] for m in json.loads(manifest.read_text(encoding="utf-8"))]


def measure() -> tuple[dict, dict, dict]:
    stats: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    clean_stats: dict[str, list[int]] = defaultdict(lambda: [0, 0])  # Pilot に構文エラーの無いファイルだけ
    sizes = {}
    for name, root in CORPORA.items():
        if not (root / "corpus" / "manifest.json").exists():
            continue
        n = 0
        for uid in corpus_ids(root):
            p_path, l_path = root / "labels" / "pilot" / f"{uid}.json", root / "labels" / "local" / f"{uid}.json"
            if not p_path.exists() or not l_path.exists():
                continue
            n += 1
            pilot = json.loads(p_path.read_text(encoding="utf-8"))
            local = json.loads(l_path.read_text(encoding="utf-8"))
            p_keys = {(i.get("line"), category(i, "pilot")) for i in pilot["issues"] if is_error(i)}
            pilot_syntax = any(i.get("syntax_error") for i in pilot["issues"] if is_error(i))
            for issue in local["issues"]:
                if not is_error(issue) or issue.get("syntax_error") or not issue.get("rule"):
                    continue
                cat = category(issue, "local")
                if cat == "syntax":
                    continue
                key = (issue.get("line"), cat)
                # 自作は原因だけ、Pilot は連鎖も出す（compare.py の CASCADES）。原因の指摘はそのまま比べる
                hit = key in p_keys
                stats[issue["rule"]][0 if hit else 1] += 1
                if not pilot_syntax:
                    clean_stats[issue["rule"]][0 if hit else 1] += 1
        sizes[name] = n
    return stats, clean_stats, sizes


def main() -> None:
    stats, clean_stats, sizes = measure()
    commit = subprocess.run(["git", "rev-parse", "HEAD"], cwd=REPO, capture_output=True, text=True).stdout.strip()
    rules = {}
    for rule, (agree, disagree) in sorted(stats.items()):
        if agree + disagree < MIN_SAMPLES:
            continue
        rules[rule] = {"value": round(agree / (agree + disagree), 3), "agree": agree, "disagree": disagree}
        clean_agree, clean_disagree = clean_stats.get(rule, (0, 0))
        if clean_agree + clean_disagree >= MIN_SAMPLES:
            # 構文エラーの無いファイルだけの値（エラー回復の違いを除く。構文エラーを直したあとの目安）
            rules[rule]["value_without_syntax_errors"] = round(clean_agree / (clean_agree + clean_disagree), 3)
    document = {
        "generated_at": time.strftime("%Y-%m-%d"),
        "generated_from": {
            "script": "eval/pilot_parity/build_rule_confidence.py",
            "commit": commit,
            "corpora": sizes,
            "reference": "OMG SysML v2 Pilot Implementation 0.63.0（開発・held-out・フォルダは 0.62.0 の正解。"
                         "BASELINE.md の段階 E で 2 つの版の差はメッセージ 2 つだけ）",
        },
        "min_samples": MIN_SAMPLES,
        "basis": BASIS,
        "caveat": CAVEAT,
        "rules": rules,
    }
    TARGET.write_text(json.dumps(document, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    for rule, entry in sorted(rules.items(), key=lambda kv: kv[1]["value"]):
        print(f"{entry['value']:.3f} {entry.get('value_without_syntax_errors', float('nan')):.3f} "
              f"{entry['agree']:6d} {entry['disagree']:5d} {rule}")
    print(f"{len(rules)} rules -> {TARGET}  corpora={sizes}")


if __name__ == "__main__":
    main()
