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


def _is_on_box_boundary(point, box, tolerance=1e-6):
    x, y = point
    on_vertical_edge = abs(x - box["x"]) < tolerance or abs(x - (box["x"] + box["width"])) < tolerance
    on_horizontal_edge = abs(y - box["y"]) < tolerance or abs(y - (box["y"] + box["height"])) < tolerance
    within_x = box["x"] - tolerance <= x <= box["x"] + box["width"] + tolerance
    within_y = box["y"] - tolerance <= y <= box["y"] + box["height"] + tolerance
    return (on_vertical_edge and within_y) or (on_horizontal_edge and within_x)


def test_edges_terminate_at_node_boundaries_not_centers():
    """表現力強化Stage 0: エッジの両端は矩形の中心ではなく縁で止まる
    （中心同士を結ぶと矩形内部を必ず貫通し、ノードを後から重ねて描く限り
    その区間が隠れて見えなくなるため）。"""
    vir = _build_view_ir(_SAMPLE)
    by_id = {n["id"]: n for n in vir["nodes"]}
    edge = next(e for e in vir["edges"] if "subsetting" in e["id"])
    engine = by_id["$root::Engine"]
    machine = by_id["$root::Machine"]
    from_point, to_point = edge["points"]

    assert _is_on_box_boundary(from_point, engine)
    assert _is_on_box_boundary(to_point, machine)

    # 退行防止: 中心点そのものにはならない(=Stage 0以前の挙動には戻っていない)。
    engine_center = [engine["x"] + engine["width"] / 2, engine["y"] + engine["height"] / 2]
    machine_center = [machine["x"] + machine["width"] / 2, machine["y"] + machine["height"] / 2]
    assert from_point != engine_center
    assert to_point != machine_center


def test_boundary_point_geometry_for_a_simple_horizontal_edge():
    """幾何計算そのものを、2つの独立した葉ノードだけの単純な入力で検証する
    （_SAMPLEのような入れ子構造では手計算での期待値検証が煩雑なため）。"""
    graph_ir = {
        "nodes": [
            {"id": "a", "type": "part_def", "label": "A", "group_id": None, "source_range": None},
            {"id": "b", "type": "part_def", "label": "B", "group_id": None, "source_range": None},
        ],
        "edges": [{"id": "a->x->b#0", "from": "a", "to": "b", "kind": "connection"}],
    }
    vir = build_view_ir(graph_ir)
    by_id = {n["id"]: n for n in vir["nodes"]}
    a, b = by_id["a"], by_id["b"]
    assert (a["width"], a["height"]) == (90, 40)
    assert (a["x"], a["y"]) == (8, 8)
    assert (b["x"], b["y"]) == (8 + 90 + 8, 8)

    # aとbは同じ高さで水平に並ぶため、中心を結ぶ直線は水平線になり、両端は
    # それぞれの箱の左右の縁(中央の高さ)で止まるはず(中心そのものではない)。
    center_y = a["y"] + a["height"] / 2
    [from_point, to_point] = vir["edges"][0]["points"]
    assert from_point == [a["x"] + a["width"], center_y]  # aの右辺
    assert to_point == [b["x"], center_y]  # bの左辺


def test_edge_kind_is_carried_through_to_view_ir():
    """表現力強化Stage 1: SVGレンダラーが種別ごとに矢印・線種を描き分けられる
    よう、edgeの'kind'をGraph IRからそのまま引き継ぐ。"""
    vir = _build_view_ir(_SAMPLE)
    edge = next(e for e in vir["edges"] if "subsetting" in e["id"])
    assert edge["kind"] == "subsetting"


def test_empty_graph_ir_produces_empty_view_ir():
    vir = build_view_ir({"nodes": [], "edges": []})
    assert vir == {"view_type": "structure", "nodes": [], "edges": []}


# --- collapsed_ids（Group2 b10, V4） --------------------------------------


def test_default_collapsed_ids_is_unchanged_behavior():
    """既存呼び出し（collapsed_ids省略時）は無変更で動作する（後方互換）。"""
    _, model = build_semantic_model(_SAMPLE.strip())
    gir = build_graph_ir(model)
    assert build_view_ir(gir) == build_view_ir(gir, collapsed_ids=None)


