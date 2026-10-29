"""KerML の意味ライブラリで、端（`end feature`）を持つ型（`Links::BinaryLink` など）を集める。

SysML の connection・interface・flow の定義がこれらを特化すると、端が usage にならない
（Pilot 0.63.0 の `A connection definition end must be a usage.`・`A flow definition end must be a usage.`。
sysml_v2_checker_advanced/validation_rules.py）。継承した端も数える（`Transfers::FlowTransfer` は Transfer から
BinaryLink の端を継承する）。

    .venv/Scripts/python.exe scripts/build_kerml_end_types.py

出力: sysml_v2_checker_advanced/kerml_end_types.json（端を持つ型の修飾名の並び）。ライブラリの版を上げたら作り直す。
"""

from __future__ import annotations

import json
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
KERNEL = REPO_ROOT / "eval" / "sysml_reference" / "sysml.library" / "Kernel Libraries" / "Kernel Semantic Library"
OUT = REPO_ROOT / "sysml_v2_checker_advanced" / "kerml_end_types.json"

_PACKAGE = re.compile(r"^\s*(?:standard\s+)?library\s+package\s+(\w+)|^\s*package\s+(\w+)")
_TYPE = re.compile(r"^\s*(?:abstract\s+)?(?:assoc\s+struct|assoc|interaction|struct|class|behavior|function|"
                   r"predicate|datatype|classifier|type)\s+(?:all\s+)?(\w+)(?:\s+specializes\s+([\w\s,:]+?))?"
                   r"(?:\s+(?:disjoint|intersects|unions|differences)\b.*)?\s*[{;]")
_END = re.compile(r"^\s*end\b")


def main() -> None:
    supertypes: dict[str, list[str]] = {}
    own_ends: set[str] = set()
    for source in sorted(KERNEL.glob("*.kerml")):
        package = None
        stack: list[tuple[str, int]] = []  # (修飾名, 本体の深さ)
        depth = 0
        text = re.sub(r"/\*.*?\*/", lambda m: "\n" * m.group(0).count("\n"), source.read_text(encoding="utf-8"),
                      flags=re.S)
        for line in text.splitlines():
            line = line.split("//")[0]
            match = _PACKAGE.match(line)
            if match and package is None:
                package = match.group(1) or match.group(2)
            match = _TYPE.match(line)
            if match and package:
                name = f"{package}::{match.group(1)}"
                bases = [b.strip() for b in (match.group(2) or "").split(",") if b.strip()]
                supertypes[name] = [b if "::" in b else f"{package}::{b}" for b in bases]
                if "{" in line:
                    stack.append((name, depth + 1))
            elif _END.match(line) and stack and stack[-1][1] == depth:
                own_ends.add(stack[-1][0])
            depth += line.count("{") - line.count("}")
            while stack and depth < stack[-1][1]:
                stack.pop()

    # import した名前（Objects の `BinaryLink`）は、同じパッケージに無ければ短い名前で探す
    by_short: dict[str, list[str]] = {}
    for name in supertypes:
        by_short.setdefault(name.split("::")[-1], []).append(name)
    for name, bases in supertypes.items():
        supertypes[name] = [b if b in supertypes or len(by_short.get(b.split("::")[-1], [])) != 1
                            else by_short[b.split("::")[-1]][0] for b in bases]

    def has_ends(name: str, seen: frozenset = frozenset()) -> bool:
        if name in own_ends:
            return True
        return any(has_ends(b, seen | {name}) for b in supertypes.get(name, []) if b not in seen)

    result = sorted(name for name in supertypes if has_ends(name))
    OUT.write_text(json.dumps(result, indent=1) + "\n", encoding="utf-8")
    print(f"{len(result)} types with ends -> {OUT}")


if __name__ == "__main__":
    main()
