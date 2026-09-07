"""GraphRAG MCPサーバーのend-to-end統合テスト。優先度: 公開準備(t3)。

GraphRAG/mcp_server.py は2,160行あるが、従来はファイル存在チェックのみで
実質テストゼロだった。FastMCPクライアントで実際にサブプロセス起動し、
ネットワーク呼び出しを伴わないツール(``list_graphs``/``get_active_graph``)
の往復を検証する。これらはサーバー起動時に ``GraphRAG/data/graphs/*.pkl``
から自動登録されたグラフの一覧を返すだけで、OpenAI APIを呼ばない。

``GraphRAG/data`` が存在しないクリーンな環境（CI等）では登録グラフ0件で
正常応答する。
"""

from __future__ import annotations

import pytest
from mcp_integration_helpers import REPO_ROOT, make_stdio_client

EXPECTED_TOOLS = {
    "load_graph",
    "search_graph",
    "explore_graph",
    "find_path",
    "smart_search",
    "list_graphs",
    "get_active_graph",
}


@pytest.fixture
async def graph_client():
    client = make_stdio_client(REPO_ROOT / "GraphRAG" / "mcp_server.py")
    async with client:
        yield client


async def test_server_starts_and_lists_expected_tools(graph_client):
    tools = await graph_client.list_tools()
    names = {t.name for t in tools}

    assert EXPECTED_TOOLS <= names


async def test_list_graphs_round_trip_without_network(graph_client):
    result = await graph_client.call_tool("list_graphs", {})

    assert result.data["success"] is True
    assert isinstance(result.data["graphs"], list)


async def test_get_active_graph_round_trip_without_network(graph_client):
    result = await graph_client.call_tool("get_active_graph", {})

    assert result.data["success"] is True
    assert isinstance(result.data["registered_graphs"], list)


async def test_find_path_uses_deduplicated_graph_if_present(graph_client):
    """データが存在する場合(a4_graph_path_precision対応後)の経路探索が
    表記ゆれ重複ノードを経由せず動作することを回帰確認する。データが無い
    クリーン環境ではノード不在エラーを許容する。
    """
    result = await graph_client.call_tool(
        "find_path", {"start_node": "requirement", "end_node": "requirement usage"}
    )

    if result.data.get("success"):
        assert result.data["path"] == ["requirement", "requirement usage"]


_SYSML_WITH_LINT_WARNING = """
package TestPackage {
    part def Vehicle {
        attribute mass : NonExistentType;
    }
}
"""


async def test_validate_sysml_model_does_not_crash_on_lint_issues(graph_client):
    """回帰テスト: _format_lint_issue が存在しない issue.rule/issue.location を
    直接参照してAttributeErrorになり、validate_sysml_modelが指摘事項を含む
    モデルに対して汎用エラーしか返せなくなっていた既存バグの再発防止
    （SysMLv2_SemanticModel_作業計画書.md Phase0）。
    """
    result = await graph_client.call_tool(
        "validate_sysml_model", {"sysml_model_text": _SYSML_WITH_LINT_WARNING}
    )

    assert result.data["success"] is True
    lint_results = result.data["lint_results"]
    assert lint_results["total_issues"] >= 1
    all_details = (
        lint_results["error_details"]
        + lint_results["warning_details"]
        + lint_results["info_details"]
    )
    assert all_details
    for detail in all_details:
        # 2026-09-07、Viewer Phase C c1: confidence を追加（実測テーブルに
        # 載っていないルールでは None）。
        assert set(detail) == {
            "severity", "rule", "message", "location", "confidence", "suggestion",
        }

    # 2026-09-03、P3-4: locationはSemantic Model連携により実際のsource_rangeを
    # 返すようになった（以前は常にNoneだった応急処置状態から本対応済み）。
    assert any(detail["location"] is not None for detail in all_details)
    located = next(detail for detail in all_details if detail["location"] is not None)
    assert located["location"]["start_line"] == 4
