"""viewer.graph_ir の新規ユニットテスト（SysMLv2_Viewer_実装仕様書.md 3章）。"""

from __future__ import annotations

from sysml_v2_checker_advanced.semantic_model import build_semantic_model
from viewer.graph_ir import (
    VIEW_TYPE_ACTIVITY,
    VIEW_TYPE_REQUIREMENT_TRACEABILITY,
    VIEW_TYPE_STATE_MACHINE,
    VIEW_TYPE_VERIFICATION,
    build_graph_ir,
)

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


def test_binding_connector_with_body_is_included_as_explicit_exception():
    """本体（`{ ... }`）を持つbinding_connectorは、中の要素を消さないよう
    従来通り自身をボックスとして描画対象に含める。"""
    text = """
    package P {
        part a;
        part b;
        bind a = b {
            doc /* note */
        }
    }
    """
    gir = _build(text)
    types = {n["type"] for n in gir["nodes"]}
    assert "binding_connector" in types


def test_simple_binary_connector_collapses_into_a_single_edge_instead_of_a_box():
    """表現力強化: 2項かつ本体を持たないconnectorは、自身をボックスとして
    描画対象に含めない（両端を直接結ぶ1本のconnectionエッジとして
    Semantic Model側で既に表現されているため）。"""
    text = """
    package P {
        part a;
        part b;
        bind a = b;
    }
    """
    gir = _build(text)
    types = {n["type"] for n in gir["nodes"]}
    assert "binding_connector" not in types
    connection_edges = [e for e in gir["edges"] if e["kind"] == "connection"]
    assert len(connection_edges) == 1
    assert connection_edges[0]["from"] == "$root::a"
    assert connection_edges[0]["to"] == "$root::b"


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


# --- view_type（Group2 b6, V1-1） ---------------------------------------


def test_default_view_type_is_unchanged_structure_view():
    """既存呼び出し（view_type省略時）が無変更で動作することを確認する
    （実装仕様書のバックエンド拡張全般で維持している後方互換方針）。"""
    _, model = build_semantic_model(_SAMPLE.strip())
    assert build_graph_ir(model) == build_graph_ir(model, view_type="structure")


_REQUIREMENT_SAMPLE = """
package P {
    part def System;
    part system;
    requirement def Req1;
    requirement req1 : Req1;
    satisfy requirement req1 : Req1 by system;
    verify req1 by system;
}
"""


def test_requirement_traceability_view_includes_only_requirement_nodes_and_satisfy_targets():
    _, model = build_semantic_model(_REQUIREMENT_SAMPLE.strip())
    gir = build_graph_ir(model, view_type=VIEW_TYPE_REQUIREMENT_TRACEABILITY)
    types_by_id = {n["id"]: n["type"] for n in gir["nodes"]}
    assert types_by_id == {
        "$root::Req1": "requirement_def",
        "$root::system": "part_instance",
        "$root::req1#2": "satisfy_requirement_usage",
        "$root::req1#3": "verify_requirement_usage",
    }
    kinds = {e["kind"] for e in gir["edges"]}
    assert kinds == {"satisfy", "verify"}
    # 非包含ビューのため全ノードがトップレベル(group_id=None)になる。
    assert all(n["group_id"] is None for n in gir["nodes"])


def test_requirement_traceability_view_excludes_unrelated_structure_nodes():
    """構造図では出るはずのMachine/Engine等の一般的な定義・使用は、
    要求トレーサビリティビューには含まれない。"""
    _, model = build_semantic_model(_SAMPLE.strip())
    gir = build_graph_ir(model, view_type=VIEW_TYPE_REQUIREMENT_TRACEABILITY)
    assert gir["nodes"] == []
    assert gir["edges"] == []


def test_unknown_view_type_raises_value_error():
    _, model = build_semantic_model(_SAMPLE.strip())
    try:
        build_graph_ir(model, view_type="no_such_view")
        assert False, "ValueErrorが送出されるべき"
    except ValueError:
        pass


# --- view_type="verification"（Group2 b8, V2） ---------------------------


def test_verification_view_includes_seed_and_resolved_neighbors():
    """viewer/frontend/app.jsのfindImpactedElementIds(既定2次)と同じBFSを
    バックエンドで再現する。myEngineを起点にすると、feature_typing経由で
    Engine(1次)・subsetting経由でMachine(2次)まで含まれる。"""
    _, model = build_semantic_model(_SAMPLE.strip())
    gir = build_graph_ir(
        model, view_type=VIEW_TYPE_VERIFICATION, finding_element_ids={"$root::myEngine"}
    )
    ids = {n["id"] for n in gir["nodes"]}
    assert ids == {"$root::myEngine", "$root::Engine", "$root::Machine"}
    kinds_by_pair = {(e["from"], e["to"]): e["kind"] for e in gir["edges"]}
    assert kinds_by_pair == {
        ("$root::myEngine", "$root::Engine"): "feature_typing",
        ("$root::Engine", "$root::Machine"): "subsetting",
    }


