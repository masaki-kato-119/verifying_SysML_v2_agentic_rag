"""コーパスの各 unit を自作チェッカーで検証し、位置付きの指摘を保存する。

このリポジトリの venv で実行する:

    .venv\\Scripts\\python.exe -I eval/pilot_parity/run_local.py

パースエラーは parse_sysml の {"type": "error", "message": "... (line N, column M); ..."} を
1 件ずつに分ける（syntax_error=True）。lint の指摘は lint_text_with_locations() の行と rule を使う。

出力: labels/local/<id>.json = {id, crashed, issues: [{severity, line, syntax_error, message, rule}]}
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import traceback
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
sys.path.insert(0, str(REPO))

_POSITION = re.compile(r"\(line (\d+), column (\d+)\)")
# パースエラーがあっても読めた部分を lint する（lint_text_with_locations の recover）。
# 段階 A から既定で有効。--no-recover で従来（パースエラーなら lint しない）と比べられる。
RECOVER = True


def check(text: str) -> dict:
    from sysml_v2_checker_advanced.semantic_model import lint_text_with_locations

    try:
        ast, _issues, dicts = lint_text_with_locations(text, recover=RECOVER)
    except Exception as exc:  # noqa: BLE001 -- 自作チェッカー自体のクラッシュも評価対象として残す
        return {"crashed": True, "crash": f"{type(exc).__name__}: {exc}\n{traceback.format_exc()}", "issues": []}
    issues = []
    if ast.get("type") == "error":
        for part in ast.get("message", "").split("; "):
            m = _POSITION.search(part)
            issues.append({"severity": "error", "line": int(m.group(1)) if m else None, "syntax_error": True,
                           "message": part, "rule": "parse"})
    for d in dicts:
        issues.append({"severity": d.get("severity"), "line": d.get("line"), "syntax_error": False,
                       "message": d.get("message"), "rule": d.get("rule")})
    return {"crashed": False, "issues": issues}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--corpus", type=Path, default=HERE / "corpus")
    ap.add_argument("--out", type=Path, default=HERE / "labels" / "local")
    ap.add_argument("--no-recover", action="store_true", help="パースエラーがあれば lint しない（段階 A より前の挙動）")
    args = ap.parse_args()
    global RECOVER
    RECOVER = not args.no_recover
    manifest = json.loads((args.corpus / "manifest.json").read_text(encoding="utf-8"))
    args.out.mkdir(parents=True, exist_ok=True)
    for entry in manifest:
        text = (args.corpus / "units" / f"{entry['id']}.sysml").read_text(encoding="utf-8")
        result = {"id": entry["id"], **check(text)}
        (args.out / f"{entry['id']}.json").write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
    print(f"checked {len(manifest)} units -> {args.out}")


if __name__ == "__main__":
    main()
