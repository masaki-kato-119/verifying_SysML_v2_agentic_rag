"""viewer.svg_renderer の新規ユニットテスト（SysMLv2_Viewer_実装仕様書.md 5章）。"""

from __future__ import annotations

from pathlib import Path

from sysml_v2_checker_advanced.semantic_model import build_semantic_model
from viewer.graph_ir import build_graph_ir
from viewer.view_ir import build_view_ir
from viewer.svg_renderer import render_svg

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
