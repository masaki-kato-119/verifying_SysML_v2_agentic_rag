"""openai_call_mcp のユニットテスト（MCP / API はモック）。"""

import json
import logging
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.fixture(scope="module")
def ocm():
    """モジュールは OPENAI_API_KEY 設定済み（conftest）後に読み込む。"""
    import openai_call_mcp as m

    return m


def _routing(mcp, *tool_names):
    """単一サーバー向けの経路表を組み立てる（接頭辞なしのツール名で登録）。"""
    return {
        name: {"server": "Test MCP", "tool": name, "mcp": mcp} for name in (tool_names or ("t",))
    }


def _call(call_id, name="t", arguments="{}"):
    """Responses API の function_call 出力アイテムを模す。"""
    return SimpleNamespace(
        type="function_call", call_id=call_id, name=name, arguments=arguments
    )


def _response(output):
    """Responses API のレスポンスを模す。"""
    return SimpleNamespace(output=list(output), output_text="")


def test_build_openai_tools_skips_nameless(ocm):
    tools = [
        SimpleNamespace(name=None),
        SimpleNamespace(name="t", description="d", inputSchema={"type": "object"}),
    ]
    out = ocm.build_openai_tools(tools)
    assert len(out) == 1
    assert out[0]["name"] == "t"
    assert out[0]["parameters"] == {"type": "object"}


def test_build_openai_tools_reads_mcp_camel_case_schema(ocm):
    """MCP 仕様の属性名は inputSchema。ここを取り違えると常に空スキーマになり、
    LLM が引数名を推測するしかなくなる。"""
    schema = {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]}
    t = SimpleNamespace(name="hybrid_search", description="", inputSchema=schema)

    out = ocm.build_openai_tools([t])

    assert out[0]["parameters"] == schema


def test_build_openai_tools_falls_back_to_snake_case_schema(ocm):
    schema = {"type": "object", "properties": {"q": {"type": "string"}}}
    t = SimpleNamespace(name="x", description="", input_schema=schema)

    out = ocm.build_openai_tools([t])

    assert out[0]["parameters"] == schema


def test_build_openai_tools_non_dict_schema(ocm):
    t = SimpleNamespace(name="x", description="", inputSchema=None)
    out = ocm.build_openai_tools([t])
    assert out[0]["parameters"] == {}


def test_extract_function_calls_filters_reasoning_items(ocm):
    """reasoning アイテムを function_call と取り違えないこと。"""
    response = _response([
        SimpleNamespace(type="reasoning"),
        _call("c1", "fn", '{"a":1}'),
        SimpleNamespace(type="message"),
    ])

    calls = ocm.extract_function_calls(response)

    assert [c.call_id for c in calls] == ["c1"]


def test_extract_function_calls_handles_empty_output(ocm):
    assert ocm.extract_function_calls(SimpleNamespace(output=None)) == []


def test_response_output_text_prefers_output_text(ocm):
    r = SimpleNamespace(output=[], output_text="answer")

    assert ocm.response_output_text(r) == "answer"


def test_response_output_text_falls_back_to_content(ocm):
    r = SimpleNamespace(
        output_text=None,
        output=[SimpleNamespace(content=[SimpleNamespace(text="a"), SimpleNamespace(text="b")])],
    )

    assert ocm.response_output_text(r) == "ab"


def test_parse_args_defaults(ocm):
    with patch.object(sys, "argv", ["openai_call_mcp.py"]):
        args = ocm.parse_args()
    assert args.model == "gpt-5.6-terra"
    assert args.no_mcp is False
    # Responses API ではツール併用時も推論を使える
    assert args.reasoning_effort == "low"


def test_ensure_and_append_log(ocm, tmp_path):
    p = ocm.ensure_log_file(str(tmp_path))
    assert Path(p).exists()
    ocm.append_log(p, "\nhello")
    assert "hello" in Path(p).read_text(encoding="utf-8")


@pytest.mark.asyncio
async def test_load_mcp_servers_missing_file(ocm):
    r = await ocm.load_mcp_servers_from_file("__nonexistent_file__.json")
    assert r == {}


@pytest.mark.asyncio
async def test_load_mcp_servers_empty_servers(ocm, tmp_path):
    p = tmp_path / "m.json"
    p.write_text('{"mcpServers": {}}', encoding="utf-8")
    r = await ocm.load_mcp_servers_from_file(str(p))
    assert r == {}


