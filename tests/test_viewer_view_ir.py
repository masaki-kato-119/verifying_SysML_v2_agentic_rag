"""viewer.view_ir の新規ユニットテスト（SysMLv2_Viewer_実装仕様書.md 4章）。"""

from __future__ import annotations

from sysml_v2_checker_advanced.semantic_model import build_semantic_model
from viewer.graph_ir import build_graph_ir
from viewer.view_ir import _LABEL_HEIGHT, _PADDING, build_view_ir

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


# --- ポートの境界表示（表現力強化h5） --------------------------------------

_PORT_SAMPLE = """
package P {
    part def Battery {
        port chargePort;
        port dataPort;
        attribute capacity : Real;
    }
}
"""


def test_simple_port_is_marked_as_boundary_port_with_fixed_square_size():
    vir = _build_view_ir(_PORT_SAMPLE)
    by_id = {n["id"]: n for n in vir["nodes"]}
    port = by_id["$root::Battery::chargePort"]
    assert port["is_boundary_port"] is True
    assert (port["width"], port["height"]) == (14, 14)


def test_boundary_port_straddles_parent_left_edge_by_default():
    """接続（エッジ）を持たないポートは、従来通り左辺を既定にする
    （境界線をまたぐ表記のため、x座標が親のxよりちょうど正方形の半分だけ
    左にずれる）。"""
    vir = _build_view_ir(_PORT_SAMPLE)
    by_id = {n["id"]: n for n in vir["nodes"]}
    parent = by_id["$root::Battery"]
    port = by_id["$root::Battery::chargePort"]
    assert port["x"] == parent["x"] - port["width"] / 2


def test_non_port_nodes_are_not_marked_as_boundary_port():
    vir = _build_view_ir(_PORT_SAMPLE)
    by_id = {n["id"]: n for n in vir["nodes"]}
    assert by_id["$root::Battery"]["is_boundary_port"] is False
    assert by_id["$root::Battery::capacity"]["is_boundary_port"] is False


def test_port_with_its_own_children_falls_back_to_nested_box():
    """自身の子要素（例: flow property）を持つポートは、内容を消さないよう
    通常の入れ子矩形として扱う（境界線をまたぐ簡略表示にはしない）。"""
    text = """
    package P {
        part def Battery {
            port chargePort {
                attribute voltage : Real;
            }
        }
    }
    """
    vir = _build_view_ir(text)
    by_id = {n["id"]: n for n in vir["nodes"]}
    port = by_id["$root::Battery::chargePort"]
    assert port["is_boundary_port"] is False
    assert (port["width"], port["height"]) != (14, 14)
    assert "$root::Battery::chargePort::voltage" in by_id


def test_multiple_ports_are_stacked_without_overlap():
    vir = _build_view_ir(_PORT_SAMPLE)
    by_id = {n["id"]: n for n in vir["nodes"]}
    a = by_id["$root::Battery::chargePort"]
    b = by_id["$root::Battery::dataPort"]
    assert a["y"] + a["height"] <= b["y"]


# --- ポートの左右配置（接続線が短くなる側を個別に選ぶ） ---------------------

_TWO_SIDED_PORT_SAMPLE = """
package P {
    part def Battery {
        port leftish;
        port rightish;
    }
    part far1;
    part far2;
    connect Battery::leftish to far1;
    connect Battery::rightish to far2;
}
"""


def _build_view_ir_with_pins(text: str, pinned_positions):
    _, model = build_semantic_model(text.strip())
    return build_view_ir(build_graph_ir(model), pinned_positions=pinned_positions)


