"""影響範囲の走査（viewer/impact.py）。

2026-09-14にフロントエンド（viewer/frontend/app.js）から移設した。移設の主目的が
**この走査の意味論を自動テストで固定すること**なので、方向づけの表がそのまま
テストになっている。
"""

from __future__ import annotations

from viewer.impact import (
    IMPACT_DEPTH,
    attach_owner_element_ids,
    build_impact_adjacency,
    build_impact_map,
    find_impacted_elements,
    impact_origin_id,
    resolve_finding_node_id,
)


def _edges(*triples):
    return [{"from": f, "to": t, "kind": k} for f, t, k in triples]


def test_declaration_kinds_propagate_against_the_edge():
    """型付け・継承・satisfy/verify は「参照先が変われば参照元が影響を受ける」。

    `semantic_model.py` の `_make_edge` は from=宣言している側・to=参照先で
    エッジを作るので、影響はエッジを逆に辿る。
    """
    for kind in ("specialization", "subsetting", "redefinition", "feature_typing",
                 "satisfy", "verify"):
        adjacency = build_impact_adjacency(_edges(("user", "target", kind)))
        assert [i["id"] for i in find_impacted_elements(adjacency, "target")] == ["user"], kind
        assert find_impacted_elements(adjacency, "user") == [], kind


def test_behavioural_kinds_propagate_along_the_edge():
    """transition/succession/flow は from=source なので向きがそのまま影響の向き。"""
    for kind in ("transition", "succession", "flow"):
        adjacency = build_impact_adjacency(_edges(("a", "b", kind)))
        assert [i["id"] for i in find_impacted_elements(adjacency, "a")] == ["b"], kind
        assert find_impacted_elements(adjacency, "b") == [], kind


def test_connection_is_undirected_and_unknown_kinds_default_to_undirected():
    """コネクタは上下が決まらないので無向。未知の種別も同じ扱い（安全側）。"""
    for kind in ("connection", "some_future_kind"):
        adjacency = build_impact_adjacency(_edges(("c", "a", kind)))
        assert [i["id"] for i in find_impacted_elements(adjacency, "a")] == ["c"], kind
        assert [i["id"] for i in find_impacted_elements(adjacency, "c")] == ["a"], kind


def test_distance_and_kinds_are_reported_and_depth_is_bounded():
    """何次で・何を通じて影響するかを返す。IMPACT_DEPTH を超えた先は辿らない。"""
    adjacency = build_impact_adjacency(_edges(
        ("Derived", "Base", "subsetting"),
        ("d", "Derived", "feature_typing"),
        ("e", "d", "feature_typing"),
    ))
    impacted = find_impacted_elements(adjacency, "Base")
    assert [(i["id"], i["distance"], i["kinds"]) for i in impacted] == [
        ("Derived", 1, ["subsetting"]),
        ("d", 2, ["feature_typing"]),
    ]
    assert IMPACT_DEPTH == 2
    # 深さを上げれば3次先も入る（定数の変更が効くことの確認）
    assert [i["id"] for i in find_impacted_elements(adjacency, "Base", depth=3)] == [
        "Derived", "d", "e",
    ]


def test_origin_is_the_owning_element_for_findings_on_inner_references():
    """Findingは要素内の参照（無名ノード）に付くことがあり、そのidはGraph IRに無い。

    無名ノードのstable_idは `<所有者のid>/<型>#<連番>`（antlr_transformer.py）。
    """
    assert impact_origin_id("$root::A::g/name_ref#0") == "$root::A::g"
    assert impact_origin_id("$root::A::g/expr#0/name_ref#1") == "$root::A::g"
    assert impact_origin_id("$root::A") == "$root::A"
    assert impact_origin_id("") == ""


def test_build_impact_map_covers_every_graph_node():
    """全ノード分を返す（Finding一覧とSVGハイライトが同じ表を使うため）。"""
    graph_ir = {
        "nodes": [{"id": "Base"}, {"id": "Derived"}, {"id": "lonely"}],
        "edges": _edges(("Derived", "Base", "subsetting")),
    }
    impact = build_impact_map(graph_ir)
    assert set(impact) == {"Base", "Derived", "lonely"}
    assert [i["id"] for i in impact["Base"]] == ["Derived"]
    assert impact["Derived"] == []
    assert impact["lonely"] == []




# --- Findingを図上のノードへ寄せる（2026-09-18） --------------------------
#
# 図のオーバーレイと重要度フィルタが生の`element_id`で突き合わせており、
# 描画ノードに当たらないFindingに対して黙って何もしていなかった。


def test_finding_on_a_rendered_node_resolves_to_itself():
    assert resolve_finding_node_id("$root::A::g", {"$root::A::g", "$root::A"}) == "$root::A::g"


def test_finding_on_an_inner_reference_resolves_to_the_nearest_rendered_ancestor():
    """`<所有者>/<型>#<連番>` 形は描画されないので、所有者まで上がる。"""
    node_ids = {"$root::A::g", "$root::A"}
    assert resolve_finding_node_id("$root::A::g/name_ref#0", node_ids) == "$root::A::g"


def test_an_id_containing_a_slash_is_kept_when_it_is_itself_rendered():
    """**これが2026-09-18に実測で見つかった落とし穴。** `/`を含むidが描画される
    ノードのidであることは普通にある（コーパスの`/`付きFinding 231件中172件）。
    無条件に最初の`/`で切ると、指摘の主語ではなく数階層上の祖先に色が付く。
    """
    rendered = "$root::S::home_b/port_usage#0::commandReceived"
    node_ids = {rendered, "$root::S::home_b", "$root::S"}
    assert resolve_finding_node_id(rendered, node_ids) == rendered
    # impact_origin_id はここでは使えない（切りすぎる）ことを併記しておく。
    assert impact_origin_id(rendered) == "$root::S::home_b"


def test_resolution_walks_up_through_both_separator_kinds():
    """`::`（名前付きの入れ子）と`/`（無名ノード）のどちらも1階層として辿る。"""
    node_ids = {"$root::S::home_b"}
    assert (
        resolve_finding_node_id("$root::S::home_b/port_usage#0::x::y", node_ids)
        == "$root::S::home_b"
    )


def test_resolution_is_none_when_nothing_matches():
    """寄せ先が無いものを無理に結び付けない。無関係な要素が指摘を持っている
    ように見える方が、フィルタに載らないことより悪い。"""
    assert resolve_finding_node_id("$root::NoSuchPackage", {"$root::A"}) is None
    assert resolve_finding_node_id("", {"$root::A"}) is None


def test_attach_owner_element_ids_fills_the_field_for_every_finding():
    node_ids = {"$root::A::g", "$root::A"}
    findings = [
        {"element_id": "$root::A::g/name_ref#0", "severity": "error", "rule": "_check_x"},
        {"element_id": None, "severity": "warning"},
        {"element_id": "$root::Nowhere", "severity": "info"},
    ]
    attach_owner_element_ids(findings, node_ids)
    assert [f["owner_element_id"] for f in findings] == ["$root::A::g", None, None]
    # 元のフィールドは触らない（source_range等の対応付けに要る）。
    assert findings[0]["element_id"] == "$root::A::g/name_ref#0"
    assert findings[0]["rule"] == "_check_x"
