"""標準ライブラリの定義の本体で宣言されている名前（継承で入りうる feature の名前）を集める。

名前解決（sysml_v2_checker_advanced/scope_resolver.py）は、ライブラリの型の中身を持たない。
そこで「ライブラリのどこかの定義・usage の本体で宣言されている名前」を集めておき、

- ``inherited``: ライブラリの型を（明示的に）継承した要素の中で、見つからない名前がこの中に
  あれば「不明」、無ければ「無い」と判定する（`[kg]` の kg は SI の直下にあり、型の本体には
  無いので、ISQ::mass を継承した feature の中でも「無い」と言える）。
- ``implicit``: 部品・動作・要件などが暗黙に特化する型（Kernel Semantic Library と
  Systems Library）の本体の名前。`self`・`start`・`done` のように、何も継承していない要素の
  中でも見えうる。

パッケージの直下の宣言は含めない（それは library_index.json の役目）。

    .venv/Scripts/python.exe scripts/build_library_feature_names.py

出力: sysml_v2_checker_advanced/library_feature_names.json。ライブラリの版を上げたら作り直す。
"""

from __future__ import annotations

import json
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
LIBRARY = REPO_ROOT / "eval" / "sysml_reference" / "sysml.library"
# 部品・動作・要件などが暗黙に特化する型があるところ。分野別ライブラリ（ISQ・TradeStudies など）の
# 型は、明示的に型付け・特化しない限り継承されない
IMPLICIT_BASE_FOLDERS = ("Kernel Libraries/Kernel Semantic Library", "Systems Library")
OUT = REPO_ROOT / "sysml_v2_checker_advanced" / "library_feature_names.json"

# 宣言のキーワード（SysML と KerML）。直後の名前（引用符つきも）を拾う
_KEYWORDS = (
    "attribute|part|item|port|action|state|occurrence|individual|snapshot|timeslice|ref|event|"
    "calc|constraint|requirement|concern|case|analysis|verification|connection|interface|flow|"
    "allocation|message|view|viewpoint|rendering|metadata|subject|objective|actor|stakeholder|"
    "return|end|exhibit|perform|include|use|feature|step|expr|bool|function|predicate|"
    "succession|binding|connector|composite|portion|derived|readonly|var|const|in|out|inout"
)
_DECLARATION = re.compile(rf"\b(?:{_KEYWORDS})\s+(?:<[^>]*>\s*)?('[^']+'|[A-Za-z_]\w*)")
# 名前の無いキーワードの並び（`in item x` の item なども名前として拾わないよう除く）
_NOT_NAMES = set(_KEYWORDS.split("|")) | {"def", "abstract", "variation", "variant", "all", "of", "by"}
_COMMENT = re.compile(r"/\*.*?\*/|//[^\n]*", re.S)
_STRING = re.compile(r'"(?:[^"\\]|\\.)*"')
_PACKAGE_HEAD = re.compile(r"\bpackage\s+(?:<[^>]*>\s*)?(?:'[^']+'|[\w:]+)\s*$")


def _body_declarations(text: str, *, direct_only: bool = False) -> set[str]:
    """パッケージ以外の本体（`{ ... }`）の中で宣言されている名前。

    direct_only=True は、パッケージ直下の定義の直接のメンバーだけ（関数の引数など、
    さらに入れ子の本体の名前は含めない）。
    """
    text = _STRING.sub('""', _COMMENT.sub(" ", text))
    names: set[str] = set()
    stack: list[bool] = []  # True = パッケージの本体
    segment_start = 0
    for i, ch in enumerate(text):
        if ch not in "{}":
            continue
        segment = text[segment_start:i]
        depth = sum(1 for is_package in stack if not is_package)
        if stack and not stack[-1] and (not direct_only or depth == 1):
            for match in _DECLARATION.finditer(segment):
                name = match.group(1).strip("'")
                if name not in _NOT_NAMES:
                    names.add(name)
        if ch == "{":
            stack.append(bool(_PACKAGE_HEAD.search(segment.rstrip())))
        elif stack:
            stack.pop()
        segment_start = i + 1
    return names


def collect(paths: list[Path], *, direct_only: bool = False) -> list[str]:
    names: set[str] = set()
    for path in paths:
        names |= _body_declarations(path.read_text(encoding="utf-8"), direct_only=direct_only)
    return sorted(names)


def _library_files(root: Path) -> list[Path]:
    return sorted(list(root.rglob("*.sysml")) + list(root.rglob("*.kerml")))


def main() -> None:
    payload = {
        "inherited": collect(_library_files(LIBRARY)),
        "implicit": collect([p for folder in IMPLICIT_BASE_FOLDERS for p in _library_files(LIBRARY / folder)],
                            direct_only=True),
    }
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=0) + "\n", encoding="utf-8")
    print(f"inherited {len(payload['inherited'])} / implicit {len(payload['implicit'])} names -> {OUT}")


if __name__ == "__main__":
    main()
