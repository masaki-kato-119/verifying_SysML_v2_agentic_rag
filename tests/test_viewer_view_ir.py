"""viewer.view_ir の新規ユニットテスト（SysMLv2_Viewer_実装仕様書.md 4章）。"""

from __future__ import annotations

from sysml_v2_checker_advanced.semantic_model import build_semantic_model
from viewer.graph_ir import build_graph_ir
from viewer.view_ir import build_view_ir

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


def _build_view_ir(text: str):
    _, model = build_semantic_model(text.strip())
    return build_view_ir(build_graph_ir(model))


def test_layout_is_deterministic_across_repeated_calls():
    vir_a = _build_view_ir(_SAMPLE)
    vir_b = _build_view_ir(_SAMPLE)
    assert vir_a == vir_b


def test_all_coordinates_are_non_negative():
    vir = _build_view_ir(_SAMPLE)
    for node in vir["nodes"]:
        assert node["x"] >= 0
        assert node["y"] >= 0
        assert node["width"] > 0
        assert node["height"] > 0


def test_child_boxes_fit_within_parent_bounds():
    vir = _build_view_ir(_SAMPLE)
    by_id = {n["id"]: n for n in vir["nodes"]}

    parent = by_id["$root::Engine"]
    child = by_id["$root::Engine::power"]
    assert child["x"] >= parent["x"]
    assert child["y"] >= parent["y"]
    assert child["x"] + child["width"] <= parent["x"] + parent["width"]
    assert child["y"] + child["height"] <= parent["y"] + parent["height"]


def test_siblings_do_not_overlap_vertically():
    vir = _build_view_ir(_SAMPLE)
    by_id = {n["id"]: n for n in vir["nodes"]}
    engine = by_id["$root::Engine"]
    machine = by_id["$root::Machine"]
    # Engineが先(name順: "Engine" < "Machine")、Machineはその下に配置される。
    assert engine["y"] + engine["height"] <= machine["y"]


def test_edges_connect_node_centers():
    vir = _build_view_ir(_SAMPLE)
    by_id = {n["id"]: n for n in vir["nodes"]}
    edge = next(e for e in vir["edges"] if "subsetting" in e["id"])
    engine = by_id["$root::Engine"]
    machine = by_id["$root::Machine"]
    expected_from = [engine["x"] + engine["width"] / 2, engine["y"] + engine["height"] / 2]
    expected_to = [machine["x"] + machine["width"] / 2, machine["y"] + machine["height"] / 2]
    assert edge["points"] == [expected_from, expected_to]


def test_empty_graph_ir_produces_empty_view_ir():
    vir = build_view_ir({"nodes": [], "edges": []})
    assert vir == {"view_type": "structure", "nodes": [], "edges": []}