@pytest.mark.asyncio
async def test_load_mcp_servers_stdio_mock(ocm, tmp_path, monkeypatch):
    p = tmp_path / "m.json"
    p.write_text(
        json.dumps({"mcpServers": {"srv": {"command": "python", "args": ["-c", "pass"]}}}),
        encoding="utf-8",
    )

    class FakeClient:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return None

        async def list_tools(self):
            return []

    async def fake_create(*a, **kw):
        return FakeClient(), "fastmcp-stdio"

    monkeypatch.setattr(ocm, "create_mcp_client", fake_create)
    r = await ocm.load_mcp_servers_from_file(str(p))
    assert "srv" in r
    assert r["srv"]["kind"] == "fastmcp-stdio"


def test_resolve_relative_path_existing_file(ocm, tmp_path):
    """存在する相対パスは定義ファイル基準の絶対パスへ解決される。"""
    (tmp_path / "sub").mkdir()
    target = tmp_path / "sub" / "server.py"
    target.write_text("", encoding="utf-8")
    resolved = ocm._resolve_relative_path("sub/server.py", str(tmp_path))
    assert Path(resolved) == target
    assert Path(resolved).is_absolute()


def test_resolve_relative_path_leaves_options_and_absolutes(ocm, tmp_path):
    """オプション引数・絶対パス・実在しないパスはそのまま返す。"""
    assert ocm._resolve_relative_path("-c", str(tmp_path)) == "-c"
    assert ocm._resolve_relative_path("--flag", str(tmp_path)) == "--flag"
    assert ocm._resolve_relative_path("", str(tmp_path)) == ""
    assert ocm._resolve_relative_path("does/not/exist.py", str(tmp_path)) == "does/not/exist.py"
    abs_path = str(tmp_path / "x.py")
    assert ocm._resolve_relative_path(abs_path, str(tmp_path)) == abs_path


@pytest.mark.asyncio
async def test_load_mcp_servers_resolves_paths_from_config_dir(ocm, tmp_path, monkeypatch):
    """サーバ定義の相対パスは、プロセスの CWD ではなく定義ファイルの場所を基準に解決する。"""
    cfg_dir = tmp_path / "project"
    cfg_dir.mkdir()
    server_py = cfg_dir / "srv" / "mcp_server.py"
    server_py.parent.mkdir()
    server_py.write_text("", encoding="utf-8")
    cfg = cfg_dir / "mcp_servers.json"
    cfg.write_text(
        json.dumps(
            {"mcpServers": {"srv": {"command": "python", "args": ["srv/mcp_server.py"], "cwd": "."}}}
        ),
        encoding="utf-8",
    )

    captured = {}

    async def fake_create(transport, **kw):
        captured.update(kw)
        return MagicMock(list_tools=AsyncMock(return_value=[])), "fastmcp-stdio"

    monkeypatch.setattr(ocm, "create_mcp_client", fake_create)
    # 定義ファイルとは無関係なディレクトリから実行しても解決できることを確認する
    monkeypatch.chdir(tmp_path)

    r = await ocm.load_mcp_servers_from_file(str(cfg))

    assert "srv" in r
    assert str(server_py) in captured["stdio_cmd"]
    assert Path(captured["stdio_cwd"]) == cfg_dir


@pytest.mark.asyncio
async def test_try_shutdown_call_missing_method_is_noop(ocm):
    """メソッドを持たないオブジェクトでは何もしない。"""
    await ocm._try_shutdown_call(object(), "transport", "terminate", 0.1)


@pytest.mark.asyncio
async def test_try_shutdown_call_awaits_coroutine(ocm):
    """コルーチンを返すメソッドは await される。"""
    called = []

    class Tr:
        async def close(self):
            called.append("close")

    await ocm._try_shutdown_call(Tr(), "transport", "close", 0.5)
    assert called == ["close"]


@pytest.mark.asyncio
async def test_try_shutdown_call_logs_and_swallows(ocm, caplog):
    """失敗しても例外は伝播せず、debug ログに残る。"""

    class Tr:
        def kill(self):
            raise RuntimeError("boom")

    with caplog.at_level(logging.DEBUG, logger="openai_call_mcp"):
        await ocm._try_shutdown_call(Tr(), "process", "kill", 0.1)

    assert any("process.kill()" in r.getMessage() for r in caplog.records)
    # 例外そのものもログに残っていること（原因追跡のため）
    assert any(r.exc_info for r in caplog.records)


