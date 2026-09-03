"""SVGレンダラー（SysMLv2_Viewer_実装仕様書.md 5章）。

View IRを純粋に走査してSVG文字列を生成する。乱数・現在時刻等の非決定要素は
一切使わない（同じView IR入力 → 常に同じSVGバイト列。5.1節）。
"""

from html import escape
from typing import Dict, Optional

_MARGIN = 8
_NODE_FILL = "#f5f5f5"
_NODE_STROKE = "#333333"
_EDGE_STROKE = "#666666"
_TEXT_COLOR = "#111111"


def _source_range_attrs(source_range: Optional[Dict]) -> str:
    """source_rangeをdata-*属性の文字列へ変換する（実装仕様書5.2節）。

    source_rangeがNone（ヘルパー関数経由で生成されctxが無いノード等。
    拡張仕様書5.2章）の場合は空文字列を返し、data-*属性自体を省略する。
    """
    if source_range is None:
        return ""
    return (
        f' data-start-offset="{source_range["start_offset"]}"'
        f' data-end-offset="{source_range["end_offset"]}"'
        f' data-start-line="{source_range["start_line"]}"'
        f' data-start-column="{source_range["start_column"]}"'
        f' data-end-line="{source_range["end_line"]}"'
        f' data-end-column="{source_range["end_column"]}"'
    )


def _render_node(node: Dict) -> str:
    element_id = escape(node["id"], quote=True)
    node_type = escape(node["type"], quote=True)
    label = escape(node["label"])
    x, y, width, height = node["x"], node["y"], node["width"], node["height"]

    return (
        f'<g class="sysml-node" data-element-id="{element_id}" data-type="{node_type}"'
        f'{_source_range_attrs(node["source_range"])}>'
        f'<rect x="{x}" y="{y}" width="{width}" height="{height}"'
        f' fill="{_NODE_FILL}" stroke="{_NODE_STROKE}" />'
        f'<text x="{x + 6}" y="{y + 16}" fill="{_TEXT_COLOR}" font-size="12">{label}</text>'
        f"</g>"
    )


def _render_edge(edge: Dict) -> str:
    edge_id = escape(edge["id"], quote=True)
    (x1, y1), (x2, y2) = edge["points"]
    return (
        f'<line class="sysml-edge" data-edge-id="{edge_id}"'
        f' x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}"'
        f' stroke="{_EDGE_STROKE}" stroke-width="1" />'
    )


def render_svg(view_ir: Dict) -> str:
    """View IRからSVG文字列を生成する。

    Args:
        view_ir: viewer.view_ir.build_view_ir() が返す
            {"view_type", "nodes": [...], "edges": [...]}

    Returns:
        SVG文字列（乱数・現在時刻を使わないため、同一入力なら常に同一出力）。
    """
    nodes = view_ir["nodes"]
    if nodes:
        # pinned_positions（手動ドラッグ配置、Group3 b11/b12）は既定の座標計算
        # （常に非負）と異なり負の座標にもなりうる。viewBoxの原点を0固定のまま
        # にすると、左・上方向へドラッグした要素がviewBox外に出て完全に不可視に
        # なってしまう（ドラッグできる範囲が不自然に狭く見える原因）。最小値も
        # 併せて計算し、viewBoxの原点をずらすことで負の座標も可視範囲に含める。
        min_x = min(n["x"] for n in nodes) - _MARGIN
        min_y = min(n["y"] for n in nodes) - _MARGIN
        max_x = max(n["x"] + n["width"] for n in nodes) + _MARGIN
        max_y = max(n["y"] + n["height"] for n in nodes) + _MARGIN
    else:
        min_x = min_y = 0
        max_x = max_y = _MARGIN * 2
    canvas_width = max_x - min_x
    canvas_height = max_y - min_y

    # エッジ(中心同士を結ぶ直線)を先に描画する。ノードは不透明な矩形なので
    # 後から重ねて描くと、線のうちボックス内部にある区間はボックスの下に
    # 隠れ、ボックス間の隙間の区間だけが可視になる（中心同士の直線でも
    # 見た目上は「ボックスの縁から縁」に近い自然な線になる）。
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{canvas_width}"'
        f' height="{canvas_height}" viewBox="{min_x} {min_y} {canvas_width} {canvas_height}">'
    ]
    parts.extend(_render_edge(e) for e in view_ir["edges"])
    parts.extend(_render_node(n) for n in nodes)
    parts.append("</svg>")
    return "".join(parts)
