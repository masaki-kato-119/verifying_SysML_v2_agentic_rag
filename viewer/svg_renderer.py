"""SVGレンダラー（SysMLv2_Viewer_実装仕様書.md 5章）。

View IRを純粋に走査してSVG文字列を生成する。乱数・現在時刻等の非決定要素は
一切使わない（同じView IR入力 → 常に同じSVGバイト列。5.1節）。
"""

import re
from html import escape
from typing import Dict, Optional

_MARGIN = 8
_NODE_FILL = "#f5f5f5"
_NODE_STROKE = "#333333"
_EDGE_STROKE = "#666666"
_TEXT_COLOR = "#111111"

# 表現力強化 Stage 1: 関連の種別ごとに矢印の形・線種を描き分ける
# （SysML/UML標準記法に近づける簡易対応。Stage 0では全エッジ同じ矢印だった）。
_MARKER_ARROW_FILLED = "sysml-arrow-filled"  # feature_typing・既定（未知の種別）
_MARKER_ARROW_HOLLOW = "sysml-arrow-hollow"  # specialization/subsetting/redefinition（継承系の慣習）
_MARKER_ARROW_OPEN = "sysml-arrow-open"  # satisfy/verify（要求適合の慣習に近い開いた矢印）

_MARKER_DEFS = (
    "<defs>"
    f'<marker id="{_MARKER_ARROW_FILLED}" viewBox="0 0 10 10" refX="9" refY="5"'
    f' markerWidth="6" markerHeight="6" orient="auto-start-reverse">'
    f'<path d="M 0 0 L 10 5 L 0 10 z" fill="{_EDGE_STROKE}" /></marker>'
    f'<marker id="{_MARKER_ARROW_HOLLOW}" viewBox="0 0 12 10" refX="11" refY="5"'
    f' markerWidth="8" markerHeight="7" orient="auto-start-reverse">'
    f'<path d="M 0 0 L 12 5 L 0 10 z" fill="#ffffff" stroke="{_EDGE_STROKE}" stroke-width="1" /></marker>'
    f'<marker id="{_MARKER_ARROW_OPEN}" viewBox="0 0 10 10" refX="9" refY="5"'
    f' markerWidth="7" markerHeight="7" orient="auto-start-reverse">'
    f'<path d="M 0 0 L 10 5 L 0 10" fill="none" stroke="{_EDGE_STROKE}" stroke-width="1.5" /></marker>'
    "</defs>"
)

# connectionは無方向（マーカー無し）。未知の種別（将来追加分）は既定の矢印にフォールバックする。
_KIND_MARKER = {
    "specialization": _MARKER_ARROW_HOLLOW,
    "subsetting": _MARKER_ARROW_HOLLOW,
    "redefinition": _MARKER_ARROW_HOLLOW,
    "feature_typing": _MARKER_ARROW_FILLED,
    "connection": None,
    "satisfy": _MARKER_ARROW_OPEN,
    "verify": _MARKER_ARROW_OPEN,
}

# satisfy/verifyは破線（要求適合はモデル要素間の直接構造ではなく「適合の主張」である
# ことを線種でも示す）。
# 表現力強化h6: feature_typingも破線にする。specialization等の継承系（実線＋
# 白抜き矢印）や、transition/succession/flow等が使う既定の実線＋塗り矢印
# フォールバックと同じ見た目になっていたため、「型付け」という別の関係種別
# であることが線種だけでは分からなかった。matrixの矢印形状（塗り矢印）は
# feature_typingのまま据え置き、線種の破線だけをsatisfy/verifyと差別化する
# （satisfy/verifyは開いた矢印、feature_typingは塗り矢印のため、破線同士でも
# 矢印の形で見分けが付く）。
_KIND_DASH = {
    "satisfy": "4 2",
    "verify": "4 2",
    "feature_typing": "4 2",
}