@pytest.mark.asyncio
async def test_close_mcp_client_none(ocm):
    await ocm.close_mcp_client(None)


@pytest.mark.asyncio
async def test_close_mcp_client_with_sync_close(ocm):
    c = MagicMock()
    c.close.return_value = None
    await ocm.close_mcp_client(c)


@pytest.mark.asyncio
async def test_execute_tool_calls_appends(ocm):
    class R:
        structured_content = {"ok": True}

    mcp = AsyncMock()
    mcp.call_tool = AsyncMock(return_value=R())

    calls = [_call("1")]
    hist = []
    res = await ocm.execute_tool_calls_and_append(hist, _routing(mcp), calls)
    assert hist[-1]["type"] == "function_call_output"
    assert res[0]["name"] == "t"


@pytest.mark.asyncio
async def test_execute_tool_calls_uses_data_when_no_structured(ocm):
    class R:
        structured_content = None
        data = {"x": 1}

    mcp = AsyncMock()
    mcp.call_tool = AsyncMock(return_value=R())
    calls = [_call("d1")]
    hist = []
    await ocm.execute_tool_calls_and_append(hist, _routing(mcp), calls)
    assert '"x": 1' in hist[-1]["output"]


@pytest.mark.asyncio
async def test_execute_tool_calls_content_string(ocm):
    class R:
        structured_content = None
        data = None
        content = "plain text"

    mcp = AsyncMock()
    mcp.call_tool = AsyncMock(return_value=R())
    calls = [_call("c1")]
    hist = []
    await ocm.execute_tool_calls_and_append(hist, _routing(mcp), calls)
    assert hist[-1]["output"] == "plain text"


@pytest.mark.asyncio
async def test_execute_tool_calls_content_list_with_text_attr(ocm):
    class Item:
        def __init__(self, text: str):
            self.text = text

    class R:
        structured_content = None
        data = None
        content = [Item("a"), Item("b")]

    mcp = AsyncMock()
    mcp.call_tool = AsyncMock(return_value=R())
    calls = [_call("x1")]
    hist = []
    await ocm.execute_tool_calls_and_append(hist, _routing(mcp), calls)
    assert hist[-1]["output"] == "a\nb"


@pytest.mark.asyncio
async def test_execute_tool_calls_mcp_exception(ocm):
    mcp = AsyncMock()
    mcp.call_tool = AsyncMock(side_effect=RuntimeError("boom"))
    calls = [_call("e1")]
    hist = []
    await ocm.execute_tool_calls_and_append(hist, _routing(mcp), calls)
    assert "例外" in hist[-1]["output"]


@pytest.mark.asyncio
async def test_run_llm_with_history_mocked(ocm):
    resp = _response([SimpleNamespace(type="message")])
    with patch.object(ocm.client.responses, "create", return_value=resp):
        out = await ocm.run_llm_with_history([{"role": "user", "content": "x"}], "gpt-5.6-luna")
    assert out is resp


@pytest.mark.asyncio
async def test_run_llm_omits_reasoning_effort_when_empty(ocm):
    """空文字なら reasoning を送らない（非 reasoning モデルは 400 になるため）。"""
    captured = {}

    def fake_create(**kwargs):
        captured.update(kwargs)
        return _response([])

    with patch.object(ocm.client.responses, "create", side_effect=fake_create):
        await ocm.run_llm_with_history([], "gpt-4.1", reasoning_effort="")

    assert "reasoning" not in captured


@pytest.mark.asyncio
async def test_run_llm_passes_reasoning_with_tools(ocm):
    """Responses API ではツールと推論を併用できる（chat/completions では不可だった）。"""
    captured = {}

    def fake_create(**kwargs):
        captured.update(kwargs)
        return _response([])

    with patch.object(ocm.client.responses, "create", side_effect=fake_create):
        await ocm.run_llm_with_history(
            [], "gpt-5.6-terra", tools=[{"type": "function", "name": "t"}], reasoning_effort="low"
        )

    assert captured["reasoning"] == {"effort": "low"}
    assert captured["tool_choice"] == "auto"


