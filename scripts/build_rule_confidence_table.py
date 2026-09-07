"""`recheck_local_only.py --rule-stats` の出力から、パッケージへ同梱する
confidence テーブル（`sysml_v2_checker_advanced/rule_confidence.json`）を作る。

## なぜ2段階にしてあるのか

計測の出力（`eval/rule_agreement.json`）は gitignore 配下で、発火した全ルールを
未測定のものも含めてそのまま持つ。一方パッケージへ同梱するのは「レビューを経た、
実際に数値が出せるルールだけ」に絞った版であり、生成元（コミット・コーパス・
参照実装のバージョン）を併記する。計測をそのまま出荷しないのは、confidence が
利用者に見える数値であり、どの実行から来たのか後から辿れる必要があるため。

## 使い方

    python scripts/recheck_local_only.py --rule-stats eval/rule_agreement.json
    python scripts/build_rule_confidence_table.py

## 数値の意味

`build_rule_agreement`（recheck_local_only.py）の docstring を参照。要点だけ:
「そのルールだけが error を出したファイル」のうち参照実装も不正と判定した割合で、
**一致率の上限**であって真の精度ではない。
"""

from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SOURCE = REPO_ROOT / "eval" / "rule_agreement.json"
TARGET = REPO_ROOT / "sysml_v2_checker_advanced" / "rule_confidence.json"

# パースエラーは LintIssue ではなく文法側の失敗なので、LintIssue.rule と
# 突き合わせるテーブルには載せない（recheck 側の集計にだけ現れる擬似ルール）。
EXCLUDED_RULES = ("__parse_error__",)

BASIS = "reference_agreement_upper_bound"
CAVEAT = (
    "「そのルールだけが error を出したファイル」のうち、参照実装も同じファイルを"
    "不正と判定した割合。参照実装が同じ箇所を同じ理由で指摘したことまでは"
    "保証しないため、一致率の上限であって真の精度ではない。"
)


def current_commit() -> str:
    try:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=REPO_ROOT, capture_output=True, text=True, check=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def main() -> int:
    if not SOURCE.exists():
        raise SystemExit(
            f"{SOURCE} がありません。先に "
            "python scripts/recheck_local_only.py --rule-stats eval/rule_agreement.json "
            "を実行してください。"
        )

    measurement = json.loads(SOURCE.read_text(encoding="utf-8"))
    rules = {}
    for rule, stats in sorted(measurement["rules"].items()):
        if rule in EXCLUDED_RULES or stats["confidence"] is None:
            continue
        rules[rule] = {
            "value": stats["confidence"],
            "sole_agree": stats["sole_agree"],
            "sole_disagree": stats["sole_disagree"],
        }

    TARGET.write_text(json.dumps({
        "generated_at": time.strftime("%Y-%m-%d"),
        "generated_from": {
            "script": "scripts/recheck_local_only.py --rule-stats",
            "commit": current_commit(),
            "corpus": "eval/sysml_samples",
            "corpus_files": measurement["total_files"],
            "reference": "OMG SysML v2 Pilot Implementation jar 0.61.0",
        },
        "min_samples": measurement["min_rule_samples"],
        "basis": BASIS,
        "caveat": CAVEAT,
        "rules": rules,
    }, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")

    total = len(measurement["rules"])
    print(f"{TARGET} を書き出した: 発火{total}ルール中{len(rules)}ルール"
          f"（単独発火{measurement['min_rule_samples']}件以上、擬似ルールを除く）")
    for rule, entry in sorted(rules.items(), key=lambda kv: kv[1]["value"]):
        print(f"  {entry['value']:.3f}  {rule}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
