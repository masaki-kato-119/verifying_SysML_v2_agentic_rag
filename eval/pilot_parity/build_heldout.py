"""段階 A〜D の開発に使っていない公開モデルで、評価用のコーパス（held-out）を作る。

研究の結果（RESULTS.md）の汎化の確認用。開発用のコーパス（build_corpus.py）は、規則を作るときに
見たデータなので、そこでの数値は楽観的になりうる。ここでは C:\\test\\sysml_models に集めた公開
リポジトリのモデルを、ディレクトリごとに 1 件（unit）にまとめる（ファイルをまたぐ import を
解決するため）。標準ライブラリそのもの（sysml.library）と、開発用コーパスの元（eval/・verified/）は除く。

    .venv\\Scripts\\python.exe -I eval/pilot_parity/build_heldout.py
    （ラベル・自作・比較は --corpus / --out / --labels に heldout/ 以下を渡す。RESULTS.md の再現手順）

出力: heldout/corpus/units/<id>.sysml と heldout/corpus/manifest.json（source はリポジトリ名）。
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

from build_corpus import concat

HERE = Path(__file__).resolve().parent
DEFAULT_MODELS = Path(r"C:\test\sysml_models")
EXCLUDED_TOP = {"eval", "verified", "memory_drafts", "analysis"}
EXCLUDED_PARTS = {"sysml.library"}


def build(models: Path, out: Path) -> list[dict]:
    units_dir = out / "units"
    units_dir.mkdir(parents=True, exist_ok=True)
    for old in units_dir.glob("*.sysml"):
        old.unlink()
    by_dir: dict[Path, list[Path]] = {}
    for path in sorted(models.rglob("*.sysml")):
        rel = path.relative_to(models)
        if rel.parts[0] in EXCLUDED_TOP or EXCLUDED_PARTS & set(rel.parts):
            continue
        by_dir.setdefault(path.parent, []).append(path)
    manifest = []
    for directory, files in sorted(by_dir.items()):
        rel = directory.relative_to(models).as_posix()
        uid = "heldout-" + re.sub(r"[^\w.-]+", "_", rel)
        (units_dir / f"{uid}.sysml").write_text(concat(files, directory), encoding="utf-8")
        manifest.append({"id": uid, "source": rel.split("/")[0], "origin": rel, "operator": None, "line": None,
                         "files": len(files)})
    (out / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8")
    return manifest


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--models", type=Path, default=DEFAULT_MODELS)
    ap.add_argument("--out", type=Path, default=HERE / "heldout" / "corpus")
    args = ap.parse_args()
    manifest = build(args.models, args.out)
    counts: dict[str, int] = {}
    for entry in manifest:
        counts[entry["source"]] = counts.get(entry["source"], 0) + 1
    print(json.dumps({"units": len(manifest), "files": sum(m["files"] for m in manifest), "by_source": counts},
                     ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