@pytest.mark.asyncio
async def test_run_llm_omits_tools_when_none(ocm):
    captured = {}

    def fake_create(**kwargs):
        captured.update(kwargs)
        return _response([])

    with patch.object(ocm.client.responses, "create", side_effect=fake_create):
        await ocm.run_llm_with_history([], "gpt-5.6-terra", tools=None)

    assert "tools" not in captured
    assert "tool_choice" not in captured


@pytest.mark.asyncio
async def test_resolve_with_history_two_rounds(ocm):
    """function_call 1 回のあと最終レスポンスを返す。"""
    reasoning_item = SimpleNamespace(type="reasoning")
    first = _response([reasoning_item, _call("t1", "fn")])
    final = SimpleNamespace(output=[SimpleNamespace(type="message")], output_text="answer")

    async def fake_run(hist, model, tools=None, reasoning_effort=""):
        if any(isinstance(h, dict) and h.get("type") == "function_call_output" for h in hist):
            return final
        return first

    mcp = AsyncMock()
    mcp.call_tool = AsyncMock(return_value=SimpleNamespace(structured_content={"ok": True}))
    history = []

    with patch.object(ocm, "run_llm_with_history", side_effect=fake_run):
        out = await ocm.resolve_with_history(history, "m", _routing(mcp, "fn"), [])

    assert ocm.response_output_text(out) == "answer"
    # reasoning アイテムを落とすとツール往復で推論の文脈が失われる
    assert reasoning_item in history


@pytest.mark.asyncio
async def test_execute_tool_calls_fallback_str_when_not_json_serializable(ocm):
    """structured/data/content がなく、json.dumps できない結果は str(result) に落ちる。"""

    class Weird:
        pass

    mcp = AsyncMock()
    mcp.call_tool = AsyncMock(return_value=Weird())
    calls = [_call("w1")]
    hist = []
    await ocm.execute_tool_calls_and_append(hist, _routing(mcp), calls)
    assert "Weird" in hist[-1]["output"] or "(" in hist[-1]["output"]


@pytest.mark.asyncio
async def test_execute_tool_calls_serialize_inner_failure(ocm):
    """structured_content が truthy だが JSON 化できない場合は内側のエラーメッセージ。"""

    class R:
        structured_content = {"x": object()}

    mcp = AsyncMock()
    mcp.call_tool = AsyncMock(return_value=R())
    calls = [_call("s1")]
    hist = []
    await ocm.execute_tool_calls_and_append(hist, _routing(mcp), calls)
    assert "シリアライズに失敗" in hist[-1]["output"]


@pytest.mark.asyncio
async def test_close_mcp_client_async_close(ocm):
    c = MagicMock()

    async def ac():
        return None

    c.close.return_value = ac()
    await ocm.close_mcp_client(c)


@pytest.mark.asyncio
async def test_close_mcp_client_aexit_only(ocm):
    class OnlyAexit:
        async def __aexit__(self, *a):
            return None

    await ocm.close_mcp_client(OnlyAexit())


@pytest.mark.asyncio
async def test_load_mcp_servers_url_branch(ocm, tmp_path, monkeypatch):
    p = tmp_path / "m.json"
    p.write_text(
        json.dumps({"mcpServers": {"remote": {"url": "http://localhost:8765/mcp"}}}),
        encoding="utf-8",
    )

    class FakeClient:
        async def list_tools(self):
            return []

    async def fake_create(transport, server_url="", **kw):
        assert transport == "tcp"
        return FakeClient(), "fastmcp-tcp"

    monkeypatch.setattr(ocm, "create_mcp_client", fake_create)
    r = await ocm.load_mcp_servers_from_file(str(p))
    assert "remote" in r
    assert r["remote"]["kind"] == "fastmcp-tcp"


def test_parse_args_overrides(ocm):
    with patch.object(
        sys,
        "argv",
        [
            "x",
            "--model",
            "gpt-4o-mini",
            "--no-mcp",
            "--transport",
            "stdio",
            "--servers-file",
            "custom.json",
        ],
    ):
        args = ocm.parse_args()
    assert args.model == "gpt-4o-mini"
    assert args.no_mcp is True
    assert args.transport == "stdio"
    assert args.servers_file == "custom.json"