_CHAIN_SAMPLE = """
package P {
    part def A;
    part def B :> A;
    part def C :> B;
    part def D :> C;
}
"""


def test_verification_view_respects_default_depth_limit():
    """既定2次までしか辿らないため、Dを起点にするとC・Bは含まれるが、
    3次先のAは含まれない。"""
    _, model = build_semantic_model(_CHAIN_SAMPLE.strip())
    gir = build_graph_ir(
        model, view_type=VIEW_TYPE_VERIFICATION, finding_element_ids={"$root::D"}
    )
    ids = {n["id"] for n in gir["nodes"]}
    assert ids == {"$root::D", "$root::C", "$root::B"}


def test_verification_view_with_no_finding_element_ids_is_empty():
    _, model = build_semantic_model(_SAMPLE.strip())
    gir = build_graph_ir(model, view_type=VIEW_TYPE_VERIFICATION, finding_element_ids=set())
    assert gir["nodes"] == []
    assert gir["edges"] == []


# --- state_machine（表現力強化Stage 3, Group B f2） -----------------------

_STATE_MACHINE_SAMPLE = """
state def AdvancedSwitch {
    entry; then Off;

    state Off;
    state On;

    transition first Off
        accept TurnOn
        then On;

    transition OnToOff
        first On
        accept TurnOff
        then Off;
}
"""


def test_state_machine_view_includes_only_state_nodes_and_transition_edges():
    _, model = build_semantic_model(_STATE_MACHINE_SAMPLE.strip())
    gir = build_graph_ir(model, view_type=VIEW_TYPE_STATE_MACHINE)
    types_by_id = {n["id"]: n["type"] for n in gir["nodes"]}
    assert types_by_id == {
        "$root::AdvancedSwitch": "state_def",
        "$root::AdvancedSwitch::Off": "state_usage",
        "$root::AdvancedSwitch::On": "state_usage",
    }
    kinds = {e["kind"] for e in gir["edges"]}
    assert kinds == {"transition"}
    assert len(gir["edges"]) == 3  # entry->Off(暗黙) + Off->On + On->Off


def test_state_machine_view_excludes_unrelated_structure_nodes():
    """構造図では出るはずのpart def等は、状態遷移図には含まれない。"""
    _, model = build_semantic_model(_SAMPLE.strip())
    gir = build_graph_ir(model, view_type=VIEW_TYPE_STATE_MACHINE)
    assert gir["nodes"] == []
    assert gir["edges"] == []


def test_state_machine_view_edges_reference_only_state_machine_nodes():
    _, model = build_semantic_model(_STATE_MACHINE_SAMPLE.strip())
    gir = build_graph_ir(model, view_type=VIEW_TYPE_STATE_MACHINE)
    node_ids = {n["id"] for n in gir["nodes"]}
    for edge in gir["edges"]:
        assert edge["from"] in node_ids
        assert edge["to"] in node_ids


# --- activity（表現力強化Stage 3, Group C g1） ----------------------------

_ACTIVITY_SAMPLE = """
action def Act {
    action step1;
    action step2;
    action step3;
    first step1 then step2;
    succession flow f1 from step2 to step3;
}
"""


def test_activity_view_includes_only_action_nodes_and_succession_flow_edges():
    _, model = build_semantic_model(_ACTIVITY_SAMPLE.strip())
    gir = build_graph_ir(model, view_type=VIEW_TYPE_ACTIVITY)
    types_by_id = {n["id"]: n["type"] for n in gir["nodes"]}
    assert types_by_id == {
        "$root::Act": "action_def",
        "$root::Act::step1": "action_usage",
        "$root::Act::step2": "action_usage",
        "$root::Act::step3": "action_usage",
    }
    kinds = {e["kind"] for e in gir["edges"]}
    assert kinds == {"succession"}  # 表現力強化e3の"flow"kindも対象だが、
    # このサンプルは"succession flow"形(kind="succession")のみを使用している
    assert len(gir["edges"]) == 2  # step1->step2, step2->step3


def test_activity_view_excludes_unrelated_structure_nodes():
    _, model = build_semantic_model(_SAMPLE.strip())
    gir = build_graph_ir(model, view_type=VIEW_TYPE_ACTIVITY)
    assert gir["nodes"] == []
    assert gir["edges"] == []


def test_activity_view_includes_plain_flow_kind_edges():
    text = """
    action def Act {
        action step1 { out item x; }
        action step2 { in item y; }
        flow step1.x to step2.y;
    }
    """
    _, model = build_semantic_model(text.strip())
    gir = build_graph_ir(model, view_type=VIEW_TYPE_ACTIVITY)
    kinds = {e["kind"] for e in gir["edges"]}
    assert kinds == {"flow"}
