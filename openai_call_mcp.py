import argparse
import asyncio
import copy
import json
import logging
import os
import re
import shlex
from datetime import datetime
from pathlib import Path

from openai import OpenAI

# 対話出力は print、内部の診断情報は logger に分ける。
# 終了処理などの「失敗しても続行する」経路は debug で追跡できるようにしておく。
logger = logging.getLogger(__name__)

if not os.environ.get("OPENAI_API_KEY"):
    raise RuntimeError("環境変数 OPENAI_API_KEY が設定されていません。OpenAIのAPIキーを設定してください。")

client = OpenAI()

def build_child_environment(env: dict | None) -> dict | None:
    """MCP サーバ（子プロセス）へ渡す環境変数を組み立てる。

    MCP SDK は子プロセスへ**安全リストの環境変数しか渡さない**
    （``mcp.client.stdio.get_default_environment()`` は PATH や SystemRoot 等のみで、
    ``OPENAI_API_KEY`` は含まれない）。親プロセスの ``os.environ`` を書き換えても
    この絞り込みは回避できないため、渡したい変数は transport の ``env`` に
    明示的に載せる必要がある。

    ここでは安全リストに ``mcp_servers.json`` の ``env`` を上書きマージする。
    PATH 等を失わせずに API キーだけを追加で渡すため。

    Args:
        env: サーバ定義の ``env``（``$NAME`` は呼び出し側で展開済み）。

    Returns:
        dict | None: 子プロセスへ渡す環境変数。``env`` が空なら None
            （SDK の既定動作に任せる）。
    """
    if not env:
        return None
    try:
        from mcp.client.stdio import get_default_environment  # type: ignore

        base = dict(get_default_environment())
    except Exception:
        logger.debug("MCP の既定環境変数を取得できませんでした", exc_info=True)
        base = {}
    base.update({k: str(v) for k, v in env.items()})
    return base


async def create_mcp_client(transport: str, server_url: str = "", stdio_cmd: str = "", stdio_cwd: str = "", env: dict | None = None):
    """MCPサーバーへ接続するクライアントを生成する。

    Args:
        transport: "tcp" | "stdio"
        server_url: リモート接続時のURL (例: http://localhost:8765)
        stdio_cmd: stdio接続時に起動するコマンド（例: "python server.py"）
        stdio_cwd: stdio接続時のカレントディレクトリ
        env: stdioで起動するサブプロセスに渡す環境変数のマッピング

    Returns:
        Tuple[client, kind]: クライアントオブジェクトと種別文字列。
    """
    if transport == "tcp":
        # fastmcp の Client を使う
        try:
            from fastmcp import Client as FastMcpClient  # type: ignore
            client = FastMcpClient(server_url)
            # Client はコンテキストマネージャとして使う必要があるため enter して接続を確立する
            try:
                await client.__aenter__()
            except Exception:
                # 確実にクリーンアップ。元の接続失敗を握りつぶさないよう、
                # クリーンアップ側の失敗は記録するだけにして raise を通す。
                try:
                    await client.__aexit__(None, None, None)
                except Exception:
                    logger.debug("接続失敗後のクリーンアップに失敗しました", exc_info=True)
                raise
            return client, "fastmcp-tcp"
        except ImportError:
            # 古い mcp パッケージのセッションAPIにフォールバック
            from mcp.client.session import Session  # type: ignore
            session = Session(server_url)
            await session.start()
            return session, "mcp-tcp"
        except Exception as e:
            raise RuntimeError(f"fastmcp クライアントの初期化に失敗しました: {e}") from e

    if transport == "stdio":
        # stdio: subprocess ベースで起動する場合
        try:
            from fastmcp import Client as FastMcpClient  # type: ignore
        except ImportError:
            raise RuntimeError(
                "stdio接続が選択されましたが、fastmcp が利用できません。`python -c \"from fastmcp import Client; print('ok')\"` で確認してください。"
            )

        if not stdio_cmd:
            raise RuntimeError("--stdio-cmd を指定してください（例: --stdio-cmd \"python server.py\"")

        parts = shlex.split(stdio_cmd)
        try:
            from fastmcp.client.transports import (  # type: ignore
                PythonStdioTransport,
                StdioTransport,
            )

            child_env = build_child_environment(env)

            # python スクリプトを直接実行する形式なら PythonStdioTransport を使う
            if (
                parts
                and (parts[0].endswith("python") or parts[0].endswith("python.exe"))
                and len(parts) >= 2
                and parts[1].endswith(".py")
            ):
                transport = PythonStdioTransport(
                    script_path=parts[1],
                    args=parts[2:] or None,
                    env=child_env,
                    cwd=stdio_cwd or None,
                )
            else:
                transport = StdioTransport(
                    command=parts[0],
                    args=parts[1:],
                    env=child_env,
                    cwd=stdio_cwd or None,
                )
            client = FastMcpClient(transport)

            # Client はコンテキストマネージャとして使う必要があるため enter して接続を確立する
            try:
                await client.__aenter__()
            except Exception:
                try:
                    await client.__aexit__(None, None, None)
                except Exception:
                    logger.debug("stdio 接続失敗後のクリーンアップに失敗しました", exc_info=True)
                raise

            return client, "fastmcp-stdio"
        except Exception as e:
            raise RuntimeError(
                f"stdioベースでの接続/起動に失敗しました: {e}. 対処: fastmcp のバージョンやコマンド指定を確認してください。"
            ) from e


