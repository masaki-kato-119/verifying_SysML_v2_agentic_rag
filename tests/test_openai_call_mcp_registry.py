"""全サーバーのツール統合提示と経路解決のテスト（MCP はモック）。

1 サーバー分のツールしか LLM に渡していなかったため、LLM は
バックエンドを選べず HybridRAG に固定されていた。その退行を検知する。
"""

import json
from types import SimpleNamespace

import pytest


@pytest.fixture(scope="module")
def ocm():
    """モジュールは OPENAI_API_KEY 設定済み（conftest）後に読み込む。"""
    import openai_call_mcp as m

    return m


def _tool(name, description=""):
    """Responses API の function tool 形状（function 配下へ入れ子にしない）。"""
    return {"type": "function", "name": name, "description": description, "parameters": {}}


def _call(call_id, name, arguments):
    """Responses API の function_call 出力アイテムを模す。"""
    return SimpleNamespace(
        type="function_call", call_id=call_id, name=name, arguments=arguments
    )


class FakeMcp:
    def __init__(self, label):
        self.label = label
        self.calls = []

    async def call_tool(self, name, args):
        self.calls.append((name, args))
        return SimpleNamespace(structured_content={"from": self.label, "tool": name})


@pytest.fixture
def servers_map():
    return {
        "Hybrid RAG MCP Server": {
            "mcp": FakeMcp("hybrid"),
            "tools": [_tool("hybrid_search", "検索")],
            "kind": "fastmcp-stdio",
        },
        "Graph RAG MCP Server": {
            "mcp": FakeMcp("graph"),
            "tools": [_tool("smart_search"), _tool("find_path")],
            "kind": "fastmcp-stdio",
        },
    }


def test_make_server_slug_sanitizes_names(ocm):
    assert ocm.make_server_slug("Hybrid RAG MCP Server") == "hybrid_rag_mcp_server"
    assert ocm.make_server_slug("グラフ RAG") == "rag"
    assert ocm.make_server_slug("!!!") == "server"


def test_registry_exposes_every_server_at_once(ocm, servers_map):
    """LLM がバックエンドを選べるには、全サーバーのツールが同時に見えている必要がある。"""
    tools, routing = ocm.build_tool_registry(servers_map)

    names = [t["name"] for t in tools]
    assert names == [
        "hybrid_rag_mcp_server__hybrid_search",
        "graph_rag_mcp_server__smart_search",
        "graph_rag_mcp_server__find_path",
    ]
    assert len(routing) == 3
    assert routing["graph_rag_mcp_server__find_path"]["server"] == "Graph RAG MCP Server"
    assert routing["graph_rag_mcp_server__find_path"]["tool"] == "find_path"


def test_registry_tags_description_with_server_name(ocm, servers_map):
    tools, _ = ocm.build_tool_registry(servers_map)

    assert tools[0]["description"].startswith("[Hybrid RAG MCP Server]")


def test_registry_does_not_mutate_source_tools(ocm, servers_map):
    ocm.build_tool_registry(servers_map)

    assert servers_map["Hybrid RAG MCP Server"]["tools"][0]["name"] == "hybrid_search"


def test_registry_only_filters_to_one_server(ocm, servers_map):
    tools, routing = ocm.build_tool_registry(servers_map, only="Graph RAG MCP Server")

    assert [t["name"] for t in tools] == [
        "graph_rag_mcp_server__smart_search",
        "graph_rag_mcp_server__find_path",
    ]
    assert all(r["server"] == "Graph RAG MCP Server" for r in routing.values())


def test_registry_disambiguates_colliding_slugs(ocm):
    servers = {
        "RAG!": {"mcp": FakeMcp("a"), "tools": [_tool("search")]},
        "R.A.G.": {"mcp": FakeMcp("b"), "tools": [_tool("search")]},
    }

    tools, routing = ocm.build_tool_registry(servers)

    names = [t["name"] for t in tools]
    assert len(set(names)) == 2
    assert {r["server"] for r in routing.values()} == {"RAG!", "R.A.G."}


def test_registry_keeps_tool_names_within_openai_limit(ocm):
    servers = {"x" * 80: {"mcp": FakeMcp("a"), "tools": [_tool("search")]}}

    tools, routing = ocm.build_tool_registry(servers)

    name = tools[0]["name"]
    assert len(name) <= ocm.MAX_TOOL_NAME_LENGTH
    assert routing[name]["tool"] == "search"


@pytest.mark.asyncio
async def test_execute_routes_each_call_to_its_own_server(ocm, servers_map):
    """1 ターン内で複数バックエンドを併用できる（= 協調が成立する）。"""
    _, routing = ocm.build_tool_registry(servers_map)
    calls = [
        _call("c1", "hybrid_rag_mcp_server__hybrid_search", '{"query":"a"}'),
        _call("c2", "graph_rag_mcp_server__find_path", '{"source":"x"}'),
    ]
    history = []

    results = await ocm.execute_tool_calls_and_append(history, routing, calls)

    # 接頭辞は剥がしてから各サーバーへ渡す
    assert servers_map["Hybrid RAG MCP Server"]["mcp"].calls == [("hybrid_search", {"query": "a"})]
    assert servers_map["Graph RAG MCP Server"]["mcp"].calls == [("find_path", {"source": "x"})]
    assert [r["server"] for r in results] == ["Hybrid RAG MCP Server", "Graph RAG MCP Server"]
    assert [h["type"] for h in history] == ["function_call_output", "function_call_output"]
    assert [h["call_id"] for h in history] == ["c1", "c2"]
    assert json.loads(history[1]["output"])["from"] == "graph"


