"""viewer.view_ir.build_flow_view_ir の新規ユニットテスト
（表現力強化 Stage 3, Group B f1: 状態遷移図・アクティビティ図向けの
層状レイアウト）。build_view_ir（入れ子矩形）とは独立した新規関数のため、
専用のテストファイルとする。
"""

from __future__ import annotations

from viewer.view_ir import build_flow_view_ir


def _node(nid, label=None):
    return {
        "id": nid, "type": "state_usage", "label": label or nid,
        "group_id": None, "source_range": None,
    }


def _edge(edge_id, from_id, to_id, kind="transition"):
    return {"id": edge_id, "from": from_id, "to": to_id, "kind": kind}


def test_simple_chain_is_layered_in_order():
    """A→B→Cの単純な鎖では、A=層0, B=層1, C=層2になる（yが単調に増える）。"""
    graph_ir = {
        "nodes": [_node("A"), _node("B"), _node("C")],
        "edges": [_edge("e1", "A", "B"), _edge("e2", "B", "C")],
    }
    vir = build_flow_view_ir(graph_ir)
    by_id = {n["id"]: n for n in vir["nodes"]}
    assert by_id["A"]["y"] < by_id["B"]["y"] < by_id["C"]["y"]


def test_nodes_with_same_layer_share_the_same_y():
    """共通の先行ノードを持つ2つのノード(B, C)は同じ層(同じy)に並ぶ。"""
    graph_ir = {
        "nodes": [_node("A"), _node("B"), _node("C")],
        "edges": [_edge("e1", "A", "B"), _edge("e2", "A", "C")],
    }
    vir = build_flow_view_ir(graph_ir)
    by_id = {n["id"]: n for n in vir["nodes"]}
    assert by_id["B"]["y"] == by_id["C"]["y"]
    assert by_id["B"]["x"] != by_id["C"]["x"]  # 同じ層内では横に並ぶ


def test_output_is_deterministic():
    graph_ir = {
        "nodes": [_node("A"), _node("B"), _node("C")],
        "edges": [_edge("e1", "A", "B"), _edge("e2", "B", "C")],
    }
    assert build_flow_view_ir(graph_ir) == build_flow_view_ir(graph_ir)


def test_cyclic_graph_does_not_crash_and_still_places_all_nodes():
    """A→B→A(循環)があっても例外を投げず、安全にフォールバックする
    （作業計画書のリスク欄で明示した要件）。"""
    graph_ir = {
        "nodes": [_node("A"), _node("B")],
        "edges": [_edge("e1", "A", "B"), _edge("e2", "B", "A")],
    }
    vir = build_flow_view_ir(graph_ir)
    ids = {n["id"] for n in vir["nodes"]}
    assert ids == {"A", "B"}
    for node in vir["nodes"]:
        assert node["x"] >= 0
        assert node["y"] >= 0


def test_disconnected_node_is_placed_at_layer_zero():
    """他のどのノードからも参照されないノードは層0(先頭)に置かれる。"""
    graph_ir = {
        "nodes": [_node("A"), _node("Isolated")],
        "edges": [],
    }
    vir = build_flow_view_ir(graph_ir)
    by_id = {n["id"]: n for n in vir["nodes"]}
    assert by_id["A"]["y"] == by_id["Isolated"]["y"]


def test_edges_terminate_at_node_boundaries():
    """Stage 0と同じ設計：エッジの両端は矩形の中心ではなく縁で止まる。"""
    graph_ir = {
        "nodes": [_node("A"), _node("B")],
        "edges": [_edge("e1", "A", "B")],
    }
    vir = build_flow_view_ir(graph_ir)
    by_id = {n["id"]: n for n in vir["nodes"]}
    a, b = by_id["A"], by_id["B"]
    edge = vir["edges"][0]
    from_point, to_point = edge["points"]
    a_center = [a["x"] + a["width"] / 2, a["y"] + a["height"] / 2]
    b_center = [b["x"] + b["width"] / 2, b["y"] + b["height"] / 2]
    assert from_point != a_center
    assert to_point != b_center


def test_edge_kind_is_carried_through():
    graph_ir = {
        "nodes": [_node("A"), _node("B")],
        "edges": [_edge("e1", "A", "B", kind="succession")],
    }
    vir = build_flow_view_ir(graph_ir)
    assert vir["edges"][0]["kind"] == "succession"


