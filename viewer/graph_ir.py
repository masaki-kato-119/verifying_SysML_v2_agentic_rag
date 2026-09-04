"""Graph IR構築（SysMLv2_Viewer_実装仕様書.md 3章）。

semantic_model（sysml_v2_checker_advanced.semantic_model.build_semantic_model()
またはantlr_transformer.parse_sysml_with_semantic_model()が返すもの）から、
構造図の描画に必要なノード・エッジだけを選別した投影（Graph IR）を作る。

新たな解析は一切行わない純粋関数。sysml_v2_checker_advancedパッケージには
一切手を入れない（実装仕様書3.4節、構想書§12原則3「View is a projection」）。
"""

from typing import Dict, List

# 実装時に判明した設計変更（当初案からの訂正）:
# 実装仕様書3.2節の当初案は「constants.pyのELEMENT_REFERENCE_ONLY_USAGE_TYPES
# 活用」としていたが、実装着手時にlinter.pyの実際の分類を確認したところ、
# ELEMENT_REFERENCE_ONLY_USAGE_TYPES（linter.py:151）と、_collect_symbolsの
# "definition的に扱う"型リスト（linter.py:244）のいずれにも、
# connection_def・connection_usage・binding_connector・
# verify_requirement_usage・message_usage 等が含まれていないことが分かった
# （linter.py側はlintルールの実装上の都合で積み上げられた分類であり、
# 「モデル要素として図に出すべきものの網羅的なリスト」ではない）。
# そのため、既存分類の流用ではなく、型名の接尾辞パターン
# （"_def"/"_usage"/"_instance"、および"package"）による判定を主とし、
# パターンに乗らない既知の例外だけを明示的な集合で補う設計に変更した。
_EXPLICIT_GRAPH_NODE_TYPES = {
    "binding_connector",  # bind文。"_def"/"_usage"/"_instance"のいずれの接尾辞も持たない
    # 表現力強化: `perform action 'X' { ... }`（新規アクションの宣言＋実行）と
    # `perform Y::'X';`（既存アクションの参照実行）はいずれも"perform_action"
    # 型だが、"_def"/"_usage"/"_instance"のいずれの接尾辞も持たない。これが
    # グラフノード対象外だったため、本体内のflow/attribute等がアクションの
    # 箱を飛び越して外側のpartの直接の子として平坦化されてしまっていた
    # （ユーザー報告：「要素を移動しても高さが縮まらない」の一因。'perform
    # action'のbody内要素が全て外側のpartに合流し、直接の子の数が不自然に
    # 多くなっていたため）。
    "perform_action",
    # `action 'X' accept 'Y' : Type via 'port';`のような、シグナル受信で
    # 始まる名前付きアクション。flow文の参照先（from/to）になりうるため、
    # ボックスとして含めないとそのflowエッジ自体が描画対象外になる。
    "accept_action",
}

_GRAPH_NODE_SUFFIXES = ("_def", "_usage", "_instance")

# Group2 b6(V1-1): 要求トレーサビリティビュー。requirement系ノード自身に加え、
# satisfy/verifyエッジの相手側（要求を満たす部品等）も対象に含めないと、
# エッジの片端が図に存在せず描画できない（3.3節の「両端が対象ノードで
# なければエッジを描画しない」設計と整合させるため）。
_REQUIREMENT_VIEW_NODE_TYPES = {
    "requirement_def", "satisfy_requirement_usage", "verify_requirement_usage",
}
_REQUIREMENT_VIEW_EDGE_KINDS = {"satisfy", "verify"}

VIEW_TYPE_STRUCTURE = "structure"
VIEW_TYPE_REQUIREMENT_TRACEABILITY = "requirement_traceability"
VIEW_TYPE_VERIFICATION = "verification"
VIEW_TYPE_STATE_MACHINE = "state_machine"
VIEW_TYPE_ACTIVITY = "activity"