def build_openai_tools(tools):
    """MCP のツール定義を Responses API の tools 形式へ変換する。

    Responses API の function tool は ``{"type","name","description","parameters"}``
    のフラットな形。Chat Completions のように ``function`` 配下へ入れ子にしない。

    引数スキーマは MCP の ``Tool.inputSchema``（キャメルケース）から取る。
    ``input_schema`` だけを見ていると常に空スキーマになり、LLM が引数名を
    推測するしかなくなる（実際 ``hybrid_search`` が ``{}`` で呼ばれて
    「Missing required argument」で失敗していた）。

    Args:
        tools: MCP の ``list_tools()`` が返すツール定義。

    Returns:
        list: Responses API へ渡せるツール定義のリスト。
    """
    openai_tools = []
    for t in tools:
        name = getattr(t, "name", None)
        if not name:
            continue
        description = getattr(t, "description", "") or ""
        # MCP 仕様は inputSchema。念のため snake_case もフォールバックで見る。
        input_schema = getattr(t, "inputSchema", None)
        if not isinstance(input_schema, dict):
            input_schema = getattr(t, "input_schema", None)
        if isinstance(input_schema, dict):
            parameters = input_schema
        else:
            # 予期しない型や未定義の場合は空の schema を使用
            logger.warning("ツール '%s' の引数スキーマを取得できませんでした", name)
            parameters = {}
        openai_tools.append(
            {
                "type": "function",
                "name": name,
                "description": description,
                "parameters": parameters,
            }
        )
    return openai_tools

def prune_tool_parameters(tool: dict, hidden: list) -> dict:
    """ツール定義から指定パラメータを取り除いた新しい定義を返す。

    隠したパラメータはサーバ側の既定値が使われる。重いオプション
    （リランク、クエリ拡張、MMR など）を LLM から見えなくすることで、
    「使えるものは全部使う」挙動によるレイテンシとコストの膨張を抑える。

    Args:
        tool: Responses API 形式のツール定義。
        hidden: 隠すパラメータ名のリスト。

    Returns:
        dict: パラメータを取り除いたツール定義（元は変更しない）。
    """
    if not hidden:
        return tool
    entry = copy.deepcopy(tool)
    params = entry.get("parameters")
    if not isinstance(params, dict):
        return entry
    properties = params.get("properties")
    if isinstance(properties, dict):
        for key in hidden:
            properties.pop(key, None)
    required = params.get("required")
    if isinstance(required, list):
        # 隠したパラメータが required に残ると、LLM が渡せない値を要求されてしまう
        params["required"] = [r for r in required if r not in set(hidden)]
    return entry


def apply_hidden_tool_params(tools: list, hide_map: dict | None, server_name: str) -> list:
    """``hide_tool_params`` 設定を適用する。

    Args:
        tools: Responses API 形式のツール定義一覧。
        hide_map: ``{ツール名: [隠すパラメータ, ...]}``。None なら何もしない。
        server_name: 警告表示用のサーバー名。

    Returns:
        list: 適用後のツール定義一覧。
    """
    if not hide_map:
        return tools
    by_name = {t.get("name"): t for t in tools}
    for tool_name in hide_map:
        if tool_name not in by_name:
            print(
                f"警告: サーバー '{server_name}' に存在しないツールが "
                f"hide_tool_params に指定されています: {tool_name}"
            )
    result = []
    for tool in tools:
        hidden = hide_map.get(tool.get("name"))
        if hidden:
            available = set((tool.get("parameters") or {}).get("properties") or {})
            unknown = [h for h in hidden if h not in available]
            if unknown:
                print(
                    f"警告: '{server_name}/{tool.get('name')}' に存在しないパラメータが "
                    f"hide_tool_params に指定されています: {sorted(unknown)}"
                )
        result.append(prune_tool_parameters(tool, hidden))
    return result


# ツール名に付けるサーバー接頭辞の区切り。OpenAI の関数名に使える文字だけで構成する。
TOOL_NAME_SEPARATOR = "__"

# OpenAI の function name の最大長。
MAX_TOOL_NAME_LENGTH = 64


def make_server_slug(name: str) -> str:
    """サーバー名をツール名に埋め込める識別子へ変換する。

    OpenAI の function name は ``[A-Za-z0-9_-]`` のみ許容されるため、
    それ以外の文字はアンダースコアへ畳み込む。

    Args:
        name: ``mcp_servers.json`` のサーバー名（日本語や空白を含みうる）。

    Returns:
        str: 小文字の識別子。空になる場合は ``"server"``。
    """
    slug = re.sub(r"[^0-9a-zA-Z]+", "_", name).strip("_").lower()
    return slug or "server"


