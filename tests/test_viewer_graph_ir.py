"""viewer.graph_ir の新規ユニットテスト（SysMLv2_Viewer_実装仕様書.md 3章）。"""

from __future__ import annotations

from sysml_v2_checker_advanced.semantic_model import build_semantic_model
from viewer.graph_ir import build_graph_ir

_SAMPLE = """
package Vehicle {
    part def Machine {
        attribute mass : Real;
    }
    part def Engine :> Machine {
        attribute power : Real;
    }
    part myEngine : Engine;
}
"""


def _build(text: str):
    _, model = build_semantic_model(text.strip())
    return build_graph_ir(model)


def test_definitions_usages_and_package_are_included():
    gir = _build(_SAMPLE)
    ids = {n["id"] for n in gir["nodes"]}
    assert ids == {
        "$root",
        "$root::Machine",
        "$root::Machine::mass",
        "$root::Engine",
        "$root::Engine::power",
        "$root::myEngine",
    }


def test_node_group_id_matches_parent_for_containment_layout():
    gir = _build(_SAMPLE)
    by_id = {n["id"]: n for n in gir["nodes"]}
    assert by_id["$root::Machine::mass"]["group_id"] == "$root::Machine"
    assert by_id["$root::Machine"]["group_id"] == "$root"
    assert by_id["$root"]["group_id"] is None


def test_resolved_edges_are_included_with_correct_kind():
    gir = _build(_SAMPLE)
    kinds_by_pair = {(e["from"], e["to"]): e["kind"] for e in gir["edges"]}
    assert kinds_by_pair[("$root::Engine", "$root::Machine")] == "subsetting"
    assert kinds_by_pair[("$root::myEngine", "$root::Engine")] == "feature_typing"


def test_unresolved_edges_are_excluded():
    """組み込み型(Real)への参照はunresolvedなので、Graph IRのエッジに現れない
    （実装仕様書3.3節：宙に浮いた矢印を避ける設計判断）。"""
    gir = _build(_SAMPLE)
    node_ids = {n["id"] for n in gir["nodes"]}
    assert "Real" not in node_ids
    for edge in gir["edges"]:
        assert edge["to"] in node_ids
        assert edge["from"] in node_ids


def test_expressions_and_statements_are_excluded():
    """式(binary_expr等)・文(if_stmt/assignment_stmt等)は"_def"/"_usage"/
    "_instance"のいずれの接尾辞も持たないため対象外になる。
    assert_constraint_usageは"_usage"接尾辞を持つ正当なSysML要素のため
    対象に含まれる（除外対象は生の式・文のみ）。"""
    text = """
    action def A {
        assert constraint : C1;
        if true { assign x := 1; }
    }
    """
    gir = _build(text)
    types = {n["type"] for n in gir["nodes"]}
    assert "assert_constraint_usage" in types
    assert "if_stmt" not in types
    assert "assignment_stmt" not in types
    assert "binary_expr" not in types


def test_binding_connector_is_included_as_explicit_exception():
    text = """
    package P {
        part a;
        part b;
        bind a = b;
    }
    """
    gir = _build(text)
    types = {n["type"] for n in gir["nodes"]}
    assert "binding_connector" in types


def test_edge_ids_are_unique_even_for_duplicate_from_kind_to():
    text = """
    package P {
        part a;
        part b;
        connect a to b;
        connect a to b;
    }
    """
    gir = _build(text)
    connection_edges = [e for e in gir["edges"] if e["kind"] == "connection"]
    ids = [e["id"] for e in connection_edges]
    assert len(ids) == len(set(ids))