# 表現力強化Stage 3, Group B f2: 状態遷移図。state_def/state_usage系ノードと
# transitionエッジのみに絞る。transitionは常に2つの状態を結ぶ（暗黙遷移の
# 遷移元＝囲むstate自身もstate_def/state_usageであるため）、要求トレーサビリ
# ティビューのような「相手側を追加で含める」処理は不要。
_STATE_MACHINE_NODE_TYPES = {"state_def", "state_usage"}
_STATE_MACHINE_EDGE_KINDS = {"transition"}

# 表現力強化Stage 3, Group C g1: アクティビティ図。action_def/action_usage系
# ノードとsuccession/flowエッジのみに絞る。succession/flowも常に2つの
# アクション（またはそのポート、e3のフォールバックによりownerアクションへ
# 解決される）を結ぶため、state_machineと同様に相手側の追加取り込みは不要。
_ACTIVITY_NODE_TYPES = {"action_def", "action_usage"}
_ACTIVITY_EDGE_KINDS = {"succession", "flow"}

# Group2 b8(V2): 検証ビュー。Findingが付いた要素を起点に、b2(I2影響範囲ハイライト,
# viewer/frontend/app.jsのfindImpactedElementIds)と同じBFS・既定2次までの
# ロジックを構造ビュー候補ノード集合上で再利用する。
_VERIFICATION_VIEW_DEPTH = 2


_CONNECTION_NODE_TYPES = {"connect_usage", "connection_usage", "binding_connector"}


def _is_collapsed_binary_connector(entry: Dict) -> bool:
    """表現力強化: 2項（end2つ）かつ本体（`{ ... }`）を持たないconnectorは、
    Semantic Model側（sysml_v2_checker_advanced.semantic_model）で自身を
    起点にするのではなく両端を直接結ぶ1本のconnectionエッジとして表現される
    （h2/h3で確立した`_make_reference_pair_edge`パターンをconnectionにも
    適用したもの）。そのため、ここでも自身をボックスとして描画対象に含める
    必要が無い（含めても、どのエッジからも参照されない孤立した空箱になる
    だけのため）。n-ary（3項以上）や本体を持つconnectorは、両端を1本の線で
    表現できない／中の要素を消さないため、従来通りボックスのまま扱う。
    """
    node = entry["node"]
    if node.get("type") not in _CONNECTION_NODE_TYPES:
        return False
    return not node.get("ends") and not node.get("children")


def _is_graph_node_type(entry: Dict) -> bool:
    """"structure"ビューでこのノードを描画対象に含めるか判定する。

    式（binary_expr等）・文（if_stmt等）・connector_end等の構造補助ノードは
    対象外（実装仕様書3.2節、拡張仕様書12章のPhase 1スコープと同じ考え方）。
    """
    node_type = entry["type"]
    if _is_collapsed_binary_connector(entry):
        return False
    if node_type == "package":
        return True
    if node_type in _EXPLICIT_GRAPH_NODE_TYPES:
        return True
    return node_type.endswith(_GRAPH_NODE_SUFFIXES)


def _select_structure_view(semantic_model: Dict, finding_element_ids=None):
    nodes_in = semantic_model["nodes"]
    node_ids = {
        stable_id for stable_id, entry in nodes_in.items() if _is_graph_node_type(entry)
    }
    return node_ids, semantic_model["edges"]


def _select_requirement_traceability_view(semantic_model: Dict, finding_element_ids=None):
    nodes_in = semantic_model["nodes"]
    requirement_ids = {
        sid for sid, entry in nodes_in.items() if entry["type"] in _REQUIREMENT_VIEW_NODE_TYPES
    }
    node_ids = set(requirement_ids)
    selected_edges = []
    for edge in semantic_model["edges"]:
        if edge["kind"] not in _REQUIREMENT_VIEW_EDGE_KINDS:
            continue
        if edge["from_id"] in requirement_ids:
            selected_edges.append(edge)
            if edge["to_id"] is not None:
                node_ids.add(edge["to_id"])
    return node_ids, selected_edges


