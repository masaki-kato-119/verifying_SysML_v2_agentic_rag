"""View IR構築とレイアウト（SysMLv2_Viewer_実装仕様書.md 4章）。

Graph IRから、決定的（乱数・現在時刻を一切使わない）な入れ子ボックス
レイアウトを持つView IRを作る。Phase Aでは「構造ビュー」1種類のみ。
"""

from typing import Dict, List, Optional, Tuple

# レイアウト定数（実装仕様書4.2節：力学モデル等の非決定的手法を避け、
# 固定パラメータによる決定的な再帰配置にする）。
_PADDING = 8
# 表現力強化 h1: 種別キーワード（«package»等）と名前を2行に分けて表示する
# ようになったため（旧: 同じ行に並べていた）、ヘッダー用の高さを24→30へ
# 拡げて2行分の見た目が窮屈にならないようにする。
_LABEL_HEIGHT = 30
_MIN_WIDTH = 90
_MIN_HEIGHT = 40
_CHAR_WIDTH = 8  # ラベル長からの概算幅（フォントメトリクスは使わない簡易推定）

# 表現力強化h5: ポート(port_usage/port_def)は、通常の子要素のように親の
# 中に入れ子矩形として並べるのではなく、SysML標準のポート表記に合わせ、
# 親矩形の左辺に境界線をまたぐ小さな正方形として配置する。自身の子要素を
# 持つポート（flow property等がbodyに書かれている場合）は、この特別扱いを
# せず通常の子要素として扱う（ネストした内容を消さないための安全策）。
_PORT_NODE_TYPES = {"port_usage", "port_def"}
_PORT_SIZE = 14
_PORT_GAP = 6


def _leaf_size(label: str) -> Tuple[int, int]:
    width = max(_MIN_WIDTH, len(label) * _CHAR_WIDTH + 2 * _PADDING)
    return width, _MIN_HEIGHT


