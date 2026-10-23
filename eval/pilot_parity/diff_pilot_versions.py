"""段階 E: Pilot の 2 つの版の正解ラベルを比べ、何が変わったかをメッセージごとに数える。

    .venv\\Scripts\\python.exe -I eval/pilot_parity/diff_pilot_versions.py --old labels --new labels_063

各コーパス（開発・held-out・フォルダ・新しい held-out）について、<コーパス>/<old>/pilot と <コーパス>/<new>/pilot の
同じ unit の指摘（error と warning、(行, メッセージ)）を比べる。メッセージの中の名前は 'X' に置き換えてまとめる。

出力: version_diff.json（コーパスごとの、増えた・消えた指摘のメッセージ別の件数と例）と標準出力の表。
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
CORPORA = {"dev": HERE, "heldout": HERE / "heldout", "folders": HERE / "folders", "heldout2": HERE / "heldout2"}


def shape(message: str) -> str:
    return re.sub(r"'[^']*'", "'X'", message or "")


def issues(path: Path) -> list[tuple[int, str, str]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    return [(i.get("line"), i.get("severity"), i.get("message") or "") for i in data.get("issues", [])]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--old", default="labels")
    ap.add_argument("--new", default="labels_063")
    ap.add_argument("--out", type=Path, default=HERE / "version_diff.json")
    args = ap.parse_args()
    report: dict = {}
    lines = []
    for name, root in CORPORA.items():
        old_dir, new_dir = root / args.old / "pilot", root / args.new / "pilot"
        if not new_dir.exists():
            continue
        added, removed = Counter(), Counter()
        examples: dict = {}
        units_changed = 0
        files = sorted(new_dir.glob("*.json"))
        for f in files:
            old_f = old_dir / f.name
            if not old_f.exists():
                continue
            a, b = set(issues(old_f)), set(issues(f))
            if a != b:
                units_changed += 1
            for line, sev, msg in b - a:
                key = (sev, shape(msg))
                added[key] += 1
                examples.setdefault(("+",) + key, (f.stem, line, msg))
            for line, sev, msg in a - b:
                key = (sev, shape(msg))
                removed[key] += 1
                examples.setdefault(("-",) + key, (f.stem, line, msg))
        report[name] = {
            "units": len(files), "units_changed": units_changed,
            "added": [{"severity": k[0], "message": k[1], "n": n, "example": examples[("+",) + k]}
                      for k, n in added.most_common()],
            "removed": [{"severity": k[0], "message": k[1], "n": n, "example": examples[("-",) + k]}
                        for k, n in removed.most_common()],
        }
        lines.append(f"## {name}: {units_changed} / {len(files)} units changed")
        for k, n in added.most_common(12):
            lines.append(f"  + {n:4d} [{k[0]}] {k[1][:100]}   e.g. {examples[('+',) + k][0][:50]}:{examples[('+',) + k][1]}")
        for k, n in removed.most_common(12):
            lines.append(f"  - {n:4d} [{k[0]}] {k[1][:100]}   e.g. {examples[('-',) + k][0][:50]}:{examples[('-',) + k][1]}")
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    sys.stdout.buffer.write(("\n".join(lines) + "\n").encode("utf-8"))


if __name__ == "__main__":
    main()