def _select_verification_view(semantic_model: Dict, finding_element_ids):
    """Findingが付いた要素（の交差点）を起点に、resolvedエッジ上をBFSで
    既定2次まで辿った関連要素だけに絞る（viewer/frontend/app.jsの
    findImpactedElementIds・IMPACT_DEPTHと同じロジックをバックエンド側で
    再利用したもの）。"""
    nodes_in = semantic_model["nodes"]
    candidate_ids = {
        stable_id for stable_id, entry in nodes_in.items() if _is_graph_node_type(entry)
    }
    resolved_edges = [
        edge for edge in semantic_model["edges"]
        if edge["resolved"] and edge["from_id"] in candidate_ids and edge["to_id"] in candidate_ids
    ]
    adjacency: Dict[str, List[str]] = {}
    for edge in resolved_edges:
        adjacency.setdefault(edge["from_id"], []).append(edge["to_id"])
        adjacency.setdefault(edge["to_id"], []).append(edge["from_id"])

    seeds = (finding_element_ids or set()) & candidate_ids
    visited = set(seeds)
    frontier = set(seeds)
    for _ in range(_VERIFICATION_VIEW_DEPTH):
        next_frontier = set()
        for stable_id in frontier:
            for neighbor in adjacency.get(stable_id, []):
                if neighbor not in visited:
                    visited.add(neighbor)
                    next_frontier.add(neighbor)
        frontier = next_frontier
        if not frontier:
            break

    selected_edges = [
        edge for edge in resolved_edges if edge["from_id"] in visited and edge["to_id"] in visited
    ]
    return visited, selected_edges


def _select_state_machine_view(semantic_model: Dict, finding_element_ids=None):
    nodes_in = semantic_model["nodes"]
    node_ids = {
        sid for sid, entry in nodes_in.items() if entry["type"] in _STATE_MACHINE_NODE_TYPES
    }
    selected_edges = [
        edge for edge in semantic_model["edges"] if edge["kind"] in _STATE_MACHINE_EDGE_KINDS
    ]
    return node_ids, selected_edges


def _select_activity_view(semantic_model: Dict, finding_element_ids=None):
    nodes_in = semantic_model["nodes"]
    node_ids = {
        sid for sid, entry in nodes_in.items() if entry["type"] in _ACTIVITY_NODE_TYPES
    }
    selected_edges = [
        edge for edge in semantic_model["edges"] if edge["kind"] in _ACTIVITY_EDGE_KINDS
    ]
    return node_ids, selected_edges


_VIEW_SELECTORS = {
    VIEW_TYPE_STRUCTURE: _select_structure_view,
    VIEW_TYPE_REQUIREMENT_TRACEABILITY: _select_requirement_traceability_view,
    VIEW_TYPE_VERIFICATION: _select_verification_view,
    VIEW_TYPE_STATE_MACHINE: _select_state_machine_view,
    VIEW_TYPE_ACTIVITY: _select_activity_view,
}