def test_port_moves_to_the_side_that_shortens_its_connection():
    """接続先が親の左右どちらにあるかに応じて、ポートごとに個別に左右を
    決める（辺の中央付近の位置は従来通り、左右どちらに置くかだけを変える）。"""
    vir = _build_view_ir_with_pins(
        _TWO_SIDED_PORT_SAMPLE,
        {
            "$root::Battery": {"x": 300, "y": 0},
            "$root::far1": {"x": -400, "y": 0},  # Batteryよりずっと左
            "$root::far2": {"x": 800, "y": 0},  # Batteryよりずっと右
        },
    )
    by_id = {n["id"]: n for n in vir["nodes"]}
    battery = by_id["$root::Battery"]
    leftish = by_id["$root::Battery::leftish"]
    rightish = by_id["$root::Battery::rightish"]
    # far1（左）に繋がるleftishは左辺、far2（右）に繋がるrightishは右辺。
    assert leftish["x"] == battery["x"] - leftish["width"] / 2
    assert rightish["x"] == battery["x"] + battery["width"] - rightish["width"] / 2


def test_port_connected_to_another_port_still_moves_to_the_shorter_side():
    """実際のバグ報告で発覚したケース: 接続先がpartではなく別のport自身の
    場合（例: 出力ポート→入力ポート）、その相手ポートも同じ「配置未確定の
    ポート一覧」に含まれる。処理順によっては相手ポートがまだpositionsに
    登録されておらず「相手が見つからない」ものとして扱われ、常に既定の
    左辺にフォールバックしてしまっていた（親ボックスの位置で近似することで
    修正）。"""
    text = """
    package P {
        part sender {
            port outp;
        }
        part receiver {
            port inp;
        }
        connect sender.outp to receiver.inp;
    }
    """
    vir = _build_view_ir_with_pins(
        text,
        {
            "$root::sender": {"x": -500, "y": 0},
            "$root::receiver": {"x": 500, "y": 0},
        },
    )
    by_id = {n["id"]: n for n in vir["nodes"]}
    receiver = by_id["$root::receiver"]
    inp = by_id["$root::receiver::inp"]
    sender = by_id["$root::sender"]
    outp = by_id["$root::sender::outp"]
    # receiverはsenderよりずっと右にあるため、inpはreceiverの左辺
    # （senderに近い側）へ来る。同様にoutpはsenderの右辺へ来る。
    assert inp["x"] == receiver["x"] - inp["width"] / 2
    assert outp["x"] == sender["x"] + sender["width"] - outp["width"] / 2


def test_port_without_a_resolvable_partner_position_defaults_to_left():
    """接続はあるが相手が現在のビューに存在しない（未解決や対象外）場合は、
    エラーにせず既定の左辺にフォールバックする。"""
    text = """
    package P {
        part def Battery {
            port p;
        }
        connect Battery::p to NoSuchElement;
    }
    """
    vir = _build_view_ir(text)
    by_id = {n["id"]: n for n in vir["nodes"]}
    battery = by_id["$root::Battery"]
    port = by_id["$root::Battery::p"]
    assert port["x"] == battery["x"] - port["width"] / 2


def test_ports_on_the_same_side_still_stack_without_overlap():
    vir = _build_view_ir_with_pins(
        _TWO_SIDED_PORT_SAMPLE,
        {
            "$root::Battery": {"x": 300, "y": 0},
            "$root::far1": {"x": -400, "y": 0},
            "$root::far2": {"x": -450, "y": 100},  # far1と同様、左側に置く。
        },
    )
    by_id = {n["id"]: n for n in vir["nodes"]}
    leftish = by_id["$root::Battery::leftish"]
    rightish = by_id["$root::Battery::rightish"]
    assert leftish["x"] == rightish["x"]  # 両方とも左辺に来る。
    lo, hi = sorted((leftish["y"], rightish["y"]))
    assert lo + leftish["height"] <= hi


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


# --- pinned_positions（Group3 b11/b12。表現力強化「手動レイアウトの階層
# 整合性」案Bで座標の意味を絶対座標→親の内容領域起点からの相対オフセットへ
# 変更した。親の内容領域の起点は「親の描画位置 + _PADDING（横）/
# _LABEL_HEIGHT + _PADDING（縦）」。ルート直下のノードは相対化の基準となる
# 親を持たないため従来どおり絶対座標のまま） -------------------------------


