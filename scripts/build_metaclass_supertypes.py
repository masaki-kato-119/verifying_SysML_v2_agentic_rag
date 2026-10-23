"""SysML・KerML のメタクラスの特化（`metadata def PartUsage specializes ItemUsage, ...`）を集める。

メタデータの annotatedElement の制約（`:> annotatedElement : SysML::PartUsage;`）を確かめるのに使う
（sysml_v2_checker_advanced/validation_rules.py の `Cannot annotate ...`）。

    .venv/Scripts/python.exe scripts/build_metaclass_supertypes.py

出力: sysml_v2_checker_advanced/metaclass_supertypes.json（メタクラス → 直接の特化の先）。ライブラリの版を
上げたら作り直す。
"""

from __future__ import annotations

import json
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
LIBRARY = REPO_ROOT / "eval" / "sysml_reference" / "sysml.library"
SOURCES = (
    LIBRARY / "Systems Library" / "SysML.sysml",
    LIBRARY / "Kernel Libraries" / "Kernel Semantic Library" / "KerML.kerml",
)
OUT = REPO_ROOT / "sysml_v2_checker_advanced" / "metaclass_supertypes.json"

_DECLARATION = re.compile(
    r"^\s*(?:abstract\s+)?(?:metadata\s+def|metaclass)\s+(\w+)(?:\s+specializes\s+([\w\s,:]+?))?\s*[;{]",
    re.MULTILINE)


def main() -> None:
    supertypes: dict = {}
    for source in SOURCES:
        text = source.read_text(encoding="utf-8")
        for name, bases in _DECLARATION.findall(text):
            supertypes[name] = [b.strip().split("::")[-1] for b in bases.split(",") if b.strip()] if bases else []
    OUT.write_text(json.dumps(dict(sorted(supertypes.items())), indent=1) + "\n", encoding="utf-8")
    print(f"{len(supertypes)} metaclasses -> {OUT}")


if __name__ == "__main__":
    main()
