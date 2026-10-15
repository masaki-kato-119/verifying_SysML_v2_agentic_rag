"""スコープつき名前解決（段階 B、eval/pilot_parity/ROADMAP.md）。

平らな名前表（linter.py の `_find_type_in_symbols`）は「どこかに同じ名前があれば解決できた」と
見なすため、import 漏れ・可視性・入れ子の誤りを見逃す。ここでは KerML の名前解決を、
AST から作った名前空間の木の上で行う。

- 名前空間の木: 名前を持つ宣言は、それを囲む宣言のメンバー。名前の無い入れ物（`then` の文、
  名前の無い usage など）は透過させ、中の宣言を外側のメンバーとする（メンバーを多めに見る
  ＝ 見逃す側に倒す）。
- 内側から見える名前: 所有メンバー（可視性を問わない）、import したメンバー、継承したメンバー
  （特化・型付け・再定義の先の、private 以外）。見つからなければ外側の名前空間へ。最後に
  ルート（全ファイルの最上位の要素）と標準ライブラリの最上位パッケージ。
- 外から `A::B` で見える名前: A の public なメンバー、public import したメンバー、
  継承した public なメンバー。
- 標準ライブラリ: パッケージ直下の名前は索引（library_index）で引く。ライブラリの要素の中身
  （型のメンバー）は持たないので「不明」。

結果は 3 値（FOUND / NOT_FOUND / UNKNOWN）。**確かめられない形は UNKNOWN にしてエラーを
出さない**（他の意味ルールと同じく、誤検出より見逃しに倒す）。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

from . import library_index

FOUND = "found"
NOT_FOUND = "not_found"
UNKNOWN = "unknown"

# name が宣言ではなく参照を表すノード
_REFERENCE_TYPES = {
    "import", "function_call", "then_stmt", "first_stmt", "else_stmt", "guarded_then_stmt",
    "new_instance", "named_argument", "identification", "arrow_lambda", "arrow_call",
    "value_binding", "render_stmt", "frame_statement",
}
# 子要素を持ちうるが、メンバーの宣言ではない値のキー（参照の列・式）
_NON_MEMBER_KEYS = {
    "redefines", "inheritance", "bases", "type_names", "type_spec", "multiplicity", "value",
    "defaultValue", "expression", "guard", "untilGuard", "arguments", "receiver", "body",
    "result_expression", "prefixMetadata", "filter", "about", "segments", "extra_types", "extraTypeRefs",
}
_DEFAULT_VISIBILITY = "public"
# 中身を確かめられない継承元の印（意味的メタデータ `#g1` は基底型を加える）
_OPAQUE_SUPERTYPE = "$opaque"


@lru_cache(maxsize=1)
def _library_feature_names() -> Dict[str, Optional[frozenset]]:
    path = Path(__file__).with_name("library_feature_names.json")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return {key: frozenset(payload[key]) for key in ("inherited", "implicit")}
    except (OSError, ValueError, KeyError, TypeError):
        return {"inherited": None, "implicit": None}  # 無ければ、どの名前も継承されうる扱い


def may_be_inherited_from_library(name: str, *, implicit: bool) -> bool:
    """`name` がライブラリの型から継承されうるか（scripts/build_library_feature_names.py）。

    implicit=True は、部品・動作などが暗黙に特化する型（Part・Action など）の本体の名前だけ。
    """
    names = _library_feature_names()["implicit" if implicit else "inherited"]
    return names is None or name in names


def _unquote(name: str) -> str:
    name = name.strip()
    if len(name) >= 2 and name[0] == name[-1] == "'":
        return name[1:-1]
    return name


def split_qualified(reference: str) -> List[str]:
    """`A::'B c'::D` → ['A', 'B c', 'D']（引用符の中の :: は区切らない）。"""
    parts, buf, quoted = [], [], False
    i = 0
    while i < len(reference):
        ch = reference[i]
        if ch == "'":
            quoted = not quoted
            buf.append(ch)
        elif not quoted and reference.startswith("::", i):
            parts.append(_unquote("".join(buf)))
            buf = []
            i += 2
            continue
        else:
            buf.append(ch)
        i += 1
    parts.append(_unquote("".join(buf)))
    return [p for p in parts if p]


@dataclass
class Import:
    target: str
    wildcard: bool
    recursive: bool
    all: bool
    visibility: str
    filter: Optional[dict] = None  # `import P::**[@Safety];` の条件
    node: Optional[dict] = None


@dataclass(eq=False)
class Scope:
    """名前空間の木の 1 要素（AST の宣言、ルート、または標準ライブラリの要素）。"""
    node: Optional[dict]
    name: Optional[str] = None
    short_name: Optional[str] = None
    visibility: str = _DEFAULT_VISIBILITY
    parent: Optional["Scope"] = None
    members: List["Scope"] = field(default_factory=list)
    imports: List[Import] = field(default_factory=list)
    supertypes: List[str] = field(default_factory=list)
    alias_target: Optional[str] = None
    library: Optional[str] = None  # 標準ライブラリの要素なら修飾名
    filters: List[dict] = field(default_factory=list)  # パッケージの `filter @Safety;`（import に効く）
    metadata: List[str] = field(default_factory=list)  # 付いているメタデータの型（`@Safety;`、`#g1`）

    def names(self) -> Tuple[str, ...]:
        return tuple(n for n in (self.name, self.short_name) if n)

    @property
    def is_package(self) -> bool:
        if self.library is not None:
            return library_index.is_library_package(self.library)
        return (self.node or {}).get("type") in ("package", "root", None)


Result = Tuple[str, List[Scope]]


def _merge(results: Iterable[Result]) -> Result:
    found: List[Scope] = []
    unknown = False
    for status, scopes in results:
        if status == FOUND:
            found.extend(s for s in scopes if s not in found)
        elif status == UNKNOWN:
            unknown = True
    if found:
        return FOUND, found
    return (UNKNOWN, []) if unknown else (NOT_FOUND, [])


class ScopeResolver:
    def __init__(self, ast: dict, external_names: Optional[Iterable[str]] = None):
        """external_names: 他のファイルにあると分かっている名前（linter の known_external_types）。
        ルートで見つからない名前がこの中にあれば「不明」とする（1 ファイル単位の検証）。"""
        self.external_names = frozenset(_unquote(n) for n in external_names or ())
        self.root = Scope(node={"type": "root"}, name=None)
        self.scope_of: Dict[int, Scope] = {}  # id(AST ノード) → それを所有する（参照を解決する）名前空間
        self.element_of: Dict[int, Scope] = {}  # id(宣言ノード) → その Scope
        self._library_cache: Dict[str, Scope] = {}
        self._active: set = set()
        self._memo_cache: Dict[tuple, Result] = {}
        self._cycle_cuts = 0  # 循環で打ち切った回数（打ち切りを含む結果は記憶しない）
        self._build(ast, self.root)

    # --- 木を作る -----------------------------------------------------------------------

    def _build(self, node, owner: Scope) -> None:
        if isinstance(node, list):
            for item in node:
                self._build(item, owner)
            return
        if not isinstance(node, dict):
            return
        node_type = node.get("type")
        self.scope_of[id(node)] = owner
        if node_type == "root" or (node_type is None and "children" in node):
            self._build_children(node, owner)
            return
        if node_type == "import":
            target = node.get("name") or ""
            # 可視性の無い import は参照実装 0.62.0 では構文エラーで、import として効かない
            # （`import ScalarValues::*;` のあとの `String` が未解決になる。llm-sonnet-A2 で実測）
            if target and node.get("visibility"):
                owner.imports.append(Import(
                    target=target, wildcard=bool(node.get("wildcard")), recursive=bool(node.get("recursive")),
                    all=bool(node.get("isAll")), visibility=node.get("visibility") or _DEFAULT_VISIBILITY,
                    filter=node.get("filter") if isinstance(node.get("filter"), dict) else None, node=node))
            return
        if node_type == "filter":
            if isinstance(node.get("expression"), dict):
                owner.filters.append(node["expression"])
            return
        if node_type == "metadata_usage" and not node.get("type_name") and isinstance(node.get("name"), str):
            # `@Safety;` / `metadata Tag about x;` の名前はメタデータの型への参照
            owner.metadata.append(split_qualified(node["name"])[-1])
            element = Scope(node=node, parent=owner, supertypes=[node["name"]])
            owner.members.append(element)
            self.element_of[id(node)] = element
            self._build_children(node, element)
            return
        if node_type == "expose":
            # expose は view の中の import（すべての可視性を取り込む、外へは見せない）
            target = node.get("qualified_name") or ""
            if target:
                owner.imports.append(Import(target=target, wildcard=bool(node.get("wildcard")),
                                            recursive=bool(node.get("recursive")), all=True, visibility="private",
                                            node=node))
            return
        name = node.get("name") if isinstance(node.get("name"), str) else None
        identification = node.get("identification")
        if node_type in ("comment", "documentation", "doc") and isinstance(identification, dict):
            # `comment cmt /* ... */` の名前は identification の中（`comment c2 about cmt` で参照される）
            name = identification.get("name") if isinstance(identification.get("name"), str) else None
        referenced = _referenced_feature(node)
        if referenced:
            # `satisfy r by d;` / `perform x;` などは r・x を参照する usage。参照実装と同じく、
            # 参照先の名前を自分の名前とし、参照先から中身を継承する
            name = split_qualified(referenced)[-1]
        if node_type in _REFERENCE_TYPES or node.get("isReference") or (name and ("::" in name or "." in name)):
            name = None
        short = node.get("shortName") if isinstance(node.get("shortName"), str) else None
        if not name and not short:
            # 名前の無い再定義（`:>> x`）は、再定義した名前の feature として持つ
            for entry in node.get("redefines") or []:
                if isinstance(entry, dict) and entry.get("kind") == "redefines" and isinstance(entry.get("target"), str):
                    name = split_qualified(entry["target"])[-1]
                    break
        supertypes = list(_supertype_references(node))
        if not name and not short and not supertypes:
            self._build_children(node, owner)  # 透過
            return
        # 名前が無くても型付け・特化があれば名前空間（`require constraint : ML { in :>> limit; }`）。
        # 名前の無い要素は外からは名前で引けない
        element = Scope(node=node, name=_unquote(name) if name else None, short_name=_unquote(short) if short else None,
                        visibility=node.get("visibility") or _DEFAULT_VISIBILITY, parent=owner)
        if node_type == "alias":
            element.alias_target = node.get("target")
        element.supertypes = supertypes
        if referenced and referenced not in element.supertypes:
            element.supertypes.append(referenced)
        if node.get("prefixMetadata"):
            element.supertypes.append(_OPAQUE_SUPERTYPE)
            element.metadata.extend(split_qualified(m)[-1] for m in node["prefixMetadata"] if isinstance(m, str))
        owner.members.append(element)
        self.element_of[id(node)] = element
        trigger = node.get("trigger")
        if isinstance(trigger, dict) and trigger.get("type_name") and isinstance(trigger.get("reference"), str):
            # `transition T ... accept s : Sig` の s は遷移のメンバー（`T.s.x` で参照される）
            element.members.append(Scope(node=trigger, name=_unquote(trigger["reference"]), parent=element,
                                         supertypes=[trigger["type_name"]]))
        self._build_children(node, element)

    def _build_children(self, node: dict, owner: Scope) -> None:
        for key, value in node.items():
            if key in _NON_MEMBER_KEYS or key == "type":
                continue
            if isinstance(value, (list, dict)):
                self._build(value, owner)

    # --- 標準ライブラリ ------------------------------------------------------------------

    def _library_scope(self, qualified: str) -> Scope:
        scope = self._library_cache.get(qualified)
        if scope is None:
            scope = Scope(node=None, name=qualified.split("::")[-1], library=qualified)
            self._library_cache[qualified] = scope
        return scope

    def _library_member(self, scope: Scope, name: str, recursive: bool = False) -> Result:
        qualified = scope.library or ""
        if not library_index.is_library_package(qualified):
            return UNKNOWN, []  # 型など、パッケージでない要素の中身は持たない
        if library_index.is_library_package(f"{qualified}::{name}"):
            return FOUND, [self._library_scope(f"{qualified}::{name}")]
        members = library_index.package_members(qualified)
        if members is None:
            return UNKNOWN, []
        if name in members:
            return FOUND, [self._library_scope(f"{qualified}::{name}")]
        short = library_index.membership_names(f"{qualified}::{name}")
        if len(short) > 1:
            return FOUND, [self._library_scope(f"{qualified}::{name}")]
        if recursive:
            return UNKNOWN, []  # 入れ子のパッケージの中身まではたどらない
        return NOT_FOUND, []

    def _library_root(self, name: str) -> Result:
        if library_index.is_library_package(name):
            return FOUND, [self._library_scope(name)]
        if name in self.external_names:
            return UNKNOWN, []
        return NOT_FOUND, []

    # --- 参照を解決する ------------------------------------------------------------------

    def resolve(self, reference: str, context: Scope, *, feature: bool = False,
                exclude: Optional[Scope] = None) -> Result:
        """`reference`（`A`、`A::B`）を `context` の内側から解決する。

        feature=True は、feature の位置の参照（再定義の先など）。見つからない名前が
        ライブラリの型から暗黙に継承されうるときは UNKNOWN にする。
        exclude は、参照を持つ宣言自身（名前の無い `:>> x` は x として登録されている）。
        """
        if reference == _OPAQUE_SUPERTYPE:
            return UNKNOWN, []
        segments = split_qualified(reference.lstrip("~"))
        if not segments:
            return UNKNOWN, []
        if segments[0] == "$":  # `$::A` はルート（グローバルな名前空間）から
            segments = segments[1:]
            if not segments:
                return UNKNOWN, []
            context, exclude = self.root, None
            owned = [m for m in self.root.members if segments[0] in m.names()]
            status, scopes = (FOUND, owned) if owned else self._library_root(segments[0])
        else:
            status, scopes = self._resolve_first(segments[0], context, exclude)
        if status == NOT_FOUND and feature and len(segments) == 1 and may_be_inherited_from_library(
                segments[0], implicit=True):
            return UNKNOWN, []
        for segment in segments[1:]:
            if status != FOUND:
                return status, []
            status, scopes = _merge(self._visible_from_outside(self._dealias(s), segment) for s in scopes)
        return status, scopes

    def _resolve_first(self, name: str, context: Scope, exclude: Optional[Scope] = None) -> Result:
        scope: Optional[Scope] = context
        unknown = False
        while scope is not None:
            status, found = self._visible_inside(scope, name, exclude)
            if status == FOUND:
                return status, found
            unknown = unknown or status == UNKNOWN
            scope = scope.parent
        status, found = self._library_root(name)
        if status != NOT_FOUND:
            return status, found  # ライブラリのパッケージ、または他のファイルにある名前（不明）
        return (UNKNOWN, []) if unknown else (NOT_FOUND, [])

    def missing_chain_member(self, start: List[Scope], tail: List[str]) -> Optional[str]:
        """`a.b.c` の b・c を順にたどり、無いと言い切れる名前を返す（無ければ None）。

        連鎖の先は、型から外に見えるメンバー（public）。protected は見えない
        （KerML のテスト VisibilityTests_Protected_FeatureChain）。
        """
        current = start
        for name in tail:
            status, found = _merge(self._chain_member(self._dealias(s), name) for s in current)
            if status == NOT_FOUND:
                return name
            if status != FOUND:
                return None
            current = found
        return None

    def _chain_member(self, scope: Scope, name: str) -> Result:
        result = self._visible_from_outside(scope, name)
        if result[0] == NOT_FOUND and may_be_inherited_from_library(name, implicit=True):
            return UNKNOWN, []
        return result

    def _dealias(self, scope: Scope, depth: int = 0) -> Scope:
        if scope.alias_target and depth < 8 and scope.parent is not None:
            status, found = self.resolve(scope.alias_target, scope.parent)
            if status == FOUND and len(found) == 1:
                return self._dealias(found[0], depth + 1)
        return scope

    def _memo(self, key: tuple, compute) -> Result:
        """循環を止めつつ結果を記憶する。import どうしが互いの対象を解決し合うと、
        記憶しなければ指数的に遅くなる。循環で打ち切った途中の結果は不完全なので記憶しない。"""
        cached = self._memo_cache.get(key)
        if cached is not None:
            return cached
        if key in self._active:
            self._cycle_cuts += 1
            return NOT_FOUND, []
        self._active.add(key)
        cuts = self._cycle_cuts
        try:
            result = compute()
        finally:
            self._active.discard(key)
        if self._cycle_cuts == cuts:
            self._memo_cache[key] = result
        return result

    def _visible_inside(self, scope: Scope, name: str, exclude: Optional[Scope] = None,
                        import_limit: Optional[int] = None) -> Result:
        """`scope` の内側から、修飾なしの `name` で見えるもの（exclude は除く）。

        import_limit は、使う import を先頭からその数までに限る（import の対象の解決用）。
        """
        def compute() -> Result:
            owned = [m for m in scope.members if name in m.names() and m is not exclude]
            if owned:
                return FOUND, owned
            return _merge([self._imported(scope, name, outside=False, limit=import_limit),
                           self._inherited(scope, name, outside=False)])
        return self._memo(("inside", id(scope), name, id(exclude), import_limit), compute)

    def _visible_from_outside(self, scope: Scope, name: str) -> Result:
        """`scope::name` で見えるもの（public なメンバー）。"""
        if scope.library is not None:
            return self._library_member(scope, name)

        def compute() -> Result:
            owned = [m for m in scope.members if name in m.names() and m.visibility == "public"]
            if owned:
                return FOUND, owned
            if any(name in m.names() for m in scope.members):
                return NOT_FOUND, []  # private / protected のメンバーは修飾名では見えない
            return _merge([self._imported(scope, name, outside=True), self._inherited(scope, name, outside=True)])
        return self._memo(("outside", id(scope), name), compute)

    def _imported(self, scope: Scope, name: str, *, outside: bool, limit: Optional[int] = None) -> Result:
        results: List[Result] = []
        for index, imp in enumerate(scope.imports[:limit]):
            if outside and imp.visibility != "public":
                continue
            conditions = ([imp.filter] if imp.filter else []) + scope.filters
            result = self._imported_one(scope, name, imp, index)
            results.append(_apply_filters(result, conditions) if conditions else result)
        return _merge(results)

    def _imported_one(self, scope: Scope, name: str, imp: Import, index: int) -> Result:
        if imp.wildcard:
            status, namespaces = self._resolve_import_target(imp.target, scope, index)
            if status != FOUND:
                return (UNKNOWN, []) if status == UNKNOWN else (NOT_FOUND, [])
            return _merge(self._members_for_import(self._dealias(ns), name, imp) for ns in namespaces)
        segments = split_qualified(imp.target)
        if not segments:
            return NOT_FOUND, []
        if name in self._import_names(imp, segments):
            return self._resolve_import_target(imp.target, scope, index)
        # 名指しの import は membership を持ち込むので、相手の短い名前・名前でも見える
        status, targets = self._resolve_import_target(imp.target, scope, index)
        if status != FOUND:
            return NOT_FOUND, []
        results: List[Result] = []
        matched = [t for t in targets if name in t.names()]
        if matched:
            results.append((FOUND, matched))
        if imp.recursive:
            results.extend(self._members_for_import(self._dealias(t), name, imp) for t in targets)
        return _merge(results)

    def _import_names(self, imp: Import, segments: List[str]) -> Tuple[str, ...]:
        qualified = "::".join(segments)
        names = set(library_index.membership_names(qualified)) if library_index.is_library_package(
            "::".join(segments[:-1])) else {segments[-1]}
        return tuple(names)

    def _resolve_import_target(self, target: str, scope: Scope, index: Optional[int] = None) -> Result:
        """import の対象を、import を持つ名前空間から解決する。

        同じ名前空間の、それより前に書かれた import も使う（`private import RiskMetadata::*;`
        のあとの `private import RiskLevelEnum::*;`）。後ろの import は使わない（Xtext の
        参照実装と同じく書いた順に解決する。互いを使い合う循環も起きない）。
        index は、この import が scope.imports の何番目か（None は全部の後ろ）。
        """
        segments = split_qualified(target)
        if not segments:
            return UNKNOWN, []
        if segments[0] == "$":
            return self.resolve(target, self.root)
        status, found = self._visible_inside(scope, segments[0], import_limit=index)
        if status != FOUND:
            outer_status, outer = self._resolve_first(segments[0], scope.parent) if scope.parent else                 self._library_root(segments[0])
            if outer_status == FOUND:
                status, found = outer_status, outer
            elif status != UNKNOWN:
                status, found = outer_status, outer
        for segment in segments[1:]:
            if status != FOUND:
                return status, []
            status, found = _merge(self._visible_from_outside(self._dealias(s), segment) for s in found)
        return status, found

    def _members_for_import(self, ns: Scope, name: str, imp: Import) -> Result:
        if ns.library is not None:
            return self._library_member(ns, name, recursive=imp.recursive)
        if imp.all:
            direct = [m for m in ns.members if name in m.names()]
            result = (FOUND, direct) if direct else _merge([self._imported(ns, name, outside=False),
                                                            self._inherited(ns, name, outside=False)])
        else:
            result = self._visible_from_outside(ns, name)
        if result[0] == FOUND or not imp.recursive:
            return result
        if name in ns.names():  # `::**` は名前空間そのものも取り込む
            return FOUND, [ns]
        # `::**`: 入れ子の要素の中へも（public なものだけ）
        nested: List[Result] = [result]
        for member in ns.members:
            if member.visibility == "public" or imp.all:
                nested.append(self._members_for_import(self._dealias(member), name, imp))
        return _merge(nested)

    def _inherited(self, scope: Scope, name: str, *, outside: bool) -> Result:
        if not scope.supertypes:
            return NOT_FOUND, []
        context = scope.parent or self.root
        results: List[Result] = []
        library_status = UNKNOWN if may_be_inherited_from_library(name, implicit=False) else NOT_FOUND
        for reference in scope.supertypes:
            status, supers = self.resolve(reference, context, exclude=scope)
            if status == UNKNOWN or reference == _OPAQUE_SUPERTYPE:
                results.append((UNKNOWN, []))  # 継承元が分からなければ中身も分からない
                continue
            if status == NOT_FOUND:
                # 継承元が無い（それ自体がエラー）。参照実装も中の名前を解決できない
                continue
            for sup in supers:
                sup = self._dealias(sup)
                if sup is scope:
                    continue
                if sup.library is not None:
                    # ライブラリの型の中身は持たない。本体で宣言されうる名前なら「不明」
                    results.append((library_status, []))
                    continue
                if outside:
                    result = self._visible_from_outside(sup, name)
                else:
                    result = self._visible_to_subtype(sup, name)
                results.append(_without_enum_literals(result))
        return _merge(results)

    def _visible_to_subtype(self, scope: Scope, name: str) -> Result:
        def compute() -> Result:
            owned = [m for m in scope.members if name in m.names() and m.visibility != "private"]
            if owned:
                return FOUND, owned
            if any(name in m.names() for m in scope.members):
                return NOT_FOUND, []
            return _merge([self._imported(scope, name, outside=True), self._inherited(scope, name, outside=False)])
        return self._memo(("subtype", id(scope), name), compute)


def _without_enum_literals(result: Result) -> Result:
    """列挙の値は型付けで継承されない（`attribute mode : ModeKind = idle;` の idle は
    参照実装で未解決。`ModeKind::idle` と書く）。"""
    status, scopes = result
    if status != FOUND:
        return result
    kept = [s for s in scopes if (s.node or {}).get("type") != "enum_literal"]
    return (FOUND, kept) if kept else (NOT_FOUND, [])


def _filter_verdict(scope: Scope, expression: dict) -> Optional[bool]:
    """import の条件（`@Safety`、`@A and not @B`）を要素に当てる。判定できなければ None。"""
    kind = expression.get("type")
    if kind == "metadata_ref" and isinstance(expression.get("reference"), str):
        if scope.library is not None:
            return None
        return split_qualified(expression["reference"])[-1] in scope.metadata
    if kind == "literal" and isinstance(expression.get("value"), bool):
        return expression["value"]
    if kind == "binary_expr" and expression.get("op") in ("and", "or"):
        left = _filter_verdict(scope, expression.get("left") or {})
        right = _filter_verdict(scope, expression.get("right") or {})
        if expression["op"] == "and":
            if left is False or right is False:
                return False
            return None if None in (left, right) else True
        if left is True or right is True:
            return True
        return None if None in (left, right) else False
    if kind == "unary_expr" and expression.get("op") == "not":
        inner = _filter_verdict(scope, expression.get("operand") or {})
        return None if inner is None else not inner
    return None


def _apply_filters(result: Result, conditions: List[dict]) -> Result:
    status, scopes = result
    if status != FOUND:
        return result
    kept: List[Scope] = []
    unknown = False
    for scope in scopes:
        verdicts = [_filter_verdict(scope, c) for c in conditions]
        if all(v is True for v in verdicts):
            kept.append(scope)
        elif None in verdicts and False not in verdicts:
            unknown = True
    if kept:
        return FOUND, kept
    return (UNKNOWN, []) if unknown else (NOT_FOUND, [])


_REFERENCING_USAGE_TYPES = {"satisfy_requirement_usage", "verify_requirement_usage", "perform_action",
                            "exhibit_state_usage", "include_use_case_usage"}


def _referenced_feature(node: dict) -> Optional[str]:
    """`satisfy r by d;`・`verify r;`・`perform x;`・`exhibit s;`・`include u;` が参照する先。"""
    node_type = node.get("type")
    if node_type not in _REFERENCING_USAGE_TYPES:
        return None
    if isinstance(node.get("reference"), str) and node["reference"]:
        return node["reference"]
    name = node.get("name")
    if not isinstance(name, str) or not name:
        return None
    if node_type == "satisfy_requirement_usage" and node.get("declaresRequirement"):
        return None
    if node.get("redefines"):
        return None  # `exhibit state s2 ::> s0;` の s2 は自分の名前
    if node_type == "satisfy_requirement_usage" or not node.get("type_name"):
        return name if node_type != "perform_action" else None
    return None


def _supertype_references(node: dict) -> Iterable[str]:
    """宣言が特化・型付け・再定義する先の参照（メンバーを継承する元）。"""
    seen = []
    type_name = node.get("type_name")
    if isinstance(type_name, str) and type_name:
        seen.append(type_name)
    for extra in node.get("type_names") or []:
        if isinstance(extra, str) and extra:
            seen.append(extra)
    inheritance = node.get("inheritance")
    if isinstance(inheritance, dict):
        for base in inheritance.get("bases") or [inheritance.get("base")]:
            if isinstance(base, str) and base:
                seen.append(base)
    for entry in node.get("redefines") or []:
        if isinstance(entry, dict) and isinstance(entry.get("target"), str):
            seen.append(entry["target"])
    out: List[str] = []
    for ref in seen:
        ref = ref.lstrip("~").strip()
        if ref and ref not in out:
            out.append(ref)
    return out


Reference = Tuple[str, str, dict, bool]  # (参照, 種類の名前, ノード, feature の位置か)


_KERML_CLASSIFIER_KINDS = ("datatype", "class", "struct", "classifier", "behavior", "function", "predicate",
                           "interaction", "assoc", "metaclass")


def _is_definition(scope: Scope) -> bool:
    if scope.library is not None:
        kind = library_index.member_kind(scope.library) or ""
        return "def" in kind.split() or any(k in kind.split() for k in _KERML_CLASSIFIER_KINDS)
    return ((scope.node or {}).get("type") or "").endswith("_def")


def _is_package(scope: Scope) -> bool:
    if scope.library is not None:
        return library_index.is_library_package(scope.library)
    return (scope.node or {}).get("type") == "package"


def kind_matches(scope: Scope, kind: str) -> Optional[bool]:
    """解決できた要素が、参照の位置で求められる種類か（分からなければ None）。

    参照実装は、種類の合わない要素を候補にしない（`part def b :> seatBelt;` で seatBelt が
    usage なら `Couldn't resolve reference to Classifier 'seatBelt'.`）。
    """
    if scope.library is not None and library_index.member_kind(scope.library) is None and not _is_package(scope):
        return None  # ライブラリの入れ子の要素など、種類が分からない
    if kind == "Classifier":
        return _is_definition(scope)
    if kind == "Type":
        return not _is_package(scope)
    if kind == "Feature":
        return not _is_definition(scope) and not _is_package(scope)
    return True


def references_of(node: dict) -> List[Reference]:
    """宣言ノードが持つ、名前空間で解決する参照（型付け・特化・再定義・alias）。"""
    refs: List[Reference] = []
    node_type = node.get("type") or ""
    is_def = node_type.endswith("_def")
    type_name = node.get("type_name")
    if isinstance(type_name, str) and type_name and not is_def:
        refs.append((type_name, "Type", node, False))
    for extra in node.get("type_names") or []:
        if isinstance(extra, str) and extra and extra != type_name:
            refs.append((extra, "Type", node, False))
    inheritance = node.get("inheritance")
    if isinstance(inheritance, dict):
        for base in inheritance.get("bases") or [inheritance.get("base")]:
            if isinstance(base, str) and base:
                refs.append((base, "Classifier" if is_def else "Feature", node, not is_def))
    for entry in node.get("redefines") or []:
        if isinstance(entry, dict) and isinstance(entry.get("target"), str) and entry["target"]:
            refs.append((entry["target"], "Feature", node, True))
    referenced = _referenced_feature(node)
    if referenced and (node_type == "satisfy_requirement_usage" or node.get("reference")):
        # `verify r;`・`exhibit s;`・`include u;` は、`verify requirement r;` などの宣言と
        # AST で区別できないので報告しない（参照として継承元を探すのには使う）
        refs.append((referenced, "Feature", node, True))
    for metadata in node.get("prefixMetadata") or []:
        if isinstance(metadata, str) and metadata:
            refs.append((metadata, "Type", node, False))  # `#refinement dependency ...` の refinement
    if node_type == "metadata_usage" and not node.get("type_name") and isinstance(node.get("name"), str):
        refs.append((node["name"], "Type", node, False))  # `@Rationale { ... }` の Rationale
    for target in node.get("about") or []:
        if isinstance(target, str) and target:
            refs.append((target, "Element", node, False))
    if node_type == "render_stmt" and not node.get("isRendering") and isinstance(node.get("name"), str):
        refs.append((node["name"], "Feature", node, True))  # `render asTreeDiagram;`
    if node_type == "transition":
        for key in ("source", "target"):
            if isinstance(node.get(key), str) and node[key]:
                refs.append((node[key], "Element", node, True))
    if node_type == "alias" and isinstance(node.get("target"), str):
        refs.append((node["target"], "Element", node, False))
    return refs


def _chain_tail(reference: str) -> List[str]:
    """`a.b.c` → ['b', 'c']。"""
    head = _chain_head(reference)
    rest = reference[len(head) + 1:] if len(reference) > len(head) else ""
    parts: List[str] = []
    while rest:
        part = _chain_head(rest)
        parts.append(_unquote(part))
        rest = rest[len(part) + 1:]
    return parts


# 式の中で name_ref になるが名前ではないもの
_EXPRESSION_KEYWORDS = frozenset({"null", "true", "false"})


def _chain_head(reference: str) -> str:
    """`a.b.c` → `a`、`A::B.c` → `A::B`（引用符の中の . は区切らない）。"""
    quoted = False
    for i, ch in enumerate(reference):
        if ch == "'":
            quoted = not quoted
        elif ch == "." and not quoted:
            return reference[:i]
    return reference


def typed_by_usages(ast: dict, external_names: Optional[Iterable[str]] = None) -> List[Tuple[dict, str]]:
    """usage の型（`attribute a : b;`）が、定義ではなく usage に解決するもの: (ノード, 型の参照)。

    参照実装は `An attribute must be typed by attribute definitions.` などを返す
    （tests/fixtures/reference_conformance/k09・k12）。解決できない型は unresolved_references が扱う。
    """
    resolver = ScopeResolver(ast, external_names)
    out: List[Tuple[dict, str]] = []

    def visit(node, owner: Scope):
        if isinstance(node, list):
            for item in node:
                visit(item, owner)
            return
        if not isinstance(node, dict):
            return
        element = resolver.element_of.get(id(node))
        node_type = node.get("type") or ""
        type_name = node.get("type_name")
        if (element is not None and not node_type.endswith("_def") and isinstance(type_name, str) and type_name
                and "." not in type_name and node_type not in _REFERENCE_TYPES):
            status, found = resolver.resolve(type_name, owner)
            if status == FOUND:
                targets = [resolver._dealias(f) for f in found]
                if all(t.library is None and t.node is not None and not _is_definition(t)
                       and not _is_package(t) for t in targets):
                    out.append((node, type_name))
        inner = element or owner
        for key, value in node.items():
            if key != "type" and isinstance(value, (dict, list)):
                visit(value, inner)

    visit(ast, resolver.root)
    return out


def unresolved_references(ast: dict, external_names: Optional[Iterable[str]] = None) -> List[Tuple[dict, str, str]]:
    """解決できないと言い切れる参照: (ノード, 参照, 種類の名前)。"""
    resolver = ScopeResolver(ast, external_names)
    out: List[Tuple[dict, str, str]] = []

    def visit(node, owner: Scope, local_names: frozenset):
        if isinstance(node, list):
            for item in node:
                visit(item, owner, local_names)
            return
        if not isinstance(node, dict):
            return
        element = resolver.element_of.get(id(node))
        param = node.get("param")
        if node.get("type") == "arrow_lambda" and isinstance(param, dict) and isinstance(param.get("name"), str):
            local_names = local_names | {param["name"]}  # `{in p; p.m}` の p
        trigger = node.get("trigger")
        if isinstance(trigger, dict) and trigger.get("type_name") and isinstance(trigger.get("reference"), str):
            local_names = local_names | {trigger["reference"]}  # `accept sig : Sig if sig.on` の sig
        if node.get("type") == "name_ref" and isinstance(node.get("reference"), str):
            # 式の中の名前（`[kg]`、`noSuch == true`、`d.m` の d）。連鎖は先頭だけ確かめる
            first = _chain_head(node["reference"])
            if first and split_qualified(first)[0] not in local_names | _EXPRESSION_KEYWORDS:
                status, found = resolver.resolve(first, owner, feature=True)
                if status == NOT_FOUND:
                    out.append((node, first, "Element"))
                elif status == FOUND:
                    missing = resolver.missing_chain_member(found, _chain_tail(node["reference"]))
                    if missing:
                        out.append((node, missing, "Element"))
        elif node.get("type") in ("import", "expose") and (node.get("name") or node.get("qualified_name")):
            target = node.get("name") or node.get("qualified_name")
            index = next((i for i, imp in enumerate(owner.imports) if imp.node is node), None)
            status, _ = resolver._resolve_import_target(target, owner, index)
            if status == NOT_FOUND:
                out.append((node, target, "Namespace" if node.get("wildcard") else "Membership"))
        else:
            for reference, kind, ref_node, feature in references_of(node):
                if "." in reference.replace("'", ""):
                    continue  # feature の連鎖は別に扱う
                # 名前の無い再定義（`:>> x`）は x として登録されているので自分を除く。
                # 名前のある `part p4 :> p4;` は、参照実装でも自分自身に解決する
                own_name = isinstance(node.get("name"), str) and node.get("name") and not _referenced_feature(node)
                status, found = resolver.resolve(reference, owner, feature=feature,
                                                 exclude=None if own_name else element)
                if status == FOUND:
                    verdicts = [kind_matches(resolver._dealias(f), kind) for f in found]
                    if verdicts and all(v is False for v in verdicts):
                        status = NOT_FOUND
                if status == NOT_FOUND:
                    out.append((ref_node, reference, kind))
        inner = element or owner
        for key, value in node.items():
            if key not in ("type",) and isinstance(value, (dict, list)):
                visit(value, inner, local_names)

    visit(ast, resolver.root, frozenset())
    return out