def _rect_boundary_point(
    cx: float, cy: float, half_w: float, half_h: float, dx: float, dy: float
) -> Tuple[float, float]:
    """矩形の中心(cx, cy)から方向(dx, dy)へ進んだときに矩形の縁と交わる点を
    返す（表現力強化 Stage 0）。中心同士を直線で結ぶと矩形の内部を必ず貫通し、
    ノードを後から重ねて描く限りその区間が隠れて見えなくなるため、エッジの
    両端をあらかじめ矩形の縁で止める。`build_view_ir`（入れ子矩形）と
    `build_flow_view_ir`（層状レイアウト）の両方で共有する純粋な幾何計算。"""
    if dx == 0 and dy == 0:
        return cx, cy
    candidates = []
    if dx != 0:
        candidates.append(half_w / abs(dx))
    if dy != 0:
        candidates.append(half_h / abs(dy))
    t = min(candidates)
    return cx + t * dx, cy + t * dy


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

    def _is_boundary_port(node_id) -> bool:
        """表現力強化h5: 自身の子を持たない単純なポートだけを境界表示の
        対象にする（flow property等のbodyを持つポートは、内容を消さない
        よう通常の入れ子矩形のまま扱う）。"""
        return nodes_by_id[node_id]["type"] in _PORT_NODE_TYPES and not _children_of(node_id)

    def _split_children(node_id) -> Tuple[List[str], List[str]]:
        children = _children_of(node_id)
        ports = [c for c in children if _is_boundary_port(c)]
        regular = [c for c in children if c not in ports]
        return regular, ports

    sizes: Dict[str, Tuple[int, int]] = {}
    positions: Dict[str, Tuple[int, int]] = {}
    # ノードごとの「フロー原点からのずれ」。ピン留めされた子が通常のフロー
    # 領域より左・上にはみ出す場合、親の矩形自体をその分だけ左・上に広げる
    # 必要がある。この値がその「広げ幅」（0以下の値）を保持する。
    content_offset: Dict[str, Tuple[int, int]] = {}
    # 表現力強化: ポートは「どちらの辺（左/右）に置けば接続先までの線が
    # 短くなるか」を、接続先の確定済み座標を見て決める必要がある。しかし
    # 接続先ノードは兄弟や別の subtree のこともあり、place()の再帰中には
    # まだ座標が確定していない場合がある。そのため place() ではポートの
    # 最終配置を行わず、(親id, ポートid一覧)だけを記録しておき、全ノードの
    # 配置が確定した後（全rootのplace()完了後）にまとめて解決する。
    pending_ports: List[Tuple[str, List[str]]] = []

    def compute_size(node_id: str) -> Tuple[int, int]:
        children = _children_of(node_id)
        if not children:
            size = _leaf_size(nodes_by_id[node_id]["label"])
            sizes[node_id] = size
            content_offset[node_id] = (0, 0)
            return size

        regular_children, port_children = _split_children(node_id)
        # ポートは正方形固定サイズとし、通常のcompute_size再帰（テキスト幅
        # ベースの_leaf_size）は適用しない（境界線をまたぐ小さな記号として
        # 描くだけで、名前の長さに応じて矩形を広げる必要が無いため）。
        for port_id in port_children:
            sizes[port_id] = (_PORT_SIZE, _PORT_SIZE)
            content_offset[port_id] = (0, 0)

        # 通常のフロー上の「スロット」割り当て（cursorの進み方）自体は、
        # ピン留めの有無に関わらず全ての子について計算する（後述のplace()でも
        # 同様。兄弟の位置をピン留めの影響から独立させるため、これは変更しない）。
        # 一方、親の矩形サイズの下限（flow_width/flow_height）は、ピン留めされた
        # 子の「使われなくなった通常スロット」まで含めてしまうと、子をどれだけ
        # コンパクトに動かしても親が縮まらなくなる（ユーザー報告のバグ）。
        # 未ピン留めの子だけを対象に「実際に描画される位置」の外接を取ることで、
        # 全ての子をピン留めして詰めれば親も縮むようにする。
        if regular_children:
            child_sizes = [compute_size(c) for c in regular_children]
            cursor_y = 0
            flow_width = 0
            flow_height = 0
            for child_id, (child_w, child_h) in zip(regular_children, child_sizes):
                flow_y = cursor_y
                cursor_y += child_h + _PADDING  # スロットはピン留めの有無に関わらず必ず進める
                if pinned_positions.get(child_id) is None:
                    flow_width = max(flow_width, child_w)
                    flow_height = max(flow_height, flow_y + child_h)
        else:
            flow_width, flow_height = 0, 0

        # ポートは親の左辺に均等間隔で並ぶため、その縦方向の必要量
        # （境界表示の対象がポートしか無い場合など）で高さの下限を確保する。
        if port_children:
            port_strip_height = len(port_children) * _PORT_SIZE + (len(port_children) - 1) * _PORT_GAP
            flow_height = max(flow_height, port_strip_height)

        # 親の内容領域は「通常のフロー領域」と「各ピン留め子の相対矩形」の
        # 和集合の外接矩形にする。ピン留め子がフロー領域より左・上にはみ出す
        # 場合はcontent_left/topが負になり、後述のplace()で親の矩形自体を
        # その分だけ左・上にずらして広げる。
        content_left, content_top = 0, 0
        content_right, content_bottom = flow_width, flow_height
        for child_id in regular_children:
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
        regular_children, port_children = _split_children(node_id)
        origin_x = anchor_x + _PADDING
        origin_y = anchor_y + _LABEL_HEIGHT + _PADDING
        cursor_y = origin_y
        for child_id in regular_children:
            flow_y = cursor_y
            cursor_y += sizes[child_id][1] + _PADDING  # ピン留めの有無に関わらず必ず進める
            pinned = pinned_positions.get(child_id)
            if pinned is not None:
                place(child_id, origin_x + pinned["x"], origin_y + pinned["y"])
            else:
                place(child_id, origin_x, flow_y)

        if port_children:
            # ポート自身の最終座標は、全ノードの配置が確定した後の
            # _place_pending_ports()でまとめて決める（下記コメント参照）。
            pending_ports.append((node_id, list(port_children)))

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

    # 表現力強化: ポートの左右配置は、接続先ノードの確定済み座標との
    # 距離で個々のポートごとに決める（辺の中央付近を基準に、接続線が
    # 短くなる側へ）。全rootのplace()が完了し、全ノードの座標が
    # 確定した後でなければ接続先の位置が分からないため、ここでまとめて
    # 処理する。
    port_edge_partners: Dict[str, List[str]] = {}
    for edge in graph_ir["edges"]:
        port_edge_partners.setdefault(edge["from"], []).append(edge["to"])
        port_edge_partners.setdefault(edge["to"], []).append(edge["from"])

    def _preferred_side(port_id: str, parent_x: float, parent_width: float) -> str:
        partner_ids = [pid for pid in port_edge_partners.get(port_id, []) if pid in positions]
        if not partner_ids:
            return "left"  # 接続が無いポートは、従来通り左辺を既定とする。
        left_x = parent_x - _PORT_SIZE / 2
        right_x = parent_x + parent_width - _PORT_SIZE / 2
        left_total = right_total = 0.0
        for partner_id in partner_ids:
            px, py = positions[partner_id]
            pw, ph = sizes[partner_id]
            partner_cx = px + pw / 2
            left_total += abs(left_x - partner_cx)
            right_total += abs(right_x - partner_cx)
        return "left" if left_total <= right_total else "right"

    port_sides: Dict[str, str] = {}
    for parent_id, port_children in pending_ports:
        parent_x, parent_y = positions[parent_id]
        parent_width, parent_height = sizes[parent_id]
        left_ports = []
        right_ports = []
        for port_id in port_children:
            side = _preferred_side(port_id, parent_x, parent_width)
            port_sides[port_id] = side
            (left_ports if side == "left" else right_ports).append(port_id)

        for side, group in (("left", left_ports), ("right", right_ports)):
            if not group:
                continue
            total_height = len(group) * _PORT_SIZE + (len(group) - 1) * _PORT_GAP
            port_y = parent_y + (parent_height - total_height) / 2
            port_x = (
                parent_x - _PORT_SIZE / 2
                if side == "left"
                else parent_x + parent_width - _PORT_SIZE / 2
            )
            for port_id in group:
                positions[port_id] = (port_x, port_y)
                port_y += _PORT_SIZE + _PORT_GAP

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
            # 表現力強化h5: SVGレンダラーが「境界線をまたぐ小さな正方形」として
            # 描くべきポートかどうかを、幅・高さの偶然の一致に頼らず明示的に
            # 伝える（自身の子を持つポートはNoneやフラグ無しではなく明示的に
            # Falseになり、通常の入れ子矩形として描かれる）。
            "is_boundary_port": _is_boundary_port(nid),
            # 表現力強化: ポートがどちら側の辺に配置されたか（"left"/"right"）を
            # 明示的に伝える。SVGレンダラーは親の矩形情報を持たないため、
            # ラベルテキストを正方形のどちら側に置くかをこのフラグだけで
            # 判断できるようにする（幾何情報からの再推測を避ける）。
            "port_side": port_sides.get(nid),
        }
        for nid in sorted(nodes_by_id)
        if nid not in excluded_ids
    ]

    def _center(node_id: str) -> Tuple[float, float]:
        x, y = positions[node_id]
        w, h = sizes[node_id]
        return x + w / 2, y + h / 2

    def _boundary_point(node_id: str, dx: float, dy: float) -> Tuple[float, float]:
        cx, cy = _center(node_id)
        w, h = sizes[node_id]
        return _rect_boundary_point(cx, cy, w / 2, h / 2, dx, dy)

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
        edge_out = {
            "id": edge["id"],
            "kind": edge["kind"],  # 表現力強化Stage 1: SVGレンダラーが種別ごとに矢印・線種を描き分けるために保持する。
            "points": [list(from_point), list(to_point)],
        }
        if "label" in edge:
            edge_out["label"] = edge["label"]  # 表現力強化h2: transitionのtrigger/guard/effectラベル。
        edges_out.append(edge_out)

    return {"view_type": graph_ir.get("view_type", "structure"), "nodes": nodes_out, "edges": edges_out}