def build_tool_registry(servers_map: dict, only: str | None = None):
    """全サーバーのツールを 1 つの一覧へ統合し、名前→サーバーの経路表を返す。

    LLM に対して「どのバックエンドを使うか」を選ばせるには、選択肢が同時に
    見えている必要がある。1 サーバー分のツールしか渡さないと、LLM は
    オーケストレータにはなれず、人間が ``/use`` で切り替えた 1 系統しか
    使えない。ここで全サーバーのツールを束ねることで初めて LLM が選べる。

    ツール名はサーバーごとに接頭辞を付けて衝突を防ぐ
    （例: ``hybrid_rag_mcp_server__hybrid_search``）。実行時には経路表から
    元のツール名と接続先クライアントを引く。

    Args:
        servers_map: ``load_mcp_servers_from_file`` の戻り値。
        only: サーバー名を指定すると、そのサーバーのツールだけに絞る
            （``/use`` 用）。``None`` なら全サーバー。

    Returns:
        tuple[list, dict]: OpenAI 形式のツール定義一覧と、
            接頭辞付きツール名 -> ``{"server", "tool", "mcp"}`` の経路表。
    """
    openai_tools: list = []
    routing: dict = {}
    used_slugs: dict = {}

    for name, spec in servers_map.items():
        if only is not None and name != only:
            continue

        slug = make_server_slug(name)
        # 別名のサーバーが同じ slug になった場合は連番で退避する
        if slug in used_slugs and used_slugs[slug] != name:
            suffix = 2
            while f"{slug}_{suffix}" in used_slugs:
                suffix += 1
            slug = f"{slug}_{suffix}"
        used_slugs[slug] = name

        for tool in spec.get("tools") or []:
            original = tool.get("name")
            if not original:
                continue
            prefixed = f"{slug}{TOOL_NAME_SEPARATOR}{original}"
            if len(prefixed) > MAX_TOOL_NAME_LENGTH:
                # 長すぎる場合は接頭辞側を削る（元のツール名は判別に必要なので残す）
                keep = MAX_TOOL_NAME_LENGTH - len(TOOL_NAME_SEPARATOR) - len(original)
                if keep <= 0:
                    logger.warning(
                        "ツール名が長すぎるため公開できません: %s / %s", name, original
                    )
                    continue
                prefixed = f"{slug[:keep]}{TOOL_NAME_SEPARATOR}{original}"
            if prefixed in routing:
                logger.warning("ツール名が衝突したためスキップします: %s", prefixed)
                continue

            entry = copy.deepcopy(tool)
            entry["name"] = prefixed
            # どのバックエンドのツールかを LLM 側でも判別できるようにする
            description = entry.get("description") or ""
            entry["description"] = f"[{name}] {description}".strip()
            openai_tools.append(entry)
            routing[prefixed] = {"server": name, "tool": original, "mcp": spec.get("mcp")}

    return openai_tools, routing


def extract_function_calls(response):
    """Responses API のレスポンスから function_call アイテムだけを取り出す。

    Args:
        response: ``client.responses.create`` の戻り値。

    Returns:
        list: ``type == "function_call"`` の出力アイテム。
    """
    return [item for item in (getattr(response, "output", None) or [])
            if getattr(item, "type", None) == "function_call"]


def response_output_text(response) -> str:
    """レスポンスから最終的なテキストを取り出す。"""
    text = getattr(response, "output_text", None)
    if text:
        return text
    # output_text が無い SDK バージョン向けのフォールバック
    parts = []
    for item in getattr(response, "output", None) or []:
        for content in getattr(item, "content", None) or []:
            piece = getattr(content, "text", None)
            if piece:
                parts.append(piece)
    return "".join(parts)


def serialize_tool_result(result) -> str:
    """fastmcp のツール結果を、LLM へ返せる文字列へ変換する。"""
    try:
        # structured_content があれば優先して使う
        if hasattr(result, "structured_content") and result.structured_content:
            return json.dumps(result.structured_content, ensure_ascii=False)
        # raw data フィールドがあれば使う
        if hasattr(result, "data") and result.data is not None:
            return json.dumps(result.data, ensure_ascii=False)
        # content フィールドが文字列またはテキストコンテンツの配列の場合
        if hasattr(result, "content") and result.content is not None:
            rc = result.content
            if isinstance(rc, str):
                return rc
            # たとえば [TextContent(...)] 形式などを想定してテキストを抽出
            try:
                texts = []
                for item in rc:
                    if hasattr(item, "text"):
                        texts.append(item.text)
                    elif isinstance(item, str):
                        texts.append(item)
                return "\n".join(texts)
            except Exception:  # noqa: BLE001
                # rc は任意の MCP バックエンドが返す未知の型（TextContent 風オブジェクトの
                # 配列を想定）。item.text 等のアクセスが何を投げるか特定できないため、
                # 表示用フォールバック（str(rc)）に落とすためだけに広く受ける。
                return str(rc)
        # フォールバック: dict にできれば JSON に、それ以外は str()
        try:
            return json.dumps(result, ensure_ascii=False)
        except TypeError:
            return str(result)
    except Exception as e:  # noqa: BLE001
        # result は任意の MCP バックエンドが返すツール結果オブジェクトで、
        # 属性アクセスや json.dumps が何を投げるか事前に列挙できない。
        # ここで失敗してもエラー文字列を LLM に返すだけの表示用フォールバックなので、
        # 種類を問わず捕捉して処理を継続する。
        return f"(ツール結果のシリアライズに失敗しました: {e})"


