"""複数ファイルのモデルを、フォルダ単位で比べるためのコーパスを作る（2026-10-22、複数ファイル対応の測定）。

開発用（build_corpus.py）・held-out（build_heldout.py）のコーパスは、フォルダのファイルをつないだ 1 テキストを
1 unit にしていた。ここではフォルダをそのまま残し、ファイルごとに 1 unit にする（Pilot はフォルダのファイルを
一緒に読み、自作はそのファイルをほかのファイルと一緒に lint する）。unit の id は `<フォルダ>__<ファイル>` で、
compare.py をそのまま使える（manifest と units/<id>.sysml の形が同じ）。

    .venv\\Scripts\\python.exe -I eval/pilot_parity/build_folders.py              # フォルダ（2 ファイル以上）
    （Pilot のラベルを付けてから）
    .venv\\Scripts\\python.exe -I eval/pilot_parity/build_folders.py --mutants    # Pilot がエラーを出さないフォルダに
                                                                                 # ファイルをまたぐ誤りを 1 つずつ入れる

source:
  folder-dev      開発で見たモデル（eval/runs・eval/runs_sonnet・eval/linter_gen の AGV、verified のテーマ）
  folder-heldout  held-out と同じ公開リポジトリのフォルダ（build_heldout.py と同じ除外）
  folder-heldout2 --heldout2: 研究に使っていない題材で、Sonnet / Haiku に 1 回で書かせたモデル
                  （C:\\test\\sysml_models\\eval\\heldout2\\<書き手>_<題材>。出力は heldout2/ 以下。2026-10-23）
  xfile-mutant    Pilot がエラーを出さないフォルダの 1 ファイルに、ほかのファイルで宣言された名前の誤記を 1 つ入れたもの
                  （operator: xfile_type_typo / xfile_feature_typo / xfile_import_typo。origin は元のフォルダの id）

出力: folders/corpus/manifest.json、folders/corpus/units/<id>.sysml（そのファイルのテキスト）、
folders/corpus/folders/<フォルダの id>/<ファイル>（一緒に読むファイル）。manifest の各要素は
{id, source, origin, folder, file, operator, line}。
"""

from __future__ import annotations

import argparse
import json
import random
import re
import shutil
from pathlib import Path

from build_corpus import read

HERE = Path(__file__).resolve().parent
DEFAULT_MODELS = Path(r"C:\test\sysml_models")
OUT = HERE / "folders" / "corpus"
# held-out と同じ除外（build_heldout.py）
EXCLUDED_TOP = {"eval", "verified", "memory_drafts", "analysis"}
EXCLUDED_PARTS = {"sysml.library"}
# 開発で見たフォルダ（eval/blind* は eval/runs* の名前を伏せた写しなので入れない）
DEV_GLOBS = ["eval/runs/*", "eval/runs_sonnet/*", "eval/linter_gen/model", "eval/linter_gen/round1_src",
             "verified/*", "verified/structure/skeleton/*"]
MUTANTS_PER_OPERATOR = 2

_DEF_DECL = re.compile(
    r"\b(?:part|attribute|port|item|action|state|requirement|interface|connection|calc|constraint|enum|"
    r"occurrence|flow|allocation|view|viewpoint|rendering|metadata|concern|individual)\s+def\s+([A-Za-z_]\w*)"
    r"|\b(?:use\s+case|verification|analysis|case)\s+def\s+([A-Za-z_]\w*)")
_USAGE_DECL = re.compile(
    r"\b(?:part|attribute|port|item|action|state|requirement|ref|in|out|inout|calc|constraint|occurrence|"
    r"exhibit\s+state|perform\s+action|interface|connection|flow|message|event\s+occurrence)\s+([a-z_]\w*)\b")
_PACKAGE_DECL = re.compile(r"\bpackage\s+([A-Za-z_]\w*)")
_IMPORT = re.compile(r"\bimport\s+([A-Za-z_]\w*)(?=::)")
# コメントと文字列（ここには誤りを入れない）
_SKIP = re.compile(r"/\*.*?\*/|//[^\n]*|\"(?:[^\"\\]|\\.)*\"|'(?:[^'\\]|\\.)*'", re.S)


