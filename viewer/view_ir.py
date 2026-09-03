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


def build_view_ir(graph_ir: Dict) -> Dict:
    """Graph IRからView IR（構造ビュー）を構築する。

    Args:
        graph_ir: {"nodes": [{"id","type","label","group_id"}, ...],
            "edges": [{"id","from","to","kind"}, ...]}（viewer.graph_ir参照）

    Returns:
        {"view_type": "structure",
         "nodes": [{"id","x","y","width","height"}, ...]（絶対座標）,
         "edges": [{"id","points": [[x,y],[x,y]]}, ...]}
    """
    nodes_by_id = {n["id"]: n for n in graph_ir["nodes"]}

    children_by_parent: Dict[Optional[str], List[str]] = {}
    for node in graph_ir["nodes"]:
        children_by_parent.setdefault(node["group_id"], []).append(node["id"])
    # 同一入力に対し常に同じ配置になるよう、子の並びをstable_idの辞書順に固定する。
    for parent_id in children_by_parent:
        children_by_parent[parent_id].sort()

    sizes: Dict[str, Tuple[int, int]] = {}
    positions: Dict[str, Tuple[int, int]] = {}

    def compute_size(node_id: str) -> Tuple[int, int]:
        children = children_by_parent.get(node_id, [])
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
        positions[node_id] = (x, y)
        children = children_by_parent.get(node_id, [])
        cursor_y = y + _LABEL_HEIGHT + _PADDING
        for child_id in children:
            place(child_id, x + _PADDING, cursor_y)
            cursor_y += sizes[child_id][1] + _PADDING

    # group_id が None のノード（ルートのみのはず。Semantic Modelのルートは
    # 常に1個。$root自身のparent_id=Noneであるため）を最上位として配置する。
    roots = sorted(children_by_parent.get(None, []))
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
    ]

    def _center(node_id: str) -> Tuple[float, float]:
        x, y = positions[node_id]
        w, h = sizes[node_id]
        return x + w / 2, y + h / 2

    # 非包含エッジ（specialization/feature_typing/connection等）は、ボックス
    # 配置が確定した後に両端の中心同士を直線で結ぶだけの単純な後処理とする
    # （実装仕様書4.2節：交差は許容し、手動調整はPhase D以降の課題とする）。
    edges_out = [
        {"id": edge["id"], "points": [list(_center(edge["from"])), list(_center(edge["to"]))]}
        for edge in graph_ir["edges"]
    ]

    return {"view_type": "structure", "nodes": nodes_out, "edges": edges_out}