async def execute_tool_calls_and_append(history: list, routing: dict, function_calls):
    """function_call を実行し、結果を function_call_output として履歴に追加する。

    Args:
        history: Responses API へ渡す input アイテムのリスト（破壊的に追記）。
        routing: ``build_tool_registry`` が返す経路表。接頭辞付きツール名から
            接続先サーバーと元のツール名を引く。
        function_calls: ``extract_function_calls`` が返した function_call アイテム。

    Returns:
        list: ログ用の要約（id / name / server / content）。
    """
    # fastmcp の ToolError をキャッチしてユーザーにわかりやすく伝える
    try:
        import fastmcp.exceptions as _fm_exc  # type: ignore
    except ImportError:
        _fm_exc = None

    results = []
    for call in function_calls:
        name = call.name
        call_id = call.call_id
        try:
            args_dict = json.loads(call.arguments or "{}")
        except json.JSONDecodeError as e:
            args_dict = None
            content = f"ツール引数の JSON を解釈できませんでした: {e}"

        route = routing.get(name)
        if route is None:
            content = (
                f"ツール '{name}' は登録されていません。"
                "提示されているツール一覧から選び直してください。"
            )
            server = "(unknown)"
        elif args_dict is None:
            server = route["server"]
        else:
            server = route["server"]
            try:
                result = await route["mcp"].call_tool(route["tool"], args_dict)
                content = serialize_tool_result(result)
            except Exception as e:  # noqa: BLE001
                # ツール呼び出し先は任意の MCP バックエンド（別プロセス/別サーバー）で、
                # 通信エラーからツール固有の例外まで何を投げるか分からない。
                # 1 回のツール呼び出し失敗でエージェントループ全体を落とさないよう、
                # 種類を問わず捕捉してエラーメッセージを LLM に返す。
                # fastmcp の ToolError はユーザーに見せて良いメッセージとして扱う
                if _fm_exc and isinstance(e, _fm_exc.ToolError):
                    content = f"ツール実行中にエラーが発生しました: {e}"
                else:
                    content = f"ツール実行時に例外が発生しました: {e}"

        history.append(
            {"type": "function_call_output", "call_id": call_id, "output": content}
        )
        results.append({"id": call_id, "name": name, "server": server, "content": content})
    return results


async def run_llm_with_history(history: list, model: str, tools=None, reasoning_effort: str = ""):
    """入力アイテム列を用いて Responses API を呼び、レスポンスを返す。

    Chat Completions ではなく Responses API を使う理由は 2 つある。

    1. **function tools と reasoning を併用できる。** ``/v1/chat/completions`` は
       この組み合わせに対応せず、GPT-5 系では ``reasoning_effort='none'`` を
       強制されるため、ツール選択に推論を使えなかった。
    2. プロンプトキャッシュの利用率が高い。オーケストレータはツール結果込みの
       全履歴を毎ターン再送するため、入力トークンが支配的になる。

    Args:
        history: Responses API の input アイテム列。
        model: OpenAI モデル名。
        tools: Responses API 形式のツール定義一覧（無ければ None）。
        reasoning_effort: 推論量（none/low/medium/high など）。空文字なら送らない。

    Returns:
        Responses API のレスポンス。
    """
    extra = {}
    if reasoning_effort:
        extra["reasoning"] = {"effort": reasoning_effort}
    if tools:
        extra["tools"] = tools
        extra["tool_choice"] = "auto"
    return client.responses.create(model=model, input=history, **extra)


async def resolve_with_history(
    history: list, model: str, routing: dict, tools, reasoning_effort: str = ""
):
    """function_call が解消するまで、MCP 実行とフォローアップを反復する。

    レスポンスの output（reasoning アイテムを含む）はそのまま履歴へ積み直す。
    reasoning アイテムを落とすと、ツール往復のあいだで推論の文脈が失われる。

    Args:
        history: Responses API の input アイテム列（破壊的に追記）。
        model: OpenAI モデル名。
        routing: ``build_tool_registry`` が返す経路表。
        tools: LLM へ提示するツール定義一覧。
        reasoning_effort: 推論量。

    Returns:
        最終レスポンス。
    """
    response = await run_llm_with_history(history, model, tools, reasoning_effort)
    function_calls = extract_function_calls(response)

    while function_calls:
        history.extend(response.output)

        log_path = globals().get("_LOG_PATH")
        if log_path:
            lines = ["\n### Assistant tool_calls", ""]
            for call in function_calls:
                # どのバックエンドを選んだかを機械可読な形で残す（選択率の実測用）
                route = routing.get(call.name) or {}
                server = route.get("server", "(unknown)")
                tool = route.get("tool", call.name)
                lines.append(
                    f"- server=`{server}` tool=`{tool}` name=`{call.name}` "
                    f"(id={call.call_id}) args:``{call.arguments}``"
                )
            append_log(log_path, "\n".join(lines) + "\n")

        results = await execute_tool_calls_and_append(history, routing, function_calls)
        if log_path and results:
            lines = ["\n### Tool results", ""]
            for r in results:
                lines.append(
                    f"#### {r['name']} (server={r['server']}, id={r['id']})"
                    f"\n\n````\n{r['content']}\n````"
                )
            append_log(log_path, "\n".join(lines) + "\n")

        response = await run_llm_with_history(history, model, tools, reasoning_effort)
        function_calls = extract_function_calls(response)

    # 最終レスポンスの output も履歴へ残す（次ターンの文脈になる）
    history.extend(response.output)
    log_path = globals().get("_LOG_PATH")
    if log_path:
        append_log(log_path, f"\n## Assistant\n\n{response_output_text(response)}\n")
    return response