def test_default_pinned_positions_is_unchanged_behavior():
    """既存呼び出し（pinned_positions省略時）は無変更で動作する（後方互換）。"""
    _, model = build_semantic_model(_SAMPLE.strip())
    gir = build_graph_ir(model)
    assert build_view_ir(gir) == build_view_ir(gir, pinned_positions=None)


def test_pinned_node_position_is_relative_to_parent_content_origin():
    _, model = build_semantic_model(_SAMPLE.strip())
    gir = build_graph_ir(model)
    vir = build_view_ir(gir, pinned_positions={"$root::Engine": {"x": 500, "y": 700}})
    by_id = {n["id"]: n for n in vir["nodes"]}
    root = by_id["$root"]
    engine = by_id["$root::Engine"]
    expected_x = root["x"] + _PADDING + 500
    expected_y = root["y"] + _LABEL_HEIGHT + _PADDING + 700
    assert (engine["x"], engine["y"]) == (expected_x, expected_y)


def test_root_level_pin_is_still_absolute():
    """親を持たない（ルート直下の）ノードには相対化の基準となる親が無いため、
    従来どおり絶対座標のまま扱う。"""
    text = "package P { part def A; } package Q { part def B; }"
    _, model = build_semantic_model(text)
    gir = build_graph_ir(model)
    vir = build_view_ir(gir, pinned_positions={"$root::P": {"x": 300, "y": 400}})
    by_id = {n["id"]: n for n in vir["nodes"]}
    assert (by_id["$root::P"]["x"], by_id["$root::P"]["y"]) == (300, 400)


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
    """ピン留めされた子も自身の「通常時のスロット」の高さ分はcursorを
    進め続けるため、他の兄弟(Machine)の位置はピン留めの影響を受けない
    （b11時点で確立した保証の維持）。"""
    _, model = build_semantic_model(_SAMPLE.strip())
    gir = build_graph_ir(model)
    vir_plain = build_view_ir(gir)
    vir_pinned = build_view_ir(gir, pinned_positions={"$root::Engine": {"x": 999, "y": 999}})
    by_id_plain = {n["id"]: n for n in vir_plain["nodes"]}
    by_id_pinned = {n["id"]: n for n in vir_pinned["nodes"]}
    assert by_id_plain["$root::Machine"] == by_id_pinned["$root::Machine"]


def test_parent_expands_to_contain_a_pinned_child_dragged_outside_flow_area():
    """表現力強化「手動レイアウトの階層整合性」案B: 子要素を通常のフロー
    配置の外（左・上方向）へピン留めすると、親の矩形がそれを包含するよう
    自動的に広がる（ユーザー指摘: 親の外に子が出て見える不整合の解消）。"""
    _, model = build_semantic_model(_SAMPLE.strip())
    gir = build_graph_ir(model)
    vir_plain = build_view_ir(gir)
    vir_pinned = build_view_ir(gir, pinned_positions={"$root::Engine": {"x": -200, "y": -200}})
    by_id_plain = {n["id"]: n for n in vir_plain["nodes"]}
    by_id_pinned = {n["id"]: n for n in vir_pinned["nodes"]}

    root_plain = by_id_plain["$root"]
    root_pinned = by_id_pinned["$root"]
    engine_pinned = by_id_pinned["$root::Engine"]

    # Engineが左・上に大きくはみ出すため、$rootの矩形もそれを包含するよう
    # 左・上に広がる(x, yが小さくなり、width/heightが増える)。
    assert root_pinned["x"] < root_plain["x"]
    assert root_pinned["y"] < root_plain["y"]
    assert root_pinned["width"] > root_plain["width"]
    assert root_pinned["height"] > root_plain["height"]

    # Engine自身は$rootの矩形の内側に収まる(以前ははみ出していた)。
    assert engine_pinned["x"] >= root_pinned["x"]
    assert engine_pinned["y"] >= root_pinned["y"]
    assert engine_pinned["x"] + engine_pinned["width"] <= root_pinned["x"] + root_pinned["width"]
    assert engine_pinned["y"] + engine_pinned["height"] <= root_pinned["y"] + root_pinned["height"]


