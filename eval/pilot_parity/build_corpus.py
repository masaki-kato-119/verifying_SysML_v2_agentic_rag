"""Pilot との差分評価に使うコーパスを作る（標準ライブラリだけで動く）。

自作チェッカーは 1 ファイル単位でしか検証しないので、複数ファイルのモデルは
1 つのテキストに連結して 1 件（unit）にする。ルートパッケージが複数あっても
Pilot も自作チェッカーも 1 テキストとして扱える。

入力（C:\\test\\sysml_models 配下。存在するものだけ使う）:
  llm      eval/runs/*, eval/runs_sonnet/*  LLM（Opus / Sonnet）が 1 回で書いた AGV モデル
  verified verified/<テーマ>/                Pilot で 0 エラー・0 警告を確かめた最小例
  probe    verified/_probe/**/*.sysml        誤りをわざと入れた負例（1 ファイル 1 件）
  mutant   verified の各 unit に、LLM がやりがちな誤りを 1 か所だけ入れたもの

出力: corpus/units/<id>.sysml と corpus/manifest.json
（id, source, origin, operator, line）。ラベル（正解）は label_pilot.py が付ける。
"""

from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterator

HERE = Path(__file__).resolve().parent
DEFAULT_MODELS = Path(r"C:\test\sysml_models")


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8-sig").replace("\r\n", "\n")


def concat(files: list[Path], root: Path) -> str:
    parts = []
    for f in sorted(files):
        parts.append(f"// ---- {f.relative_to(root).as_posix()}\n{read(f).rstrip()}\n")
    return "\n".join(parts)


# --- 変異の種類（LLM の生成で実際に見た誤り。sysmlv2-bp-antipatterns より） ----------------

@dataclass(frozen=True)
class Operator:
    name: str
    pattern: re.Pattern[str]
    rewrite: Callable[[re.Match[str]], str]
    delete_line: bool = False


def _sub(template: str) -> Callable[[re.Match[str]], str]:
    return lambda m: m.expand(template)


OPERATORS = [
    # 可視性の無い import（Sonnet A2/A3 で数百件のエラーの根本原因）
    Operator("drop_import_visibility", re.compile(r"\b(?:private|public) (import\b)"), _sub(r"\1")),
    # 型を持つ標準ライブラリの import 漏れ（sysml-v2-lsp の 816 件の約 95%）
    Operator("drop_library_import", re.compile(r"^\s*private import (?:ScalarValues|ISQ|SI)::\*;\s*$"),
             _sub(""), delete_line=True),
    # 入れ子のフィーチャを :: でたどる（Must be an accessible feature）
    Operator("dot_to_colons", re.compile(r"^(\s*(?:connect|flow|bind|allocate|interface|first|then|satisfy)\b.*?\b[a-z]\w*)\.([a-z]\w*)"),
             _sub(r"\1::\2")),
    # perform の action 抜け（Sonnet C2 の 20 件）
    Operator("perform_drop_action", re.compile(r"\bperform action (\w+\s*:)"), _sub(r"perform \1")),
    # 存在しない型名（推測した型名）
    Operator("unknown_type", re.compile(r"(\b(?:part|attribute|item|port|action|state)\s+\w+\s*:\s*~?)([A-Z]\w*)"),
             _sub(r"\1\2Typo")),
    # 継承した属性の :>> 抜け
    Operator("drop_redefinition", re.compile(r"\battribute :>> (\w+)"), _sub(r"attribute \1")),
    # item def で型付けした値を attribute にする
    Operator("item_as_attribute", re.compile(r"\bref item (\w+\s*:)"), _sub(r"attribute \1")),
    # def 側の default を = にする（下位の上書きで Cannot override a binding feature value）
    Operator("default_to_binding", re.compile(r"(\battribute \w+[^;=]*?)\bdefault\b(?!\s*:=)"), _sub(r"\1=")),
    # 予約語を名前にする
    Operator("reserved_word_name", re.compile(r"(\b(?:part|attribute|port)\s+)([a-z]\w*)(\s*:)"), _sub(r"\1frame\3")),
    # SI に無い単位
    Operator("unknown_unit", re.compile(r"\[(kg|m/s|W|V|s|N)\]"), lambda m: {"kg": "[kgs]", "m/s": "[mps]", "W": "[kWh]",
                                                                         "V": "[kV]", "s": "[ms]", "N": "[kN]"}[m.group(1)]),
    # 論理演算子 and → &&
    Operator("and_to_ampersand", re.compile(r"(\{[^}]*?) and "), _sub(r"\1 && ")),
    # 制約の比較 == を = にする（Pilot は通す。誤検出の測定用）
    Operator("equality_to_binding", re.compile(r"(\b(?:constraint|require|assert)\b[^{]*\{[^}]*?)==") , _sub(r"\1=")),
]