def parse_args():
    """CLI引数をパースする。"""
    parser = argparse.ArgumentParser(description="OpenAI + MCP CLI")
    parser.add_argument("--model", default="gpt-5.6-terra", help="OpenAIモデル名")
    parser.add_argument(
        "--reasoning-effort",
        default="low",
        help=(
            "reasoning モデルの推論量 (none/low/medium/high など)。空文字で送信しない。"
            "Responses API を使うため、ツール併用時も 'none' 以外を指定できる"
        ),
    )
    parser.add_argument("--system-prompt-file", default="openai.md", help="システムプロンプトを含むMarkdownファイルのパス (デフォルト: openai.md)")
    parser.add_argument("--no-mcp", action="store_true", help="MCPを使わずに純粋なLLM応答のみ")
    parser.add_argument("--transport", choices=["tcp", "stdio"], default="tcp", help="MCPトランスポート種別 (単一サーバー接続のフォールバック用)")
    parser.add_argument("--stdio-cmd", default="", help="stdioサーバーを起動するコマンド (単一サーバー接続のフォールバック用)")
    parser.add_argument("--stdio-cwd", default="", help="stdioサーバーの作業ディレクトリ (単一サーバー接続のフォールバック用)")
    parser.add_argument("--servers-file", default="mcp_servers.json", help="MCPサーバー定義JSONファイルパス")
    parser.add_argument("--log-dir", default="logs", help="会話ログを保存するディレクトリ（Markdown, 日時付きファイル）")
    return parser.parse_args()


def _resolve_relative_path(arg: str, base_dir: str) -> str:
    """サーバ定義中の引数が相対パスなら ``base_dir`` 基準の絶対パスへ変換する。

    パスに見えない引数（``--flag`` などのオプション）や、既に絶対パスの引数は
    そのまま返す。これによりサーバ定義 JSON に環境依存の絶対パスを書かずに済む。

    Args:
        arg: サーバ定義の ``args`` に含まれる 1 要素。
        base_dir: 相対パスの基準ディレクトリ（通常は定義 JSON のある場所）。

    Returns:
        str: 解決後の引数文字列。
    """
    if not arg or arg.startswith("-") or os.path.isabs(arg):
        return arg
    candidate = os.path.normpath(os.path.join(base_dir, arg))
    return candidate if os.path.exists(candidate) else arg


async def load_mcp_servers_from_file(path: str, stdio_cwd_fallback: str = "") -> dict:
    """JSONで定義された複数MCPサーバーを読み込み、接続して辞書を返す。

    返却形式: { name: {"mcp": mcp_client, "tools": openai_tools, "kind": kind} }
    """
    if not os.path.exists(path):
        return {}
    with open(path, "r", encoding="utf-8") as f:
        cfg = json.load(f)
    # 定義ファイル内の相対パスは、定義ファイルのある場所を基準に解決する。
    # （プロセスの起動ディレクトリに依存させないため）
    base_dir = os.path.dirname(os.path.abspath(path)) or os.getcwd()
    servers = {}
    for name, spec in cfg.get("mcpServers", {}).items():
        try:
            if "command" in spec:
                args = [_resolve_relative_path(a, base_dir) for a in spec.get("args", [])]
                cmd = shlex.join([spec.get("command")] + args)
                cwd = spec.get("cwd", "")
                if cwd:
                    cwd = os.path.normpath(os.path.join(base_dir, cwd))
                # env 指定があればホストの env 参照表記 ($NAME) を展開
                raw_env = spec.get("env") or {}
                final_env = {}
                if isinstance(raw_env, dict):
                    for k, v in raw_env.items():
                        if isinstance(v, str) and v.startswith("$"):
                            final_env[k] = os.environ.get(v[1:], "")
                        else:
                            final_env[k] = v
                else:
                    final_env = raw_env

                # stdio 起動: create_mcp_client に委譲
                if final_env:
                    print(f"サーバー '{name}' を起動/接続します。注: 渡す env keys: {list(final_env.keys())}")
                else:
                    print(f"サーバー '{name}' を起動/接続します。env は渡されません。")
                mcp_client, kind = await create_mcp_client("stdio", stdio_cmd=cmd, stdio_cwd=cwd or stdio_cwd_fallback, env=final_env)
            elif "url" in spec:
                # リモート接続 (HTTP/SSE 等)
                url = spec.get("url")
                mcp_client, kind = await create_mcp_client("tcp", server_url=url)
            else:
                print(f"サーバー定義 '{name}' は 'command' か 'url' を含む必要があります。スキップします。")
                continue

            # tools を取得（fastmcp.Client または互換APIを想定）
            try:
                tools = await mcp_client.list_tools()
            except Exception:  # noqa: BLE001
                # 一部の古いクライアントでは同期メソッドの場合もあるため、フォールバック。
                # クライアント実装（fastmcp / 旧 mcp SDK 等）によって async 呼び出し失敗時に
                # 投げる例外の型がまちまちなため、種類を問わず同期フォールバックへ回す。
                tools = await asyncio.to_thread(getattr(mcp_client, "list_tools", lambda: []))
            # expose_tools が指定されていれば、そのツールだけを LLM に見せる。
            # 全サーバーのツールを同時提示すると管理系ツールがノイズになるため、
            # 検索系だけに絞れるようにしている。
            built = build_openai_tools(tools)
            expose = spec.get("expose_tools")
            if expose:
                allowed = set(expose)
                available = {t["name"] for t in built}
                missing = allowed - available
                if missing:
                    print(
                        f"警告: サーバー '{name}' に存在しないツールが expose_tools に指定されています: "
                        f"{sorted(missing)}"
                    )
                built = [t for t in built if t["name"] in allowed]
            built = apply_hidden_tool_params(built, spec.get("hide_tool_params"), name)
            servers[name] = {"mcp": mcp_client, "tools": built, "kind": kind, "spec": spec}
        except Exception as e:  # noqa: BLE001
            # 複数サーバーを順に読み込む中の 1 件の失敗（設定不備、起動コマンドの失敗、
            # 接続タイムアウト等、原因は多様）で他サーバーの読み込みまで止めないよう、
            # 種類を問わず捕捉してスキップする。
            print(f"サーバー '{name}' の起動/接続に失敗しました: {e}")
    return servers


