"""フォルダ単位のコーパスの結果をまとめる（複数ファイル対応の前後、dev / held-out、ファイルをまたぐ誤り）。

compare.py をフォルダのラベルで 2 回実行してから使う（BASELINE.md「フォルダ単位のコーパス」の再現手順）:

    compare.py --corpus folders/corpus --labels folders/labels        --out folders/results/multi
    compare.py --corpus folders/corpus --labels folders/labels_single --out folders/results/single
    .venv\\Scripts\\python.exe -I eval/pilot_parity/analyze_folders.py

出力: folders/results/SUMMARY.md と summary.json。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE / "folders"  # main() の --root で変える
MODES = {"single": "1 ファイルずつ（以前の MCP）", "multi": "フォルダを読む（今の MCP）"}


def load_units(mode: str) -> dict[str, dict]:
    return {u["id"]: u for u in json.loads((ROOT / "results" / mode / "units.json").read_text(encoding="utf-8"))}


def rate(num: int, den: int) -> str:
    return f"{num / den:.1%}" if den else "—"


def line_kind(rows: list[dict]) -> tuple[int, int, int]:
    """Pilot に構文エラーの無いファイルの、行 + 種類の (一致, Pilot, 自作)。RESULTS.md の主な指標と同じ数え方。"""
    rows = [r for r in rows if "syntax" not in r["pilot_categories"]]
    return sum(r["matched"] for r in rows), sum(r["pilot_n"] for r in rows), sum(r["local_n"] for r in rows)


def main() -> None:
    import argparse

    global ROOT
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--root", default="folders", help="コーパスの置き場所（folders / heldout2）")
    ROOT = HERE / ap.parse_args().root
    manifest = {m["id"]: m for m in json.loads((ROOT / "corpus" / "manifest.json").read_text(encoding="utf-8"))}
    pilot_labels = ROOT / "labels" / "pilot"
    hidden = {uid for uid in manifest
              if json.loads((pilot_labels / f"{uid}.json").read_text(encoding="utf-8")).get("hidden")}
    summary: dict = {}
    lines = ["# フォルダ単位のコーパスの結果", "",
             f"ファイル {len(manifest)} 件（フォルダ {len({m['folder'] for m in manifest.values()})} 個）。"
             f"Pilot がほかのファイルから見えなくしたファイル（最上位のパッケージ名が標準ライブラリと重なる）: {len(hidden)} 件。", ""]

    lines += ["## 行 + 種類（Pilot に構文エラーの無いファイル）", "",
              "| source | ファイル | " + " | ".join(f"{label} 再現率 / 適合率" for label in MODES.values())
              + " | " + " | ".join(f"{label} 誤検出のファイル" for label in MODES.values()) + " |",
              "| --- | --- | " + " | ".join("---" for _ in MODES) + " | " + " | ".join("---" for _ in MODES) + " |"]
    units = {mode: load_units(mode) for mode in MODES}
    for source in ("folder-dev", "folder-heldout", "folder-heldout2", "xfile-mutant"):
        ids = [uid for uid, m in manifest.items() if m["source"] == source]
        cells, alarms = [], []
        for mode in MODES:
            rows = [units[mode][uid] for uid in ids]
            m, p, loc = line_kind(rows)
            cells.append(f"{rate(m, p)} / {rate(m, loc)}")
            false_alarm = sum(r["verdict"] == "false_alarm" for r in rows)
            clean = sum(r["verdict"] in ("false_alarm", "both_clean") for r in rows)
            alarms.append(f"{false_alarm} / {clean}")
            summary.setdefault(source, {})[mode] = {"matched": m, "pilot": p, "local": loc,
                                                    "false_alarm_files": false_alarm, "pilot_clean_files": clean}
        n_rows = len([1 for uid in ids if "syntax" not in units["multi"][uid]["pilot_categories"]])
        lines.append(f"| {source} | {n_rows} / {len(ids)} | " + " | ".join(cells) + " | " + " | ".join(alarms) + " |")

    # ファイルをまたぐ誤り: Pilot が入れた行にエラーを出したもののうち、自作も同じ行にエラーを出したか
    lines += ["", "## ファイルをまたぐ誤り（xfile-mutant）", "",
              "Pilot が誤りを入れた行にエラーを出した版のうち、自作も同じ行にエラー（種類は問わない / 同じ種類）を出した数。", "",
              "| operator | 版 | Pilot がその行に出した | " + " | ".join(f"{label}: 行 / 行 + 種類" for label in MODES.values()) + " |",
              "| --- | --- | --- | " + " | ".join("---" for _ in MODES) + " |"]
    mutants = [m for m in manifest.values() if m["source"] == "xfile-mutant"]
    for op in sorted({m["operator"] for m in mutants}) + ["(合計)"]:
        rows = [m for m in mutants if op == "(合計)" or m["operator"] == op]
        injected = [m for m in rows if any(k[0] == m["line"] for k in units["multi"][m["id"]]["pilot_keys"])]
        cells = []
        for mode in MODES:
            on_line = sum(any(k[0] == m["line"] for k in units[mode][m["id"]]["local_keys"]) for m in injected)
            same_kind = sum(bool({tuple(k) for k in units[mode][m["id"]]["local_keys"] if k[0] == m["line"]}
                                 & {tuple(k) for k in units[mode][m["id"]]["pilot_keys"] if k[0] == m["line"]})
                            for m in injected)
            cells.append(f"{on_line} / {same_kind}")
            summary.setdefault("xfile-mutant-detection", {}).setdefault(op, {})[mode] = {
                "on_line": on_line, "same_kind": same_kind}
        summary["xfile-mutant-detection"][op]["mutants"] = len(rows)
        summary["xfile-mutant-detection"][op]["pilot_error"] = len(injected)
        lines.append(f"| {op} | {len(rows)} | {len(injected)} | " + " | ".join(cells) + " |")

    out = ROOT / "results"
    (out / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")
    (out / "SUMMARY.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    # -I では PYTHONIOENCODING が効かないので、コンソールの文字コード（cp932）に無い文字があっても落ちないように書く
    sys.stdout.buffer.write(("\n".join(lines) + "\n").encode("utf-8"))


if __name__ == "__main__":
    main()
