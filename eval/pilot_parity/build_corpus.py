"""Pilot との差分評価に使うコーパスを作る（標準ライブラリだけで動く）。

自作チェッカーは 1 ファイル単位でしか検証しないので、複数ファイルのモデルは
1 つのテキストに連結して 1 件（unit）にする。ルートパッケージが複数あっても
Pilot も自作チェッカーも 1 テキストとして扱える。

入力（C:\\test\\sysml_models 配下。存在するものだけ使う）:
  llm      eval/runs/*, eval/runs_sonnet/*  LLM（Opus / Sonnet）が 1 回で書いた AGV モデル
  verified verified/<テーマ>/                Pilot で 0 エラー・0 警告を確かめた最小例
  probe    verified/_probe/**/*.sysml        誤りをわざと入れた負例（1 ファイル 1 件）
  mutant   verified の各 unit に、LLM がやりがちな誤りを 1 か所だけ入れたもの
  xpect    Pilot ソースの org.omg.sysml.xpect.tests（*.sysml.xt）。期待（XPECT errors /
           warnings）を manifest の expected に入れる。オラクルの確認と、検証ルールの網羅度に使う
  kerml    Pilot ソースの org.omg.kerml.xpect.tests の名前解決のテスト（imports / scoping /
           visibility / linking）を SysML に書き換えたもの（kerml_to_sysml）。ラベルは書き換えた
           テキストに Pilot が付けるので、書き換えが元のテストの意図とずれても比較は正しい

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
DEFAULT_XPECT = Path(r"C:\pilot_tmp\SysML-v2-Pilot-Implementation\org.omg.sysml.xpect.tests\src")
DEFAULT_KERML_XPECT = Path(r"C:\pilot_tmp\SysML-v2-Pilot-Implementation\org.omg.kerml.xpect.tests")
# 名前解決（段階 B）に関わる KerML のテストのフォルダ
KERML_DIRS = ("imports", "scoping", "visibility", "linking")


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8-sig").replace("\r\n", "\n")


def concat(files: list[Path], root: Path) -> str:
    parts = []
    for f in sorted(files):
        parts.append(f"// ---- {f.relative_to(root).as_posix()}\n{read(f).rstrip()}\n")
    return "\n".join(parts)


# --- KerML のテストを SysML に書き換える ---------------------------------------------------

# 定義のキーワード（KerML → SysML）。名前解決のテストは種類の違いを問わないので part def に寄せる
_KERML_DEFS = [(re.compile(r"\b(?:classifier|class|struct|type)\b(?=\s+[\w'<])"), "part def"),
               (re.compile(r"\bdatatype\b(?=\s+[\w'<])"), "attribute def"),
               (re.compile(r"\bmetaclass\b(?=\s+[\w'<])"), "metadata def"),
               (re.compile(r"\bfeature\b(?=\s+[\w'<:~])"), "part")]
# キーワード無しの feature 宣言（`x : A;`、`public y :> z;`）。行頭の名前のあとに型付け・特化が続く
_KERML_BARE_FEATURE = re.compile(
    r"^(\s*(?:(?:public|private|protected)\s+)?)(?=[A-Za-z_]\w*\s*(?::|:>|:>>|\bsubsets\b|\bredefines\b|\[))")
_KERML_NOT_FEATURE = re.compile(r"^\s*(?:(?:public|private|protected)\s+)?(?:import|alias|package|part|attribute|"
                                r"doc|comment|filter|dependency)\b")


def kerml_to_sysml(text: str) -> str:
    """KerML の名前解決テストを、Pilot と自作の両方が読める SysML に書き換える（行数は変えない）。"""
    out = []
    for line in text.split("\n"):
        code, sep, comment = line.partition("//")
        for pattern, repl in _KERML_DEFS:
            code = pattern.sub(repl, code)
        if not _KERML_NOT_FEATURE.match(code):
            code = _KERML_BARE_FEATURE.sub(r"\1part ", code, count=1)
        out.append(code + sep + comment)
    return "\n".join(out)


_SETUP_FILE = re.compile(r'File\s*\{\s*from\s*=\s*"([^"]+)"')


def kerml_unit(test: Path, project: Path) -> str:
    """テスト本体（設定部分は空行）に、設定が読み込む /src の KerML ファイルを後ろへ連結する。"""
    raw = read(test)
    setup = _XPECT_SETUP.search(raw)
    deps: list[Path] = []
    for ref in _SETUP_FILE.findall(setup.group(0) if setup else ""):
        if ref.startswith("/library/"):
            continue  # KerML の Base ライブラリ。SysML の標準ライブラリにもある
        path = project / ref.lstrip("/") if ref.startswith("/") else test.parent / ref
        if path.is_file() and path not in deps:
            deps.append(path)
    body = _XPECT_SETUP.sub(lambda m: "\n" * m.group(0).count("\n"), raw, count=1)
    parts = [kerml_to_sysml(body).rstrip()]
    for dep in deps:
        parts.append(f"// ---- {dep.name}\n{kerml_to_sysml(read(dep)).rstrip()}")
    return "\n".join(parts) + "\n"


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


# --- Pilot 自身の xpect テスト（*.sysml.xt） ----------------------------------------

_XPECT_SETUP = re.compile(r"\A\s*//\*\s*XPECT_SETUP.*?END_SETUP\s*\*/", re.S)
# `// XPECT errors --> "msg" at "snippet"`（1 行）と `//* XPECT errors --- "msg" at "..." ... --- */`（複数行）
_XPECT_BLOCK = re.compile(r"XPECT (errors|warnings)\s*(?:-->|---)(.*?)(?:---\s*\*/|$)", re.S | re.M)
_XPECT_ITEM = re.compile(r'"((?:[^"\\]|\\.)*)"\s+at\s+"((?:[^"\\]|\\.)*)"')


def xpect_expectations(text: str) -> list[dict]:
    """XPECT errors / warnings に書かれた期待（kind, message, at）。"""
    found = []
    for m in _XPECT_BLOCK.finditer(text):
        for item in _XPECT_ITEM.finditer(m.group(2)):
            found.append({"kind": m.group(1)[:-1], "message": item.group(1), "at": item.group(2)})
    return found


def build(models: Path, out: Path, per_operator: int, xpect: Path | None = None,
          kerml: Path | None = None) -> list[dict]:
    units_dir = out / "units"
    units_dir.mkdir(parents=True, exist_ok=True)
    for old in units_dir.glob("*.sysml"):
        old.unlink()
    manifest: list[dict] = []

    def add(uid: str, text: str, source: str, origin: str, operator: str | None = None, line: int | None = None,
            **extra: object) -> None:
        (units_dir / f"{uid}.sysml").write_text(text, encoding="utf-8")
        manifest.append({"id": uid, "source": source, "origin": origin, "operator": operator, "line": line, **extra})

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

    # Pilot の xpect テスト（SysML のものだけ）。設定部分を空行に置き換え、行番号を保つ。
    # XPECT の注釈は SysML のコメント（// と //* */）なので、残したまま検証できる。
    for f in sorted(xpect.rglob("*.sysml.xt")) if xpect and xpect.is_dir() else []:
        raw = read(f)
        body = _XPECT_SETUP.sub(lambda m: "\n" * m.group(0).count("\n"), raw, count=1)
        rel = f.relative_to(xpect).as_posix()
        add("xpect-" + re.sub(r"[^\w.-]+", "_", rel[:-len(".sysml.xt")]), body, "xpect", rel,
            expected=xpect_expectations(raw))

    # KerML の名前解決のテスト（SysML に書き換え）
    kerml_tests = kerml / "src" / "org" / "omg" / "kerml" / "xpect" / "tests" if kerml else None
    for folder in KERML_DIRS if kerml_tests and kerml_tests.is_dir() else ():
        for f in sorted((kerml_tests / folder).rglob("*.kerml.xt")):
            rel = f.relative_to(kerml_tests).as_posix()
            add("kerml-" + re.sub(r"[^\w.-]+", "_", rel[:-len(".kerml.xt")]), kerml_unit(f, kerml), "kerml", rel)

    (out / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8")
    return manifest


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--models", type=Path, default=DEFAULT_MODELS)
    ap.add_argument("--out", type=Path, default=HERE / "corpus")
    ap.add_argument("--per-operator", type=int, default=4)
    ap.add_argument("--xpect", type=Path, default=DEFAULT_XPECT,
                    help="Pilot ソースの org.omg.sysml.xpect.tests/src（無ければ xpect は入れない）")
    ap.add_argument("--kerml-xpect", type=Path, default=DEFAULT_KERML_XPECT,
                    help="Pilot ソースの org.omg.kerml.xpect.tests（無ければ kerml は入れない）")
    args = ap.parse_args()
    manifest = build(args.models, args.out, args.per_operator, args.xpect, args.kerml_xpect)
    counts: dict[str, int] = {}
    for m in manifest:
        key = m["source"] if m["source"] != "mutant" else f"mutant:{m['operator']}"
        counts[key] = counts.get(key, 0) + 1
    print(json.dumps({"units": len(manifest), "by_source": counts}, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