# **定義（`_def`）は直角、使用（`_usage`/`_instance`）は角丸。**
#
# SysML v2の図記法が定義と使用を角の形で区別しているので、それに合わせている
# （仕様書の Table 4 "Definition and Usage – Representative Notation"）。
# つまりこれは独自の工夫ではなく、規格への追従である。
#
# **2026-09-18にStage 3の実装を訂正した。** それまで角丸は「状態・アクション」を
# 表しており（`state_def`/`state_usage`/`action_def`/`action_usage`の4種類）、
# これはUMLで状態・アクションを角丸で描く慣習を持ち込んだものだった。SysML v2で
# 角の形が意味するのはdef/usageなので、この流用は規格と衝突していた――
# 「`state def`が角丸」は、SysML v2の記法で読めば「これはusageである」と
# 言っているに等しい。定義側を直角へ直したのはその訂正であって、
# 記法忠実度を下げる判断ではない。
#
# 境界上のポート（`_render_port_node`）はこの規則の対象外。ポートは矩形では
# なく境界上の小さな正方形で描いており、そこに角丸を入れても形が潰れて
# 読み取れないうえ、「ポートである」ことは既に形で分かっている。
_ROUNDED_CORNER_RADIUS = 10

# 表現力強化 h2: 状態遷移のtrigger/guard/effectラベル。UML/SysML標準記法の
# 慣習である「trigger [guard] / effect」文字列を、Semantic Model側
# （_format_transition_label）で組み立て済みの状態でedge["label"]として
# 受け取り、エッジの中点付近にテキストとして描画するだけの薄い対応とする。
_EDGE_LABEL_COLOR = "#444444"
_EDGE_LABEL_FONT_SIZE = 10

# 表現力強化 h1: 要素の種別キーワード表示。UMLのステレオタイプ表記に合わせ
# 「«part def»」のようにギユメで囲み、名前とは別の行に表示する（同じ行に
# 並べると読みにくいとのフィードバックにより2行表示へ変更）。ジオメトリは
# コンテナの見出し高さ（`view_ir.py`の`_LABEL_HEIGHT`）のみ2行分に拡張した。
# `_usage`と`_instance`のどちらも「使用」側として扱う。ステレオタイプ表記の
# 組み立て（_type_keyword）と角の形（_is_usage_type）の両方がこれを使う。
_USAGE_TYPE_SUFFIX_RE = re.compile(r"(_usage|_instance)$")
_TYPE_KEYWORD_COLOR = "#888888"
_TYPE_KEYWORD_FONT_SIZE = 9


def _type_keyword(node_type: str) -> str:
    """SysML v2の慣習に合わせ、定義（`_def`）は"part def"のように"def"を
    残し、使用（`_usage`/`_instance`）は接尾辞を落として"part"のように
    キーワードのみ表示する（定義・使用を区別する記法上意味のある差のため、
    単純な接尾辞除去ではなく`_def`だけ扱いを変える）。"""
    if node_type.endswith("_def"):
        return node_type[: -len("_def")].replace("_", " ") + " def"
    return _USAGE_TYPE_SUFFIX_RE.sub("", node_type).replace("_", " ")


def _is_usage_type(node_type: str) -> bool:
    """使用側（`_usage`/`_instance`）なら真。定義（`_def`）と、どちらでもない
    もの（`package`等）は偽。角の形をこれで決める（上の`_ROUNDED_CORNER_RADIUS`
    のコメント参照）。"""
    return bool(_USAGE_TYPE_SUFFIX_RE.search(node_type))


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


def _render_port_node(node: Dict) -> str:
    """表現力強化h5: ポートを、親の内部構成要素と同じ入れ子矩形ではなく、
    境界線をまたぐ小さな正方形（SysML標準のポート表記）として描く。
    正方形自体は小さく2行の種別＋名前を収める余地が無いため、名前は
    正方形の外側（配置された辺の外側）に1行の小さいテキストとして添え、
    種別キーワードはホバー用の<title>にのみ残す（クリックでのInspector連携は
    data-element-idが担うため、視覚情報を削っても要素の追跡性は失われない）。
    ラベルの左右は、View IR側が接続線の短さで決めた`port_side`
    （表現力強化: ポートの左右個別配置）にそのまま従う。左辺なら左に、
    右辺なら右にラベルを置き、ポートの箱を挟んでラベルが接続線と反対側に
    来るようにする。"""
    element_id = escape(node["id"], quote=True)
    node_type = escape(node["type"], quote=True)
    label = escape(node["label"])
    keyword = escape(_type_keyword(node["type"]))
    x, y, width, height = node["x"], node["y"], node["width"], node["height"]
    if node.get("port_side") == "right":
        label_x, text_anchor = x + width + 4, "start"
    else:
        label_x, text_anchor = x - 4, "end"
    return (
        f'<g class="sysml-node sysml-port-node" data-element-id="{element_id}" data-type="{node_type}"'
        f'{_source_range_attrs(node["source_range"])}>'
        f"<title>«{keyword}» {label}</title>"
        f'<rect x="{x}" y="{y}" width="{width}" height="{height}"'
        f' fill="{_NODE_FILL}" stroke="{_NODE_STROKE}" />'
        f'<text x="{label_x}" y="{y + height / 2 + 4}" fill="{_TEXT_COLOR}" font-size="10"'
        f' text-anchor="{text_anchor}">{label}</text>'
        f"</g>"
    )