# --- 層状（フロー）レイアウト（表現力強化 Stage 3, Group B f1） -----------
# 状態遷移図・アクティビティ図向け。build_view_ir（入れ子矩形、包含関係の
# 表現）とは根本的に異なる用途のため、独立した新規関数として追加する
# （既存のbuild_view_irには一切手を入れない）。ここでは有向グラフの
# トポロジー（transition/succession/flowエッジ）だけを見て、ノードを
# 層（レイヤー）ごとに上から下へ並べる簡易Sugiyama系アルゴリズムを使う。
# 対象ノードの入れ子構造（group_id）はこのビューでは考慮しない――複合状態
# 等のネストは、最小限の対応としてこの段階ではスコープ外とする。

_FLOW_LAYER_GAP = 60  # 層と層の間の縦方向の間隔
_FLOW_NODE_GAP = 16  # 同じ層内でのノード間の横方向の間隔


def _assign_layers(node_ids: List[str], edges: List[Dict]) -> Dict[str, int]:
    """各ノードへ層番号（0始まり、入力が無いノードが0）を割り当てる。

    「全ての直接の先行ノードの層+1の最大値」という素朴な最長路レイヤリング。
    循環参照（A→B→A等）がある場合、DFSの再帰スタック上にある祖先への
    エッジ（back edge）を検出したら、そのエッジは無いものとして扱う
    （層0として扱うことで無限再帰を避ける。作業計画書のリスク欄で明示した
    安全側フォールバック）。決定的にするため、開始順序をstable_id順で固定する。
    """
    node_id_set = set(node_ids)
    predecessors: Dict[str, List[str]] = {nid: [] for nid in node_ids}
    for edge in edges:
        if edge["from"] in node_id_set and edge["to"] in node_id_set:
            predecessors[edge["to"]].append(edge["from"])
    for nid in predecessors:
        predecessors[nid].sort()  # 決定的な走査順

    layer: Dict[str, int] = {}
    visiting: set = set()

    def compute(nid: str) -> int:
        if nid in layer:
            return layer[nid]
        if nid in visiting:
            return 0  # 循環検出: back edgeを無視する安全側フォールバック
        visiting.add(nid)
        preds = predecessors[nid]
        result = 0 if not preds else 1 + max(compute(p) for p in preds)
        visiting.discard(nid)
        layer[nid] = result
        return result

    for nid in sorted(node_ids):
        compute(nid)
    return layer