def test_collapsed_node_excludes_descendants_from_nodes():
    _, model = build_semantic_model(_SAMPLE.strip())
    gir = build_graph_ir(model)
    vir = build_view_ir(gir, collapsed_ids={"$root::Engine"})
    ids = {n["id"] for n in vir["nodes"]}
    assert "$root::Engine" in ids
    assert "$root::Engine::power" not in ids
    # 折りたたみ対象外のノード（Machine配下等）は影響を受けない。
    assert "$root::Machine::mass" in ids


def test_collapsed_node_is_sized_as_a_leaf():
    """折りたたんだノードは子を含めた包含サイズではなく、ラベルのみの
    最小サイズ（_leaf_size相当）で描画される。"""
    _, model = build_semantic_model(_SAMPLE.strip())
    gir = build_graph_ir(model)
    vir_expanded = build_view_ir(gir)
    vir_collapsed = build_view_ir(gir, collapsed_ids={"$root::Engine"})
    by_id_expanded = {n["id"]: n for n in vir_expanded["nodes"]}
    by_id_collapsed = {n["id"]: n for n in vir_collapsed["nodes"]}
    assert by_id_collapsed["$root::Engine"]["height"] < by_id_expanded["$root::Engine"]["height"]


def test_edges_into_collapsed_descendants_are_excluded():
    """折りたたみで除外された子孫を指すエッジ（例: power(engine配下)の
    feature_typing）は、両端の位置が存在しないため描画対象から除かれる。"""
    text = """
    package Vehicle {
        part def Machine {
            attribute mass : Real;
        }
        part def Engine :> Machine {
            part powerSource : Machine;
        }
    }
    """
    _, model = build_semantic_model(text.strip())
    gir = build_graph_ir(model)
    vir = build_view_ir(gir, collapsed_ids={"$root::Engine"})
    ids = {n["id"] for n in vir["nodes"]}
    assert "$root::Engine::powerSource" not in ids
    # powerSourceのfeature_typingエッジ自体が(KeyErrorにならず)除外されている。
    assert not any("powerSource" in edge["id"] for edge in vir["edges"])


# --- pinned_positions（Group3 b11, L1-1） ---------------------------------


def test_default_pinned_positions_is_unchanged_behavior():
    """既存呼び出し（pinned_positions省略時）は無変更で動作する（後方互換）。"""
    _, model = build_semantic_model(_SAMPLE.strip())
    gir = build_graph_ir(model)
    assert build_view_ir(gir) == build_view_ir(gir, pinned_positions=None)


def test_pinned_node_position_is_respected():
    _, model = build_semantic_model(_SAMPLE.strip())
    gir = build_graph_ir(model)
    vir = build_view_ir(gir, pinned_positions={"$root::Engine": {"x": 500, "y": 700}})
    by_id = {n["id"]: n for n in vir["nodes"]}
    assert (by_id["$root::Engine"]["x"], by_id["$root::Engine"]["y"]) == (500, 700)


def test_pinned_node_children_stay_relative_to_pinned_position():
    """ピン留めしたノードの子孫は、通常どおりその親を起点に相対配置される
    （包含関係を保つ）。"""
    _, model = build_semantic_model(_SAMPLE.strip())
    gir = build_graph_ir(model)
    vir = build_view_ir(gir, pinned_positions={"$root::Engine": {"x": 500, "y": 700}})
    by_id = {n["id"]: n for n in vir["nodes"]}
    parent = by_id["$root::Engine"]
    child = by_id["$root::Engine::power"]
    assert child["x"] >= parent["x"]
    assert child["y"] >= parent["y"]
    assert child["x"] + child["width"] <= parent["x"] + parent["width"]
    assert child["y"] + child["height"] <= parent["y"] + parent["height"]


def test_unpinned_siblings_are_unaffected_by_a_pin():
    _, model = build_semantic_model(_SAMPLE.strip())
    gir = build_graph_ir(model)
    vir_plain = build_view_ir(gir)
    vir_pinned = build_view_ir(gir, pinned_positions={"$root::Engine": {"x": 999, "y": 999}})
    by_id_plain = {n["id"]: n for n in vir_plain["nodes"]}
    by_id_pinned = {n["id"]: n for n in vir_pinned["nodes"]}
    assert by_id_plain["$root::Machine"] == by_id_pinned["$root::Machine"]
