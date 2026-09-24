"""標準ライブラリの公開名の索引（library_index.json）を引く。

索引は scripts/build_library_index.py が eval/sysml_reference/sysml.library から
生成したもので、パッケージごとに「外から `Pkg::名前` で見える名前」を持つ
（public な自前の宣言、短い名前、public import で再公開された名前、入れ子の
パッケージ）。ライブラリの版を上げたら、生成スクリプトで作り直すこと。

判定は3値で返す。索引で確かめられない形（型のメンバーまで降りる修飾名、
索引が `complete: false` としたパッケージ）は ``None``（検証不能）にして、
呼び出し側が「存在しないとは言い切れない」として通せるようにする。
"""

from __future__ import annotations

import difflib
import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Dict, List, Optional

_INDEX_PATH = Path(__file__).with_name("library_index.json")


@lru_cache(maxsize=1)
def _packages() -> Dict[str, Dict]:
    try:
        payload = json.loads(_INDEX_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        # 索引が無い・壊れている場合は、従来どおり「ライブラリ配下は検証不能」に倒す
        return {}
    return payload.get("packages", {})


def _unquote(segment: str) -> str:
    segment = segment.strip()
    if len(segment) >= 2 and segment[0] == segment[-1] == "'":
        return segment[1:-1]
    return segment


def _split(qualified_name: str) -> List[str]:
    return [_unquote(s) for s in qualified_name.split("::")]


def is_library_package(qualified_name: str) -> bool:
    return "::".join(_split(qualified_name)) in _packages()


def package_members(qualified_name: str) -> Optional[Dict[str, str]]:
    """パッケージから外へ見える名前 → 宣言の種別。索引に無い、または
    complete でないパッケージは ``None``。"""
    entry = _packages().get("::".join(_split(qualified_name)))
    if entry is None or not entry.get("complete"):
        return None
    return entry["members"]


def _owning_package(segments: List[str]) -> Optional[int]:
    """先頭から見て最も長い「パッケージである接頭辞」の長さ。"""
    packages = _packages()
    for length in range(len(segments), 0, -1):
        if "::".join(segments[:length]) in packages:
            return length
    return None


def resolve_qualified_name(qualified_name: str) -> Optional[bool]:
    """標準ライブラリの修飾名が実在するか。

    - True: 実在する（`ISQ::MassValue`、`SI::kg`、`ISQ`）。パッケージの直下の名前まで
      確かめられれば、その先（`ISQ::MassValue::num` のような型のメンバー）は
      継承が絡むので確かめずに True とする。
    - False: 実在しない（`ISQ::Mass`）。
    - None: 判定できない（先頭がライブラリのパッケージでない、または索引が
      そのパッケージを complete と言えない）。
    """
    segments = _split(qualified_name)
    length = _owning_package(segments)
    if length is None:
        return None
    if length == len(segments):
        return True
    entry = _packages()["::".join(segments[:length])]
    if segments[length] in entry["members"]:
        return True
    return False if entry.get("complete") else None


def member_kind(qualified_name: str) -> Optional[str]:
    """`Pkg::名前` の宣言の種別（`attribute def` など）。分からなければ ``None``。"""
    segments = _split(qualified_name)
    length = _owning_package(segments)
    if length is None or length != len(segments) - 1:
        return None
    return _packages()["::".join(segments[:length])]["members"].get(segments[length])


def suggest(qualified_name: str, limit: int = 3) -> List[str]:
    """実在しない修飾名に対する、近い名前の候補（`ISQ::Mass` → `ISQ::MassValue`）。"""
    segments = _split(qualified_name)
    length = _owning_package(segments)
    if length is None or length >= len(segments):
        return []
    prefix = "::".join(segments[:length])
    wanted = segments[length]
    members = list(_packages()[prefix]["members"])
    # `Mass` → `MassValue` のように「後ろに Value を付けた名前」が典型なので、
    # 前方一致を類似度より優先する
    def by_value_then_length(m: str):
        return (not m.endswith("Value"), len(m))

    starts = sorted((m for m in members if m.startswith(wanted) and m != wanted), key=by_value_then_length)
    # `Time::Instant` → `Time::TimeInstantValue` のように、名前を含むもの
    lowered = wanted.lower()
    contains = sorted(
        (m for m in members if lowered in m.lower() and not m.startswith(wanted)), key=by_value_then_length
    )
    close = difflib.get_close_matches(wanted, members, n=limit, cutoff=0.75)
    ordered: List[str] = []
    for name in starts[:limit] + contains[:limit] + close:
        if name not in ordered:
            ordered.append(name)
    return [f"{prefix}::{_quote_if_needed(name)}" for name in ordered[:limit]]


def _quote_if_needed(name: str) -> str:
    """そのまま書ける名前でなければ引用符で囲む（`km/h` → `'km/h'`）。"""
    return name if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name) else f"'{name}'"


# import のヒントで優先して挙げるパッケージ（LLM が書くモデルで最もよく要るもの）
_PREFERRED_PACKAGES = ("ScalarValues", "ISQ", "SI", "USCustomaryUnits")


def packages_defining(name: str, limit: int = 2) -> List[str]:
    """非修飾名 `name` を外へ見せているライブラリのパッケージ（import のヒント用）。"""
    name = _unquote(name)
    found = [q for q, entry in _packages().items() if name in entry["members"]]

    def rank(q: str):
        preferred = _PREFERRED_PACKAGES.index(q) if q in _PREFERRED_PACKAGES else len(_PREFERRED_PACKAGES)
        return (preferred, q.count("::"), len(q))

    return sorted(found, key=rank)[:limit]


def membership_names(qualified_name: str) -> List[str]:
    """名指しの import（`import SI::volt;`）で見えるようになる名前（名前と短い名前）。

    import は membership を持ち込むので、`volt` を import すれば短い名前の `V` も、
    `V` を import すれば `volt` も見える（参照実装で `[V]` が解決する。2026-09-24）。
    """
    segments = _split(qualified_name)
    length = _owning_package(segments)
    if length is None or length != len(segments) - 1:
        return [segments[-1]]
    entry = _packages()["::".join(segments[:length])]
    name = segments[-1]
    names = {name}
    for short, long in (entry.get("short_names") or {}).items():
        if name in (short, long):
            names.update((short, long))
    return sorted(names)