def test_pinning_a_child_to_its_normal_flow_position_is_a_no_op():
    """通常のフロー配置と全く同じ位置を明示的にピン留めしても出力は変わらない
    （無用な拡大をしないことの確認）。Engineは最初の子のため、通常時の
    フロー位置がちょうど内容領域の起点(相対オフセット(0, 0))と一致する。"""
    _, model = build_semantic_model(_SAMPLE.strip())
    gir = build_graph_ir(model)
    vir_plain = build_view_ir(gir)
    vir_pinned = build_view_ir(gir, pinned_positions={"$root::Engine": {"x": 0, "y": 0}})
    assert vir_plain == vir_pinned


# --- 親矩形が縮む（表現力強化: 高さの下限バグ修正） ------------------------
# ユーザー報告: 子要素をコンパクトに動かしても、親の高さがある一定
# （「全ての子を通常通り積んだ場合の高さ」）より小さくならない。

def test_parent_shrinks_when_all_children_are_pinned_into_a_compact_area():
    """全ての子をピン留めして重ねると、親はその重なった範囲だけを包含する
    大きさまで縮む（以前は「通常フロー時の高さ」が常に下限になっており
    縮まなかった）。"""
    _, model = build_semantic_model(_SAMPLE.strip())
    gir = build_graph_ir(model)
    vir_plain = build_view_ir(gir)
    vir_compact = build_view_ir(
        gir,
        pinned_positions={
            "$root::Engine": {"x": 0, "y": 0},
            "$root::Machine": {"x": 0, "y": 0},
            "$root::myEngine": {"x": 0, "y": 0},
        },
    )
    by_id_plain = {n["id"]: n for n in vir_plain["nodes"]}
    by_id_compact = {n["id"]: n for n in vir_compact["nodes"]}
    assert by_id_compact["$root"]["height"] < by_id_plain["$root"]["height"]
    # 重なり合った領域は、最も背の高い子（Engine、入れ子のpowerを持つため86px）
    # を包含できる大きさまでは縮む。
    tallest_child_height = max(n["height"] for nid, n in by_id_compact.items() if nid != "$root")
    assert by_id_compact["$root"]["height"] == _LABEL_HEIGHT + tallest_child_height + 2 * _PADDING


def test_parent_does_not_shrink_below_what_unpinned_siblings_still_need():
    """一部の子だけをピン留めして重ねても、ピン留めされていない残りの兄弟が
    通常のフロー配置で必要とする高さより親が縮むことはない。"""
    _, model = build_semantic_model(_SAMPLE.strip())
    gir = build_graph_ir(model)
    vir_plain = build_view_ir(gir)
    # EngineだけをMachineの位置に重ねる（myEngineはピン留めしない）。
    vir_partial = build_view_ir(gir, pinned_positions={"$root::Engine": {"x": 0, "y": 0}})
    by_id_plain = {n["id"]: n for n in vir_plain["nodes"]}
    by_id_partial = {n["id"]: n for n in vir_partial["nodes"]}
    # myEngine（ピン留めされていない）は通常のフロー位置のまま動かない。
    assert by_id_partial["$root::myEngine"] == by_id_plain["$root::myEngine"]
    # 親は、ピン留めされていないmyEngineを収めるのに必要な高さは維持する。
    my_engine = by_id_partial["$root::myEngine"]
    assert by_id_partial["$root"]["height"] >= (my_engine["y"] - by_id_partial["$root"]["y"]) + my_engine["height"]
