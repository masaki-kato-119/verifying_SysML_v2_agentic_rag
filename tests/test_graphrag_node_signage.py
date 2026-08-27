"""graphrag.node_signage のノード案内情報生成のテスト。優先度: GraphRAG。

NodeSignageManagerはノード名の部分文字列判定でentry_point/exit_routes/warnings
を組み立てる、これまでテストが無かったモジュール。組み立て時に見つけたバグ
（下記）の回帰テストも含む。

バグ: _generate_exit_routes内の分岐が
`if relation == 'has_parameter' or 'parameter' in node_lower:` となっており、
ノード名に"parameter"を含むだけで、そのノードから出るすべてのエッジが実際の
relationを無視して"has_parameter"に誤分類されていた（例: "actionparameter" から
relation='uses'で出ているエッジまで "→ has_parameter" と表示される）。
`'parameter' in node_lower` の条件を削除して修正した。
"""

import networkx as nx
import pytest
from graphrag.node_signage import NodeSignageManager


def _manager(edges=(), isolated_nodes=()):
    g = nx.DiGraph()
    for u, v, relation in edges:
        g.add_edge(u, v, relation=relation)
    for n in isolated_nodes:
        g.add_node(n)
    return NodeSignageManager(g), g


# ---- entry_point ----


@pytest.mark.parametrize(
    "node,expected",
    [
        ("actiondefinition", "action定義を探している場合はここ"),
        ("partdefinition", "part定義を探している場合はここ"),
        ("itemdefinition", "item定義を探している場合はここ"),
        ("portdefinition", "port定義を探している場合はここ"),
        ("interfacedefinition", "interface定義を探している場合はここ"),
        ("constraintdefinition", "constraint定義を探している場合はここ"),
        ("requirementdefinition", "requirement定義を探している場合はここ"),
        ("somethingdefinition", "定義を探している場合はここ"),
        ("actionusage", "action使用を探している場合はここ"),
        ("partusage", "part使用を探している場合はここ"),
        ("itemusage", "item使用を探している場合はここ"),
        ("genericusage", "使用を探している場合はここ"),
        ("someparameter", "parameterを探している場合はここ"),
        ("someparam", "parameterを探している場合はここ"),
        ("someconstraint", "constraintを探している場合はここ"),
        ("somerequirement", "requirementを探している場合はここ"),
    ],
)
def test_entry_point_matches_expected_message(node, expected):
    manager, _ = _manager(isolated_nodes=[node])

    assert manager.get_signage(node)["entry_point"] == expected


def test_entry_point_absent_when_no_keyword_matches():
    manager, _ = _manager(isolated_nodes=["widget"])

    assert "entry_point" not in manager.get_signage("widget")


# ---- exit_routes ----


@pytest.mark.parametrize(
    "relation",
    [
        "has_parameter",
        "requires_input",
        "produces_output",
        "is_defined_in",
        "governs_flow_of",
        "splits_into",
        "merges_from",
        "specializes",
        "subsets",
        "redefines",
        "is-a",
        "part-of",
        "uses",
        "depends-on",
        "some_unmapped_relation",
    ],
)
def test_exit_routes_labels_edge_with_its_relation(relation):
    manager, _ = _manager(edges=[("source_node", "target_node", relation)])

    routes = manager.get_signage("source_node")["exit_routes"]

    assert f"target_node → {relation}" in routes


def test_exit_routes_regression_edge_relation_not_overridden_by_parameter_in_name():
    """バグ修正の回帰テスト: ノード名に'parameter'を含んでも実際のrelationを保持する。"""
    manager, _ = _manager(edges=[("actionparameter", "target_node", "uses")])

    routes = manager.get_signage("actionparameter")["exit_routes"]

    assert "target_node → uses" in routes
    assert "target_node → has_parameter" not in routes


def test_exit_routes_deduplicates_identical_entries():
    g = nx.DiGraph()
    g.add_edge("source_node", "target_node", relation="uses")
    manager = NodeSignageManager(g)
    # 手動で重複するルートを追加してみても集合として扱われる
    manager.update_signage(
        "source_node", {"exit_routes": manager.get_signage("source_node")["exit_routes"]}
    )

    routes = manager.get_signage("source_node")["exit_routes"]
    assert len(routes) == len(set(routes))


