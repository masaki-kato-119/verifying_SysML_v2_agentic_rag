"""viewer.svg_renderer の新規ユニットテスト（SysMLv2_Viewer_実装仕様書.md 5章）。"""

from __future__ import annotations

from pathlib import Path

import pytest

from sysml_v2_checker_advanced.semantic_model import build_semantic_model
from viewer.graph_ir import build_graph_ir
from viewer.svg_renderer import render_svg
from viewer.view_ir import build_view_ir

_FIXTURES_DIR = Path(__file__).parent / "fixtures" / "viewer"

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


def _render(text: str) -> str:
    _, model = build_semantic_model(text.strip())
    return render_svg(build_view_ir(build_graph_ir(model)))


def test_output_is_a_single_well_formed_svg_root():
    svg = _render(_SAMPLE)
    assert svg.startswith('<svg xmlns="http://www.w3.org/2000/svg"')
    assert svg.endswith("</svg>")
    assert svg.count("<svg") == 1


def test_node_carries_traceability_data_attributes():
    svg = _render(_SAMPLE)
    assert 'data-element-id="$root::Engine"' in svg
    assert 'data-type="part_def"' in svg
    assert 'data-start-line="5"' in svg
    assert 'data-start-offset="82"' in svg


def test_edge_is_rendered_as_line_with_id():
    svg = _render(_SAMPLE)
    assert '<line class="sysml-edge"' in svg
    assert "subsetting" in svg


def test_nodes_are_drawn_before_edges():
    """表現力強化Stage 0: ノードを先に描画し、エッジを後から重ねる
    （旧実装は逆順で、エッジがノードの矩形に隠れて見えなかった）。"""
    svg = _render(_SAMPLE)
    first_node_index = svg.index('<g class="sysml-node"')
    first_edge_index = svg.index('<line class="sysml-edge"')
    assert first_node_index < first_edge_index


def test_edge_has_arrow_marker():
    """表現力強化Stage 0: 関連の向き(→)を示す矢印マーカーを持つ。"""
    svg = _render(_SAMPLE)
    assert "<marker" in svg
    assert "marker-end=" in svg


# --- 種別ごとの矢印・線種（表現力強化 Stage 1） ----------------------------


def _render_single_edge(kind):
    view_ir = {
        "view_type": "structure",
        "nodes": [
            {"id": "a", "type": "part_def", "label": "A", "source_range": None,
             "x": 0, "y": 0, "width": 90, "height": 40},
            {"id": "b", "type": "part_def", "label": "B", "source_range": None,
             "x": 200, "y": 0, "width": 90, "height": 40},
        ],
        "edges": [{"id": "e", "kind": kind, "points": [[90, 20], [200, 20]]}],
    }
    return render_svg(view_ir)


def test_specialization_uses_hollow_arrow():
    svg = _render_single_edge("specialization")
    assert 'marker-end="url(#sysml-arrow-hollow)"' in svg


def test_subsetting_and_redefinition_use_hollow_arrow_too():
    assert 'marker-end="url(#sysml-arrow-hollow)"' in _render_single_edge("subsetting")
    assert 'marker-end="url(#sysml-arrow-hollow)"' in _render_single_edge("redefinition")


def test_feature_typing_uses_filled_arrow():
    svg = _render_single_edge("feature_typing")
    assert 'marker-end="url(#sysml-arrow-filled)"' in svg


def test_feature_typing_is_dashed_to_distinguish_from_default_fallback():
    """表現力強化h6: feature_typingは塗り矢印のまま破線にすることで、
    実線＋塗り矢印になる既定フォールバック（transition等）と見分けが付く
    ようにする。矢印の形自体（塗り）はsatisfy/verify（開いた矢印）とも
    見分けが付くため、破線+塗り矢印という組み合わせで一意になる。"""
    svg = _render_single_edge("feature_typing")
    assert 'stroke-dasharray="4 2"' in svg
    assert 'marker-end="url(#sysml-arrow-filled)"' in svg


def test_unknown_edge_kind_fallback_stays_solid():
    """既定フォールバック（未知の種別）は実線のまま。feature_typingの破線化
    がフォールバック全体に影響していないことを確認する。"""
    svg = _render_single_edge("some_future_kind")
    assert "stroke-dasharray=" not in svg


def test_connection_has_no_arrow_marker():
    """connectionは無方向として扱う（矢印マーカーを付けない）。"""
    svg = _render_single_edge("connection")
    assert "marker-end=" not in svg


