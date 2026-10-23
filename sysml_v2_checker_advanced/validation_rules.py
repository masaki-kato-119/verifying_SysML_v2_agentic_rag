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

        inner = element or owner
        for key, value in node.items():
            if key != "type" and isinstance(value, (dict, list)):
                visit(value, inner)

    visit(ast, resolver.root)
    return out