def build_graph_ir(
    semantic_model: Dict,
    view_type: str = VIEW_TYPE_STRUCTURE,
    finding_element_ids=None,
) -> Dict:
    """semantic_modelからGraph IRを構築する。

    Args:
        semantic_model: {"nodes": {stable_id: {type, name, parent_id, ...}},
            "edges": [{from_id, to_id, kind, resolved, ...}], "root_id": ...}
        view_type: "structure"（既定、実装仕様書3章）、
            "requirement_traceability"（Group2 b6、requirement_def/
            satisfy_requirement_usage/verify_requirement_usageとその
            satisfy/verify先を中心にしたビュー）、
            "verification"（Group2 b8、finding_element_idsを起点に
            resolvedエッジ上をBFSで既定2次まで辿った要素に絞ったビュー）、または
            "state_machine"（表現力強化Stage 3 Group B f2、state_def/
            state_usage系ノードとtransitionエッジのみに絞ったビュー。
            `viewer.view_ir.build_flow_view_ir`と組み合わせて使う想定）、または
            "activity"（表現力強化Stage 3 Group C g1、action_def/
            action_usage系ノードとsuccession/flowエッジのみに絞ったビュー。
            同じく`build_flow_view_ir`と組み合わせて使う）
        finding_element_ids: view_type="verification"の起点となる要素id集合
            （Findingが付いた要素のelement_id）。他のview_typeでは無視される。

    Returns:
        {"view_type", "nodes": [{"id", "type", "label", "group_id", "source_range"}, ...],
         "edges": [{"id", "from", "to", "kind"}, ...]}
        （実装仕様書3.3節。view_typeはview_ir.pyがView IRに引き継ぐために持たせる
        （b7デバッグで発覚: view_ir.py側が"structure"を決め打ちしていたバグの修正）。
        source_rangeは5章のSVGレンダラーがトレーサビリティ
        属性として埋め込むために持たせる）。エッジは resolved=True のものだけを
        含む（3.3節の設計判断：未解決参照は「宙に浮いた矢印」になるため描画しない）。

    Raises:
        ValueError: 未知のview_typeを渡した場合。
    """
    if view_type not in _VIEW_SELECTORS:
        raise ValueError(f"未知のview_typeです: {view_type!r}")

    nodes_in = semantic_model["nodes"]
    graph_node_ids, edges_source = _VIEW_SELECTORS[view_type](semantic_model, finding_element_ids)

    def _effective_parent(stable_id: str):
        """直接の親が対象外ノード種別（例: requirement_traceabilityビューでの
        part_def等）の場合、対象に含まれる直近の祖先まで遡る。"structure"
        ビューでは各ノードの直接の親は常に対象種別のため実質no-opだが、
        フィルタが狭いビューでは孤立ノード（親を辿れず未配置になる）を
        防ぐために必要。"""
        parent_id = nodes_in[stable_id]["parent_id"]
        while parent_id is not None and parent_id not in graph_node_ids:
            parent_id = nodes_in[parent_id]["parent_id"]
        return parent_id

    nodes_out: List[Dict] = []
    for stable_id in graph_node_ids:
        entry = nodes_in[stable_id]
        # 表現力強化: 一部のノード種別は、`_assign_semantic_ids`が使う
        # "name"キーとは別のフィールドに人間可読な名前を持つ。entry["name"]が
        # Noneのまま既定の種別名という無意味なラベルに落ちるのを防ぐため、
        # 既知のフィールドを優先度順にフォールバックとして試す：
        # - "reference"：`perform Y::'X';`（既存アクションの参照実行）
        # - "actionName"：`action 'X' accept ... via ...;`（accept_actionだが
        #   `_assign_semantic_ids`は"name"だけを見るため匿名IDになる）
        node = entry["node"]
        label = entry["name"] or node.get("reference") or node.get("actionName") or entry["type"]
        nodes_out.append({
            "id": stable_id,
            "type": entry["type"],
            "label": label,
            "group_id": _effective_parent(stable_id),
            "source_range": entry["source_range"],
        })

    edges_out: List[Dict] = []
    for index, edge in enumerate(edges_source):
        if not edge["resolved"]:
            continue
        if edge["from_id"] not in graph_node_ids or edge["to_id"] not in graph_node_ids:
            # from/toの一方が対象外ノード種別（式・文等）を指す場合は描画対象外。
            continue
        # 同じfrom/kind/toの組が複数回起きうる（例: 同じ相手への複数connect）ため、
        # SVG要素idとしての一意性を保証するためインデックスを含める。
        edge_out = {
            "id": f"{edge['from_id']}->{edge['kind']}->{edge['to_id']}#{index}",
            "from": edge["from_id"],
            "to": edge["to_id"],
            "kind": edge["kind"],
        }
        if "label" in edge:
            edge_out["label"] = edge["label"]
        edges_out.append(edge_out)

    return {"view_type": view_type, "nodes": nodes_out, "edges": edges_out}
