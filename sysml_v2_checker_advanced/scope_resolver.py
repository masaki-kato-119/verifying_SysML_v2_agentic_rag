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
import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from . import library_index
from .antlr_transformer import _with_extra, extra_of

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
    referenced: Optional[str] = None  # 参照する usage（`perform x;`）の参照先
    # 名前を介さない継承元（variation の中の variant は、外側の variation を暗黙に特化する）
    super_scopes: List["Scope"] = field(default_factory=list)
    filters: List[dict] = field(default_factory=list)  # パッケージの `filter @Safety;`（import に効く）
    metadata: List[str] = field(default_factory=list)  # 付いているメタデータの型（`@Safety;`、`#g1`）
    # メタデータの値（`@Safety { isMandatory = true; }` → {"Safety": {"isMandatory": True}}）
    metadata_values: Dict[str, Dict[str, object]] = field(default_factory=dict)

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
    def __init__(self, ast: dict, external_names: Optional[Iterable[str]] = None,
                 other_asts: Sequence[dict] = ()):
        """external_names: 他のファイルにあると分かっている名前（linter の known_external_types）。
        ルートで見つからない名前がこの中にあれば「不明」とする（1 ファイル単位の検証）。

        other_asts: 同じモデルのほかのファイルの AST（複数ファイルのモデル）。参照実装と同じく、
        各ファイルの最上位の要素をグローバルな名前空間に置き、どのファイルからも
        修飾なしの名前（`private import AGV_Definitions::*;` の AGV_Definitions）で引ける。
        ファイルの最上位の import はそのファイルの中だけに効く。判定するのは ast の参照だけ。
        """
        self.external_names = frozenset(_unquote(n) for n in external_names or ())
        self.root = Scope(node={"type": "root"}, name=None)
        self.file_roots: List[Scope] = [self.root]
        self.scope_of: Dict[int, Scope] = {}  # id(AST ノード) → それを所有する（参照を解決する）名前空間
        self.element_of: Dict[int, Scope] = {}  # id(宣言ノード) → その Scope
        self._library_cache: Dict[str, Scope] = {}
        self._active: set = set()
        self._memo_cache: Dict[tuple, Result] = {}
        self._cycle_cuts = 0  # 循環で打ち切った回数（打ち切りを含む結果は記憶しない）
        self._build(ast, self.root)
        if other_asts:
            global_scope = Scope(node={"type": "root"}, name=None)
            self.root.parent = global_scope
            for other in other_asts:
                file_root = Scope(node={"type": "root"}, name=None, parent=global_scope)
                self._build(other, file_root)
                self.file_roots.append(file_root)
            # 最上位の private な要素もほかのファイルから見える（参照実装で確認、2026-10-22）
            global_scope.members = [m for file_root in self.file_roots for m in file_root.members]
        self._name_referencing_usages()
        self._drop_plain_metadata_opaque()

    def _drop_plain_metadata_opaque(self) -> None:
        """前置のメタデータ（`#idd port p { ... }`）が足す基底の型を、分かる範囲で確かめる。

        前置のメタデータは基底の型を足しうる（SemanticMetadata の `:>> baseType = X meta ...`）ので、
        型を不明（opaque）にしていた。metadata def の特化の連鎖をたどり、baseType が書いてあれば X を
        継承元にし、SemanticMetadata まで baseType が無ければ何も足さない。それ以外（ほかのライブラリの
        metadata、解決できない名前）は不明のまま（フォルダ単位のコーパスの Arrowhead_Framework_Example、
        2026-10-22。参照実装は `x.APIS_MQTT.retal` の retal を確かめる）。
        """
        changed = False

        def base_of(definition: Scope) -> Optional[str]:
            """metadata def 自身に書いた `:>> baseType = X meta T` / `default X meta T` の X。"""
            for child in (definition.node or {}).get("children") or []:
                if not isinstance(child, dict):
                    continue
                targets = [e.get("target") for e in child.get("redefines") or [] if isinstance(e, dict)]
                if child.get("type") == "value_binding":
                    targets.append(child.get("target"))
                if "baseType" not in targets:
                    continue
                for key in ("value", "defaultValue"):
                    expr = child.get(key)
                    base = expr.get("base") if isinstance(expr, dict) and expr.get("type") == "meta_expr" else None
                    if isinstance(base, dict) and isinstance(base.get("reference"), str):
                        return base["reference"]
                return ""  # baseType を書いているが形が分からない
            return None

        def added(name: str, context: Scope, depth: int = 0):
            """("none", []) 何も足さない / ("base", 継承元) / ("unknown", [])。"""
            if depth > 8:
                return "unknown", []
            status, found = self.resolve(name, context)
            if status != FOUND or not found:
                return "unknown", []
            bases: List[Scope] = []
            for definition in (self._dealias(f) for f in found):
                if definition.library is not None:
                    if definition.library.split("::")[-1] == "SemanticMetadata":
                        continue
                    return "unknown", []
                if (definition.node or {}).get("type") != "metadata_def":
                    return "unknown", []
                base = base_of(definition)
                if base == "":
                    return "unknown", []
                if base is not None:
                    status, targets = self.resolve(base, definition, feature=True)
                    if status != FOUND:
                        return "unknown", []
                    bases.extend(targets)
                    continue
                for supertype in definition.supertypes:
                    kind, more = added(supertype, definition.parent or self.root, depth + 1)
                    if kind == "unknown":
                        return kind, []
                    bases.extend(more)
            return ("base" if bases else "none"), bases

        def walk(scope: Scope) -> None:
            nonlocal changed
            for member in scope.members:
                names = [m for m in (member.node or {}).get("prefixMetadata") or [] if isinstance(m, str)]
                if names and _OPAQUE_SUPERTYPE in member.supertypes:
                    results = [added(n, member.parent or self.root) for n in names]
                    if all(kind != "unknown" for kind, _ in results):
                        # 前置のメタデータで足したもの（最後に足した 1 つ）だけを外し、baseType を継承元にする
                        last = len(member.supertypes) - 1 - member.supertypes[::-1].index(_OPAQUE_SUPERTYPE)
                        del member.supertypes[last]
                        member.super_scopes.extend(b for _kind, bases in results for b in bases)
                        changed = True
                walk(member)

        for file_root in self.file_roots:
            walk(file_root)
        if changed:
            self._memo_cache.clear()  # 外す前の探索結果は古い

    @property
    def global_members(self) -> List[Scope]:
        """グローバルな名前空間の要素（`$::A` の A の候補）。1 ファイルならこのファイルのルートの要素。"""
        return self.root.parent.members if self.root.parent is not None else self.root.members

    def _name_referencing_usages(self) -> None:
        """参照する usage（`perform generateTorque;`）は、参照先の宣言名を自分の名前として持つ
        （`torqueGenerator.generateTorque` で引ける。参照実装の effective name）。短い名前は持たない
        （`satisfy P::'R-010' by s;` のあとの `satisfy 'R-010' by s;` は解決しない）。"""
        pending = []

        def walk(scope: Scope) -> None:
            for member in scope.members:
                if member.referenced and not member.name:
                    pending.append(member)
                walk(member)

        for file_root in self.file_roots:
            walk(file_root)
        for scope in pending:
            status, found = self.resolve(scope.referenced, scope.parent or self.root, feature=True, exclude=scope)
            names = {self._dealias(f).name for f in found} if status == FOUND else set()
            if len(names) == 1 and None not in names:
                scope.name = names.pop()
        if pending:
            self._memo_cache.clear()  # 名前を付ける前の探索結果は古い

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
        if node_type == "metadata_usage" and not node.get("type_name") and isinstance(node.get("name"), str) \
                and split_qualified(node["name"]):  # エラー回復で名前が空になったものは除く
            # `@Safety;` / `metadata Tag about x;` の名前はメタデータの型への参照
            meta_name = split_qualified(node["name"])[-1]
            owner.metadata.append(meta_name)
            values = owner.metadata_values.setdefault(meta_name, {})
            for child in node.get("children") or []:
                value = child.get("value") if isinstance(child, dict) else None
                if isinstance(child.get("name") if isinstance(child, dict) else None, str) \
                        and isinstance(value, dict) and value.get("type") == "literal":
                    values[child["name"]] = value.get("value")
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
        if node_type == "accept_action" and isinstance(node.get("actionName"), str):
            name = node["actionName"]  # `action triggerResponse accept incomingInquiry : M;`
        identification = node.get("identification")
        if node_type in ("comment", "documentation", "doc") and isinstance(identification, dict):
            # `comment cmt /* ... */` の名前は identification の中（`comment c2 about cmt` で参照される）
            name = identification.get("name") if isinstance(identification.get("name"), str) else None
        referenced = _referenced_feature(node)
        if referenced:
            # `satisfy r by d;` / `perform x;` などは r・x を参照する usage。参照先から中身を
            # 継承するが、参照先の名前では引けない（同じファイルの `satisfy 'R-010' by s;` が
            # 前の行の `satisfy P::'R-010' by s;` に解決したりしない。参照実装で確認）
            name = None
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
        if referenced and referenced not in supertypes:
            supertypes.append(referenced)
        if not name and not short and not supertypes:
            self._build_children(node, owner)  # 透過
            return
        # 名前が無くても型付け・特化があれば名前空間（`require constraint : ML { in :>> limit; }`）。
        # 名前の無い要素は外からは名前で引けない
        element = Scope(node=node, name=_unquote(name) if name else None, short_name=_unquote(short) if short else None,
                        visibility=node.get("visibility") or _DEFAULT_VISIBILITY, parent=owner)
        if node_type == "alias":
            element.alias_target = node.get("target")
        if node_type == "param" and name and not node.get("type_name") and not node.get("redefines")                 and owner.supertypes and node.get("direction"):
            # 型付きの usage の本体の型なしの引数（`action focus : Focus { out item image; }`）は、
            # 型の同名の引数を暗黙に再定義し、その型を持つ（`focus.image.isWellFocused`）
            supertypes.append(name)
        element.supertypes = supertypes
        element.referenced = referenced
        if node.get("variability") == "variant" and (owner.node or {}).get("variability") == "variation":
            element.super_scopes.append(owner)  # `variation part def EC :> Engine { variant 'v6' { ... } }`
        if node_type == "message_usage" and isinstance(node.get("payload_name"), str):
            # `message m of fc : F` の fc は message のメンバー（`m.fc`）
            element.members.append(Scope(node=node, name=_unquote(node["payload_name"]), parent=element,
                                         supertypes=[node["type_name"]] if isinstance(node.get("type_name"), str) else []))
        if node_type == "accept_action" and isinstance(node.get("message"), str):
            # 受け取るもの（`accept incomingInquiry : M`）は accept のメンバー（`triggerResponse.incomingInquiry`）
            payload = Scope(node=node, name=_unquote(node["message"]), parent=element,
                            supertypes=[node["message_type"]] if isinstance(node.get("message_type"), str) else [])
            element.members.append(payload)
        if node_type == "objective_usage" and owner.supertypes:
            # 自分の objective は継承した objective を暗黙に再定義する（中で継承した objective の
            # メンバーを再定義できる。validation_09 の `verify x :>> massRequirement;`）
            element.supertypes.append(_OPAQUE_SUPERTYPE)
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
        for end_name, path in _named_ends(node):
            # `interface i : I connect x ::> a.p to ...` の x は接続のメンバー。型の端 x を再定義し、
            # a.p を部分集合にする（中の `connect y ::> x.q` の x.q は a.p のメンバー。held-out の
            # Vehicle_Example、2026-10-22）
            supertypes = [path]
            if isinstance(node.get("type_name"), str) and node["type_name"]:
                supertypes.append(f"{node['type_name'].lstrip('~')}::{end_name}")
            element.members.append(Scope(node={"type": "connection_end", "name": end_name}, name=end_name,
                                         parent=element, supertypes=supertypes))
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
        head = _chain_head(reference)
        if head != reference:
            # `a.b.c`（feature の連鎖）: 先頭を解決し、残りは型から外に見えるメンバーとしてたどる
            status, scopes = self.resolve(head, context, feature=feature, exclude=exclude)
            for name in _chain_tail(reference):
                if status != FOUND:
                    return status, []
                status, scopes = _merge(self._chain_member(self._dealias(s), name) for s in scopes)
            return status, scopes
        segments = split_qualified(reference.lstrip("~"))
        if not segments:
            return UNKNOWN, []
        if segments[0] == "$":  # `$::A` はルート（グローバルな名前空間）から
            segments = segments[1:]
            if not segments:
                return UNKNOWN, []
            context, exclude = self.root, None
            owned = [m for m in self.global_members if segments[0] in m.names()]
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
            # 自分自身は import の経路からも見つかりうる（参照する usage に参照先の名前を付けたため）
            found = [f for f in found if f is not exclude]
            if status == FOUND and found:
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
        記憶しなければ指数的に遅くなる。

        循環で打ち切ったところは「不明」を返す（誤ったエラーを出さない）。途中に打ち切りを
        含む結果も記憶する。打ち切りを含む結果を記憶しない作りでは、大きなモデル
        （held-out の sysml-v2-lsp/examples、146 KB）で指数的に遅くなった（2026-10-16）。
        """
        cached = self._memo_cache.get(key)
        if cached is not None:
            return cached
        if key in self._active:
            self._cycle_cuts += 1
            return UNKNOWN, []
        self._active.add(key)
        try:
            result = compute()
        finally:
            self._active.discard(key)
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
        if scope.super_scopes:
            direct = [self._visible_to_subtype(sup, name) for sup in scope.super_scopes]
            rest = self._inherited_by_name(scope, name, outside=outside)
            return _merge(direct + [rest])
        return self._inherited_by_name(scope, name, outside=outside)

    def _inherited_by_name(self, scope: Scope, name: str, *, outside: bool) -> Result:
        if not scope.supertypes:
            # 型（定義・usage）は暗黙にライブラリの型を特化する（Part・Action・Calculation など）。
            # その直接のメンバー（`result`・`start` など）は修飾名の先でも見えうる
            node_type = (scope.node or {}).get("type") or ""
            if scope.node is not None and node_type not in ("package", "root") \
                    and may_be_inherited_from_library(name, implicit=True):
                return UNKNOWN, []
            return NOT_FOUND, []
        context = scope.parent or self.root
        results: List[Result] = []
        library_status = UNKNOWN if may_be_inherited_from_library(name, implicit=False) else NOT_FOUND
        for reference in scope.supertypes:
            status, supers = self.resolve(reference, context, exclude=scope)
            if status == UNKNOWN:
                # 継承元が分からなければ中身も分からない。ただし、ライブラリの型から継承した
                # feature（`item b : Box { :>> length = 80 [cm]; }` の length）なら、その中身も
                # ライブラリの型の本体の名前に限られる
                head = split_qualified(reference)[0] if reference != _OPAQUE_SUPERTYPE else ""
                from_library = bool(head) and head not in self.external_names and not scope.metadata
                results.append((library_status, []) if from_library else (UNKNOWN, []))
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


_ABSENT = object()  # メタデータが無い、または値が書かれていない


def _metadata_value(scope: Scope, expression: dict):
    """`(as Safety).isMandatory` の値。メタデータか値が無ければ _ABSENT、判定できなければ None。"""
    base = expression.get("base") or {}
    if expression.get("type") != "member_access" or base.get("type") != "as_cast" or base.get("base") is not None \
            or not isinstance(base.get("type_name"), str) or not isinstance(expression.get("member"), str):
        return None
    if scope.library is not None:
        return None
    values = scope.metadata_values.get(split_qualified(base["type_name"])[-1])
    if values is None:
        return _ABSENT
    return values.get(expression["member"], _ABSENT)


def _filter_verdict(scope: Scope, expression: dict) -> Optional[bool]:
    """import の条件（`@Safety`、`@A and not @B`、`(as Safety).isMandatory == true`）を要素に当てる。

    判定できなければ None。メタデータの値の条件は、参照実装の Import_Filtered のラベルで確かめた
    意味だけを扱う: `(as M).f` は値が true のときだけ真、`(as M).f == v` は値が v と書かれている
    ときだけ真（メタデータや値が無ければ偽）。
    """
    kind = expression.get("type")
    value = _metadata_value(scope, expression)
    if value is not None:
        return value is True
    if kind == "binary_expr" and expression.get("op") == "==" and (expression.get("right") or {}).get("type") == "literal":
        left = _metadata_value(scope, expression.get("left") or {})
        if left is not None:
            return left is not _ABSENT and left == expression["right"].get("value")
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
                            "exhibit_state_usage", "include_use_case_usage", "require_usage"}


def _referenced_feature(node: dict) -> Optional[str]:
    """`satisfy r by d;`・`verify r;`・`perform x;`・`exhibit s;`・`include u;` が参照する先。"""
    node_type = node.get("type")
    if node_type == "feature_usage" and node.get("variability") == "variant" and isinstance(node.get("name"), str)             and not node.get("type_name") and not node.get("redefines"):
        # variation の中の `variant '6cylEngine';`（キーワードも型も無い形）は既存の usage を参照する
        return node["name"]
    if node_type in ("do_action", "entry_action", "exit_action") and isinstance(node.get("action_reference"), str)             and node["action_reference"] and not node.get("type_name"):
        # state の `do senseTemperature { out temp; }` は既存の action を参照する（`senseTemperature.temp`）
        return node["action_reference"]
    if node_type not in _REFERENCING_USAGE_TYPES:
        return None
    if isinstance(node.get("reference"), str) and node["reference"]:
        return _normalized_text(node, "reference")
    name = node.get("name")
    if not isinstance(name, str) or not name:
        return None
    # `exhibit a.b;`・`satisfy a.b by c;` の `.` は正規化で `::` になっている。元の区切りに戻す
    name = _normalized_text(node, "name") or name
    if node_type == "satisfy_requirement_usage" and node.get("declaresRequirement"):
        return None
    if extra_of(node, "referenceForm") or node_type == "require_usage":
        return name  # `verify r;`・`exhibit s;`・`require c;`（キーワード無しの形）は必ず参照
    if node.get("redefines"):
        return None  # `exhibit state s2 ::> s0;` の s2 は自分の名前
    # exhibit / verify は参照形かどうかが AST に残る（referenceForm）。include だけは区別できないので、
    # 型が無ければ参照とみなす
    if node_type == "satisfy_requirement_usage" or (node_type == "include_use_case_usage" and not node.get("type_name")):
        return name
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
            seen.append(_normalized_text(entry, "target") or entry["target"])
            # `part c :> a, b;` の 2 つ目以降（targets）
            seen.extend(t for t in entry.get("targets") or [] if isinstance(t, str) and t)
    out: List[str] = []
    for ref in seen:
        ref = ref.lstrip("~").strip()
        if ref and ref not in out:
            out.append(ref)
    return out


Reference = Tuple[str, str, dict, bool]  # (参照, 種類の名前, ノード, feature の位置か)


_KERML_CLASSIFIER_KINDS = ("datatype", "class", "struct", "classifier", "behavior", "function", "predicate",
                           "interaction", "assoc", "metaclass")


def _encloses(outer: Scope, scope: Optional[Scope]) -> bool:
    """outer が scope 自身か、scope を囲む名前空間か。"""
    while scope is not None:
        if scope is outer:
            return True
        scope = scope.parent
    return False


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
    if scope.library is not None and (library_index.member_kind(scope.library) or "alias") == "alias" \
            and not _is_package(scope):
        return None  # ライブラリの入れ子の要素・alias など、種類が分からない
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
            refs.append((_normalized_text(entry, "target") or entry["target"], "Feature", node, True))
    referenced = _referenced_feature(node)
    if referenced and (node_type in ("satisfy_requirement_usage", "require_usage") or node.get("reference")
                       or extra_of(node, "referenceForm")):
        # キーワードの有無が AST に残らない形（`include u;` など）は、宣言と区別できないので
        # 報告しない（参照として継承元を探すのには使う）
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
        trigger = node.get("trigger")
        if isinstance(trigger, dict) and not trigger.get("trigger_kind") and not trigger.get("type_name"):
            # `accept TaskAssigned` の型（after / when / at は型を持たない。`accept s : Sig` の Sig は
            # trigger のノードの type_name として確かめる）
            accepted = trigger.get("reference")
            if isinstance(accepted, str) and accepted and _chain_head(accepted) == accepted:
                refs.append((accepted, "Type", trigger, False))
    if node_type == "accept_action" and not node.get("after"):
        # `action r accept Sig via p;` の Sig、`accept s : Sig via p` の Sig（受け取るものの型）
        accepted = node.get("message_type") or node.get("message")
        if isinstance(accepted, str) and accepted and _chain_head(accepted) == accepted:
            refs.append((accepted, "Type", node, False))
    if node_type == "flow_usage" and isinstance(node.get("item_type"), str) and node["item_type"]:
        refs.append((node["item_type"], "Type", node, False))  # `flow f of Msg from ... to ...` の Msg
    if node_type == "alias" and isinstance(node.get("target"), str):
        refs.append((node["target"], "Element", node, False))
    return refs


def _expression_chain_kind(reference: str) -> str:
    """式の中の連鎖の先が無いときの、参照実装のメッセージの種類の語（2026-10-23 に確認）。

    `a.bx`（2 つ）は `Element`、3 つ以上（`a.b.nx`、`a.bx.c.m`）は `Feature`。値の式でも制約の式でも同じ。
    """
    return "Element" if len(_chain_tail(reference)) == 1 else "Feature"


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
# 式の木で呼び出しの形になる演算子（`(a and b) xor (c and d)` は function_call の xor になる）
_OPERATOR_NAMES = frozenset({"xor", "and", "or", "not", "implies", "if", "as", "meta", "hastype", "istype", "all"})


_IDENTIFIER_END = re.compile(r"[A-Za-z_]\w*$")
_IDENTIFIER_START = re.compile(r"[A-Za-z_]")


def _declared_names(tree) -> frozenset:
    """式の木の中で宣言されている名前（ラムダの本体の feature など）。"""
    names = set()

    def walk(node):
        if isinstance(node, list):
            for item in node:
                walk(item)
        elif isinstance(node, dict):
            if node.get("type") not in _REFERENCE_TYPES and node.get("type") != "name_ref" \
                    and isinstance(node.get("name"), str):
                names.add(node["name"])
            for value in node.values():
                if isinstance(value, (dict, list)):
                    walk(value)

    walk(tree)
    return frozenset(names)


def _chain_head(reference: str) -> str:
    """`a.b.c` → `a`、`A::B.c` → `A::B`（引用符の中の . は区切らない）。

    AST は引用符を外した名前を持つことがある（`DroneSpecification::'1.1'` →
    `DroneSpecification::1.1`）。そこで . の前後が識別子のときだけ連鎖の区切りとみなす。
    """
    quoted = False
    for i, ch in enumerate(reference):
        if ch == "'":
            quoted = not quoted
        elif (ch == "." and not quoted and _IDENTIFIER_END.search(reference[:i])
              and _IDENTIFIER_START.match(reference[i + 1:])):
            return reference[:i]
    return reference


def _path_segments(text: str) -> List[Tuple[Optional[str], str]]:
    """`A::b.c` → [(None, 'A'), ('::', 'b'), ('.', 'c')]（引用符の中の区切りは区切らない）。"""
    out: List[Tuple[Optional[str], str]] = []
    buf: List[str] = []
    sep: Optional[str] = None
    quoted = False
    i = 0
    while i < len(text):
        ch = text[i]
        if ch == "'":
            quoted = not quoted
            buf.append(ch)
        elif not quoted and (text.startswith("::", i) or ch == "."):
            out.append((sep, _unquote("".join(buf))))
            sep = "::" if ch == ":" else "."
            buf = []
            i += 2 if ch == ":" else 1
            continue
        else:
            buf.append(ch)
        i += 1
    out.append((sep, _unquote("".join(buf))))
    return [(s, n) for s, n in out if n]


def _segments_text(segments) -> Optional[str]:
    """connector_end の segments（[[名前, 直前の区切り], ...]）を元の書き方の文字列に戻す。"""
    parts = []
    for item in segments or []:
        if not isinstance(item, (list, tuple)) or len(item) != 2 or not isinstance(item[0], str):
            return None
        name = item[0] if re.fullmatch(r"[A-Za-z_]\w*", item[0]) else f"'{item[0]}'"
        parts.append((item[1] or "") + name)
    return "".join(parts) or None


def _normalized_text(node: dict, key: str) -> Optional[str]:
    """`::` に正規化された端の文字列から、元の区切りを取り戻す（`<key>_source` が無ければ元は `.`）。"""
    source = extra_of(node, f"{key}_source")
    if isinstance(source, str) and source:
        return source
    value = node.get(key)
    return value.replace("::", ".") if isinstance(value, str) and value else None


def _end_paths(node: dict, named_ends: bool = True) -> List[str]:
    """接続・束縛・flow・allocate・succession・message・satisfy の by の端（元の書き方の文字列）。

    named_ends=False は、端の名前の付いた端（`connect x ::> a.p to ...`）を除く。
    """
    return [text for text, _end in _end_entries(node, named_ends)]


def _end_entries(node: dict, named_ends: bool = True) -> List[Tuple[str, Optional[dict]]]:
    """_end_paths の端と、その端のノード（行を持つ `x ::> a.p` の端だけ。ほかは None）。"""
    out: List[Tuple[str, Optional[dict]]] = []
    end_nodes: Dict[int, dict] = {}

    def connector_end(end):
        if not isinstance(end, dict):
            return
        if "reference_subsetting" in end:
            text = _normalized_text(end["reference_subsetting"], "referenced_feature")
            if text:
                # 元の書き方は端の名前と演算子を含む（`x ::> a.nosuch` → `x::>a.nosuch`）
                stripped = _END_NAME_PREFIX.sub("", text)
                if stripped != text and not named_ends:
                    return
                text = stripped
                if extra_of(end["reference_subsetting"], "line") is not None:
                    end_nodes[len(out)] = end["reference_subsetting"]
        elif end.get("segments"):
            text = _segments_text(end["segments"])
        else:
            text = end.get("reference") if isinstance(end.get("reference"), str) else None
        if text:
            out.append((text, None))

    node_type = node.get("type")
    if node_type in _SUCCESSION_STATEMENTS:
        name = node.get("name")
        return [(name, None)] if isinstance(name, str) and name else []
    if node_type == "flow_from_stmt":  # action の中の `flow from a.x to b.y;`（区切りはそのまま）
        return [(node[key], None) for key in ("from_port", "to_port") if isinstance(node.get(key), str) and node[key]]
    if node_type in ("flow_usage", "message_usage"):
        for key in ("from_end", "to_end"):
            text = _normalized_text(node, key)
            if text:
                line = extra_of(node, f"{key}_line")
                if line is not None:
                    # 端の行を持つ、指摘の置き場所（flow の先頭と端が違う行のとき、参照実装は端の行に出す）
                    end_nodes[len(out)] = _with_extra({"type": "flow_end", "end": text}, {"line": line})
                out.append((text, None))
        return [(text, end_nodes.get(i)) for i, (text, _none) in enumerate(out)]
    if node_type in ("satisfy_requirement_usage", "verify_requirement_usage"):
        text = _normalized_text(node, "by")
        return [(text, None)] if text else []
    for key in ("from_end", "to_end", "firstEnd", "thenEnd", "leftEnd", "rightEnd"):
        connector_end(node.get(key))
    for end in node.get("ends") or []:
        connector_end(end)
    for key in ("interface_part", "connector_part"):
        part = node.get(key)
        if isinstance(part, dict):
            connector_end(part.get("from_end"))
            connector_end(part.get("to_end"))
    return [(text, end_nodes.get(i)) for i, (text, _none) in enumerate(out)]


_END_NAME_PREFIX = re.compile(r"^\s*(?P<name>[A-Za-z_]\w*|'(?:[^'\\]|\\.)*')\s*(?:::>|references)\s*")


def _named_ends(node: dict) -> List[Tuple[str, str]]:
    """接続の端の名前と、その端が部分集合にする feature（`connect x ::> a.p to y ::> b.q` → (x, a.p), (y, b.q)）。"""
    out: List[Tuple[str, str]] = []
    for key in ("interface_part", "connector_part"):
        part = node.get(key)
        if not isinstance(part, dict):
            continue
        for side in ("from_end", "to_end"):
            end = part.get(side)
            subsetting = end.get("reference_subsetting") if isinstance(end, dict) else None
            text = _normalized_text(subsetting, "referenced_feature") if isinstance(subsetting, dict) else None
            match = _END_NAME_PREFIX.match(text) if text else None
            if match and text[match.end():]:
                out.append((_unquote(match.group("name")), text[match.end():]))
    for end in node.get("ends") or []:
        # n 項の接続（`connect (x ::> a.p, y ::> b.q)`。held-out の Arrowhead_Framework_Example）
        if isinstance(end, dict) and isinstance(end.get("declared_name"), str) and end["declared_name"]:
            path = _segments_text(end.get("segments")) or end.get("reference")
            if isinstance(path, str) and path:
                out.append((_unquote(end["declared_name"]), path))
    return out

# `first a then b;` / `then b;` の参照先（端と同じく、外側の型の feature を指せない）
_SUCCESSION_STATEMENTS = frozenset({"then_stmt", "first_stmt"})


def inaccessible_features(ast: dict, external_names: Optional[Iterable[str]] = None,
                          other_asts: Sequence[dict] = ()) -> List[Tuple[dict, str]]:
    """参照実装の `Must be an accessible feature (use dot notation for nesting)` に当たる参照。

    2026-10-16 に参照実装で境界を確かめた規則:

    - 接続の端（connect / bind / flow / allocate / interface / succession / message、satisfy の by）で、
      `::` の左が型（定義でも usage でも）、右が feature（`a::engine`、`Vehicle::engine`）。
    - 特化・部分集合の先で、`::` の左が usage（`part x :> vehicle::engine;`）。再定義（`:>>`）と、
      左が定義のもの（`:> Vehicle::wheel`）は通る。
    - 接続の端の単純名が、接続を持つ型ではなく、それを囲む外側の型の feature
      （`part sub { connect a to b; }` の a・b）。値の式（`part a2 = a;`）は通る。

    戻り値: (ノード, 問題の参照)。解決できない参照は扱わない（unresolved_references が出す）。
    """
    resolver = ScopeResolver(ast, external_names, other_asts)
    out: List[Tuple[dict, str]] = []

    def is_type(scope: Scope) -> bool:
        return scope.library is None and not _is_package(scope) and (scope.node or {}).get("type") != "root"

    def is_feature(scope: Scope) -> bool:
        return not _is_definition(scope) and not _is_package(scope) and (scope.node or {}).get("type") != "root"

    def colon_violation(text: str, context: Scope, *, end: bool):
        """`::` で feature をたどっていれば、その左の要素（定義なら Scope、usage なら "usage"）。"""
        segments = _path_segments(text)
        if len(segments) < 2 or not any(sep == "::" for sep, _ in segments):
            return None
        status, current = resolver._resolve_first(segments[0][1], context)
        for sep, name in segments[1:]:
            if status != FOUND:
                return None
            qualifiers = [resolver._dealias(s) for s in current]
            status, current = _merge(resolver._chain_member(q, name) if sep == "." else
                                     resolver._visible_from_outside(q, name) for q in qualifiers)
            if sep != "::" or status != FOUND:
                continue
            targets = [resolver._dealias(s) for s in current]
            # 列挙の値（`E::e2`）は feature のアクセスではない
            if not targets or not all(is_feature(t) and t.library is None
                                      and (t.node or {}).get("type") != "enum_literal" for t in targets):
                continue
            # 参照を囲む型自身のメンバー（`occurrence def <PRJ> P { ... x = PRJ::company; }`）は通る
            # （参照実装で確認、2026-10-23。sysmod の `stakeholder :>> c = PRJ::logisticCompany;`）
            if any(_encloses(q, context) for q in qualifiers):
                continue
            if all(is_type(q) and not _is_definition(q) for q in qualifiers):
                return "usage"
            if end and all(is_type(q) for q in qualifiers) and len(qualifiers) == 1:
                return qualifiers[0]
        return None

    def outer_feature(name: str, context: Scope) -> bool:
        if not is_type(context):
            return False
        scope: Optional[Scope] = context
        while scope is not None:
            status, found = resolver._visible_inside(scope, name)
            if status == FOUND:
                if scope is context or not is_type(scope):
                    return False
                return all(is_feature(resolver._dealias(f)) for f in found)
            if status == UNKNOWN:
                return False
            scope = scope.parent
        return False

    def across_definition(name: str, context: Scope) -> bool:
        """値の式の名前が、入れ子の定義の外側にある型の feature に解決するか。

        `part def Frigate { part pilot; occurrence def Seq2 { ref part p2 = pilot; } }` は NG、
        Seq2 が usage（`occurrence seq3 { ... }`）なら通る（2026-10-16、probe BH-19c で確認）。
        """
        crossed = False
        scope: Optional[Scope] = context
        while scope is not None:
            status, found = resolver._visible_inside(scope, name)
            if status == FOUND:
                return crossed and is_type(scope) and all(
                    is_feature(resolver._dealias(f)) and (f.node or {}).get("type") != "enum_literal" for f in found)
            if status == UNKNOWN:
                return False
            if _is_definition(scope):
                crossed = True
            scope = scope.parent
        return False

    def visit(node, owner: Scope):
        if isinstance(node, list):
            for item in node:
                visit(item, owner)
            return
        if not isinstance(node, dict):
            return
        element = resolver.element_of.get(id(node))
        if node.get("type") == "name_ref" and isinstance(node.get("reference"), str):
            head = _path_segments(_chain_head(node["reference"]))
            if len(head) == 1 and head[0][1] not in _FLOW_CONTEXT_NAMES | _EXPRESSION_KEYWORDS \
                    and across_definition(head[0][1], owner):
                out.append((node, head[0][1]))
        # interface_part / connector_part の端は、それを持つ interface / allocation（の所有者の文脈）で扱う
        own_ends = [] if node.get("type") in ("binary_interface_part", "binary_connector_part") else _end_paths(node)
        found: List[Tuple[str, object]] = []
        for text in own_ends:
            segments = _path_segments(text)
            if not segments or segments[0][1] in _FLOW_CONTEXT_NAMES:
                continue
            violation = colon_violation(text, owner, end=True)
            if violation is None and not any(sep == "::" for sep, _ in segments):
                # message の端は、入れ子の usage の中なら外側の feature を指せる（入れ子の定義の中は不可）。
                # connect・flow・succession などは入れ子の usage の中でも不可（2026-10-16 参照実装で確認）
                outer = across_definition if node.get("type") == "message_usage" else outer_feature
                if outer(segments[0][1], owner):
                    violation = "outer"
            if violation is not None:
                found.append((text, violation))
        # 両端が同じ定義の feature（`allocate Car::tank to Car::engine;`）は参照実装でも通る
        # （verified/connections。別々の定義 `Car::tank to Eng::engine` はエラー）
        qualifiers = {id(v) for _t, v in found if isinstance(v, Scope)}
        if len(found) == len(own_ends) >= 2 and len(qualifiers) == 1 \
                and all(isinstance(v, Scope) for _t, v in found):
            found = []
        out.extend((node, text) for text, _v in found)
        for entry in node.get("redefines") or []:
            if isinstance(entry, dict) and entry.get("kind") in ("subsets", "references") \
                    and isinstance(entry.get("target"), str):
                source = _normalized_text(entry, "target")
                if source and colon_violation(source, owner, end=False) == "usage":
                    out.append((node, source))
        name_source = extra_of(node, "name_source")
        if isinstance(name_source, str) and node.get("type") == "satisfy_requirement_usage" \
                and colon_violation(name_source, owner, end=False) == "usage":
            out.append((node, name_source))
        inner = element or owner
        for key, value in node.items():
            if key != "type" and isinstance(value, (dict, list)):
                visit(value, inner)

    visit(ast, resolver.root)
    return out


# 端の先頭に来うる文脈の名前（`this.x`）。どこを指すかを確かめない
_FLOW_CONTEXT_NAMES = frozenset({"this", "that", "self"})


# --- 段階 C: 解決結果を使う種類の判定 ---------------------------------------------------
#
# 参照実装の SysMLValidator.checkAllTypes / checkOneType を写す。usage の「すべての型」
# （明示の型付けと、部分集合・再定義の先から継承した型）が、usage の種類ごとに決まった
# メタクラスのインスタンスであること。解決できない型は代理（proxy）として残り、どの
# メタクラスにも当たらないので、型が未解決なら種類のエラーも連鎖して出る（実測どおり）。

# 定義の種類 → その定義が当たるメタクラス（参照実装の型階層のうち、判定に使うもの）。
# KerML の階層: Behavior は Class、Function は Behavior、Predicate は Function。
# action def は Behavior、calc def は Function、constraint def・requirement def は Predicate。
_CLASS = frozenset({"Classifier", "Class"})
_BEHAVIOR = _CLASS | {"Behavior", "ActionDef"}
_FUNCTION = _BEHAVIOR | {"Function", "CalcDef"}
_PREDICATE = _FUNCTION | {"Predicate", "ConstraintDef"}
_PART = _CLASS | {"ItemDef", "PartDef"}
_CONNECTION = _PART | {"Association", "ConnectionDef"}
_CASE = _FUNCTION | {"CaseDef"}
_DEF_CLASSES: Dict[str, frozenset] = {
    "attribute_def": frozenset({"Classifier", "DataType"}),
    "enum_def": frozenset({"Classifier", "DataType", "Enumeration"}),
    "occurrence_def": _CLASS,
    "individual_def": _CLASS | {"IndividualDef"},
    "item_def": _CLASS | {"ItemDef"},
    "part_def": _PART,
    "port_def": _CLASS | {"PortDef"},
    "metadata_def": _CLASS | {"ItemDef", "Metaclass"},
    "connection_def": _CONNECTION,
    "interface_def": _CONNECTION | {"InterfaceDef"},
    "allocation_def": _CONNECTION | {"AllocationDef"},
    "flow_def": _CONNECTION | _BEHAVIOR | {"Interaction"},
    "action_def": _BEHAVIOR,
    "activity_def": _BEHAVIOR,
    "state_def": _BEHAVIOR | {"StateDef"},
    "calculation_def": _FUNCTION,
    "constraint_def": _PREDICATE,
    "requirement_def": _PREDICATE | {"RequirementDef"},
    "concern_def": _PREDICATE | {"RequirementDef"},
    "viewpoint_def": _PREDICATE | {"RequirementDef", "ViewpointDef"},
    "case_def": _CASE,
    "analysis_case_def": _CASE | {"AnalysisCaseDef"},
    "verification_case_def": _CASE | {"VerificationCaseDef"},
    "use_case_def": _CASE | {"UseCaseDef"},
    "view_def": _PART | {"ViewDef"},
    "rendering_def": _PART | {"RenderingDef"},
}

# 標準ライブラリの宣言の種類（索引の `attribute def` など）→ 上の定義の種類。KerML の
# 宣言は分かるものだけ（datatype・struct・metaclass）。それ以外（function・behavior・
# assoc・alias など）は種類が分からないので判定しない
_LIBRARY_DEF_KINDS = {
    "attribute": "attribute_def", "enum": "enum_def", "occurrence": "occurrence_def", "item": "item_def",
    "part": "part_def", "port": "port_def", "metadata": "metadata_def", "connection": "connection_def",
    "interface": "interface_def", "allocation": "allocation_def", "flow": "flow_def", "action": "action_def",
    "state": "state_def", "calc": "calculation_def", "constraint": "constraint_def",
    "requirement": "requirement_def", "concern": "concern_def", "case": "case_def",
    "analysis": "analysis_case_def", "verification": "verification_case_def", "use": "use_case_def",
    "view": "view_def", "viewpoint": "viewpoint_def", "rendering": "rendering_def",
}
# KerML の宣言（索引の種類の最後の語）→ メタクラス
_LIBRARY_KERML_CLASSES: Dict[str, frozenset] = {
    "datatype": _DEF_CLASSES["attribute_def"],
    "classifier": frozenset({"Classifier"}),
    "class": _CLASS,
    "struct": _CLASS,
    "behavior": _CLASS | {"Behavior"},
    "function": _CLASS | {"Behavior", "Function"},
    "predicate": _CLASS | {"Behavior", "Function", "Predicate"},
    "interaction": _CLASS | {"Behavior", "Association", "Interaction"},
    "assoc": frozenset({"Classifier", "Association"}),
    "metaclass": _CLASS | {"Metaclass"},
}
_LIBRARY_USAGE_WORDS = frozenset({
    "attribute", "part", "item", "port", "action", "occurrence", "calc", "constraint", "requirement",
    "connection", "interface", "allocation", "flow", "state", "view", "rendering", "feature", "step", "expr",
})

# usage の種類 → (求めるメタクラス, 参照実装のメッセージ, 型はちょうど 1 つか)
_USAGE_TYPE_RULES: Dict[str, Tuple[str, str, bool]] = {}


def _usage_rule(types: Iterable[str], required: str, message: str, one: bool = False) -> None:
    for usage_type in types:
        _USAGE_TYPE_RULES[usage_type] = (required, message, one)


_usage_rule(["attribute_usage"], "DataType", "An attribute must be typed by attribute definitions.")
_usage_rule(["enum_usage"], "Enumeration", "An enumeration must be typed by one enumeration definition.", True)
_usage_rule(["part_instance", "item_usage", "occurrence_usage", "portion_usage",
             "event_occurrence_usage"], "Class",
            "An occurrence, item or part must be typed by occurrence definitions.")
_usage_rule(["port_usage"], "PortDef", "A port must be typed by port definitions.")
_usage_rule(["connection_usage"], "Association", "A connection must be typed by connection definitions.")
_usage_rule(["interface_usage"], "InterfaceDef", "An interface must be typed by interface definitions.")
_usage_rule(["allocation_usage"], "AllocationDef", "An allocation must be typed by allocation definitions.")
# message の `of E` は運ぶものの型（AST では type_name）で、message 自身の型ではないので見ない
_usage_rule(["flow_usage"], "Interaction",
            "A flow connection must be typed by flow connection definitions.")
_usage_rule(["individual_usage"], "IndividualDef", "An individual must be typed by one individual definition.", True)
_usage_rule(["action_usage", "perform_action"], "Behavior", "An action must be typed by action definitions.")
_usage_rule(["state_usage", "exhibit_state_usage"], "Behavior", "A state must be typed by state definitions.")
_usage_rule(["calculation_usage"], "Function", "A calculation must be typed by one calculation definition.", True)
_usage_rule(["constraint_usage", "assert_constraint_usage"], "Predicate",
            "A constraint must be typed by one constraint definition.", True)
_usage_rule(["requirement_usage", "concern_usage", "satisfy_requirement_usage", "verify_requirement_usage"],
            "RequirementDef",
            "A requirement must be typed by one requirement definition.", True)
_usage_rule(["case_usage"], "CaseDef", "A case must be typed by one case definition.", True)
_usage_rule(["analysis_case_usage"], "AnalysisCaseDef",
            "An analysis case must be typed by one analysis case definition.", True)
_usage_rule(["verification_case_usage"], "VerificationCaseDef",
            "A verification case must be typed by one verification case definition.", True)
_usage_rule(["use_case_usage", "include_use_case_usage"], "UseCaseDef",
            "A use case must be typed by one use case definition.", True)
_usage_rule(["view_usage"], "ViewDef", "A view must be typed by one view definition.", True)
_usage_rule(["viewpoint_usage"], "ViewpointDef", "A viewpoint must be typed by one viewpoint definition.", True)
_usage_rule(["rendering_usage"], "RenderingDef", "A rendering must be typed by one rendering definition.", True)
_usage_rule(["metadata_usage"], "Metaclass", "A metadata usage must be typed by one metadata definition.", True)
_usage_rule(["feature_usage", "subject_usage", "actor_usage", "stakeholder_usage"], "Classifier",
            "A usage must be typed by definitions.")
# 引数（`in item x : T`）は書いたキーワードで決まる
_PARAM_KIND_TYPES = {"attribute": "attribute_usage", "item": "item_usage", "part": "part_instance",
                     "port": "port_usage", "action": "action_usage", "occurrence": "occurrence_usage"}

_PROXY = "proxy"  # 解決できない型（参照実装では代理のまま残り、どのメタクラスにも当たらない）


def _classes_of(scope: Scope) -> Optional[frozenset]:
    """定義が当たるメタクラスの集合。usage なら空集合、分からなければ None。"""
    if scope.library is not None:
        if library_index.is_library_package(scope.library):
            return frozenset()
        kind = library_index.member_kind(scope.library)
        if not kind:
            return None
        words = kind.split()
        if "def" in words:
            index = words.index("def")
            return _DEF_CLASSES.get(_LIBRARY_DEF_KINDS.get(words[index - 1] if index else "", ""))
        kerml = [w for w in words if w in _LIBRARY_KERML_CLASSES]
        if kerml:  # `assoc struct` は両方
            return frozenset().union(*(_LIBRARY_KERML_CLASSES[w] for w in kerml))
        last = words[-1] if words else ""
        if last in _LIBRARY_USAGE_WORDS:
            return frozenset()
        return None
    node_type = (scope.node or {}).get("type") or ""
    if node_type.endswith("_def"):
        classes = _DEF_CLASSES.get(node_type)
        if classes is not None and (scope.node or {}).get("isIndividual"):
            classes = classes | {"IndividualDef"}  # `individual part def Thing;`
        return classes
    return frozenset()  # usage・パッケージは定義ではない


def _usage_rule_of(node: dict) -> Optional[Tuple[str, str, bool]]:
    node_type = node.get("type") or ""
    if node_type in ("param", "calc_parameter"):
        kind = node.get("kind")
        node_type = _PARAM_KIND_TYPES.get(kind, "feature_usage") if isinstance(kind, str) or kind is None \
            else "feature_usage"
    return _USAGE_TYPE_RULES.get(node_type)


def kind_violations(ast: dict, external_names: Optional[Iterable[str]] = None,
                    other_asts: Sequence[dict] = ()) -> List[Tuple[dict, str]]:
    """usage の型の種類と、perform / exhibit / satisfy の参照先の種類の誤り: (ノード, 参照実装のメッセージ)。"""
    resolver = ScopeResolver(ast, external_names, other_asts)
    out: List[Tuple[dict, str]] = []
    cache: Dict[int, Optional[List[object]]] = {}

    def all_types(node: dict, owner: Scope, depth: int = 0) -> Optional[List[object]]:
        """usage のすべての型（Scope か _PROXY）。分からない型が混ざれば None。"""
        key = id(node)
        if key in cache:
            return cache[key]
        cache[key] = None  # 循環への備え
        types: List[object] = []
        explicit = [t for t in [node.get("type_name")] + list(node.get("type_names") or [])
                    if isinstance(t, str) and t]
        for reference in dict.fromkeys(explicit):
            status, found = resolver.resolve(reference.lstrip("~"), owner)
            if status == NOT_FOUND:
                types.append(_PROXY)
            elif status == FOUND:
                types.extend(resolver._dealias(f) for f in found)
            else:
                return None
        element = resolver.element_of.get(id(node))
        inherited_from = [_normalized_text(entry, "target") or entry["target"] for entry in node.get("redefines") or []
                          if isinstance(entry, dict) and entry.get("kind") in ("redefines", "subsets")
                          and isinstance(entry.get("target"), str)]
        referenced = _referenced_feature(node) or (
            node.get("name") if node.get("type") == "event_occurrence_usage" and node.get("isReference") else None)
        if referenced and not inherited_from:
            inherited_from.append(referenced)  # 参照する usage は参照先の型を持つ
        for target in inherited_from:
            if depth > 5:
                return None
            status, found = resolve_path(target, owner, element)
            if status != FOUND:
                return None
            for feature in found:
                feature = resolver._dealias(feature)
                if feature.library is not None or feature.node is None:
                    return None
                inherited = all_types(feature.node, feature.parent or resolver.root, depth + 1)
                if inherited is None:
                    return None
                types.extend(inherited)
        cache[key] = types
        return types

    def resolve_path(text: str, owner: Scope, exclude: Optional[Scope]) -> Result:
        """`a`・`a.b.c`・`P::a` を最後の要素まで解決する（feature の位置）。"""
        segments = _path_segments(text)
        if not segments:
            return UNKNOWN, []
        head = segments[0][1]
        index = 1
        while index < len(segments) and segments[index][0] == "::":
            head = f"{head}::{segments[index][1]}"
            index += 1
        status, found = resolver.resolve(head, owner, feature=True, exclude=exclude)
        for _sep, name in segments[index:]:
            if status != FOUND:
                return status, []
            status, found = _merge(resolver._chain_member(resolver._dealias(f), name) for f in found)
        if status == FOUND and not all(is_feature_scope(resolver._dealias(f)) for f in found):
            return UNKNOWN, []  # 定義などを指す誤りは未解決参照・参照先の種類の規則が扱う
        return status, found

    def is_feature_scope(scope: Scope) -> bool:
        return scope.library is None and scope.node is not None and not _is_definition(scope) \
            and not _is_package(scope)

    def check_ends(node: dict, owner: Scope) -> None:
        """接続・束縛・flow の端の feature の型が解決できない（参照実装は端の行にも出す）。"""
        if node.get("type") in ("binary_interface_part", "binary_connector_part", "satisfy_requirement_usage",
                                "verify_requirement_usage"):
            return  # satisfy / verify の by は接続の端ではない
        if node.get("type") in ("connection_usage", "interface_usage", "allocation_usage") \
                and isinstance(node.get("type_name"), str):
            # 型付きの接続は型の定義の端（`end bead : TireBead;`）を暗黙に再定義する
            status, found = resolver.resolve(node["type_name"].lstrip("~"), owner)
            for definition in (resolver._dealias(f) for f in found) if status == FOUND else []:
                for end in definition.members:
                    if (end.node or {}).get("type") == "connection_end_member":
                        types = all_types(end.node, definition)
                        if types and any(t is _PROXY for t in types):
                            out.append((node, "A usage must be typed by definitions."))
                            return
        # 端の名前の付いた端（`connect x ::> a.p to ...`）は、参照実装は端の行に端の種類の
        # メッセージ（`A port must be typed by port definitions.`）を出す。AST に端の行が
        # 無いので出さない（行の違う指摘は、見逃しと誤検出の両方になる）
        for text in _end_paths(node, named_ends=False):
            status, found = resolve_path(text, owner, None)
            if status != FOUND:
                continue
            for feature in found:
                feature = resolver._dealias(feature)
                types = all_types(feature.node, feature.parent or resolver.root)
                if types and any(t is _PROXY for t in types):
                    out.append((node, "A usage must be typed by definitions."))
                    return

    def explicit_types(node: dict) -> int:
        return len(dict.fromkeys(t for t in [node.get("type_name")] + list(node.get("type_names") or [])
                                 if isinstance(t, str) and t))

    def check_usage(node: dict, owner: Scope) -> None:
        rule = _usage_rule_of(node)
        if rule is None or node.get("type") == "metadata_usage" and not node.get("type_name"):
            return
        required, message, one = rule
        types = all_types(node, owner)
        if types is None and required != "IndividualDef":
            # 継承した型が分からなくても、明示の型が 1 つでも種類違いなら checkAllTypes は満たされない
            # （`attribute heat : Heat :>> payload;` の Heat が item def）
            for reference in dict.fromkeys(t for t in [node.get("type_name")] + list(node.get("type_names") or [])
                                           if isinstance(t, str) and t):
                status, found = resolver.resolve(reference.lstrip("~"), owner)
                classes = [_classes_of(resolver._dealias(f)) for f in found] if status == FOUND else []
                if classes and all(c is not None and required not in c for c in classes):
                    out.append((node, message))
                    return
            return
        if not types:
            return  # 型が無い（暗黙の型）
        if any(t is _PROXY for t in types[:explicit_types(node)]):
            # 自分の型が解決できない。参照実装はここでも種類のエラーを重ねて出すが、原因は同じ
            # 要素の未解決参照（_check_scoped_references）なので重ねない（compare.py は連鎖として数える）
            return
        if required == "IndividualDef":
            # individual は「型のうち individual def がちょうど 1 つ」（ほかの型が混ざってもよい。
            # 2 つ以上は参照実装が別のメッセージ `At most one individual definition` を出す）
            known = [_classes_of(t) for t in types if t is not _PROXY]
            if any(c is None for c in known):
                return
            if not any(required in c for c in known):
                out.append((node, message))
            return
        verdicts = []
        for t in types:
            classes = None if t is _PROXY else _classes_of(t)
            if t is _PROXY:
                verdicts.append(False)
            elif classes is None:
                return  # 種類の分からない型が混ざれば判定しない
            else:
                verdicts.append(required in classes)
        if not all(verdicts) or (one and explicit_types(node) > 1):
            out.append((node, message))

    def check_metadata(node: dict, owner: Scope) -> None:
        if (node.get("type") or "").endswith("_stmt"):
            return  # 包みの文（special_stmt など）は中の要素と同じ前置メタデータを持つ
        names = [m for m in node.get("prefixMetadata") or [] if isinstance(m, str)]
        if node.get("type") == "metadata_usage" and not node.get("type_name") and isinstance(node.get("name"), str):
            names.append(node["name"])
        for name in names:
            status, found = resolver.resolve(name, owner)
            targets = [resolver._dealias(f) for f in found] if status == FOUND else []
            if targets and all(is_abstract(t) for t in targets):
                out.append((node, "Must have a concrete type"))
                return
            if (status == FOUND and all(
                    (_classes_of(resolver._dealias(f)) is not None
                     and "Metaclass" not in (_classes_of(resolver._dealias(f)) or ())) for f in found)):
                out.append((node, "A metadata usage must be typed by one metadata definition."))
                return

    def check_reference(node: dict, owner: Scope, element: Optional[Scope]) -> None:
        node_type = node.get("type")
        referenced = _referenced_feature(node)
        if not referenced or node_type not in ("perform_action", "exhibit_state_usage", "satisfy_requirement_usage"):
            return
        if node_type != "satisfy_requirement_usage" and not (node.get("reference") or extra_of(node, "referenceForm")):
            return
        required, message = {
            "perform_action": ("action_usage", "Must reference an action."),
            "exhibit_state_usage": ("state_usage", "Must reference a state."),
            "satisfy_requirement_usage": ("requirement_usage", "Must reference a requirement."),
        }[node_type]
        if _chain_head(referenced) != referenced:
            return  # 連鎖の先の種類はここでは見ない
        status, found = resolver.resolve(referenced, owner, feature=True, exclude=element)
        if status != FOUND:  # 解決できないものは未解決参照の指摘が出る（参照実装の連鎖は compare.py で数える）
            return
        kinds = {(resolver._dealias(f).node or {}).get("type") for f in found}
        allowed = {
            "action_usage": {"action_usage", "perform_action", "accept_action", "send_action", "calculation_usage",
                             "state_usage", "exhibit_state_usage", "case_usage", "analysis_case_usage",
                             "verification_case_usage", "use_case_usage", "include_use_case_usage"},
            "state_usage": {"state_usage", "exhibit_state_usage"},
            "requirement_usage": {"requirement_usage", "concern_usage", "satisfy_requirement_usage",
                                  "viewpoint_usage", "objective_usage"},
        }[required]
        if all(resolver._dealias(f).library is None for f in found) and not kinds & allowed and None not in kinds:
            out.append((node, message))

    def is_abstract(scope: Scope) -> bool:
        if scope.library is not None:
            return "abstract" in (library_index.member_kind(scope.library) or "").split()
        return bool((scope.node or {}).get("isAbstract"))

    def visit(node, owner: Scope):
        if isinstance(node, list):
            for item in node:
                visit(item, owner)
            return
        if not isinstance(node, dict):
            return
        element = resolver.element_of.get(id(node))
        if element is not None or node.get("type") in ("param", "calc_parameter"):
            check_usage(node, owner)
        check_metadata(node, owner)
        check_reference(node, owner, element)
        check_ends(node, owner)
        inner = element or owner
        for key, value in node.items():
            if key != "type" and isinstance(value, (dict, list)):
                visit(value, inner)

    visit(ast, resolver.root)
    return out


def unresolved_references(ast: dict, external_names: Optional[Iterable[str]] = None,
                          other_asts: Sequence[dict] = ()) -> List[Tuple[dict, str, str]]:
    """解決できないと言い切れる参照: (ノード, 参照, 種類の名前)。"""
    resolver = ScopeResolver(ast, external_names, other_asts)
    out: List[Tuple[dict, str, str]] = []

    def visit(node, owner: Scope, local_names: frozenset, local_types: Optional[Dict[str, str]] = None):
        local_types = local_types or {}
        if isinstance(node, list):
            for item in node:
                visit(item, owner, local_names, local_types)
            return
        if not isinstance(node, dict):
            return
        element = resolver.element_of.get(id(node))
        param = node.get("param")
        if node.get("type") == "arrow_lambda" and isinstance(param, dict) and isinstance(param.get("name"), str):
            local_names = local_names | {param["name"]}  # `{in p; p.m}` の p
            if isinstance(param.get("typeName"), str) and param["typeName"]:
                # 型のある引数（`{in ref w : WheelAssy; w.wheel.outerDiameter ...}`）は、連鎖を型から確かめる
                local_types = {**local_types, param["name"]: param["typeName"]}
        if node.get("type") == "arrow_lambda":
            # 本体の中で宣言した名前（`{in i; private thisSample : T = ...; ... thisSample.t ...}`）
            local_names = local_names | _declared_names([node.get("body"), node.get("children")])
        trigger = node.get("trigger")
        if isinstance(trigger, dict) and trigger.get("type_name") and isinstance(trigger.get("reference"), str):
            local_names = local_names | {trigger["reference"]}  # `accept sig : Sig if sig.on` の sig
        if node.get("type") == "accept_action" and isinstance(node.get("message"), str) and node.get("message_type"):
            # state の本体の `accept cl : T via p do action { ... cl.itms ... }` は、AST では do の action が
            # accept の子になる。受け取るもの cl を子から見えるようにする（参照実装では遷移のメンバー。
            # Arrowhead_Framework_Example の AHFNorwayTopics）
            local_names = local_names | {node["message"]}
        if node.get("type") in ("function_call", "new_instance", "arrow_call", "arrow_lambda") \
                and isinstance(node.get("name"), str):
            # 式の中の呼び出し・インスタンス生成の名前（`Velocity(dt, v)`、`new Publish(t, p)`、
            # `xs->forAll {...}`・`xs->size()`）。参照実装は import していないライブラリの関数
            # （`sqrt(2.0)`、`->forAll` の ControlFunctions::forAll）も未解決にする（2026-10-23 に確認）
            called = node["name"]
            if called and _chain_head(called) == called and split_qualified(called)[0] not in local_names \
                    and called not in _OPERATOR_NAMES:
                status, _found = resolver.resolve(called, owner)
                if status == NOT_FOUND:
                    out.append((node, called, "Element"))
        if node.get("type") == "name_ref" and isinstance(node.get("reference"), str):
            # 式の中の名前（`[kg]`、`noSuch == true`、`d.m` の d）。連鎖は先頭だけ確かめる
            first = _chain_head(node["reference"])
            if first in local_types and first != node["reference"]:
                status, types = resolver.resolve(local_types[first], owner)
                if status == FOUND:
                    missing = resolver.missing_chain_member(types, _chain_tail(node["reference"]))
                    if missing:
                        out.append((node, missing, _expression_chain_kind(node["reference"])))
            elif first and split_qualified(first)[0] not in local_names | _EXPRESSION_KEYWORDS:
                status, found = resolver.resolve(first, owner, feature=True)
                if status == NOT_FOUND:
                    out.append((node, first, "Element"))
                elif status == FOUND:
                    missing = resolver.missing_chain_member(found, _chain_tail(node["reference"]))
                    if missing:
                        out.append((node, missing, _expression_chain_kind(node["reference"])))
        if node.get("type") not in ("binary_interface_part", "binary_connector_part"):
            # 接続・allocate・satisfy の by などの端の連鎖（`a.b.c`）。`::` を含む端はアクセス範囲の
            # 判定（inaccessible_features）に任せ、ここでは `.` だけの連鎖を確かめる
            for text, end_node in _end_entries(node):
                segments = _path_segments(text)
                if not segments or any(sep == "::" for sep, _ in segments) \
                        or segments[0][1] in _FLOW_CONTEXT_NAMES:
                    continue
                at = end_node if end_node is not None else node  # 端の行に出す（`x ::> a.p` の端）
                status, found = resolver.resolve(segments[0][1], owner, feature=True)
                if status == NOT_FOUND and node.get("type") not in _SUCCESSION_STATEMENTS:
                    # 端の先頭の名前が無い（`connect a.p to nob.p;` の nob、`connect a to nob2;`）。
                    # 参照実装は先頭を出す（先の `.p` も重ねて出すが、同じ行・同じ種類）
                    out.append((at, segments[0][1], "Feature"))
                elif status == FOUND and len(segments) > 1:
                    missing = resolver.missing_chain_member(found, [name for _sep, name in segments[1:]])
                    if missing:
                        out.append((at, missing, "Feature"))
        referenced = _referenced_feature(node)
        if referenced and _chain_head(referenced) != referenced and (
                node.get("type") in ("satisfy_requirement_usage", "require_usage") or node.get("reference")
                or extra_of(node, "referenceForm")):
            # 参照の連鎖（`perform transportTask.receiveCommand;`）: 先頭と 2 番目以降を確かめる
            head = _chain_head(referenced)
            status, found = resolver.resolve(head, owner, feature=True, exclude=element)
            if status == NOT_FOUND:
                out.append((node, head, "Feature"))
            elif status == FOUND:
                missing = resolver.missing_chain_member(found, _chain_tail(referenced))
                if missing:
                    out.append((node, missing, "Feature"))
        if node.get("type") in ("import", "expose") and (node.get("name") or node.get("qualified_name")):
            target = node.get("name") or node.get("qualified_name")
            index = next((i for i, imp in enumerate(owner.imports) if imp.node is node), None)
            status, _ = resolver._resolve_import_target(target, owner, index)
            if status == NOT_FOUND:
                out.append((node, target, "Namespace" if node.get("wildcard") else "Membership"))
        else:
            for reference, kind, ref_node, feature in references_of(node):
                if _chain_head(reference) != reference:
                    # feature の連鎖（引用符の中の . は区切りではない）。部分集合・再定義の先
                    # （`ref part sub :> c.noo;`）は先頭と 2 番目以降を確かめる。参照する usage の
                    # 連鎖（`perform a.b`）は上で確かめた
                    if kind == "Feature" and reference != _referenced_feature(node):
                        head = _chain_head(reference)
                        # 先頭が自分の名前（`ref p : Person :> p.asPresident;`）なら自分自身に解決する
                        own = isinstance(node.get("name"), str) and _unquote(node["name"]) == _unquote(head)
                        status, found = resolver.resolve(head, owner, feature=True, exclude=None if own else element)
                        if status == NOT_FOUND:
                            out.append((ref_node, head, "Feature"))
                        elif status == FOUND:
                            missing = resolver.missing_chain_member(found, _chain_tail(reference))
                            if missing:
                                out.append((ref_node, missing, "Feature"))
                    continue
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
                visit(value, inner, local_names, local_types)

    visit(ast, resolver.root, frozenset())
    return out

