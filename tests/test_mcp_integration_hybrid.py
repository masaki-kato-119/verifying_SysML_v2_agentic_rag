"""HybridRAG MCPサーバーのend-to-end統合テスト。優先度: 公開準備(t2)。

従来は ``(PROJECT_ROOT / "mcp_server.py").exists()`` というファイル存在チェック
のみで、実際にサーバープロセスが起動しMCPハンドシェイクが成立するか・ツール
スキーマが壊れていないかは一度も検証されていなかった。ここではFastMCP
クライアントで実際に ``HybridRAG/mcp_server.py`` をサブプロセス起動し、
ネットワーク呼び出し(OpenAI Embedding API)を伴わない範囲でツール呼び出しの
往復を検証する。

``meta_search``/``list_documents`` はSQLiteメタデータのみを読むため、
``HybridRAG/data`` が未生成のクリーンな環境（CI等）でも空リストで正常応答する。
"""

from __future__ import annotations

import pytest
from mcp_integration_helpers import REPO_ROOT, make_stdio_client

EXPECTED_TOOLS = {
    "hybrid_search",
    "vector_search",
    "meta_search",
    "semantic_search",
    "index_path",
    "list_documents",
    "delete_document",
    "update_document",
}


@pytest.fixture
async def hybrid_client():
    client = make_stdio_client(
        REPO_ROOT / "HybridRAG" / "mcp_server.py",
        extra_env={"RAG_PRELOAD_RERANKER": "0"},
    )
    async with client:
        yield client


async def test_server_starts_and_lists_expected_tools(hybrid_client):
    tools = await hybrid_client.list_tools()
    names = {t.name for t in tools}

    assert EXPECTED_TOOLS <= names


async def test_meta_search_round_trip_without_network(hybrid_client):
    result = await hybrid_client.call_tool("meta_search", {"limit": 1})

    assert isinstance(result.data, list)
    if result.data:
        assert "chunk_id" in result.data[0]


async def test_list_documents_round_trip_without_network(hybrid_client):
    result = await hybrid_client.call_tool("list_documents", {})

    assert isinstance(result.data, list)
    if result.data:
        assert "file_path" in result.data[0]
