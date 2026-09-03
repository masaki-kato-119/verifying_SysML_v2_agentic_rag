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
}

_GRAPH_NODE_SUFFIXES = ("_def", "_usage", "_instance")


def _is_graph_node_type(node_type: str) -> bool:
    """このノード種別を構造図のノードとして描画対象に含めるか判定する。

    式（binary_expr等）・文（if_stmt等）・connector_end等の構造補助ノードは
    対象外（実装仕様書3.2節、拡張仕様書12章のPhase 1スコープと同じ考え方）。
    """
    if node_type == "package":
        return True
    if node_type in _EXPLICIT_GRAPH_NODE_TYPES:
        return True
    return node_type.endswith(_GRAPH_NODE_SUFFIXES)


def build_graph_ir(semantic_model: Dict) -> Dict:
    """semantic_modelからGraph IRを構築する。

    Args:
        semantic_model: {"nodes": {stable_id: {type, name, parent_id, ...}},
            "edges": [{from_id, to_id, kind, resolved, ...}], "root_id": ...}

    Returns:
        {"nodes": [{"id", "type", "label", "group_id", "source_range"}, ...],
         "edges": [{"id", "from", "to", "kind"}, ...]}
        （実装仕様書3.3節。source_rangeは5章のSVGレンダラーがトレーサビリティ
        属性として埋め込むために持たせる）。エッジは resolved=True のものだけを
        含む（3.3節の設計判断：未解決参照は「宙に浮いた矢印」になるため描画しない）。
    """
    nodes_in = semantic_model["nodes"]

    graph_node_ids = {
        stable_id for stable_id, entry in nodes_in.items() if _is_graph_node_type(entry["type"])
    }

    nodes_out: List[Dict] = []
    for stable_id in graph_node_ids:
        entry = nodes_in[stable_id]
        nodes_out.append({
            "id": stable_id,
            "type": entry["type"],
            "label": entry["name"] or entry["type"],
            "group_id": entry["parent_id"],
            "source_range": entry["source_range"],
        })

    edges_out: List[Dict] = []
    for index, edge in enumerate(semantic_model["edges"]):
        if not edge["resolved"]:
            continue
        if edge["from_id"] not in graph_node_ids or edge["to_id"] not in graph_node_ids:
            # from/toの一方が対象外ノード種別（式・文等）を指す場合は描画対象外。
            continue
        # 同じfrom/kind/toの組が複数回起きうる（例: 同じ相手への複数connect）ため、
        # SVG要素idとしての一意性を保証するためインデックスを含める。
        edges_out.append({
            "id": f"{edge['from_id']}->{edge['kind']}->{edge['to_id']}#{index}",
            "from": edge["from_id"],
            "to": edge["to_id"],
            "kind": edge["kind"],
        })

    return {"nodes": nodes_out, "edges": edges_out}