def folder_id(rel: str) -> str:
    return "folder-" + re.sub(r"[^\w.-]+", "_", rel)


def collect_heldout2(models: Path) -> list[tuple[str, Path, list[Path]]]:
    """新しい held-out（eval/heldout2 の各フォルダ。2 ファイル以上）。"""
    out = []
    for directory in sorted(p for p in (models / "eval" / "heldout2").iterdir() if p.is_dir()):
        files = sorted(directory.glob("*.sysml"))
        if len(files) >= 2:
            out.append(("folder-heldout2", directory, files))
    return out


def collect_folders(models: Path) -> list[tuple[str, Path, list[Path]]]:
    """(source, フォルダ, ファイル)。2 ファイル以上のフォルダだけ（サブフォルダは含めない。validate_sysml の既定と同じ）。"""
    out = []
    dev_dirs = {d.resolve() for pattern in DEV_GLOBS for d in models.glob(pattern) if d.is_dir()}
    by_dir: dict[Path, list[Path]] = {}
    for path in sorted(models.rglob("*.sysml")):
        rel = path.relative_to(models)
        if EXCLUDED_PARTS & set(rel.parts):
            continue
        by_dir.setdefault(path.parent, []).append(path)
    for directory, files in sorted(by_dir.items()):
        if len(files) < 2:
            continue
        top = directory.relative_to(models).parts[0]
        if directory.resolve() in dev_dirs:
            out.append(("folder-dev", directory, files))
        elif top not in EXCLUDED_TOP:
            out.append(("folder-heldout", directory, files))
    return out


def write_folder(uid: str, texts: dict[str, str], source: str, origin: str, manifest: list,
                 operator: str | None = None, line: int | None = None, mutated: str | None = None) -> None:
    target = OUT / "folders" / uid
    if target.exists():
        shutil.rmtree(target)
    target.mkdir(parents=True)
    for name, text in texts.items():
        (target / name).write_text(text, encoding="utf-8")
    for name, text in texts.items():
        if mutated is not None and name != mutated:
            continue  # 誤りを入れた版は、入れたファイルだけを unit にする（ほかのファイルは元と同じ）
        safe_name = re.sub(r"[^\w.-]+", "_", name)
        file_uid = f"{uid}__{safe_name}"
        (OUT / "units" / f"{file_uid}.sysml").write_text(text, encoding="utf-8")
        manifest.append({"id": file_uid, "source": source, "origin": origin, "folder": uid, "file": name,
                         "operator": operator, "line": line if name == mutated else None})


def _outside(text: str) -> list[tuple[int, int]]:
    spans, last = [], 0
    for m in _SKIP.finditer(text):
        spans.append((last, m.start()))
        last = m.end()
    spans.append((last, len(text)))
    return spans


def _candidates(text: str, pattern: re.Pattern, names: set[str]) -> list[tuple[int, int, str]]:
    out = []
    for start, end in _outside(text):
        for m in pattern.finditer(text, start, end):
            name = m.group(1)
            if name in names:
                out.append((m.start(1), m.end(1), name))
    return out


def _typo(name: str, taken: set[str]) -> str | None:
    """1 文字の誤記（最後から 2 文字目を落とす）。フォルダのどこにも無い名前になるものだけ。"""
    if len(name) < 4:
        return None
    typo = name[:-2] + name[-1]
    return typo if typo not in taken else None


