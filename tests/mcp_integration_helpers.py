"""MCPサーバーのend-to-end統合テスト用の共通ヘルパー。

FastMCPクライアントで各 ``mcp_server.py`` を実際にサブプロセスとして起動し、
MCPプロトコル経由でツール呼び出しを検証するテスト(``test_mcp_integration_*.py``)
から使う。単体テストが内部関数を直接呼ぶのに対し、ここでは実際の
stdio起動・ハンドシェイク・ツールディスパッチまで含めて検証する。

MCP SDKは子プロセスへ安全リストの環境変数しか渡さない
(``mcp.client.stdio.get_default_environment()`` はPATH等のみで、
``OPENAI_API_KEY`` を含まない)ため、渡したい変数は明示的に
``PythonStdioTransport(env=...)`` へ載せる必要がある
(``openai_call_mcp.build_child_environment`` と同じ理由)。
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Optional

from fastmcp import Client
from fastmcp.client.transports import PythonStdioTransport
from mcp.client.stdio import get_default_environment

REPO_ROOT = Path(__file__).resolve().parent.parent

# conftest.py がテスト全体でOPENAI_API_KEYをこのダミー値に強制上書きしている。
# 子プロセスにも同じ値を渡し、実APIキー不在でもサーバー起動自体は
# 妨げられないようにする(実際の埋め込み/LLM呼び出しは行わないツールのみを検証する)。
DUMMY_OPENAI_API_KEY = "test-openai-key-for-pytest"


def make_stdio_client(script_path: str, extra_env: Optional[dict[str, Any]] = None) -> Client:
    """指定した ``mcp_server.py`` をstdioサブプロセスとして起動するClientを作る。

    Args:
        script_path: リポジトリルートからの相対、または絶対パス。
        extra_env: 追加で子プロセスに渡す環境変数(例: リランカー先読み無効化)。

    Returns:
        Client: ``async with`` で接続する未接続のFastMCPクライアント。
    """
    env = dict(get_default_environment())
    env["OPENAI_API_KEY"] = os.environ.get("OPENAI_API_KEY") or DUMMY_OPENAI_API_KEY
    if extra_env:
        env.update({k: str(v) for k, v in extra_env.items()})

    resolved = Path(script_path)
    if not resolved.is_absolute():
        resolved = REPO_ROOT / resolved

    transport = PythonStdioTransport(
        script_path=str(resolved),
        env=env,
        cwd=str(REPO_ROOT),
    )
    return Client(transport)