def mutants(text: str, per_operator: int) -> Iterator[tuple[str, str, int]]:
    """(operator, mutated text, 1-based line) を、各変異について最大 per_operator 件。"""
    lines = text.split("\n")
    for op in OPERATORS:
        made = 0
        for i, line in enumerate(lines):
            if made >= per_operator:
                break
            m = op.pattern.search(line)
            if not m:
                continue
            new_lines = list(lines)
            if op.delete_line:
                new_lines[i] = ""  # 行番号を保つため空行にする
            else:
                new_lines[i] = line[:m.start()] + op.rewrite(m) + line[m.end():]
            if new_lines[i] == line:
                continue
            made += 1
            yield op.name, "\n".join(new_lines), i + 1


def build(models: Path, out: Path, per_operator: int) -> list[dict]:
    units_dir = out / "units"
    units_dir.mkdir(parents=True, exist_ok=True)
    for old in units_dir.glob("*.sysml"):
        old.unlink()
    manifest: list[dict] = []

    def add(uid: str, text: str, source: str, origin: str, operator: str | None = None, line: int | None = None) -> None:
        (units_dir / f"{uid}.sysml").write_text(text, encoding="utf-8")
        manifest.append({"id": uid, "source": source, "origin": origin, "operator": operator, "line": line})

    # LLM が書いたモデル（フォルダごとに 1 件）
    for group in ("runs", "runs_sonnet"):
        base = models / "eval" / group
        for run in sorted(p for p in base.glob("*") if p.is_dir()) if base.is_dir() else []:
            files = list(run.rglob("*.sysml"))
            if files:
                add(f"llm-{'opus' if group == 'runs' else 'sonnet'}-{run.name}", concat(files, run), "llm",
                    f"{group}/{run.name}")

    # 検証済みの最小例（テーマごとに 1 件）と、その変異体
    verified = models / "verified"
    for theme in sorted(p for p in verified.glob("*") if p.is_dir() and not p.name.startswith("_")):
        files = list(theme.rglob("*.sysml"))
        if not files:
            continue
        text = concat(files, theme)
        uid = f"verified-{theme.name}"
        add(uid, text, "verified", f"verified/{theme.name}")
        for n, (op, mutated, line) in enumerate(mutants(text, per_operator)):
            add(f"mutant-{theme.name}-{op}-{n:03d}", mutated, "mutant", f"verified/{theme.name}", op, line)

    # 負例（1 ファイル 1 件）
    probe = verified / "_probe"
    for f in sorted(probe.rglob("*.sysml")) if probe.is_dir() else []:
        rel = f.relative_to(probe).as_posix()
        add("probe-" + re.sub(r"[^\w.-]+", "_", rel[:-len(".sysml")]), read(f), "probe", f"verified/_probe/{rel}")

    (out / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8")
    return manifest


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--models", type=Path, default=DEFAULT_MODELS)
    ap.add_argument("--out", type=Path, default=HERE / "corpus")
    ap.add_argument("--per-operator", type=int, default=4)
    args = ap.parse_args()
    manifest = build(args.models, args.out, args.per_operator)
    counts: dict[str, int] = {}
    for m in manifest:
        key = m["source"] if m["source"] != "mutant" else f"mutant:{m['operator']}"
        counts[key] = counts.get(key, 0) + 1
    print(json.dumps({"units": len(manifest), "by_source": counts}, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