def mutate_folder(uid: str, texts: dict[str, str], manifest: list, rng: random.Random) -> int:
    declared = {}
    for name, text in texts.items():
        body = _SKIP.sub(" ", text)
        declared[name] = {
            "type": {a or b for a, b in _DEF_DECL.findall(body)},
            "feature": set(_USAGE_DECL.findall(body)),
            "package": set(_PACKAGE_DECL.findall(body)),
        }
    all_words = set(re.findall(r"[A-Za-z_]\w*", "\n".join(texts.values())))
    made = 0
    operators = {
        # ほかのファイルで宣言された型の名前（`part x : Vehicle;` の Vehicle）
        "xfile_type_typo": (re.compile(r"(?<![\w.:])([A-Z]\w*)\b(?!\s*(?:\{|;))"), "type"),
        # ほかのファイルで宣言された feature の名前の、連鎖の 2 番目以降（`v.maxSpeed` の maxSpeed）
        "xfile_feature_typo": (re.compile(r"(?<=\.)([a-z_]\w*)\b"), "feature"),
        # ほかのファイルのパッケージの import（`private import Defs::*;` の Defs）
        "xfile_import_typo": (_IMPORT, "package"),
    }
    for operator, (pattern, kind) in operators.items():
        sites = []
        for name, text in texts.items():
            own = declared[name][kind]
            others = set().union(*(d[kind] for n, d in declared.items() if n != name)) - own
            for start, end, word in _candidates(text, pattern, others):
                sites.append((name, start, end, word))
        rng.shuffle(sites)
        used_words = set()
        for name, start, end, word in sites:
            typo = _typo(word, all_words)
            if typo is None or word in used_words:
                continue
            used_words.add(word)
            text = texts[name]
            line = text.count("\n", 0, start) + 1
            mutated = {**texts, name: text[:start] + typo + text[end:]}
            n = sum(1 for m in manifest if m.get("operator") == operator and m["origin"] == uid)
            write_folder(f"{uid}--{operator}-{n:02d}", mutated, "xfile-mutant", uid, manifest,
                         operator=operator, line=line, mutated=name)
            made += 1
            if len(used_words) >= MUTANTS_PER_OPERATOR:
                break
    return made


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--models", type=Path, default=DEFAULT_MODELS)
    ap.add_argument("--mutants", action="store_true",
                    help="Pilot がエラーを出さないフォルダ（<root>/labels/pilot）に誤りを入れた版を足す")
    ap.add_argument("--heldout2", action="store_true",
                    help="新しい held-out（eval/heldout2）を heldout2/ 以下に作る")
    args = ap.parse_args()
    global OUT
    root = HERE / ("heldout2" if args.heldout2 else "folders")
    OUT = root / "corpus"
    manifest_path = OUT / "manifest.json"
    if args.mutants:
        manifest = [m for m in json.loads(manifest_path.read_text(encoding="utf-8")) if m["source"] != "xfile-mutant"]
        for old in (OUT / "folders").glob("*--*"):
            shutil.rmtree(old)
        for old in (OUT / "units").glob("*--*"):
            old.unlink()
        labels = root / "labels" / "pilot"
        clean = {}
        for m in manifest:
            label = labels / f"{m['id']}.json"
            if not label.exists():
                continue
            issues = json.loads(label.read_text(encoding="utf-8"))["issues"]
            ok = not any(i["severity"] == "error" for i in issues)
            clean[m["folder"]] = clean.get(m["folder"], True) and ok
        made = 0
        for uid in sorted(u for u, ok in clean.items() if ok):
            folder = OUT / "folders" / uid
            texts = {p.name: p.read_text(encoding="utf-8") for p in sorted(folder.glob("*.sysml"))}
            made += mutate_folder(uid, texts, manifest, random.Random(uid))
        print(json.dumps({"clean_folders": sum(clean.values()), "mutants": made}, ensure_ascii=False))
    else:
        if OUT.exists():
            shutil.rmtree(OUT)
        (OUT / "units").mkdir(parents=True)
        manifest = []
        collected = collect_heldout2(args.models) if args.heldout2 else collect_folders(args.models)
        for source, directory, files in collected:
            rel = directory.relative_to(args.models).as_posix()
            texts = {f.name: read(f) for f in files}
            write_folder(folder_id(rel), texts, source, rel, manifest)
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8")
    counts: dict[str, int] = {}
    for m in manifest:
        counts[m["source"]] = counts.get(m["source"], 0) + 1
    print(json.dumps({"units": len(manifest), "folders": len({m["folder"] for m in manifest}), "by_source": counts},
                     ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
