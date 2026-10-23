"""フォルダ単位のコーパス（build_folders.py）の各ファイルを、自作チェッカーで検証する。

既定は MCP の lint_sysml_file の既定と同じく、同じフォルダのほかのファイルを一緒に読む
（model_files.parse_other_file。構文エラーのファイルは、エラー回復で読めた部分を使う）。
--single は、ほかのファイルを読まない（複数ファイル対応の前の MCP と同じ）。

    .venv\\Scripts\\python.exe -I eval/pilot_parity/run_local_folders.py             # → folders/labels/local
    .venv\\Scripts\\python.exe -I eval/pilot_parity/run_local_folders.py --single    # → folders/labels_single/local

出力の形は run_local.py と同じ（compare.py にそのまま渡せる）。
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import traceback
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(HERE))

from run_local import _POSITION  # noqa: E402


def check(text: str, other_asts: list) -> dict:
    from sysml_v2_checker_advanced.semantic_model import lint_text_with_locations

    try:
        ast, _issues, dicts = lint_text_with_locations(text, recover=True, other_asts=other_asts)
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
    ap.add_argument("--single", action="store_true", help="ほかのファイルを読まない")
    ap.add_argument("--root", default="folders", help="コーパスの置き場所（folders / heldout2）")
    ap.add_argument("--missing", action="store_true", help="結果の無いファイルだけ検証する（誤りを入れた版を足したあと）")
    args = ap.parse_args()
    from sysml_v2_checker_advanced.model_files import parse_other_file

    base = HERE / args.root
    corpus = base / "corpus"
    labels = base / ("labels_single" if args.single else "labels")
    out = labels / "local"
    out.mkdir(parents=True, exist_ok=True)
    if args.single:
        # compare.py は <labels>/pilot と <labels>/local を読む。Pilot のラベルは同じものを使う
        pilot = base / "labels" / "pilot"
        if (labels / "pilot").exists():
            shutil.rmtree(labels / "pilot")
        shutil.copytree(pilot, labels / "pilot")
    manifest = json.loads((corpus / "manifest.json").read_text(encoding="utf-8"))
    by_folder: dict[str, list[dict]] = {}
    for entry in manifest:
        by_folder.setdefault(entry["folder"], []).append(entry)
    for n, (folder, entries) in enumerate(sorted(by_folder.items()), 1):
        if args.missing:
            entries = [e for e in entries if not (out / f"{e['id']}.json").exists()]
            if not entries:
                continue
        directory = corpus / "folders" / folder
        asts = {}
        if not args.single:
            for path in sorted(directory.glob("*.sysml")):
                ast, _errors = parse_other_file(path.read_text(encoding="utf-8"))
                if ast is not None:
                    asts[path.name] = ast
        for e in entries:
            text = (corpus / "units" / f"{e['id']}.sysml").read_text(encoding="utf-8")
            others = [ast for name, ast in asts.items() if name != e["file"]]
            result = {"id": e["id"], **check(text, others)}
            (out / f"{e['id']}.json").write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
        if n % 20 == 0:
            print(f"{n}/{len(by_folder)}", flush=True)
    print(f"checked {len(manifest)} files in {len(by_folder)} folders -> {out}")


if __name__ == "__main__":
    main()