def ensure_log_file(log_dir: str) -> str:
    """ログ用ディレクトリを作成し、日時入りMarkdownファイルを生成してパスを返す。"""
    path = Path(log_dir)
    path.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    log_path = str(path / f"{ts}.md")
    with open(log_path, "w", encoding="utf-8") as f:
        f.write(f"# Conversation Log {ts}\n")
    return log_path

def append_log(log_path: str, text: str) -> None:
    """Markdownログにテキストを追記する。"""
    with open(log_path, "a", encoding="utf-8") as f:
        f.write(text)

async def _try_shutdown_call(target, attr_name: str, method_name: str, timeout: float) -> None:
    """トランスポート/プロセスの終了メソッドを、あれば呼び出す。

    終了処理は「試せるものを順に試す」性質のため個々の失敗では止めないが、
    握りつぶすと接続やプロセスのリークに気づけなくなるため debug ログを残す。

    Args:
        target: ``transport`` や ``process`` などのオブジェクト。
        attr_name: ログ用の属性名。
        method_name: 呼び出すメソッド名（``terminate`` / ``close`` / ``kill``）。
        timeout: コルーチンを待つ最大秒数。
    """
    method = getattr(target, method_name, None)
    if method is None:
        return
    try:
        result = method()
        if asyncio.iscoroutine(result):
            await asyncio.wait_for(result, timeout=timeout)
    except Exception:
        logger.debug("%s.%s() の呼び出しに失敗しました", attr_name, method_name, exc_info=True)


async def close_mcp_client(client_obj, timeout: float = 2.0):
    """Try to gracefully close a MCP client, with fallbacks.

    This attempts to call async close()/__aexit__, then falls back to
    terminating underlying transports/processes to avoid destructor warnings
    on Windows when the event loop is closed.
    """
    if client_obj is None:
        return
    try:
        # Prefer explicit close() if present
        if hasattr(client_obj, "close") and callable(getattr(client_obj, "close")):
            try:
                close_result = client_obj.close()
                if asyncio.iscoroutine(close_result):
                    await asyncio.wait_for(close_result, timeout=timeout)
            except asyncio.TimeoutError:
                print("クライアントのクローズがタイムアウトしました。続行します。")
            except RuntimeError as e:
                # Event loop が既に閉じている等の状況は無視
                print(f"クライアントクローズ中にランタイムエラー: {e}")
        elif hasattr(client_obj, "__aexit__"):
            try:
                result = client_obj.__aexit__(None, None, None)
                if asyncio.iscoroutine(result):
                    await asyncio.wait_for(result, timeout=timeout)
            except asyncio.TimeoutError:
                print("クライアントの __aexit__ がタイムアウトしました。続行します。")
            except RuntimeError as e:
                print(f"クライアント __aexit__ 中にランタイムエラー: {e}")

        # Try to aggressively close underlying transports/process objects
        for attr in ("transport", "_transport", "process", "proc"):
            tr = getattr(client_obj, attr, None)
            if tr is None:
                continue
            for method in ("terminate", "close", "kill"):
                await _try_shutdown_call(tr, attr, method, timeout)
    except Exception as e:  # noqa: BLE001
        # 終了処理は「試せるものを順に試す」ベストエフォートの後片付けであり、
        # ここで想定外の例外を止めてしまうとプロセス終了自体が失敗しかねない。
        # 種類を問わず捕捉して、続行できるようにする。
        print(f"クライアントの終了処理で例外が発生しました: {e}")