def test_satisfy_and_verify_use_open_arrow_and_dashed_line():
    for kind in ("satisfy", "verify"):
        svg = _render_single_edge(kind)
        assert 'marker-end="url(#sysml-arrow-open)"' in svg
        assert 'stroke-dasharray="4 2"' in svg


def test_edge_carries_kind_as_data_attribute():
    svg = _render_single_edge("satisfy")
    assert 'data-kind="satisfy"' in svg


def test_unknown_edge_kind_falls_back_to_filled_arrow():
    """将来エッジ種別が追加されても描画がクラッシュせず、既定の矢印にフォールバックする。"""
    svg = _render_single_edge("some_future_kind")
    assert 'marker-end="url(#sysml-arrow-filled)"' in svg


# --- 状態遷移図（表現力強化 Stage 3, Group B f3） -------------------------


def _single_node_svg(node_type):
    return render_svg({
        "view_type": "structure",
        "nodes": [{
            "id": "$root::A", "type": node_type, "label": "A", "source_range": None,
            "x": 0, "y": 0, "width": 90, "height": 40,
        }],
        "edges": [],
    })


# 角の形は「定義か使用か」を表す。SysML v2の図記法がそう区別しているため
# （仕様書 Table 4 "Definition and Usage – Representative Notation"）。
# 2026-09-18以前は「状態・アクションかどうか」を表しておりstate_def/action_defも
# 角丸だったが、それはUMLの慣習の持ち込みで、SysML v2の記法とは衝突していた。
@pytest.mark.parametrize(
    "node_type",
    ["part_usage", "state_usage", "action_usage", "attribute_usage", "part_instance"],
)
def test_usage_nodes_are_rounded(node_type):
    assert 'rx="10" ry="10"' in _single_node_svg(node_type)


@pytest.mark.parametrize(
    "node_type",
    ["part_def", "state_def", "action_def", "requirement_def", "package"],
)
def test_definition_and_package_nodes_are_square(node_type):
    """`state_def`と`action_def`がここにいるのが訂正点。UMLの慣習を持ち込んで
    角丸にしていたが、SysML v2では角丸はusageを意味するので直角が正しい。"""
    assert "rx=" not in _single_node_svg(node_type)


def test_definition_and_its_usage_are_told_apart_by_shape():
    """同じ`part`でも def と usage で形が変わる、というのがこの規則の要点。"""
    assert "rx=" not in _single_node_svg("part_def")
    assert 'rx="10" ry="10"' in _single_node_svg("part_usage")


def test_transition_edge_gets_a_directional_arrow():
    """transitionはStage 1の_KIND_MARKERに個別エントリが無いため、既定の
    塗り矢印にフォールバックする（それでも「方向のある矢印」という
    f3の要件は満たす）。"""
    svg = _render_single_edge("transition")
    assert 'marker-end="url(#sysml-arrow-filled)"' in svg
    assert 'data-kind="transition"' in svg


def test_end_to_end_activity_renders_rounded_actions_with_arrows():
    """Semantic Model→Graph IR(activity)→build_flow_view_ir→render_svg
    の全経路を、実際にパースしたアクション連鎖で通しで確認する。"""
    from sysml_v2_checker_advanced.semantic_model import build_semantic_model
    from viewer.graph_ir import VIEW_TYPE_ACTIVITY, build_graph_ir
    from viewer.view_ir import build_flow_view_ir

    text = """
    action def Act {
        action step1;
        action step2;
        first step1 then step2;
    }
    """
    _, model = build_semantic_model(text.strip())
    gir = build_graph_ir(model, view_type=VIEW_TYPE_ACTIVITY)
    vir = build_flow_view_ir(gir)
    svg = render_svg(vir)

    # step1 + step2 のみ。Act は action **def** なので直角（2026-09-18の規則変更）。
    assert svg.count('rx="10" ry="10"') == 2
    assert svg.count('data-kind="succession"') == 1
    assert "<marker" in svg


def test_end_to_end_state_machine_renders_rounded_states_with_arrows():
    """Semantic Model→Graph IR(state_machine)→build_flow_view_ir→render_svg
    の全経路を、実際にパースした状態機械で通しで確認する。"""
    from sysml_v2_checker_advanced.semantic_model import build_semantic_model
    from viewer.graph_ir import VIEW_TYPE_STATE_MACHINE, build_graph_ir
    from viewer.view_ir import build_flow_view_ir

    text = """
    state def AdvancedSwitch {
        entry; then Off;
        state Off;
        state On;
        transition first Off accept TurnOn then On;
        transition OnToOff first On accept TurnOff then Off;
    }
    """
    _, model = build_semantic_model(text.strip())
    gir = build_graph_ir(model, view_type=VIEW_TYPE_STATE_MACHINE)
    vir = build_flow_view_ir(gir)
    svg = render_svg(vir)

    # Off + On のみ。AdvancedSwitch は state **def** なので直角。
    assert svg.count('rx="10" ry="10"') == 2
    assert svg.count('data-kind="transition"') == 3
    assert "<marker" in svg