def build_flow_view_ir(graph_ir: Dict) -> Dict:
    """Graph IRから層状（フロー）レイアウトのView IRを構築する
    （状態遷移図・アクティビティ図向け、表現力強化Stage 3）。

    Args:
        graph_ir: build_view_irと同じ形。`view_type`は`"state_machine"`
            または`"activity"`を想定するが、この関数自体はどちらにも依存しない
            （ノードの集合とエッジのトポロジーだけを見る）。

    Returns:
        build_view_irと同じ形の辞書（"view_type","nodes","edges"）。
        乱数・現在時刻を使わない決定的な純粋関数（同一入力→常に同一出力）。
    """
    nodes_by_id = {n["id"]: n for n in graph_ir["nodes"]}
    node_ids = list(nodes_by_id.keys())

    layer_of = _assign_layers(node_ids, graph_ir["edges"])

    nodes_by_layer: Dict[int, List[str]] = {}
    for nid in sorted(node_ids):
        nodes_by_layer.setdefault(layer_of[nid], []).append(nid)

    sizes = {nid: _leaf_size(nodes_by_id[nid]["label"]) for nid in node_ids}
    positions: Dict[str, Tuple[int, int]] = {}

    y = _PADDING
    for layer_index in sorted(nodes_by_layer):
        ids_in_layer = nodes_by_layer[layer_index]
        layer_height = max(sizes[nid][1] for nid in ids_in_layer)
        x = _PADDING
        for nid in ids_in_layer:
            width, _height = sizes[nid]
            positions[nid] = (x, y)
            x += width + _FLOW_NODE_GAP
        y += layer_height + _FLOW_LAYER_GAP

    nodes_out = [
        {
            "id": nid,
            "type": nodes_by_id[nid]["type"],
            "label": nodes_by_id[nid]["label"],
            "source_range": nodes_by_id[nid]["source_range"],
            "x": positions[nid][0], "y": positions[nid][1],
            "width": sizes[nid][0], "height": sizes[nid][1],
        }
        for nid in sorted(node_ids)
    ]

    def _center(nid: str) -> Tuple[float, float]:
        x, y = positions[nid]
        w, h = sizes[nid]
        return x + w / 2, y + h / 2

    edges_out = []
    for edge in graph_ir["edges"]:
        if edge["from"] not in positions or edge["to"] not in positions:
            continue
        from_c = _center(edge["from"])
        to_c = _center(edge["to"])
        dx, dy = to_c[0] - from_c[0], to_c[1] - from_c[1]
        from_cx, from_cy = from_c
        to_cx, to_cy = to_c
        from_w, from_h = sizes[edge["from"]]
        to_w, to_h = sizes[edge["to"]]
        from_point = _rect_boundary_point(from_cx, from_cy, from_w / 2, from_h / 2, dx, dy)
        to_point = _rect_boundary_point(to_cx, to_cy, to_w / 2, to_h / 2, -dx, -dy)
        edge_out = {
            "id": edge["id"],
            "kind": edge.get("kind"),
            "points": [list(from_point), list(to_point)],
        }
        if "label" in edge:
            edge_out["label"] = edge["label"]  # 表現力強化h2: transitionのtrigger/guard/effectラベル。
        edges_out.append(edge_out)

    return {"view_type": graph_ir.get("view_type", "flow"), "nodes": nodes_out, "edges": edges_out}
