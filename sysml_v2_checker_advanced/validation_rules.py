"""参照実装（SysMLValidator）の個別の検証ルール（段階 D、eval/pilot_parity/ROADMAP.md）。

名前解決（scope_resolver）の結果を使うものと、構造だけで決まるものがある。どれも参照実装の
xpect テスト（org.omg.sysml.xpect.tests の validation/invalid）と、Pilot 0.62.0 で確かめた形。
メッセージは参照実装と同じ英文（compare.py は同じ文言の指摘を同じ種類として数える）。
"""

from __future__ import annotations

from typing import Iterable, List, Optional, Sequence, Tuple

from .scope_resolver import FOUND, Scope, ScopeResolver, _classes_of

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

