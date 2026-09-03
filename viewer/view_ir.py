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
            （Group3 b11, L1-1）。指定ノードは計算結果ではなくこの座標で
            配置し、その子孫は引き続きこの座標を起点に相対配置する
            （包含関係を保つため）。他のノード（兄弟・非対象ノード）は
            従来どおりの決定的アルゴリズムで計算する――ピン留めノードとの
            重なりを解消する制約解法は行わない、既存コードの「手動調整は
            Phase D以降の課題」という割り切り（4.2節）を踏襲した設計判断。
            省略時は従来どおり（後方互換）。

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

    def compute_size(node_id: str) -> Tuple[int, int]:
        children = _children_of(node_id)
        if not children:
            size = _leaf_size(nodes_by_id[node_id]["label"])
            sizes[node_id] = size
            return size

        child_sizes = [compute_size(c) for c in children]
        content_width = max(w for w, _h in child_sizes)
        content_height = sum(h for _w, h in child_sizes) + _PADDING * (len(children) - 1)
        width = max(_MIN_WIDTH, content_width + 2 * _PADDING)
        height = _LABEL_HEIGHT + content_height + 2 * _PADDING
        size = (width, height)
        sizes[node_id] = size
        return size

    def place(node_id: str, x: int, y: int) -> None:
        pinned = pinned_positions.get(node_id)
        if pinned is not None:
            x, y = pinned["x"], pinned["y"]
        positions[node_id] = (x, y)
        children = _children_of(node_id)
        cursor_y = y + _LABEL_HEIGHT + _PADDING
        for child_id in children:
            place(child_id, x + _PADDING, cursor_y)
            cursor_y += sizes[child_id][1] + _PADDING

    # group_id が None のノード（ルートのみのはず。Semantic Modelのルートは
    # 常に1個。$root自身のparent_id=Noneであるため）を最上位として配置する。
    roots = sorted(c for c in children_by_parent.get(None, []) if c not in excluded_ids)
    cursor_x = _PADDING
    for root_id in roots:
        compute_size(root_id)
        place(root_id, cursor_x, _PADDING)
        cursor_x += sizes[root_id][0] + _PADDING

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
