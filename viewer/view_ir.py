"""View IR構築とレイアウト（SysMLv2_Viewer_実装仕様書.md 4章）。

Graph IRから、決定的（乱数・現在時刻を一切使わない）な入れ子ボックス
レイアウトを持つView IRを作る。Phase Aでは「構造ビュー」1種類のみ。
"""

from typing import Dict, List, Optional, Tuple

# レイアウト定数（実装仕様書4.2節：力学モデル等の非決定的手法を避け、
# 固定パラメータによる決定的な再帰配置にする）。
_PADDING = 8
_LABEL_HEIGHT = 24
_MIN_WIDTH = 90
_MIN_HEIGHT = 40
_CHAR_WIDTH = 8  # ラベル長からの概算幅（フォントメトリクスは使わない簡易推定）


def _leaf_size(label: str) -> Tuple[int, int]:
    width = max(_MIN_WIDTH, len(label) * _CHAR_WIDTH + 2 * _PADDING)
    return width, _MIN_HEIGHT


def build_view_ir(graph_ir: Dict, collapsed_ids=None, pinned_positions=None) -> Dict:
    """Graph IRからView IR（構造ビュー）を構築する。

    Args:
        graph_ir: {"nodes": [{"id","type","label","group_id"}, ...],
            "edges": [{"id","from","to","kind"}, ...]}（viewer.graph_ir参照）
        collapsed_ids: 折りたたむノードidの集合（Group2 b10, V4）。指定した
            ノードの子孫（孫以降を含む）をレイアウト計算・出力の両方から
            除外し、指定ノード自身は子を持たない葉として最小サイズで描画する。
            省略時は従来どおり全ノードを描画する（後方互換）。
        pinned_positions: 手動配置を尊重するノードid→{"x","y"}の辞書
            （Group3 b11/b12。表現力強化「手動レイアウトの階層整合性」案Bで
            座標の意味を変更した）。**親を持つノードについては、値は親の
            内容領域の起点（親の描画位置 + パディング + ラベル高さ。非ピン留め
            の子が通常並ぶのと同じ基準点）からの相対オフセットとして解釈する。
            親要素はこの相対オフセットも包含するよう自身のサイズを拡張する**
            （子が親の矩形からはみ出して見える不整合を解消するため）。
            親を持たない（ルート直下の）ノードは、相対化の基準となる親が
            存在しないため従来どおり絶対座標のまま扱う。
            兄弟の通常配置（フロー配置）はピン留めの有無に関わらず必ず計算し
            続ける――ピン留めされた子も自身の「通常時のスロット」の高さ分は
            引き続きcursorを進めるため、ピン留めしても他の兄弟の位置はずれない
            （b11時点で確立した「兄弟は影響を受けない」という保証を維持する）。
            重なり自体を解消する制約解法までは行わない――既存コードの
            「手動調整はPhase D以降の課題」という割り切り（4.2節）を踏襲した
            設計判断。省略時は従来どおり（後方互換）。

    Returns:
        {"view_type": graph_irのview_type（省略時は"structure"を既定とする）,
         "nodes": [{"id","x","y","width","height"}, ...]（絶対座標）,
         "edges": [{"id","kind","points": [[x,y],[x,y]]}, ...]}
        （"kind"は表現力強化Stage 1でSVGレンダラーが矢印・線種を描き分けるために
        Graph IRからそのまま引き継ぐ）
    """
    collapsed_ids = collapsed_ids or set()
    pinned_positions = pinned_positions or {}
    nodes_by_id = {n["id"]: n for n in graph_ir["nodes"]}

    children_by_parent: Dict[Optional[str], List[str]] = {}
    for node in graph_ir["nodes"]:
        children_by_parent.setdefault(node["group_id"], []).append(node["id"])
    # 同一入力に対し常に同じ配置になるよう、子の並びをstable_idの辞書順に固定する。
    for parent_id in children_by_parent:
        children_by_parent[parent_id].sort()

    # collapsed_idsで指定されたノードの子孫（孫以降を含む）を、レイアウト・
    # 出力の両方から除外する集合として先に確定させる。
    excluded_ids: set = set()

    def _collect_descendants(node_id: str) -> None:
        for child_id in children_by_parent.get(node_id, []):
            if child_id not in excluded_ids:
                excluded_ids.add(child_id)
                _collect_descendants(child_id)

    for collapsed_id in collapsed_ids:
        if collapsed_id in nodes_by_id:
            _collect_descendants(collapsed_id)

    def _children_of(node_id) -> List[str]:
        if node_id in collapsed_ids:
            return []  # 折りたたみ対象自身は子を持たない葉として扱う。
        return [c for c in children_by_parent.get(node_id, []) if c not in excluded_ids]

    sizes: Dict[str, Tuple[int, int]] = {}
    positions: Dict[str, Tuple[int, int]] = {}
    # ノードごとの「フロー原点からのずれ」。ピン留めされた子が通常のフロー
    # 領域より左・上にはみ出す場合、親の矩形自体をその分だけ左・上に広げる
    # 必要がある。この値がその「広げ幅」（0以下の値）を保持する。
    content_offset: Dict[str, Tuple[int, int]] = {}

    def compute_size(node_id: str) -> Tuple[int, int]:
        children = _children_of(node_id)
        if not children:
            size = _leaf_size(nodes_by_id[node_id]["label"])
            sizes[node_id] = size
            content_offset[node_id] = (0, 0)
            return size

        # 通常のフロー配置は、ピン留めの有無に関わらず全ての子について計算する
        # （後述のplace()でも同様。兄弟の位置をピン留めの影響から独立させるため）。
        child_sizes = [compute_size(c) for c in children]
        flow_width = max(w for w, _h in child_sizes)
        flow_height = sum(h for _w, h in child_sizes) + _PADDING * (len(children) - 1)

        # 親の内容領域は「通常のフロー領域」と「各ピン留め子の相対矩形」の
        # 和集合の外接矩形にする。ピン留め子がフロー領域より左・上にはみ出す
        # 場合はcontent_left/topが負になり、後述のplace()で親の矩形自体を
        # その分だけ左・上にずらして広げる。
        content_left, content_top = 0, 0
        content_right, content_bottom = flow_width, flow_height
        for child_id in children:
            pinned = pinned_positions.get(child_id)
            if pinned is None:
                continue
            child_w, child_h = sizes[child_id]
            content_left = min(content_left, pinned["x"])
            content_top = min(content_top, pinned["y"])
            content_right = max(content_right, pinned["x"] + child_w)
            content_bottom = max(content_bottom, pinned["y"] + child_h)

        width = max(_MIN_WIDTH, (content_right - content_left) + 2 * _PADDING)
        height = _LABEL_HEIGHT + (content_bottom - content_top) + 2 * _PADDING
        size = (width, height)
        sizes[node_id] = size
        content_offset[node_id] = (content_left, content_top)
        return size

    def place(node_id: str, anchor_x: int, anchor_y: int) -> None:
        """anchor_x/yは「親から見た通常のフロー配置上の位置」。実際の矩形は
        content_offset分だけずらして配置する（ピン留め子を包含するための
        拡張分。ピン留めが無ければcontent_offsetは(0, 0)で従来と同じ）。"""
        offset_x, offset_y = content_offset.get(node_id, (0, 0))
        x, y = anchor_x + offset_x, anchor_y + offset_y
        positions[node_id] = (x, y)
        children = _children_of(node_id)
        if not children:
            return
        origin_x = anchor_x + _PADDING
        origin_y = anchor_y + _LABEL_HEIGHT + _PADDING
        cursor_y = origin_y
        for child_id in children:
            flow_y = cursor_y
            cursor_y += sizes[child_id][1] + _PADDING  # ピン留めの有無に関わらず必ず進める
            pinned = pinned_positions.get(child_id)
            if pinned is not None:
                place(child_id, origin_x + pinned["x"], origin_y + pinned["y"])
            else:
                place(child_id, origin_x, flow_y)

    # group_id が None のノード（ルートのみのはず。Semantic Modelのルートは
    # 常に1個。$root自身のparent_id=Noneであるため）を最上位として配置する。
    # ルート直下のノードには相対化の基準となる親が無いため、ピン留めされて
    # いれば従来どおり絶対座標として扱う。
    roots = sorted(c for c in children_by_parent.get(None, []) if c not in excluded_ids)
    cursor_x = _PADDING
    for root_id in roots:
        compute_size(root_id)
        flow_x = cursor_x
        cursor_x += sizes[root_id][0] + _PADDING
        pinned = pinned_positions.get(root_id)
        if pinned is not None:
            offset_x, offset_y = content_offset[root_id]
            place(root_id, pinned["x"] - offset_x, pinned["y"] - offset_y)
        else:
            place(root_id, flow_x, _PADDING)

    # type/label/source_rangeはGraph IRからそのまま引き継ぐ（5章のSVG
    # レンダラーがレイアウト結果に加えてこれらを必要とするため。View IRは
    # 「幾何情報だけ」ではなく、レンダラーへの唯一の入力として自己完結させる）。
    nodes_out = [
        {
            "id": nid,
            "type": nodes_by_id[nid]["type"],
            "label": nodes_by_id[nid]["label"],
            "source_range": nodes_by_id[nid]["source_range"],
            "x": positions[nid][0], "y": positions[nid][1],
            "width": sizes[nid][0], "height": sizes[nid][1],
        }
        for nid in sorted(nodes_by_id)
        if nid not in excluded_ids
    ]

    def _center(node_id: str) -> Tuple[float, float]:
        x, y = positions[node_id]
        w, h = sizes[node_id]
        return x + w / 2, y + h / 2

    def _boundary_point(node_id: str, dx: float, dy: float) -> Tuple[float, float]:
        """ノードの中心から方向(dx, dy)へ進んだときに矩形の縁と交わる点を返す
        （表現力強化 Stage 0）。中心同士を直線で結ぶと矩形の内部を必ず貫通し、
        ノードを後から重ねて描く限りその区間が隠れて見えなくなるため、
        エッジの両端をあらかじめ矩形の縁で止める設計に変更した。"""
        cx, cy = _center(node_id)
        if dx == 0 and dy == 0:
            return cx, cy
        _w, h = sizes[node_id]
        half_w, half_h = _w / 2, h / 2
        candidates = []
        if dx != 0:
            candidates.append(half_w / abs(dx))
        if dy != 0:
            candidates.append(half_h / abs(dy))
        t = min(candidates)
        return cx + t * dx, cy + t * dy

    # 非包含エッジ（specialization/feature_typing/connection等）は、ボックス
    # 配置が確定した後に両端を結ぶ直線として後処理する（実装仕様書4.2節：
    # 交差は許容し、手動調整はPhase D以降の課題とする）。両端は中心同士では
    # なく矩形の縁（Stage 0）とすることで、ノードの矩形に隠れる区間を無くす。
    # 折りたたみで除外された子孫を指すエッジは、両端の位置が存在しないため
    # 描画対象から除く（3.3節の「宙に浮いた矢印を避ける」設計と同じ考え方）。
    edges_out = []
    for edge in graph_ir["edges"]:
        if edge["from"] in excluded_ids or edge["to"] in excluded_ids:
            continue
        from_center = _center(edge["from"])
        to_center = _center(edge["to"])
        dx = to_center[0] - from_center[0]
        dy = to_center[1] - from_center[1]
        from_point = _boundary_point(edge["from"], dx, dy)
        to_point = _boundary_point(edge["to"], -dx, -dy)
        edges_out.append({
            "id": edge["id"],
            "kind": edge["kind"],  # 表現力強化Stage 1: SVGレンダラーが種別ごとに矢印・線種を描き分けるために保持する。
            "points": [list(from_point), list(to_point)],
        })

    return {"view_type": graph_ir.get("view_type", "structure"), "nodes": nodes_out, "edges": edges_out}