def test_edge_referencing_missing_node_is_excluded():
    """フィルタ等で片端のノードが対象外になったエッジは、KeyErrorにならず
    単純に除外される（build_view_irの折りたたみ由来エッジ除外と同じ考え方）。"""
    graph_ir = {
        "nodes": [_node("A")],
        "edges": [_edge("e1", "A", "NotInGraph")],
    }
    vir = build_flow_view_ir(graph_ir)
    assert vir["edges"] == []


def test_empty_graph_produces_empty_view_ir():
    vir = build_flow_view_ir({"nodes": [], "edges": []})
    assert vir["nodes"] == []
    assert vir["edges"] == []


def test_view_type_is_carried_through_from_graph_ir():
    graph_ir = {"view_type": "state_machine", "nodes": [_node("A")], "edges": []}
    vir = build_flow_view_ir(graph_ir)
    assert vir["view_type"] == "state_machine"


# --- 手動配置（pinned_positions、2026-09-18追加） -------------------------
#
# それまで状態遷移図・アクティビティ図だけがドラッグしても位置を覚えなかった
# （build_flow_view_ir が引数を持っていなかった）。構造ビュー側と違い、
# フローレイアウトは入れ子を作らないので**座標は絶対値**である。


def test_pinned_node_moves_to_the_given_absolute_position():
    graph_ir = {
        "nodes": [_node("A"), _node("B")],
        "edges": [_edge("e1", "A", "B")],
    }
    vir = build_flow_view_ir(graph_ir, pinned_positions={"B": {"x": 400, "y": 300}})
    by_id = {n["id"]: n for n in vir["nodes"]}
    assert (by_id["B"]["x"], by_id["B"]["y"]) == (400, 300)


def test_pinning_one_node_does_not_move_the_others():
    """build_view_ir が b11 で確立した「兄弟は影響を受けない」保証を、
    フロー側でも守る（層配置を計算し終えてから上書きする順序による）。"""
    graph_ir = {
        "nodes": [_node("A"), _node("B"), _node("C")],
        "edges": [_edge("e1", "A", "B"), _edge("e2", "B", "C")],
    }
    before = {n["id"]: (n["x"], n["y"]) for n in build_flow_view_ir(graph_ir)["nodes"]}
    after = {
        n["id"]: (n["x"], n["y"])
        for n in build_flow_view_ir(graph_ir, pinned_positions={"B": {"x": 400, "y": 300}})["nodes"]
    }
    assert after["A"] == before["A"]
    assert after["C"] == before["C"]
    assert after["B"] != before["B"]


def test_edges_follow_a_pinned_node():
    """ピン留めしたノードに繋がる線が元の位置に取り残されないこと。"""
    graph_ir = {
        "nodes": [_node("A"), _node("B")],
        "edges": [_edge("e1", "A", "B")],
    }
    before = build_flow_view_ir(graph_ir)
    after = build_flow_view_ir(graph_ir, pinned_positions={"B": {"x": 400, "y": 300}})
    assert after["edges"][0]["points"] != before["edges"][0]["points"]
    # 終点はピン留めしたBの矩形の境界上にあること（元の位置に取り残されて
    # いれば、この範囲から外れる）。
    b = next(n for n in after["nodes"] if n["id"] == "B")
    end_x, end_y = after["edges"][0]["points"][1]
    assert b["x"] <= end_x <= b["x"] + b["width"]
    assert b["y"] <= end_y <= b["y"] + b["height"]


def test_pinned_id_not_in_this_view_is_ignored():
    """ビューを跨いだ保存値や古いモデル由来のidが混じってもKeyErrorにしない
    （pinned_positionsはview_typeごとに分けて保存しているが、同じビュー内でも
    テキスト編集でノードが消えることがある）。"""
    graph_ir = {"nodes": [_node("A")], "edges": []}
    vir = build_flow_view_ir(graph_ir, pinned_positions={"GoneFromTheModel": {"x": 9, "y": 9}})
    assert [n["id"] for n in vir["nodes"]] == ["A"]


def test_pinned_positions_default_to_no_pinning():
    """引数を渡さない既存の呼び出しが従来どおり動く（後方互換）。"""
    graph_ir = {"nodes": [_node("A"), _node("B")], "edges": [_edge("e1", "A", "B")]}
    assert build_flow_view_ir(graph_ir) == build_flow_view_ir(graph_ir, pinned_positions=None)