def test_node_shows_dimmed_type_keyword_above_label():
    """表現力強化 h1: ノードの名前の上に、ギユメで囲んだ種別キーワードを
    別行（UMLのステレオタイプ表記）として小さく薄い色で添える。
    SysML v2の慣習に合わせ、定義（_def）は"part def"のように"def"を残し、
    使用（_usage）は接尾辞を落として"part"のみ表示する。"""
    svg = _render(_SAMPLE)
    assert '<tspan x="22" fill="#888888" font-size="9">«part def»</tspan>' in svg
    assert '<tspan x="22" dy="14">Engine</tspan>' in svg
    assert "«part»" in svg  # myEngine (part_usage、defを含まないキーワード)


def test_type_keyword_distinguishes_def_from_usage():
    from viewer.svg_renderer import _type_keyword

    assert _type_keyword("part_def") == "part def"
    assert _type_keyword("part_usage") == "part"
    assert _type_keyword("state_def") == "state def"
    assert _type_keyword("state_usage") == "state"
    assert _type_keyword("satisfy_requirement_usage") == "satisfy requirement"


def test_transition_edge_with_trigger_guard_effect_renders_label():
    """表現力強化 h2: transitionのtrigger/guard/effectを
    「trigger [guard] / effect」形のラベルとしてエッジ中点付近に描画する。"""
    from sysml_v2_checker_advanced.semantic_model import build_semantic_model
    from viewer.graph_ir import VIEW_TYPE_STATE_MACHINE, build_graph_ir
    from viewer.view_ir import build_flow_view_ir

    text = """
    state def PowerState {
        state Off;
        state On;
        transition first Off accept TurnOn if powerLevel > 0.0 do action logStart then On;
    }
    """
    _, model = build_semantic_model(text.strip())
    gir = build_graph_ir(model, view_type=VIEW_TYPE_STATE_MACHINE)
    vir = build_flow_view_ir(gir)
    svg = render_svg(vir)

    assert 'class="sysml-edge-label"' in svg
    assert "TurnOn [powerLevel &gt; 0.0] / logStart" in svg


def test_transition_edge_without_label_renders_no_label_text():
    """暗黙遷移などtrigger/guard/effectを持たないtransitionは、ラベル用の
    <text>を一切出力しない（既存の描画を無駄に増やさない）。"""
    svg = _render_single_edge("connection")
    assert 'class="sysml-edge-label"' not in svg


def test_boundary_port_renders_as_small_square_with_external_label():
    """表現力強化h5: 境界線をまたぐポートは、他ノードと同じ入れ子矩形の
    2行ラベルではなく、小さい正方形＋外側の1行ラベル＋ホバー用titleで描く。"""
    view_ir = {
        "view_type": "structure",
        "nodes": [
            {"id": "$root::Battery", "type": "part_def", "label": "Battery", "source_range": None,
             "x": 16, "y": 46, "width": 106, "height": 86, "is_boundary_port": False},
            {"id": "$root::Battery::chargePort", "type": "port_usage", "label": "chargePort",
             "source_range": None, "x": 9, "y": 72, "width": 14, "height": 14, "is_boundary_port": True},
        ],
        "edges": [],
    }
    svg = render_svg(view_ir)
    assert 'class="sysml-node sysml-port-node"' in svg
    assert "<title>«port» chargePort</title>" in svg
    assert '<rect x="9" y="72" width="14" height="14"' in svg
    assert 'text-anchor="end">chargePort</text>' in svg
    # 通常ノードの2行ラベル（ステレオタイプ+名前を分けるtspan）は使わない。
    port_node_markup = svg.split('data-element-id="$root::Battery::chargePort"')[1].split("</g>")[0]
    assert "<tspan" not in port_node_markup


