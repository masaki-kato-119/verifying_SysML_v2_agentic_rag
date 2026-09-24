"""標準ライブラリの「パッケージ → 外から見える名前」の索引を生成する。

リンターは `ISQ::MassValue` のような標準ライブラリの修飾名や、
`private import ScalarValues::*;` で持ち込まれる名前の実在を、この索引で確かめる
（sysml_v2_checker_advanced/library_index.py）。実行のたびにライブラリを
パースしなくて済むよう、生成結果を sysml_v2_checker_advanced/library_index.json として
同梱する。**ライブラリの版を上げたら、このスクリプトで作り直すこと。**

    .venv/Scripts/python.exe scripts/build_library_index.py
    .venv/Scripts/python.exe scripts/build_library_index.py --check   # AST との突き合わせだけ行う

## なぜ自前の軽量スキャナーなのか

ライブラリ94ファイルのうち36ファイルは KerML で書かれており（ScalarValues、Base、
Occurrences など）、SysML 用のこのパーサーでは読めない。索引に要るのはパッケージ直下の
宣言の名前と、`import` / `alias` だけなので、宣言の先頭（キーワード列 → 短い名前 →
名前）だけを読むスキャナーで両方の言語を扱う。定義の本体（`{ ... }`）の中は読まない。

正しさは2通りで担保する。

- `.sysml` の58ファイルでは、パーサーの AST から求めた「パッケージ直下の名前」と
  スキャナーの結果を突き合わせる。`.kerml` の36ファイルは AST が無いので、行頭の
  宣言を拾う素朴な抽出と突き合わせる（check_kerml_lines）。どちらも --check で
  実行され、差があれば終了コード 1。
- 読み切れない形（未知の文、解決できない public import、`::**`）に出会ったパッケージは
  `complete: false` にする。リンターはそのパッケージ配下の名前を「検証不能」として
  通す。**索引の漏れで誤検出を出すより、見逃す側に倒す**（過去に USCustomaryUnits の
  漏れで7ファイルに誤検出を出した。constants.py の STANDARD_LIBRARY_PACKAGES 参照）。

## 索引の形

    {
      "library_version": "0.62.0",
      "packages": {
        "ISQ": {"complete": true, "members": {"MassValue": "attribute def", "mass": "attribute", ...}},
        "SI":  {"complete": true, "members": {"kg": "attribute", "kilogram": "attribute", ...}},
        ...
      }
    }

`members` は外から `Pkg::名前` で見える名前（public な自前の宣言、短い名前、
public import で再公開された名前、入れ子のパッケージ）。値は宣言のキーワード列
（`attribute def`、`datatype`、`alias` など）で、種別の判定に使う。
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

LIBRARY_DIR = REPO_ROOT / "eval" / "sysml_reference" / "sysml.library"
OUTPUT_PATH = REPO_ROOT / "sysml_v2_checker_advanced" / "library_index.json"
LIBRARY_VERSION = "0.62.0"

# 宣言の名前より前に来うる予約語。名前の後に来る `specializes` や `:>` などは
# ここに要らない（名前を読んだ時点で止まるため）。言語ごとに分けてある: 片方の
# 言語だけの予約語は、もう片方では普通の名前として使える
# （例: ISQChemistryMolecular.sysml の `alias multiplicity for degeneracy;`。
# `multiplicity` は KerML の予約語だが SysML では名前）。
_COMMON_KEYWORDS = {
    "abstract", "variation", "variant", "individual", "readonly", "derived", "end",
    "in", "out", "inout", "ref", "nonunique", "ordered", "snapshot", "timeslice",
    "standard", "library", "package", "succession", "binding", "connector", "first", "then",
}
_SYSML_KEYWORDS = _COMMON_KEYWORDS | {
    "constant", "def", "part", "attribute", "item", "port", "action", "state", "calc",
    "constraint", "requirement", "concern", "case", "analysis", "verification", "use",
    "view", "viewpoint", "rendering", "metadata", "occurrence", "connection", "interface",
    "allocation", "flow", "message", "enum", "exhibit", "perform", "include",
    "satisfy", "assert", "assume", "require", "subject", "actor", "stakeholder",
    "objective", "event", "entry", "exit", "do", "accept", "send", "assign",
    "bind", "connect", "allocate", "transition", "frame", "verify", "expose", "render",
}
_KERML_KEYWORDS = _COMMON_KEYWORDS | {
    "const", "var", "composite", "portion", "member", "datatype", "class", "struct",
    "assoc", "classifier", "type", "feature", "step", "expr", "bool", "function",
    "predicate", "behavior", "interaction", "metaclass", "namespace", "multiplicity",
    "flow", "all",
}
KEYWORDS_BY_SUFFIX = {".sysml": _SYSML_KEYWORDS, ".kerml": _KERML_KEYWORDS}
# 走査中のファイルの予約語（scan_file が切り替える）
DECLARATION_KEYWORDS: set[str] = _SYSML_KEYWORDS

# パッケージ直下に現れても名前を持ち込まない文
NON_MEMBER_STATEMENTS = {
    "doc", "comment", "locale", "rep", "language", "filter", "dependency",
    # KerML の関係の宣言（`subclassifier SelfLink specializes SelfSameLifeLink;` など）。
    # 名前を付けられる形もあるが、ライブラリでは使われていない
    "subclassifier", "specialization", "subtype", "subset", "redefinition", "conjugation",
    "conjugate", "disjoining", "disjoint", "inverting", "featuring", "typing",
}

_TOKEN_RE = re.compile(
    r"""
    (?P<ws>\s+)
  | (?P<line_comment>//[^\n]*)
  | (?P<block_comment>/\*.*?\*/)
  | (?P<string>"(?:[^"\\]|\\.)*")
  | (?P<quoted>'(?:[^'\\]|\\.)*')
  | (?P<ident>[A-Za-z_][A-Za-z0-9_]*)
  | (?P<number>\d[\d.eE+-]*)
  | (?P<punct>::>|:>>|:>|::|\*\*|=>|->|\.\.|==|!=|<=|>=|:=|[{}();<>:,.\[\]=#@*~+\-/%^&|!?$])
    """,
    re.VERBOSE | re.DOTALL,
)


_COMMENT_MARK = "/**/"
# 本文のブロックコメントで終わる文
_COMMENT_BODY_STATEMENTS = {"doc", "comment", "rep"}


def tokenize(text: str) -> list[str]:
    tokens: list[str] = []
    pos = 0
    while pos < len(text):
        m = _TOKEN_RE.match(text, pos)
        if not m:
            pos += 1  # 解釈できない1文字は読み飛ばす（名前の抽出には関わらない）
            continue
        pos = m.end()
        kind = m.lastgroup
        if kind in ("ws", "line_comment", "string"):
            continue
        if kind == "block_comment":
            # `doc /* ... */` や `comment X /* ... */` は `;` で終わらない。本文の
            # ブロックコメントで文が終わることを _read_statement に伝えるため、
            # 印を残す（これが無いと、直後の宣言を doc 文の一部として読み飛ばす。
            # Base.kerml の `doc /* ... */ abstract classifier Anything {` で実際に
            # Anything が索引から漏れ、17ファイルに誤検出を出した）
            tokens.append(_COMMENT_MARK)
            continue
        tok = m.group()
        if kind == "quoted":
            tok = tok[1:-1]
            tokens.append("'" + tok)  # 引用符付きの名前であることを印で残す（予約語と区別する）
            continue
        tokens.append(tok)
    return tokens


def _name_of(token: str) -> str | None:
    if token.startswith("'"):
        return token[1:]
    if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", token) and token not in DECLARATION_KEYWORDS:
        return token
    return None


@dataclass
class PackageScan:
    qname: str
    owned: dict[str, str] = field(default_factory=dict)  # public な自前の宣言 名前 → 種別
    imports: list[tuple[str, str]] = field(default_factory=list)  # (path, "*"|"**"|"")
    problems: list[str] = field(default_factory=list)


class LibraryScanner:
    def __init__(self) -> None:
        self.packages: dict[str, PackageScan] = {}

    def scan_file(self, text: str, source: str, suffix: str = ".sysml") -> None:
        global DECLARATION_KEYWORDS
        DECLARATION_KEYWORDS = KEYWORDS_BY_SUFFIX[suffix]
        self._tokens = tokenize(text)
        self._pos = 0
        self._source = source
        self._scan_body(None)

    # --- 低水準 ---------------------------------------------------------------
    def _peek(self) -> str | None:
        return self._tokens[self._pos] if self._pos < len(self._tokens) else None

    def _skip_braced_body(self) -> None:
        """直前に `{` を読んだ状態から、対応する `}` の直後まで読み飛ばす。"""
        depth = 1
        while self._pos < len(self._tokens) and depth:
            tok = self._tokens[self._pos]
            if tok == "{":
                depth += 1
            elif tok == "}":
                depth -= 1
            self._pos += 1

    def _read_statement(self) -> tuple[list[str], str | None]:
        """`;` か `{` か `}`（本体の終わり）までの文を読む。終端記号も返す。"""
        stmt: list[str] = []
        while self._pos < len(self._tokens):
            tok = self._tokens[self._pos]
            if tok == _COMMENT_MARK:
                self._pos += 1
                head = [t for t in stmt if t not in ("public", "private", "protected")][:1]
                if head and head[0] in _COMMENT_BODY_STATEMENTS:
                    return stmt, ";"
                continue
            if tok in (";", "{", "}"):
                if tok != "}":
                    self._pos += 1
                return stmt, tok
            stmt.append(tok)
            self._pos += 1
        return stmt, None

    # --- 名前空間の本体 ------------------------------------------------------------
    def _scan_body(self, package: PackageScan | None) -> None:
        while self._pos < len(self._tokens):
            if self._peek() == "}":
                self._pos += 1
                return
            stmt, term = self._read_statement()
            if not stmt:
                if term == "{":
                    self._skip_braced_body()
                continue
            self._handle_statement(package, stmt, term)

    def _handle_statement(self, package: PackageScan | None, stmt: list[str], term: str | None) -> None:
        visibility = "public"
        toks = list(stmt)
        if toks and toks[0] in ("public", "private", "protected"):
            visibility = toks.pop(0)
        # 前置のメタデータ（`#Name`）は宣言の一部ではない
        while len(toks) >= 2 and toks[0] == "#":
            toks = toks[2:]

        head = toks[0] if toks else ""
        if head == "import":
            self._handle_import(package, visibility, toks[1:])
            if term == "{":
                self._skip_braced_body()
            return
        if head == "alias":
            names = self._declared_names(toks[1:])
            if package is not None and visibility == "public":
                for n in names:
                    package.owned[n] = "alias"
            if term == "{":
                self._skip_braced_body()
            return
        if head in NON_MEMBER_STATEMENTS or head == "@" or not head:
            if term == "{":
                self._skip_braced_body()
            return

        keywords = []
        i = 0
        while i < len(toks) and toks[i] in DECLARATION_KEYWORDS:
            keywords.append(toks[i])
            i += 1
        names = self._declared_names(toks[i:])
        kind = " ".join(k for k in keywords if k not in ("standard", "library")) or "feature"

        if "package" in keywords and term == "{":
            if not names:
                if package is not None:
                    package.problems.append(f"名前の無いパッケージ: {' '.join(stmt)[:60]}")
                self._skip_braced_body()
                return
            qname = names[-1] if package is None else f"{package.qname}::{names[-1]}"
            if package is not None and visibility == "public":
                for n in names:
                    package.owned[n] = "package"
            inner = self.packages.setdefault(qname, PackageScan(qname))
            self._scan_body(inner)
            return

        if package is None:
            # パッケージの外の宣言。ライブラリにはこの形は無い（1ファイル1パッケージ）
            if term == "{":
                self._skip_braced_body()
            return

        if not keywords and not names:
            package.problems.append(f"{self._source}: 読めない文: {' '.join(stmt)[:80]}")
        elif visibility == "public":
            for n in names:
                package.owned[n] = kind
        if term == "{":
            self._skip_braced_body()

    @staticmethod
    def _declared_names(toks: list[str]) -> list[str]:
        """キーワード列の直後にある `<短い名前>? 名前?` を読む。"""
        names: list[str] = []
        i = 0
        if len(toks) >= 3 and toks[0] == "<":
            short = _name_of(toks[1])
            if short and toks[2] == ">":
                names.append(short)
                i += 3
        if i < len(toks):
            name = _name_of(toks[i])
            # `x : T` の `x` は名前。`: T`（名前なし）なら何も足さない
            if name is not None:
                names.append(name)
        return names

    def _handle_import(self, package: PackageScan | None, visibility: str, toks: list[str]) -> None:
        if package is None or visibility != "public":
            return  # private import は外から見える名前を増やさない
        if toks and toks[0] == "all":
            toks = toks[1:]
        segments: list[str] = []
        wildcard = ""
        i = 0
        while i < len(toks):
            tok = toks[i]
            if tok == "::":
                i += 1
                continue
            if tok in ("*", "**"):
                wildcard = tok
                break
            name = _name_of(tok)
            if name is None and tok in DECLARATION_KEYWORDS:
                name = tok  # 予約語と同じ綴りのメンバー名（例: `time`）はここでは名前として扱う
            if name is None:
                break  # `[` などのフィルター
            segments.append(name)
            i += 1
        if segments and i + 1 < len(toks) and toks[i] == "*" and toks[i + 1] == "*":
            wildcard = "**"
        if not segments:
            package.problems.append(f"読めない import: {' '.join(toks)[:60]}")
            return
        package.imports.append(("::".join(segments), wildcard))


def resolve_index(packages: dict[str, PackageScan]) -> dict[str, dict]:
    exported: dict[str, dict[str, str]] = {}
    complete: dict[str, bool] = {}
    in_progress: set[str] = set()

    def lookup_package(path: str, context: str) -> str | None:
        # 入れ子の相対名 → 大域名の順に探す
        parts = context.split("::")
        for depth in range(len(parts), 0, -1):
            candidate = "::".join(parts[:depth]) + "::" + path
            if candidate in packages:
                return candidate
        return path if path in packages else None

    def resolve(qname: str) -> None:
        if qname in exported or qname in in_progress:
            return
        in_progress.add(qname)
        scan = packages[qname]
        members = dict(scan.owned)
        ok = not scan.problems
        for path, wildcard in scan.imports:
            if wildcard == "**":
                ok = False  # 再帰 import は定義のメンバーまで持ち込む。列挙しない
                continue
            if wildcard == "*":
                target = lookup_package(path, qname)
                if target is None:
                    ok = False  # 定義のメンバーの import（enum 値など）。列挙しない
                    continue
                resolve(target)
                if target in in_progress and target not in exported:
                    ok = False  # 循環。安全側に倒す
                    continue
                members.update({k: v for k, v in exported[target].items() if k not in members})
                ok = ok and complete[target]
                continue
            owner, _, name = path.rpartition("::")
            target = lookup_package(owner, qname) if owner else None
            if target is None:
                ok = False
                continue
            resolve(target)
            kind = exported.get(target, {}).get(name)
            if kind is None:
                ok = False if not complete.get(target, False) else ok
                if complete.get(target, False):
                    scan.problems.append(f"存在しない名前の import: {path}")
                    ok = False
                continue
            members.setdefault(name, kind)
        exported[qname] = members
        complete[qname] = ok
        in_progress.discard(qname)

    for qname in packages:
        resolve(qname)
    return {q: {"complete": complete[q], "members": dict(sorted(exported[q].items()))} for q in sorted(packages)}


def library_files() -> list[Path]:
    return sorted(p for p in LIBRARY_DIR.rglob("*") if p.suffix in (".sysml", ".kerml"))


def scan_library() -> dict[str, PackageScan]:
    scanner = LibraryScanner()
    for path in library_files():
        scanner.scan_file(path.read_text(encoding="utf-8"), path.name, path.suffix)
    return scanner.packages


# --- AST との突き合わせ ----------------------------------------------------------------
_AST_SKIP_TYPES = {"import", "documentation", "comment", "metadata_annotation", "filter"}


def _unquote(name: str) -> str:
    return name[1:-1] if len(name) >= 2 and name[0] == name[-1] == "'" else name


def _ast_package_members(node: dict, prefix: str, out: dict[str, set[str]]) -> None:
    """AST から、各パッケージが直接持つ public な名前（短い名前を含む）を集める。"""
    qname = node.get("name") if not prefix else f"{prefix}::{node.get('name')}"
    names = out.setdefault(qname, set())

    def visit(child: dict) -> None:
        ctype = child.get("type")
        if ctype in _AST_SKIP_TYPES:
            return
        if ctype == "package":
            if child.get("visibility") in (None, "public"):
                names.add(_unquote(child.get("name")))
            _ast_package_members(child, qname, out)
            return
        if child.get("name") or child.get("shortName"):
            if child.get("visibility") in (None, "public"):
                for key in ("name", "shortName"):
                    if child.get(key):
                        names.add(_unquote(child[key]))
            return
        for value in child.values():
            for grand in value if isinstance(value, list) else [value]:
                if isinstance(grand, dict) and grand.get("type"):
                    visit(grand)

    for key, value in node.items():
        if key == "source_range":
            continue
        for child in value if isinstance(value, list) else [value]:
            if isinstance(child, dict) and child.get("type"):
                visit(child)


def check_against_ast(packages: dict[str, PackageScan]) -> int:
    from sysml_v2_checker_advanced.parser import parse_sysml

    differences = 0
    for path in library_files():
        if path.suffix != ".sysml":
            continue
        ast = parse_sysml(path.read_text(encoding="utf-8"))
        if ast.get("type") == "error":
            print(f"[skip] {path.name}: パースできない")
            continue
        roots = [ast] if ast.get("type") == "package" else [c for c in ast.get("children", []) if c.get("type") == "package"]
        ast_members: dict[str, set[str]] = {}
        for root in roots:
            _ast_package_members(root, "", ast_members)
        for qname, names in ast_members.items():
            scanned = set(packages.get(qname, PackageScan(qname)).owned)
            missing, extra = names - scanned, scanned - names
            if missing or extra:
                differences += 1
                print(f"[diff] {path.name} {qname}: AST にだけある {sorted(missing)[:8]} / スキャナーにだけある {sorted(extra)[:8]}")
    return differences


# KerML ファイル用の、スキャナーとは独立した素朴な抽出。パッケージ直下（字下げ1段）の
# 行頭にある宣言だけを拾う。行をまたぐ宣言や入れ子のパッケージは拾えないので、
# 「素朴な抽出が拾ったのにスキャナーに無い名前」だけを差として報告する。
_KERML_LINE_RE = re.compile(
    r"^(?:\t| {4})(?!\s)(?:public\s+)?"
    r"(?:(?:abstract|const|var|composite|portion|member|readonly|derived|all)\s+)*"
    r"(?:datatype|class|struct|assoc|classifier|type|feature|step|expr|bool|function|"
    r"predicate|behavior|interaction|metaclass|connector|multiplicity)\s+"
    r"(?:(?:all|struct)\s+)?('[^']+'|[A-Za-z_][A-Za-z0-9_]*)"
)


def check_kerml_lines(packages: dict[str, PackageScan]) -> int:
    differences = 0
    for path in library_files():
        if path.suffix != ".kerml":
            continue
        text = path.read_text(encoding="utf-8")
        top = re.search(r"package\s+('[^']+'|[A-Za-z_][A-Za-z0-9_]*)", text)
        if top is None or re.search(r"^\s+(?:public\s+|private\s+)?package\s", text, re.M):
            continue  # 入れ子のパッケージを持つファイル（KerML.kerml）は字下げが揃わない
        qname = top.group(1).strip("'")
        scanned = set(packages.get(qname, PackageScan(qname)).owned)
        found = {m.group(1).strip("'") for line in text.splitlines() if (m := _KERML_LINE_RE.match(line))}
        missing = found - scanned
        if missing:
            differences += 1
            print(f"[diff] {path.name} {qname}: 行の抽出にだけある {sorted(missing)[:8]}")
    return differences


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--check", action="store_true", help="AST との突き合わせだけ行い、索引は書かない")
    args = parser.parse_args()

    if not LIBRARY_DIR.is_dir():
        print(f"標準ライブラリが見つからない: {LIBRARY_DIR}（eval/sysml_reference/reference_driver.py の手順で取得する）")
        return 2
    packages = scan_library()
    differences = check_against_ast(packages) + check_kerml_lines(packages)
    index = resolve_index(packages)
    incomplete = [q for q, v in index.items() if not v["complete"]]
    problems = [(q, p) for q, s in packages.items() for p in s.problems]
    print(f"パッケージ {len(index)} 件（complete でないもの {len(incomplete)} 件）、突き合わせの差 {differences} 件")
    for q in incomplete:
        print(f"  incomplete: {q}")
    for q, p in problems:
        print(f"  problem: {q}: {p}")
    if args.check:
        return 1 if differences else 0
    payload = {"library_version": LIBRARY_VERSION, "packages": index}
    OUTPUT_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"書き出した: {OUTPUT_PATH.relative_to(REPO_ROOT)}")
    return 1 if differences else 0


if __name__ == "__main__":
    raise SystemExit(main())
