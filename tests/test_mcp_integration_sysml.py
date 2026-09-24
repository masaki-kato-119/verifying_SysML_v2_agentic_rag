"""SysML v2 Checker MCPサーバーのend-to-end統合テスト。優先度: 公開準備(t4)。

このサーバーはOpenAI APIキーを一切必要としない(``mcp_servers.json`` でも
``"env": {}``)ため、パース・リント・AST生成を実際にネットワーク無しで
最初から最後まで検証できる。FastMCPクライアントで実際にサブプロセス起動し、
MCPプロトコル経由でツール呼び出しの往復を検証する。
"""

from __future__ import annotations

import pytest
from mcp_integration_helpers import REPO_ROOT, make_stdio_client

EXPECTED_TOOLS = {
    "parse_sysml_file",
    "parse_sysml_text",
    "lint_sysml_file",
    "lint_sysml_text",
    "get_ast_json",
    "analyze_sysml_complete",
    "get_semantic_model_file",
    "get_semantic_model_text",
    "get_server_info",
}

# 2026-09-24: import 無しの組み込み型は参照実装0.62.0でエラー（Couldn't resolve reference to Type 'X'.）。
# 正しいモデルとして使うため ScalarValues を import する
VALID_SYSML_TEXT = """
package SimpleTest {
    private import ScalarValues::*;
    part def SimplePart {
        attribute name : String;
    }
}
"""


@pytest.fixture
async def sysml_client():
    client = make_stdio_client(REPO_ROOT / "sysml_v2_checker_advanced" / "mcp_server.py")
    async with client:
        yield client


async def test_server_starts_and_lists_expected_tools(sysml_client):
    tools = await sysml_client.list_tools()
    names = {t.name for t in tools}

    assert EXPECTED_TOOLS <= names


async def test_get_server_info(sysml_client):
    result = await sysml_client.call_tool("get_server_info", {})

    assert result.data["name"] == "SysML v2 Advanced Checker MCP Server"
    assert set(result.data["tools"]) == EXPECTED_TOOLS


async def test_parse_sysml_text_round_trip(sysml_client):
    result = await sysml_client.call_tool("parse_sysml_text", {"sysml_text": VALID_SYSML_TEXT})

    assert result.data["success"] is True


async def test_lint_sysml_text_round_trip(sysml_client):
    result = await sysml_client.call_tool("lint_sysml_text", {"sysml_text": VALID_SYSML_TEXT})

    assert result.data["success"] is True
    assert result.data["summary"]["errors"] == 0


async def test_analyze_sysml_complete_round_trip(sysml_client):
    """analyze_sysml_complete はテキスト直接渡しに対応しておらずファイルパス指定のみ。"""
    result = await sysml_client.call_tool("analyze_sysml_complete", {"file_path": "test_sysml.sysml"})

    assert result.data["success"] is True
    assert "ast_json" in result.data


async def test_get_semantic_model_text_round_trip(sysml_client):
    result = await sysml_client.call_tool("get_semantic_model_text", {"sysml_text": VALID_SYSML_TEXT})

    assert result.data["success"] is True
    semantic_model = result.data["semantic_model"]
    assert semantic_model["root_id"] == "$root"
    assert "$root::SimplePart" in semantic_model["nodes"]
    assert semantic_model["nodes"]["$root::SimplePart"]["type"] == "part_def"
    assert isinstance(semantic_model["edges"], list)


async def test_get_semantic_model_text_parse_error(sysml_client):
    result = await sysml_client.call_tool("get_semantic_model_text", {"sysml_text": "this is not valid sysml {{{"})

    assert result.data["success"] is False
    assert result.data["semantic_model"] is None


# 行番号の付いた指摘（2026-09-25）。以前は lint 系ツールの指摘に位置が無く
# （line も source_range も None）、LLM がどの行を直せばよいか分からなかった。
# 各エラーを別の行に置き、ツールの応答がその行を指すことを確かめる。
LOCATED_ERRORS_TEXT = """package P {
    private import ISQ::*;
    part def V {
        attribute m : ISQ::Mass;
        attribute w = 1.8 [kg];
    }
    action def B {
        action a { out x : MassValue; }
        action b { in y : MassValue; }
        flow x to b.y;
    }
    event TimerEvent;
    part def S { port p : ~Nope; }
}
"""

# ルール → そのエラーがある行
EXPECTED_ERROR_LINES = {
    "_check_attribute_def": 4,  # ISQ::Mass は存在しない
    "_check_quantity_units": 5,  # SI を import していない kg
    "_check_one_flow_end": 10,  # 名前1つの flow の端点
    "_check_event_references": 12,  # `event X;` は参照で、X が無い
    "_check_port_usage": 13,  # 存在しない port def
    "_check_conjugated_port_typing": 13,  # 合成ノードの指摘も元の port usage の行に付く
}


def _error_lines(issues):
    return {i["rule"]: i["line"] for i in issues if i["severity"] == "error"}


async def test_lint_sysml_text_reports_the_line_of_each_error(sysml_client):
    result = await sysml_client.call_tool("lint_sysml_text", {"sysml_text": LOCATED_ERRORS_TEXT})

    assert result.data["success"] is True
    issues = result.data["issues"]
    assert _error_lines(issues) == EXPECTED_ERROR_LINES
    assert all(i["line"] is not None for i in issues)
    ranged = [i for i in issues if i["rule"] == "_check_attribute_def"][0]
    assert ranged["source_range"]["start_line"] == 4
    assert ranged["element_id"] == "$root::V::m"


async def test_lint_sysml_file_reports_the_line_of_each_error(sysml_client, tmp_path):
    path = tmp_path / "located.sysml"
    path.write_text(LOCATED_ERRORS_TEXT, encoding="utf-8")

    result = await sysml_client.call_tool("lint_sysml_file", {"file_path": str(path)})

    assert result.data["success"] is True
    assert _error_lines(result.data["issues"]) == EXPECTED_ERROR_LINES