@pytest.mark.asyncio
async def test_execute_reports_unknown_tool_without_raising(ocm):
    history = []

    results = await ocm.execute_tool_calls_and_append(
        history, {}, [_call("c1", "nope", "{}")]
    )

    assert "登録されていません" in results[0]["content"]
    assert history[0]["call_id"] == "c1"


@pytest.mark.asyncio
async def test_execute_reports_invalid_arguments_json(ocm, servers_map):
    _, routing = ocm.build_tool_registry(servers_map)
    history = []

    results = await ocm.execute_tool_calls_and_append(
        history, routing, [_call("c1", "hybrid_rag_mcp_server__hybrid_search", "{not json")]
    )

    assert "JSON" in results[0]["content"]
    # 壊れた引数でサーバーを叩かない
    assert servers_map["Hybrid RAG MCP Server"]["mcp"].calls == []


@pytest.mark.asyncio
async def test_expose_tools_allowlist_filters_tool_surface(ocm, tmp_path, monkeypatch):
    """管理系ツールを隠して検索系だけを提示できる。"""
    cfg = tmp_path / "m.json"
    cfg.write_text(
        json.dumps(
            {
                "mcpServers": {
                    "srv": {
                        "command": "python",
                        "args": ["-c", "pass"],
                        "expose_tools": ["smart_search"],
                    }
                }
            }
        ),
        encoding="utf-8",
    )

    class FakeClient:
        async def list_tools(self):
            return [
                SimpleNamespace(name="smart_search", description="", input_schema={}),
                SimpleNamespace(name="clear_all_graphs", description="", input_schema={}),
            ]

    async def fake_create(*a, **kw):
        return FakeClient(), "fastmcp-stdio"

    monkeypatch.setattr(ocm, "create_mcp_client", fake_create)

    servers = await ocm.load_mcp_servers_from_file(str(cfg))

    assert [t["name"] for t in servers["srv"]["tools"]] == ["smart_search"]


def test_child_environment_includes_declared_vars(ocm):
    """MCP SDK は安全リストしか子へ渡さないので、明示的に載せる必要がある。"""
    child = ocm.build_child_environment({"OPENAI_API_KEY": "sk-test"})

    assert child["OPENAI_API_KEY"] == "sk-test"


def test_child_environment_keeps_safe_defaults(ocm):
    """PATH 等を落とすと子プロセスが起動できなくなる。"""
    child = ocm.build_child_environment({"OPENAI_API_KEY": "sk-test"})

    assert "PATH" in child


def test_child_environment_is_none_when_nothing_declared(ocm):
    """env 未指定なら SDK の既定動作に任せる。"""
    assert ocm.build_child_environment(None) is None
    assert ocm.build_child_environment({}) is None


def test_child_environment_stringifies_values(ocm):
    child = ocm.build_child_environment({"PORT": 8765})

    assert child["PORT"] == "8765"


def _tool_with_params(name, properties, required=None):
    return {
        "type": "function",
        "name": name,
        "description": "",
        "parameters": {
            "type": "object",
            "properties": dict(properties),
            "required": list(required or []),
        },
    }


def test_prune_removes_hidden_parameters(ocm):
    """重いオプションを隠すとサーバ側の既定値（＝無効）が使われる。"""
    tool = _tool_with_params("hybrid_search", {"query": {}, "use_rerank": {}, "use_mmr": {}})

    pruned = ocm.prune_tool_parameters(tool, ["use_rerank", "use_mmr"])

    assert set(pruned["parameters"]["properties"]) == {"query"}


def test_prune_does_not_mutate_original(ocm):
    tool = _tool_with_params("hybrid_search", {"query": {}, "use_rerank": {}})

    ocm.prune_tool_parameters(tool, ["use_rerank"])

    assert "use_rerank" in tool["parameters"]["properties"]


def test_prune_drops_hidden_names_from_required(ocm):
    """required に残ると LLM が渡せない値を要求されてしまう。"""
    tool = _tool_with_params("t", {"query": {}, "use_rerank": {}}, required=["query", "use_rerank"])

    pruned = ocm.prune_tool_parameters(tool, ["use_rerank"])

    assert pruned["parameters"]["required"] == ["query"]


def test_prune_with_empty_hidden_list_is_noop(ocm):
    tool = _tool_with_params("t", {"query": {}})

    assert ocm.prune_tool_parameters(tool, []) is tool


def test_prune_tolerates_missing_parameters_block(ocm):
    tool = {"type": "function", "name": "t", "description": ""}

    assert ocm.prune_tool_parameters(tool, ["x"])["name"] == "t"


def test_apply_hidden_tool_params_targets_named_tool_only(ocm):
    tools = [
        _tool_with_params("hybrid_search", {"query": {}, "use_rerank": {}}),
        _tool_with_params("vector_search", {"query": {}, "use_rerank": {}}),
    ]

    out = ocm.apply_hidden_tool_params(tools, {"hybrid_search": ["use_rerank"]}, "srv")

    assert set(out[0]["parameters"]["properties"]) == {"query"}
    assert set(out[1]["parameters"]["properties"]) == {"query", "use_rerank"}


def test_apply_hidden_tool_params_without_config_is_noop(ocm):
    tools = [_tool_with_params("t", {"query": {}})]

    assert ocm.apply_hidden_tool_params(tools, None, "srv") is tools
