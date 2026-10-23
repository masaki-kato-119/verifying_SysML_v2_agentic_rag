"""参照実装（SysMLValidator）の個別の検証ルール（段階 D、eval/pilot_parity/ROADMAP.md）。

名前解決（scope_resolver）の結果を使うものと、構造だけで決まるものがある。どれも参照実装の
xpect テスト（org.omg.sysml.xpect.tests の validation/invalid）と、Pilot 0.62.0 で確かめた形。
メッセージは参照実装と同じ英文（compare.py は同じ文言の指摘を同じ種類として数える）。
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from .antlr_transformer import extra_of
from .scope_resolver import FOUND, Scope, ScopeResolver, _classes_of, _normalized_text

Violation = Tuple[dict, str]

_CASE_TYPES = frozenset({
    "case_def", "case_usage", "analysis_case_def", "analysis_case_usage", "verification_case_def",
    "verification_case_usage", "use_case_def", "use_case_usage",
})
# モデルの水準で評価できない式（メタデータの値・filter の条件に書けない）。参照実装の
# MetadataUsage_Invalid で確かめた形: 関数の呼び出し、`~`、`->` の呼び出し。
# `new Image(location = ...)`（インスタンスの生成）は通る（verified/structure の @Icon）
_NOT_MODEL_LEVEL = frozenset({"function_call", "arrow_call", "arrow_lambda"})


def _not_model_level(expression) -> bool:
    if isinstance(expression, list):
        return any(_not_model_level(item) for item in expression)
    if not isinstance(expression, dict):
        return False
    kind = expression.get("type")
    if kind in _NOT_MODEL_LEVEL:
        return True
    if kind == "unary_expr" and expression.get("op") == "~":
        return True
    return any(_not_model_level(value) for key, value in expression.items()
               if key != "type" and isinstance(value, (dict, list)))


def validation_violations(ast: dict, external_names: Optional[Iterable[str]] = None,
                          other_asts: Sequence[dict] = ()) -> List[Violation]:
    resolver = ScopeResolver(ast, external_names, other_asts)
    out: List[Violation] = []

    def resolved_definitions(type_names: List[str], owner: Scope) -> Optional[List[Scope]]:
        found_all: List[Scope] = []
        for name in type_names:
            status, found = resolver.resolve(name.lstrip("~"), owner)
            if status != FOUND:
                return None
            found_all.extend(resolver._dealias(f) for f in found)
        return found_all

    def explicit_types(node: dict) -> List[str]:
        return list(dict.fromkeys(t for t in [node.get("type_name")] + list(node.get("type_names") or [])
                                  if isinstance(t, str) and t))

    def own_ends(node: dict) -> List[dict]:
        return [c for c in node.get("children") or [] if isinstance(c, dict) and c.get("type") == "connection_end_member"]

    def own_objectives(node: dict) -> List[dict]:
        return [c for c in node.get("children") or [] if isinstance(c, dict) and c.get("type") == "objective_usage"]

    def inherited_objectives(element: Scope, depth: int = 0) -> int:
        """型・特化の先（このファイルの定義と usage）が持つ objective の数。分からなければ 0。"""
        total = 0
        for reference in element.supertypes:
            status, found = resolver.resolve(reference, element.parent or resolver.root, exclude=element)
            if status != FOUND or depth > 5:
                continue
            for sup in (resolver._dealias(f) for f in found):
                if sup.library is None and sup.node is not None:
                    total += len(own_objectives(sup.node)) + inherited_objectives(sup, depth + 1)
        return total

    def inherited_end_count(element: Scope, depth: int = 0) -> Optional[int]:
        """特化した flow def から継承する端の数（このファイルの定義だけ。分からなければ None）。"""
        total = 0
        for reference in element.supertypes:
            status, found = resolver.resolve(reference, element.parent or resolver.root, exclude=element)
            if status != FOUND or depth > 5:
                return None
            for sup in (resolver._dealias(f) for f in found):
                if sup.library is not None or sup.node is None:
                    return None
                deeper = inherited_end_count(sup, depth + 1)
                if deeper is None:
                    return None
                total += len(own_ends(sup.node)) + deeper
        return total

    def visit(node, owner: Scope):
        if isinstance(node, list):
            for item in node:
                visit(item, owner)
            return
        if not isinstance(node, dict):
            return
        node_type = node.get("type") or ""
        element = resolver.element_of.get(id(node))

        # 「Only one objective is allowed.」: case の本体の 2 つ目以降の objective
        if node_type in _CASE_TYPES:
            objectives = own_objectives(node)
            # 型・特化の先の case が objective を持てば、自分の objective はすべて 2 つ目以降
            # （`case c : C { objective o3; }` で C に objective がある。CaseSubjectObjective_Invalid）
            # 自分の objective は継承した objective を 1 つ暗黙に再定義する。継承した objective が
            # 2 つ以上なら、自分の objective はすべて余分（validation_09 は継承 1・自分 1 で通る）
            inherited = inherited_objectives(element) if element is not None else 0
            first_allowed = 0 if inherited >= 2 else 1
            for extra in objectives[first_allowed:]:
                if not (extra.get("redefines") or []):
                    out.append((extra, "Only one objective is allowed."))

        # 「An enumeration attribute cannot have more than one type.」
        if node_type == "attribute_usage" and len(explicit_types(node)) > 1:
            definitions = resolved_definitions(explicit_types(node), owner)
            if definitions and any((d.node or {}).get("type") == "enum_def" for d in definitions):
                out.append((node, "An enumeration attribute cannot have more than one type."))

        # 「At most one individual definition is allowed.」
        if node_type == "individual_usage" and len(explicit_types(node)) > 1:
            definitions = resolved_definitions(explicit_types(node), owner)
            if definitions and sum(1 for d in definitions if "IndividualDef" in (_classes_of(d) or ())) > 1:
                out.append((node, "At most one individual definition is allowed."))

        # 「A flow definition can have at most two ends.」（0.62.0 は `A flow connection definition ...`。0.63.0 で文言が変わった）
        if node_type == "flow_def" and element is not None:
            ends = own_ends(node)
            inherited = inherited_end_count(element)
            if len(ends) > 2:
                out.extend((end, "A flow definition can have at most two ends.") for end in ends[2:])
            elif inherited is not None and inherited + len(ends) > 2:  # `flow def J :> I;` も
                out.append((node, "A flow definition can have at most two ends."))

        # 「An interface end must be a port.」
        if node_type in ("interface_def", "interface_usage"):
            for end in own_ends(node):
                if end.get("kind") not in (None, "port"):
                    out.append((end, "An interface end must be a port."))

        # 「Owned usages of a port definition (other than ports) must be referential.」
        # 「Nested usages in a port usage (other than ports) must be referential.」
        if node_type in ("port_def", "port_usage"):
            message = ("Owned usages of a port definition (other than ports) must be referential."
                       if node_type == "port_def" else
                       "Nested usages in a port usage (other than ports) must be referential.")
            for child in node.get("children") or []:
                if isinstance(child, dict) and child.get("type") in ("part_instance", "item_usage", "occurrence_usage") \
                        and not child.get("isRef"):
                    out.append((child, message))

        # 「Must be model-level evaluable」「Must have a Boolean result」: filter の条件とメタデータの値
        if node_type == "filter" and isinstance(node.get("expression"), dict):
            expression = node["expression"]
            if expression.get("type") == "new_instance" or (
                    expression.get("type") == "literal" and expression.get("literal_type") != "boolean"):
                out.append((node, "Must have a Boolean result"))
            elif _not_model_level(expression):
                out.append((node, "Must be model-level evaluable"))
        if node_type == "metadata_usage":
            for child in node.get("children") or []:
                if isinstance(child, dict) and _not_model_level(child.get("value")):
                    out.append((child, "Must be model-level evaluable"))

        # 「Redefining feature must have a compatible direction」
        check_directions(node, owner, element)
        # 「Cannot override a binding feature value」「Subsetting/redefining feature must be constant ...」
        check_overrides(node, owner, element)
        # 「Referent must be time varying.」
        if node_type == "assignment_stmt" and extra_of(node, "assignKeyword"):
            check_assignment(node, owner)
        # 「Must correspond to one input parameter of the invoked type」
        if node_type == "function_call" and isinstance(node.get("name"), str) and node["name"]:
            check_invocation(node, owner)
        # 「Cannot annotate <メタクラス>」
        check_annotations(node, owner)

        inner = element or owner
        for key, value in node.items():
            if key != "type" and isinstance(value, (dict, list)):
                visit(value, inner)

    reported_direction: set = set()

    def check_directions(node: dict, owner: Scope, element: Optional[Scope]) -> None:
        """再定義の方向（Pilot 0.63.0 で確かめた規則、2026-10-23）。

        - 型付きの usage の方向のある引数は、`:>>` の有無にかかわらず、型の引数を**順番どおりに**再定義する
          （`action s : Shoot { out item picture; }` の picture は Shoot の最初の引数 image を再定義する）。
        - 明示的な再定義（`:>> x`・`redefines x`）は、その先の方向と比べる（`calc c : C { :>> x = 1.0; }` の
          方向の無い再定義は、`in x` に対して食い違い）。
        - 順番の再定義は振る舞い（action・calc・state・case・constraint・requirement）の usage だけ。ポート・part の
          中の方向のある feature は順番では再定義しない（sysmod の `port p : PositionPort { out item _position; }`）。
        - 共役のポート（`port q : ~P`）の中では、P の feature の方向が反転する（`in` ↔ `out`）。
        型の引数の並びが分からないとき（型が特化を持つ・ライブラリの型）、共役か分からないときは判定しない。
        """
        node_type = node.get("type") or ""
        if node_type in _BEHAVIOR_USAGE_TYPES:
            type_names = explicit_types(node)
            own = _directed_parameters(node)
            if len(type_names) == 1 and own:
                definitions = resolved_definitions(type_names, owner)
                if definitions and len(definitions) == 1 and definitions[0].node is not None \
                        and definitions[0].library is None and not definitions[0].supertypes:
                    for redefined, redefining in zip(_directed_parameters(definitions[0].node), own):
                        if not _direction_compatible(redefined.get("direction"), redefining.get("direction")):
                            report_direction(redefining)
        targets = []
        if node_type == "value_binding" and node.get("kind") == "redefines" and isinstance(node.get("target"), str):
            targets.append(node["target"])
        for entry in node.get("redefines") or []:
            if isinstance(entry, dict) and entry.get("kind") == "redefines" and isinstance(entry.get("target"), str):
                targets.append(entry["target"])
        if not targets or id(node) in reported_direction:
            return
        own_direction = node.get("direction") if node_type in ("param", "calc_parameter") else None
        if own_direction == "return":
            return
        conjugated = port_conjugation(owner)
        if conjugated is None:
            return  # ポートの中だが、共役か分からない
        for target in targets:
            status, found = resolver.resolve(target, owner, feature=True, exclude=element)
            if status != FOUND or len(found) != 1 or found_lexically(found[0], owner):
                continue
            redefined = resolver._dealias(found[0]).node or {}
            direction = redefined.get("direction")
            if conjugated:
                direction = {"in": "out", "out": "in"}.get(direction, direction)
            if redefined.get("type") in ("param", "calc_parameter") \
                    and not _direction_compatible(direction, own_direction):
                report_direction(node)
                return

    def port_conjugation(owner: Scope, depth: int = 0) -> Optional[bool]:
        """owner がポートの usage なら、その型が共役（`~P`）か。ポートでなければ False、分からなければ None。"""
        node = owner.node or {}
        is_port = node.get("type") == "port_usage" or (node.get("type") in ("param",) and node.get("kind") == "port")
        if not is_port:
            return False
        type_name = node.get("type_name")
        if isinstance(type_name, str) and type_name:
            return type_name.startswith("~")
        # `port :>> fuelInPort { ... }`（型の無い再定義）: 再定義の先のポートの型から
        if depth > 5:
            return None
        for reference in owner.supertypes:
            status, found = resolver.resolve(reference, owner.parent or resolver.root, feature=True, exclude=owner)
            if status == FOUND and len(found) == 1 and found[0].node is not None:
                return port_conjugation(resolver._dealias(found[0]), depth + 1)
        return None

    def check_overrides(node: dict, owner: Scope, element: Optional[Scope]) -> None:
        """値の上書きと constant（Pilot 0.63.0 で確かめた規則、2026-10-23）。

        - 再定義の先が `=` / `:=` の値を持つ（default ではない）とき、値を持つ再定義（`=`・`:=`・`default`）は
          `Cannot override a binding feature value`。先が default の値なら上書きできる。再定義の先は、継承の途中の
          再定義（`x1 : Base { :>> a = 20; }` を `x1sub :> x1 { :>> a = 25; }` が上書き）も含む。
        - constant の feature の再定義・部分集合は constant でなければならない（値の無い `:>> w { }` も）。
        """
        node_type = node.get("type") or ""
        targets = []  # (種類, 先)
        if node_type == "value_binding" and isinstance(node.get("target"), str):
            targets.append((node.get("kind") or "redefines", node["target"]))
        for entry in node.get("redefines") or []:
            if isinstance(entry, dict) and entry.get("kind") in ("redefines", "subsets") \
                    and isinstance(entry.get("target"), str):
                targets.append((entry["kind"], entry["target"]))
        if not targets:
            return
        has_value = node.get("value") is not None or node.get("defaultValue") is not None
        is_constant = bool(node.get("isConstant"))
        for kind, target in targets:
            status, found = resolver.resolve(target, owner, feature=True, exclude=element)
            if status != FOUND or len(found) != 1 or (kind == "redefines" and found_lexically(found[0], owner)):
                continue
            redefined = resolver._dealias(found[0])
            if redefined.library is not None or redefined.node is None:
                continue
            target_node = redefined.node
            if kind == "redefines" and has_value and (
                    target_node.get("value") is not None
                    or bound_in_supertypes(owner, split_last(target), redefined)):
                out.append((node, "Cannot override a binding feature value"))
            if target_node.get("isConstant") and not is_constant:
                out.append((node, "Subsetting/redefining feature must be constant if subsetted/redefined feature is"
                                  " constant"))

    def check_assignment(node: dict, owner: Scope) -> None:
        """`assign x := v;` の代入先が時間とともに変わる feature か（Pilot 0.63.0 で確かめた規則、2026-10-23）。

        - 合成の action・calc・state・case の usage（`action d;`）は変わらない。`ref action`・`perform`・
          `exhibit state`・constraint・requirement は代入できる。
        - occurrence（part・item・action・port・connection など）の定義・usage が持つ feature は変わる
          （constant・derived・end も通る）。属性の定義・usage、列挙、パッケージが持つもの（`ad.k`・`E::e1`・
          パッケージの直下の `pp`）は変わらない。
        """
        target = _normalized_text(node, "name")
        if not target:
            return
        status, found = resolver.resolve(target, owner, feature=True)
        if status != FOUND or len(found) != 1:
            return
        referent = resolver._dealias(found[0])
        if referent.library is not None or referent.node is None or referent.parent is None:
            return
        referent_type = referent.node.get("type") or ""
        holder = referent.parent
        if holder.library is not None:
            return
        holder_type = (holder.node or {}).get("type") or ""
        # 名前の無い要素（`action { attribute i; ... }`）は名前解決では透過なので、持ち主は本体を見て確かめる
        owned_directly = any(child is referent.node for key in ("children", "params")
                             for child in (holder.node or {}).get(key) or [])
        if (referent_type in _COMPOSITE_BEHAVIOR_USAGES and not referent.node.get("isRef"))                 or (holder_type in _NOT_OCCURRENCE_OWNERS and owned_directly):
            out.append((node, "Referent must be time varying."))

    def invoked_parameters(name: str, owner: Scope) -> Optional[Tuple[List[dict], set]]:
        """呼び出した型の引数の並び（subject と方向のある引数、宣言の順）と、型のメンバーの名前。分からなければ None。

        呼び出せるのは、このファイルの振る舞いの定義（特化を持たないもの。特化した定義の引数は継承した引数を
        順番に再定義するので並びが変わる）と、その定義で型付けした、自分では引数を書いていない usage。
        """
        status, found = resolver.resolve(name, owner)
        if status == FOUND and len(found) > 1:
            # `verify r;` は参照先 r の名前を持つ。宣言の r のほうを呼ぶ
            found = [f for f in found if not f.referenced]
        if status != FOUND or len(found) != 1:
            return None
        invoked = resolver._dealias(found[0])
        if invoked.library is not None or invoked.node is None:
            return None
        node = invoked.node
        if node.get("type") not in _INVOCABLE_DEFINITIONS:
            if node.get("type") not in _BEHAVIOR_USAGE_TYPES or _invocation_parameters(node)                     or len(explicit_types(node)) != 1 or invoked.supertypes != explicit_types(node):
                return None
            definitions = resolved_definitions(explicit_types(node), invoked.parent or resolver.root)
            if not definitions or len(definitions) != 1 or definitions[0].node is None                     or definitions[0].library is not None:
                return None
            invoked = definitions[0]
            node = invoked.node
            if node.get("type") not in _INVOCABLE_DEFINITIONS:
                return None
        if invoked.supertypes:
            return None
        parameters = _invocation_parameters(node)
        if node.get("type") in _SUBJECT_DEFINITIONS and not any(p.get("type") == "subject_usage" for p in parameters):
            # 自分で subject を書いていない要件・case は、ライブラリの subject を継承する（引数が 1 つある）
            return None
        members = {name for member in invoked.members for name in member.names()}
        return parameters, members

    def check_invocation(node: dict, owner: Scope) -> None:
        """呼び出しの引数と、呼び出した型の引数の対応（Pilot 0.63.0 で確かめた規則、2026-10-23）。

        - 位置の引数は、型の subject と方向のある引数（`in`・`out`・`inout`。return と方向の無い属性は除く）に
          宣言の順に対応する。対応する引数が無い位置の引数は 1 つごとに誤り（`F(1.0, 2.0, 3.0)`、
          `r(s, 60.0)` で RateReq の入力が subject だけ）。
        - `out` の引数に対応した位置の引数は、誤りに加えて方向の食い違い（`G(1.0, 2.0)` の 2 つ目が `out o`）。
        - 名前付きの引数（`F(w = 2.0)`）は、型にその名前の引数が無ければ誤り。型にその名前の feature も
          無ければ、未解決も出す（方向の無い属性 `RR(m = 1.0)` は未解決にならない）。
        """
        invoked = invoked_parameters(node["name"], owner)
        if invoked is None:
            return
        parameters, members = invoked
        position = 0
        names = {p.get("name") for p in parameters}
        for argument in node.get("arguments") or []:
            if not isinstance(argument, dict):
                continue
            if argument.get("type") == "named_argument":
                if isinstance(argument.get("name"), str) and argument["name"] not in names:
                    if argument["name"] not in members:
                        out.append((argument, f"Couldn't resolve reference to Feature '{argument['name']}'."))
                    out.append((argument, "Must correspond to one input parameter of the invoked type"))
                continue
            if position >= len(parameters):
                out.append((argument, "Must correspond to one input parameter of the invoked type"))
            elif parameters[position].get("direction") == "out":
                out.append((argument, "Must correspond to one input parameter of the invoked type"))
                out.append((argument, "Redefining feature must have a compatible direction"))
            position += 1

    def annotation_restrictions(name: str, owner: Scope, depth: int = 0) -> Optional[frozenset]:
        """メタデータの定義が注釈できる要素のメタクラス（`:> annotatedElement : SysML::PartUsage;`）。

        制約が無ければ空集合。特化の先のメタデータの定義の制約も足す（どれかに当たればよい）。
        ライブラリの Metadata 以外を特化している、メタクラスの名前が分からないなどで確かめられなければ None。
        """
        status, found = resolver.resolve(name, owner)
        if status != FOUND or len(found) != 1 or depth > 6:
            return None
        definition = resolver._dealias(found[0])
        if definition.library is not None:
            return frozenset() if definition.library.split("::")[-1] in ("Metadata", "MetadataItem") else None
        node = definition.node or {}
        if node.get("type") != "metadata_def":
            return None
        restrictions = set()
        for child in node.get("children") or []:
            if not isinstance(child, dict) or not any(
                    isinstance(e, dict) and e.get("kind") in ("subsets", "redefines")
                    and isinstance(e.get("target"), str) and e["target"].split("::")[-1] == "annotatedElement"
                    for e in child.get("redefines") or []):
                continue
            metaclass = (child.get("type_name") or "").split("::")[-1]
            if metaclass not in _metaclass_supertypes():
                return None
            restrictions.add(metaclass)
        for reference in definition.supertypes:
            inherited = annotation_restrictions(reference, definition.parent or resolver.root, depth + 1)
            if inherited is None:
                return None
            restrictions |= inherited
        return frozenset(restrictions)

    def check_annotations(node: dict, owner: Scope) -> None:
        """注釈する要素のメタクラスが、メタデータの定義の annotatedElement の制約に当たるか（Pilot 0.63.0 で
        確かめた規則、2026-10-23）。

        `@M;`・`metadata m : M;` は囲む要素（パッケージも）を、`metadata m : M about x;` は x を、`#M part p;` は
        p を注釈する。制約が複数あれば、どれかに当たればよい。
        """
        uses: List[Tuple[dict, str, List[dict]]] = []  # (出す位置, メタデータの定義, 注釈する要素)
        if node.get("type") == "metadata_usage":
            metadata = node.get("type_name") or node.get("name")
            if isinstance(metadata, str) and metadata:
                targets = []
                for target in node.get("about") or []:
                    status, found = resolver.resolve(target, owner) if isinstance(target, str) else (None, [])
                    if status != FOUND or len(found) != 1:
                        return
                    targets.append(resolver._dealias(found[0]).node)
                uses.append((node, metadata, targets or [owner.node]))
        for metadata in node.get("prefixMetadata") or []:
            if isinstance(metadata, str) and metadata:
                uses.append((node, metadata, [node]))
        for at, metadata, targets in uses:
            restrictions = annotation_restrictions(metadata, owner)
            if not restrictions:
                continue
            for target in targets:
                metaclass = _METACLASS_OF.get((target or {}).get("type") or "")
                if metaclass and not (_metaclass_ancestors(metaclass) & restrictions):
                    out.append((at, f"Cannot annotate {metaclass}"))

    def found_lexically(found: Scope, owner: Scope) -> bool:
        """再定義の先が、継承ではなく、再定義を囲む名前空間（owner かその外側）の要素として見つかったか。

        再定義の先は継承した feature のはず。型が解決できないとき（import の誤記など）や、構文エラーの回復で
        要素が別の本体に入ったとき、名前解決は外側の同じ名前に届いてしまう。そのときは判定しない
        （フォルダ単位のコーパスの誤検出、2026-10-23）。
        """
        scope: Optional[Scope] = owner
        while scope is not None:
            if found.parent is scope:
                return True
            scope = scope.parent
        return False

    def split_last(reference: str) -> str:
        return reference.split("::")[-1].split(".")[-1].strip("'")

    def bound_in_supertypes(scope: Scope, name: str, stop: Scope, depth: int = 0) -> bool:
        """継承の途中で、キーワードの無い束縛（`p1 : P { :>> d = 2.0; }`）が name に値を付けているか。

        キーワードの無い `:>> d = 2.0;` は名前解決のメンバーにならないので、特化・型付けの先の本体を見る。
        stop（解決した再定義の先）まで来たらやめる。
        """
        if depth > 6:
            return False
        for reference in scope.supertypes:
            status, found = resolver.resolve(reference, scope.parent or resolver.root, exclude=scope)
            if status != FOUND:
                continue
            for sup in (resolver._dealias(f) for f in found):
                if sup is stop or sup.node is None or sup.library is not None:
                    continue
                for child in sup.node.get("children") or []:
                    if isinstance(child, dict) and child.get("type") == "value_binding" \
                            and child.get("kind") == "redefines" and child.get("value") is not None \
                            and isinstance(child.get("target"), str) and split_last(child["target"]) == name:
                        return True
                if bound_in_supertypes(sup, name, stop, depth + 1):
                    return True
        return False

    def report_direction(node: dict) -> None:
        if id(node) not in reported_direction:
            reported_direction.add(id(node))
            out.append((node, "Redefining feature must have a compatible direction"))

    visit(ast, resolver.root)
    return out


# 代入先にならない合成の振る舞いの usage（`assign d := null;` の `action d;`）
_COMPOSITE_BEHAVIOR_USAGES = frozenset({
    "action_usage", "calculation_usage", "calc_usage", "state_usage", "case_usage", "analysis_case_usage",
    "verification_case_usage", "use_case_usage",
})
# AST の種類 → SysML のメタクラス（注釈できる要素の制約を確かめるもの。無いものは確かめない）
_METACLASS_OF: Dict[str, str] = {
    "package": "Package", "library_package": "LibraryPackage",
    "part_def": "PartDefinition", "part_instance": "PartUsage", "item_def": "ItemDefinition", "item_usage": "ItemUsage",
    "attribute_def": "AttributeDefinition", "attribute_usage": "AttributeUsage", "port_def": "PortDefinition",
    "port_usage": "PortUsage", "action_def": "ActionDefinition", "action_usage": "ActionUsage",
    "state_def": "StateDefinition", "state_usage": "StateUsage", "calculation_def": "CalculationDefinition",
    "calculation_usage": "CalculationUsage", "constraint_def": "ConstraintDefinition",
    "constraint_usage": "ConstraintUsage", "assert_constraint_usage": "AssertConstraintUsage",
    "requirement_def": "RequirementDefinition", "requirement_usage": "RequirementUsage",
    "concern_def": "ConcernDefinition", "concern_usage": "ConcernUsage", "case_def": "CaseDefinition",
    "case_usage": "CaseUsage", "analysis_case_def": "AnalysisCaseDefinition", "analysis_case_usage": "AnalysisCaseUsage",
    "verification_case_def": "VerificationCaseDefinition", "verification_case_usage": "VerificationCaseUsage",
    "use_case_def": "UseCaseDefinition", "use_case_usage": "UseCaseUsage", "connection_def": "ConnectionDefinition",
    "connection_usage": "ConnectionUsage", "interface_def": "InterfaceDefinition", "interface_usage": "InterfaceUsage",
    "allocation_def": "AllocationDefinition", "allocation_usage": "AllocationUsage", "flow_def": "FlowDefinition",
    "flow_usage": "FlowUsage", "occurrence_def": "OccurrenceDefinition", "occurrence_usage": "OccurrenceUsage",
    "enum_def": "EnumerationDefinition", "view_def": "ViewDefinition", "view_usage": "ViewUsage",
    "viewpoint_def": "ViewpointDefinition", "viewpoint_usage": "ViewpointUsage",
    "rendering_def": "RenderingDefinition", "rendering_usage": "RenderingUsage", "metadata_def": "MetadataDefinition",
    "exhibit_state_usage": "ExhibitStateUsage", "perform_action": "PerformActionUsage",
    "satisfy_requirement_usage": "SatisfyRequirementUsage", "include_use_case_usage": "IncludeUseCaseUsage",
    "event_occurrence_usage": "EventOccurrenceUsage",
}


@lru_cache(maxsize=1)
def _metaclass_supertypes() -> Dict[str, List[str]]:
    """scripts/build_metaclass_supertypes.py が作る、メタクラス → 直接の特化の先。"""
    try:
        return json.loads(Path(__file__).with_name("metaclass_supertypes.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


@lru_cache(maxsize=None)
def _metaclass_ancestors(metaclass: str) -> frozenset:
    seen = {metaclass}
    pending = [metaclass]
    while pending:
        for base in _metaclass_supertypes().get(pending.pop(), []):
            if base not in seen:
                seen.add(base)
                pending.append(base)
    return frozenset(seen)


# 呼び出せる振る舞いの定義
_INVOCABLE_DEFINITIONS = frozenset({
    "calculation_def", "calc_def", "action_def", "constraint_def", "requirement_def", "concern_def", "case_def",
    "analysis_case_def", "verification_case_def", "use_case_def", "state_def",
})
# ライブラリから subject を継承する定義
_SUBJECT_DEFINITIONS = frozenset({
    "requirement_def", "concern_def", "viewpoint_def", "case_def", "analysis_case_def", "verification_case_def",
    "use_case_def",
})
# 時間とともに変わる feature を持たない名前空間
_NOT_OCCURRENCE_OWNERS = frozenset({"root", "package", "library_package", "attribute_def", "attribute_usage", "enum_def"})

# 型の引数を順番に再定義する usage（振る舞い）
_BEHAVIOR_USAGE_TYPES = frozenset({
    "action_usage", "perform_action", "calculation_usage", "calc_usage", "state_usage", "exhibit_state_usage",
    "case_usage", "analysis_case_usage", "verification_case_usage", "use_case_usage", "constraint_usage",
    "assert_constraint_usage", "requirement_usage",
})


def _directed_parameters(node: dict) -> List[dict]:
    """方向（in / out / inout）のある引数（宣言の順。return は除く）。"""
    out = []
    for key in ("params", "children"):
        for child in node.get(key) or []:
            if isinstance(child, dict) and child.get("type") in ("param", "calc_parameter") \
                    and child.get("direction") in ("in", "out", "inout"):
                out.append(child)
    return out


def _invocation_parameters(node: dict) -> List[dict]:
    """呼び出しの引数が対応する引数: subject と方向のある引数（宣言の順。return は除く）。"""
    out = []
    for key in ("params", "children"):
        for child in node.get(key) or []:
            if not isinstance(child, dict):
                continue
            if child.get("type") == "subject_usage" or (
                    child.get("type") in ("param", "calc_parameter") and child.get("direction") in ("in", "out", "inout")):
                out.append(child)
    return out


def _direction_compatible(redefined: Optional[str], redefining: Optional[str]) -> bool:
    """Pilot 0.63.0 で確かめた表: in ← in、out ← out、inout ← in / out / inout。方向の無い feature はどれでも
    再定義できるが、方向のある feature を方向の無い feature で再定義すると食い違い。"""
    if redefined not in ("in", "out", "inout"):
        return True
    if redefining is None:
        return False
    if redefined == "inout":
        return redefining in ("in", "out", "inout")
    return redefining == redefined