async def main():
    args = parse_args()

    # システムプロンプトを読み込む（存在すれば会話履歴の先頭に system ロールとして追加）
    system_prompt = None
    try:
        system_prompt_path = getattr(args, "system_prompt_file", "openai.md")
        if system_prompt_path and os.path.exists(system_prompt_path):
            with open(system_prompt_path, "r", encoding="utf-8") as f:
                system_prompt = f.read().strip() or None
    except (OSError, UnicodeDecodeError) as e:
        print(f"システムプロンプトの読み込みに失敗しました: {e}")

    if system_prompt:
        history = globals().setdefault("_CONV_HISTORY", [])
        if not history:
            history.append({"role": "system", "content": system_prompt})
        # ログにも出力
        # ensure_log_file はまだ呼ばれていないが _LOG_PATH は設定後に更新するため先に追記
        globals()['_SYSTEM_PROMPT_PATH'] = system_prompt_path

    # === MCPサーバーに接続（必要なら）===
    mcp = None
    kind = None
    openai_tools = None
    tool_routing: dict = {}
    servers_map = {}
    # None なら全サーバーのツールを提示する（= LLM がバックエンドを選べる）。
    # サーバー名が入っている場合は /use による絞り込み中。
    server_filter = None
    # ログファイルの初期化
    log_path = ensure_log_file(args.log_dir)
    globals()['_LOG_PATH'] = log_path
    append_log(log_path, f"\n- Model: `{args.model}`\n- Transport(default): `{args.transport}`\n- Servers file: `{args.servers_file}`\n\n")

    # システムプロンプト情報をログに追記（ファイルがあれば）
    if system_prompt:
        append_log(log_path, f"- System prompt file: `{system_prompt_path}`\n\n{system_prompt}\n\n")

    if not args.no_mcp:
        # まずJSONファイルから複数サーバーを読み込む
        servers_map = await load_mcp_servers_from_file(args.servers_file, args.stdio_cwd)
        if servers_map:
            # 全サーバーのツールをまとめて提示する。どのバックエンドを使うかは
            # 人間の /use ではなく LLM が選ぶ。
            openai_tools, tool_routing = build_tool_registry(servers_map)
            print("読み込んだMCPサーバー:")
            for n, s in servers_map.items():
                print(f"- {n} ({s.get('kind')}) tools={len(s.get('tools') or [])}")
            print(f"LLM に提示するツール数: {len(openai_tools)}（全サーバー同時提示）")
            append_log(
                log_path,
                "\n- Exposed servers: "
                + ", ".join(f"{n}({len(s.get('tools') or [])})" for n, s in servers_map.items())
                + "\n",
            )
        else:
            # JSONが見つからない/空の場合、既存の単一接続フローにフォールバック
            try:
                server_url = "ws://localhost:8765"
                mcp, kind = await create_mcp_client(
                    transport=args.transport,
                    server_url=server_url,
                    stdio_cmd=args.stdio_cmd,
                    stdio_cwd=args.stdio_cwd,
                )
                tools = await mcp.list_tools()
                servers_map = {
                    "Default MCP": {"mcp": mcp, "tools": build_openai_tools(tools), "kind": kind}
                }
                openai_tools, tool_routing = build_tool_registry(servers_map)
                print("単一MCPサーバーに接続しました: Default MCP")
            except Exception as e:  # noqa: BLE001
                # 単一サーバー接続はオプション機能へのフォールバックであり、
                # transport 種別やバックエンド実装で失敗の型が変わりうる。
                # ここで失敗しても MCP なしで CLI 自体は起動を続けたいため広く受ける。
                print(f"MCP接続に失敗しました: {e}\nMCPを使わずに起動します。")
                servers_map = {}

    print("MCP-CLI ready. プロンプトを入力してください。終了: Ctrl+C / Ctrl+Z+Enter (Windows)")
    print(
        "コマンド: /servers (一覧), /use <name> (1サーバーに絞る), /use all (絞り込み解除), "
        "/help (このメッセージ), /paste (複数行貼付: 終了は単独の '.' 行)"
    )

    try:
        while True:
            print("")
            raw = input(">> ")
            if raw is None:
                continue

            # /paste で複数行入力モード
            if raw.strip() == "/paste":
                print("複数行入力モード。貼り付けて、終了するには単独の行に '.' を入力してEnterしてください。")
                lines = []
                while True:
                    try:
                        line = input()
                    except EOFError:
                        break
                    if line == ".":
                        break
                    lines.append(line)
                user_input = "\n".join(lines)
                if not user_input:
                    continue
            elif raw.startswith("/paste "):
                # /paste <inline content>
                user_input = raw[len("/paste "):].rstrip("\n")
                if not user_input.strip():
                    continue
            else:
                user_input = raw.strip()
                if not user_input:
                    continue

            # 内部コマンドの処理
            if user_input.startswith("/"):
                if user_input == "/servers":
                    if not servers_map:
                        print("登録されたMCPサーバーはありません。")
                    else:
                        print("登録されたMCPサーバー:")
                        for n, s in servers_map.items():
                            exposed = server_filter is None or server_filter == n
                            mark = "" if exposed else " (絞り込みにより非提示)"
                            print(f"- {n} ({s.get('kind')}) tools={len(s.get('tools') or [])}{mark}")
                        if server_filter is None:
                            print("提示範囲: 全サーバー（LLM がバックエンドを選択）")
                        else:
                            print(f"提示範囲: '{server_filter}' のみ（/use all で解除）")
                    continue
                if user_input.startswith("/use "):
                    target = user_input[len("/use "):].strip()
                    if target in ("all", "*"):
                        server_filter = None
                        openai_tools, tool_routing = build_tool_registry(servers_map)
                        print(f"絞り込みを解除しました。提示ツール数: {len(openai_tools)}")
                        append_log(globals()["_LOG_PATH"], "\n- Tool scope: all servers\n")
                    elif target in servers_map:
                        server_filter = target
                        openai_tools, tool_routing = build_tool_registry(servers_map, only=target)
                        print(
                            f"'{target}' のツールだけを提示します（{len(openai_tools)} 個）。"
                            "/use all で全サーバーに戻せます。"
                        )
                        append_log(globals()["_LOG_PATH"], f"\n- Tool scope: {target}\n")
                    else:
                        print(f"サーバー '{target}' は見つかりません。/servers で一覧を確認してください。")
                    continue
                if user_input.startswith("/env "):
                    var = user_input[len("/env "):].strip()
                    if not var:
                        print("使い方: /env <ENV_VAR_NAME>")
                        continue
                    # 絞り込み中はそのサーバー、そうでなければ最初のサーバーに問い合わせる
                    env_target = server_filter or (next(iter(servers_map), None))
                    env_client = servers_map.get(env_target, {}).get("mcp") if env_target else None
                    if not env_client:
                        print("現在接続中のMCPサーバーがありません。")
                        continue
                    try:
                        print(f"（問い合わせ先: {env_target}）")
                        res = await env_client.call_tool("is_env_set", {"var_name": var})
                        if isinstance(res, dict):
                            present = res.get("present")
                            masked = res.get("value_masked")
                            if present:
                                print(f"{var} は設定されています (masked: {masked})")
                            else:
                                print(f"{var} は設定されていません。")
                        else:
                            print(f"envチェック結果: {res}")
                    except Exception as e:  # noqa: BLE001
                        # /env は対話 REPL の 1 コマンドに過ぎない。MCP バックエンドへの
                        # 問い合わせ失敗の型は接続先次第で予測できないため広く受け、
                        # ループ全体を落とさずにエラーだけ表示して続行する。
                        print(f"envチェックに失敗しました: {e}")
                    continue
                if user_input.startswith("/restart "):
                    target = user_input[len("/restart "):].strip()
                    if not target:
                        print("使い方: /restart <server name>")
                        continue
                    if target not in servers_map:
                        print(f"サーバー '{target}' は見つかりません。/servers で一覧を確認してください。")
                        continue
                    print(f"サーバー '{target}' を再起動します (既存クライアントを閉じて、設定に基づき起動します)。")
                    spec = servers_map[target].get("spec") or {}
                    # クローズ
                    try:
                        await close_mcp_client(servers_map[target].get("mcp"), timeout=2.0)
                    except Exception:
                        # 閉じられなくても再起動は試す価値があるため続行する。
                        logger.warning(
                            "再起動前のクライアント終了に失敗しました: %s", target, exc_info=True
                        )
                    # 再作成
                    try:
                        if "command" in spec:
                            cmd = " ".join([spec.get("command")] + spec.get("args", []))
                            cwd = spec.get("cwd", "")
                            raw_env = spec.get("env") or {}
                            final_env = {}
                            if isinstance(raw_env, dict):
                                for k, v in raw_env.items():
                                    if isinstance(v, str) and v.startswith("$"):
                                        final_env[k] = os.environ.get(v[1:], "")
                                    else:
                                        final_env[k] = v
                            else:
                                final_env = raw_env
                            mcp_client, kind = await create_mcp_client("stdio", stdio_cmd=cmd, stdio_cwd=cwd or args.stdio_cwd, env=final_env)
                        elif "url" in spec:
                            url = spec.get("url")
                            mcp_client, kind = await create_mcp_client("tcp", server_url=url)
                        else:
                            print("指定されたサーバー定義に command か url がありません。再起動をスキップします。")
                            continue
                        # tools を再取得
                        try:
                            tools = await mcp_client.list_tools()
                        except Exception:  # noqa: BLE001
                            # 一部の古いクライアントでは同期メソッドの場合もあるため、フォールバック。
                            # クライアント実装によって async 呼び出し失敗時の例外の型が
                            # まちまちなため、種類を問わず同期フォールバックへ回す。
                            tools = await asyncio.to_thread(getattr(mcp_client, "list_tools", lambda: []))
                        servers_map[target] = {"mcp": mcp_client, "tools": build_openai_tools(tools), "kind": kind, "spec": spec}
                        # 経路表が古いクライアントを指したままにならないよう作り直す
                        openai_tools, tool_routing = build_tool_registry(
                            servers_map, only=server_filter
                        )
                        print(f"サーバー '{target}' の再起動に成功しました。")
                    except Exception as e:  # noqa: BLE001
                        # /restart も対話 REPL の 1 コマンド。接続先/transport次第で
                        # 失敗の型は予測できないため広く受け、ループを継続する。
                        print(f"サーバー '{target}' の再起動に失敗しました: {e}")
                    continue

            # 履歴管理: ユーザー発言を追加
            history = globals().setdefault("_CONV_HISTORY", [])
            history.append({"role": "user", "content": user_input})
            append_log(globals()["_LOG_PATH"], f"\n## User\n\n{user_input}\n")

            # どのバックエンドのツールを呼ぶかは LLM が経路表の中から選ぶ
            if openai_tools and tool_routing:
                response = await resolve_with_history(
                    history, args.model, tool_routing, openai_tools, args.reasoning_effort
                )
            else:
                response = await run_llm_with_history(
                    history, args.model, reasoning_effort=args.reasoning_effort
                )
                history.extend(response.output)
                append_log(
                    globals()["_LOG_PATH"],
                    f"\n## Assistant\n\n{response_output_text(response)}\n",
                )

            # 最終回答を表示
            print(response_output_text(response) or "")

    except (KeyboardInterrupt, EOFError):
        print("\nBye")
    finally:
        # 全てのMCPクライアントを穏やかに閉じる（タイムアウト付きで複数方式を試す）
        # 終了処理の失敗で他のクライアントのクローズを止めないよう、
        # 1 件ずつ捕捉して記録し、最後まで試みる。
        try:
            targets = (
                [(name, s.get("mcp")) for name, s in servers_map.items()]
                if servers_map
                else [("(single)", mcp)]
            )
            for name, client_obj in targets:
                if client_obj is None:
                    continue
                try:
                    await close_mcp_client(client_obj, timeout=2.0)
                except Exception:
                    logger.warning(
                        "サーバー '%s' のクライアント終了に失敗しました", name, exc_info=True
                    )
            # 少し待ってバックグラウンドでのクリーンアップ処理を許容する
            await asyncio.sleep(0.05)
        except Exception:
            logger.warning("MCPクライアントの終了処理で例外が発生しました", exc_info=True)


if __name__ == "__main__":
    asyncio.run(main())