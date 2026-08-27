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
    "get_server_info",
}

VALID_SYSML_TEXT = """
package SimpleTest {
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