def test_exit_routes_adds_generic_usage_pointer_for_definition_nodes():
    manager, _ = _manager(isolated_nodes=["actiondefinition"])

    routes = manager.get_signage("actiondefinition")["exit_routes"]

    assert "actionusage → 使用例を参照" in routes


def test_exit_routes_adds_generic_pointers_for_parameter_nodes():
    manager, _ = _manager(isolated_nodes=["someparameter"])

    routes = manager.get_signage("someparameter")["exit_routes"]

    assert "action → has_parameter" in routes
    assert "constraint → constraint_parameter" in routes


def test_exit_routes_adds_generic_pointers_for_constraint_nodes():
    manager, _ = _manager(isolated_nodes=["someconstraint"])

    routes = manager.get_signage("someconstraint")["exit_routes"]

    assert "requirement → constraint" in routes
    assert "action → constraint" in routes


def test_exit_routes_absent_for_isolated_node_without_keywords():
    manager, _ = _manager(isolated_nodes=["widget"])

    assert "exit_routes" not in manager.get_signage("widget")


# ---- warnings ----


def test_warnings_for_definition_node_includes_action_specific_hint():
    manager, _ = _manager(isolated_nodes=["actiondefinition"])

    warnings = manager.get_signage("actiondefinition")["warnings"]

    assert "詳細実装は別ノード参照" in warnings
    assert "actionusageノードで使用例を確認" in warnings


def test_warnings_for_definition_node_includes_part_specific_hint():
    manager, _ = _manager(isolated_nodes=["partdefinition"])

    warnings = manager.get_signage("partdefinition")["warnings"]

    assert "partusageノードで使用例を確認" in warnings


def test_warnings_for_usage_node_points_to_definition():
    manager, _ = _manager(isolated_nodes=["actionusage"])

    warnings = manager.get_signage("actionusage")["warnings"]

    assert "定義は対応するdefinitionノードを参照" in warnings


def test_warnings_for_parameter_node():
    manager, _ = _manager(isolated_nodes=["someparameter"])

    warnings = manager.get_signage("someparameter")["warnings"]

    assert "パラメータの詳細はactionノードを参照" in warnings


def test_warnings_for_constraint_node():
    manager, _ = _manager(isolated_nodes=["someconstraint"])

    warnings = manager.get_signage("someconstraint")["warnings"]

    assert "制約の詳細はrequirementノードを参照" in warnings


def test_warnings_flags_low_connectivity_node():
    manager, _ = _manager(isolated_nodes=["widget"])

    warnings = manager.get_signage("widget")["warnings"]

    assert "このノードは接続が少ないため、関連情報が限定的です" in warnings


def test_warnings_skips_low_connectivity_flag_for_well_connected_node():
    manager, _ = _manager(edges=[("in1", "sink", "uses"), ("in2", "sink", "uses")])

    warnings = manager.get_signage("sink").get("warnings", [])

    assert "このノードは接続が少ないため、関連情報が限定的です" not in warnings


# ---- signage is omitted entirely when there is nothing to report ----


def test_signage_key_absent_for_node_with_no_keywords_and_enough_connections():
    manager, graph = _manager(edges=[("in1", "sink", "uses"), ("in2", "sink", "uses")])

    assert "signage" not in graph.nodes["sink"]
    assert manager.get_signage("sink") == {}


# ---- get_signage / update_signage ----


def test_get_signage_returns_empty_dict_for_unknown_node():
    manager, _ = _manager()

    assert manager.get_signage("does-not-exist") == {}


def test_update_signage_is_noop_for_unknown_node():
    manager, _ = _manager()

    manager.update_signage("does-not-exist", {"entry_point": "x"})  # should not raise

    assert manager.get_signage("does-not-exist") == {}


def test_update_signage_merges_into_existing_signage():
    manager, _ = _manager(isolated_nodes=["widget"])

    manager.update_signage("widget", {"custom_note": "hello"})

    signage = manager.get_signage("widget")
    assert signage["custom_note"] == "hello"
    # 既存のwarningsは保持される
    assert "warnings" in signage