def _render_node(node: Dict) -> str:
    if node.get("is_boundary_port"):
        return _render_port_node(node)

    element_id = escape(node["id"], quote=True)
    node_type = escape(node["type"], quote=True)
    label = escape(node["label"])
    keyword = escape(_type_keyword(node["type"]))
    x, y, width, height = node["x"], node["y"], node["width"], node["height"]
    corner_attrs = (
        f' rx="{_ROUNDED_CORNER_RADIUS}" ry="{_ROUNDED_CORNER_RADIUS}"'
        if _is_usage_type(node["type"])
        else ""
    )

    return (
        f'<g class="sysml-node" data-element-id="{element_id}" data-type="{node_type}"'
        f'{_source_range_attrs(node["source_range"])}>'
        f'<rect x="{x}" y="{y}" width="{width}" height="{height}"'
        f' fill="{_NODE_FILL}" stroke="{_NODE_STROKE}"{corner_attrs} />'
        f'<text x="{x + 6}" y="{y + 10}" fill="{_TEXT_COLOR}" font-size="12">'
        f'<tspan x="{x + 6}" fill="{_TYPE_KEYWORD_COLOR}" font-size="{_TYPE_KEYWORD_FONT_SIZE}">'
        f"«{keyword}»</tspan>"
        f'<tspan x="{x + 6}" dy="14">{label}</tspan>'
        f"</text>"
        f"</g>"
    )


def _render_edge(edge: Dict) -> str:
    edge_id = escape(edge["id"], quote=True)
    (x1, y1), (x2, y2) = edge["points"]
    kind = edge.get("kind")
    # 既知の種別で明示的にNoneが指定されていれば無方向(connection)、それ以外の
    # 未知の種別（将来のエッジ種別追加分）は既定の矢印にフォールバックする。
    marker_id = _KIND_MARKER[kind] if kind in _KIND_MARKER else _MARKER_ARROW_FILLED
    marker_attr = f' marker-end="url(#{marker_id})"' if marker_id else ""
    dash = _KIND_DASH.get(kind)
    dash_attr = f' stroke-dasharray="{dash}"' if dash else ""
    kind_attr = f' data-kind="{escape(kind, quote=True)}"' if kind else ""
    line = (
        f'<line class="sysml-edge" data-edge-id="{edge_id}"{kind_attr}'
        f' x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}"'
        f' stroke="{_EDGE_STROKE}" stroke-width="1"{dash_attr}{marker_attr} />'
    )
    label = edge.get("label")
    if not label:
        return line
    mid_x, mid_y = (x1 + x2) / 2, (y1 + y2) / 2
    label_text = (
        f'<text class="sysml-edge-label" x="{mid_x}" y="{mid_y - 4}"'
        f' fill="{_EDGE_LABEL_COLOR}" font-size="{_EDGE_LABEL_FONT_SIZE}"'
        f' text-anchor="middle">{escape(label)}</text>'
    )
    return line + label_text


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

    # 表現力強化 Stage 0: ノードを先に、エッジを後に描画する（旧実装は逆順
    # だった）。View IR側でエッジの両端が既にノードの矩形の縁で止まるよう
    # 計算されているため（view_ir.pyの_boundary_point）、この順序でもエッジが
    # ノードの矩形に隠れることはない。念のため後勝ちの描画順にしておくことで、
    # 座標計算の誤差やstroke-widthの分だけ縁にわずかに重なっても、エッジ側が
    # 上に来て見えなくなることを防ぐ。
    edges = view_ir["edges"]
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{canvas_width}"'
        f' height="{canvas_height}" viewBox="{min_x} {min_y} {canvas_width} {canvas_height}">',
    ]
    if edges:
        parts.append(_MARKER_DEFS)
    parts.extend(_render_node(n) for n in nodes)
    parts.extend(_render_edge(e) for e in edges)
    parts.append("</svg>")
    return "".join(parts)