def test_right_side_port_places_its_label_on_the_right():
    """表現力強化: 右辺に配置されたポート（View IR側の`port_side`）は、
    ラベルも箱の右側に置く（左辺固定だった頃はラベルが常に左だったため、
    右辺のポートでは箱と重なってしまっていた）。"""
    view_ir = {
        "view_type": "structure",
        "nodes": [
            {"id": "$root::Battery", "type": "part_def", "label": "Battery", "source_range": None,
             "x": 16, "y": 46, "width": 106, "height": 86, "is_boundary_port": False},
            {"id": "$root::Battery::dataPort", "type": "port_usage", "label": "dataPort",
             "source_range": None, "x": 115, "y": 72, "width": 14, "height": 14,
             "is_boundary_port": True, "port_side": "right"},
        ],
        "edges": [],
    }
    svg = render_svg(view_ir)
    assert 'text-anchor="start">dataPort</text>' in svg
    assert '<text x="133' in svg  # x(115) + width(14) + 4


def test_no_marker_defs_when_there_are_no_edges():
    """エッジが1本も無い場合はdefs自体を出さない（出力を無駄に増やさない）。"""
    view_ir = {
        "view_type": "structure",
        "nodes": [{
            "id": "$root::a", "type": "part_def", "label": "A", "source_range": None,
            "x": 0, "y": 0, "width": 90, "height": 40,
        }],
        "edges": [],
    }
    svg = render_svg(view_ir)
    assert "<defs>" not in svg
    assert "<marker" not in svg


def test_output_is_deterministic():
    assert _render(_SAMPLE) == _render(_SAMPLE)


def test_label_with_special_characters_is_escaped():
    """エスケープ自体はレンダラー単体の責務のため、SysML文法の制約を経由せず
    view_irを直接組み立てて検証する（引用符付き名前がXMLで問題になる文字を
    許容するかは文法依存であり、このテストの関心事ではない）。"""
    view_ir = {
        "view_type": "structure",
        "nodes": [{
            "id": "$root::x",
            "type": "part_def",
            "label": "A<B&C\"D",
            "source_range": None,
            "x": 0, "y": 0, "width": 100, "height": 40,
        }],
        "edges": [],
    }
    svg = render_svg(view_ir)
    assert "A&lt;B&amp;C&quot;D" in svg
    assert "A<B&C\"D" not in svg  # 生の特殊文字がそのままSVGに漏れていない


def test_svg_output_matches_golden_fixture():
    """固定入力に対するSVG出力をゴールデンファイルと比較する（実装仕様書5.1節：
    決定性の担保。乱数・現在時刻を使わないため、同じ入力は常に同じバイト列に
    なるはずで、ズレが生じたらレンダラーの変更が意図せぬ出力変化を
    起こしていないか要確認）。ゴールデンファイルは
    tests/fixtures/viewer/vehicle_sample.svg。意図的な出力変更をした場合は
    このフィクスチャを再生成すること。
    """
    golden = (_FIXTURES_DIR / "vehicle_sample.svg").read_text(encoding="utf-8")
    assert _render(_SAMPLE) == golden


def test_empty_view_ir_still_produces_valid_svg():
    svg = render_svg({"view_type": "structure", "nodes": [], "edges": []})
    assert svg == '<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 16 16"></svg>'


def test_negative_node_position_stays_within_viewbox():
    """手動ドラッグ配置（Group3 b11/b12, pinned_positions）で左・上方向に
    動かした要素は負の座標になりうる。viewBoxの原点が0固定のままだと、
    そのノードがviewBox外に出て完全に不可視になってしまう不具合があったため、
    viewBoxの原点も負の座標を含むよう動かすことを確認する。"""
    view_ir = {
        "view_type": "structure",
        "nodes": [
            {"id": "$root::a", "type": "part_def", "label": "A", "source_range": None,
             "x": -50, "y": -30, "width": 90, "height": 40},
            {"id": "$root::b", "type": "part_def", "label": "B", "source_range": None,
             "x": 100, "y": 100, "width": 90, "height": 40},
        ],
        "edges": [],
    }
    svg = render_svg(view_ir)
    assert 'viewBox="-58 -38 256 186"' in svg
    # 負座標のノード自体はそのままの座標で描画される(移動しているのはviewBoxの原点だけ)。
    assert 'x="-50" y="-30"' in svg


def test_all_non_negative_positions_keep_viewbox_origin_at_zero():
    """既存の（pinned_positions未使用の）通常レイアウトでは常にx,y>=8のため、
    負のノードが無いケースでviewBoxの原点が動いてしまわないことを確認する
    （後方互換：ゴールデンファイルテストが暗黙に前提としている挙動の明示化）。"""
    view_ir = {
        "view_type": "structure",
        "nodes": [
            {"id": "$root::a", "type": "part_def", "label": "A", "source_range": None,
             "x": 8, "y": 8, "width": 90, "height": 40},
        ],
        "edges": [],
    }
    svg = render_svg(view_ir)
    assert 'viewBox="0 0 106 56"' in svg
