"""GraphRAG MCPサーバーへの永続的なstdioクライアント（Group4 b15/b16, R1）。

b15での決定：Viewerバックエンド（FastAPI）からHybridRAG/GraphRAGを呼ぶ方式は
MCPクライアント(stdio)経由とする。README.md（18〜24行）が明記する公開契約が
「MCPサーバー（stdio経由）」であり、`GraphRAG/graphrag/`配下は内部実装として
シグネチャ安定性が保証されていないため。

接続はリクエストごとに起動せず、プロセス内で1つだけ生成して使い回す
（`tests/mcp_integration_helpers.py`と同じfastmcp Client + PythonStdioTransport
パターンだが、`async with`でその場を抜けず`__aenter__`したまま保持する点が
異なる）。明示的なシャットダウンフックは持たない――開発ツールとしての
Viewerプロセス終了時に子プロセスも終了する、という割り切り（作業計画書
Group4リスク欄と同じ「必要になった時点で見直す」方針）。
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
from typing import Optional

from fastmcp import Client
from fastmcp.client.transports import PythonStdioTransport
from mcp.client.stdio import get_default_environment

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_GRAPHRAG_SERVER_SCRIPT = _REPO_ROOT / "GraphRAG" / "mcp_server.py"

# tests/mcp_integration_helpers.pyと同じ理由：MCP SDKは子プロセスへ安全リストの
# 環境変数しか渡さない(PATH等のみ)ため、OPENAI_API_KEYは明示的に渡す必要がある。
# 実キーが無くても、埋め込み/LLM呼び出しを行わないツール(search_graph等)の
# 起動・呼び出し自体は妨げられない。
_DUMMY_OPENAI_API_KEY = "dev-placeholder-openai-key"

_client: Optional[Client] = None
_client_lock = asyncio.Lock()


def _build_client() -> Client:
    env = dict(get_default_environment())
    env["OPENAI_API_KEY"] = os.environ.get("OPENAI_API_KEY") or _DUMMY_OPENAI_API_KEY
    transport = PythonStdioTransport(
        script_path=str(_GRAPHRAG_SERVER_SCRIPT),
        env=env,
        cwd=str(_REPO_ROOT),
    )
    return Client(transport)


async def get_rag_client() -> Client:
    """接続済みのGraphRAG MCPクライアントを返す（初回呼び出し時のみ起動）。"""
    global _client
    async with _client_lock:
        if _client is None:
            client = _build_client()
            await client.__aenter__()
            _client = client
    return _client
