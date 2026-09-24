"""公式実装（参照実装）と自作チェッカーに同じ入力を与え、判定を並べて表示する。

規則の境界を「推測でなく実測で」決めるための道具。1回のJVM起動（ReferenceBatch）で
複数の入力をまとめて問い合わせ、前後にcanaryを挟んで結果の健全性を確かめる
（参照実装は負荷下で黙って0件を返すことがあるため。canaryが通らない回の結果は
信用しないこと）。

入力の与え方:

    # ファイル（またはディレクトリ内の *.sysml）をそのまま判定する
    .venv/Scripts/python.exe scripts/probe_reference.py tests/fixtures/reference_conformance

    # 1つのテキストファイルに複数のケースを並べる。`--- <名前>` の行で区切る
    .venv/Scripts/python.exe scripts/probe_reference.py --cases cases.txt

判定は「エラーの有無」の一致で見る（check_repros.py と同じ）。一致しないケースが
あれば終了コード 1。
"""

from __future__ import annotations

import argparse
import importlib.util
import sys
import tempfile
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

REFERENCE_DRIVER_PATH = REPO_ROOT / "eval" / "sysml_reference" / "reference_driver.py"


def _load_reference_driver():
    spec = importlib.util.spec_from_file_location("sysml_reference_driver", REFERENCE_DRIVER_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _split_cases(text: str) -> list[tuple[str, str]]:
    cases: list[tuple[str, str]] = []
    name, lines = None, []
    for line in text.splitlines():
        if line.startswith("--- "):
            if name is not None:
                cases.append((name, "\n".join(lines) + "\n"))
            name, lines = line[4:].strip(), []
        else:
            lines.append(line)
    if name is not None:
        cases.append((name, "\n".join(lines) + "\n"))
    return cases


def _collect_inputs(args) -> list[tuple[str, str]]:
    inputs: list[tuple[str, str]] = []
    for raw in args.paths:
        path = Path(raw)
        files = sorted(path.glob("*.sysml")) if path.is_dir() else [path]
        for f in files:
            inputs.append((f.name, f.read_text(encoding="utf-8")))
    if args.cases:
        inputs.extend(_split_cases(Path(args.cases).read_text(encoding="utf-8")))
    return inputs


def self_verdict(text: str) -> tuple[bool, list[str]]:
    """MCP ツール lint_sysml_text と同じ経路での判定。"""
    from sysml_v2_checker_advanced.parser import lint_sysml, parse_sysml

    ast = parse_sysml(text)
    if ast.get("type") == "error":
        return True, ["parse error: " + (ast.get("message") or "")[:160]]
    issues = lint_sysml(ast)
    errors = [f"L{i.line} {i.message}" for i in issues if i.severity == "error"]
    warnings = [f"(warning) L{i.line} {i.message}" for i in issues if i.severity == "warning"]
    return bool(errors), errors + (warnings if _SHOW_WARNINGS else [])


_SHOW_WARNINGS = False


def main() -> int:
    global _SHOW_WARNINGS
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("paths", nargs="*", help=".sysml ファイル、またはそれを含むディレクトリ")
    parser.add_argument("--cases", help="`--- 名前` 区切りで複数ケースを並べたテキストファイル")
    parser.add_argument("--warnings", action="store_true", help="自作チェッカーの warning も表示する")
    args = parser.parse_args()
    _SHOW_WARNINGS = args.warnings

    inputs = _collect_inputs(args)
    if not inputs:
        parser.error("判定する入力がない")

    driver = _load_reference_driver()
    mismatches = 0
    with tempfile.TemporaryDirectory() as tmp, driver.ReferenceBatch() as batch:
        ok, detail = batch.run_canary()
        print(f"[canary before] {detail}")
        if not ok:
            return 2
        for index, (name, text) in enumerate(inputs):
            path = Path(tmp) / f"case{index:03d}.sysml"
            path.write_text(text, encoding="utf-8")
            result = batch.check_file(str(path))
            if result["crashed"]:
                print(f"[CRASH] {name}: {(result.get('raw_stderr') or '')[-200:]}")
                mismatches += 1
                continue
            ref_errors = [
                f"L{d.get('line')} {d.get('message')}"
                for d in result["diagnostics"]
                if (d.get("severity") or "").lower() == "error"
            ]
            self_has, self_lines = self_verdict(text)
            same = self_has == bool(ref_errors)
            mismatches += not same
            print(f"[{'OK' if same else 'NG'}] {name}")
            for line in ref_errors or ["0 errors"]:
                print(f"    ref : {line}")
            for line in self_lines or ["0 errors"]:
                print(f"    self: {line}")
        ok, detail = batch.run_canary()
        print(f"[canary after] {detail}")
        if not ok:
            return 2
    print(f"\n一致しない: {mismatches} 件 / {len(inputs)} 件")
    return 1 if mismatches else 0


if __name__ == "__main__":
    raise SystemExit(main())
