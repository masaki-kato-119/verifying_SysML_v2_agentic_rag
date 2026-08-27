"""会話ログからバックエンド選択率を集計する。

``openai_call_mcp.py`` は各 tool_call を

    - server=`Graph RAG MCP Server` tool=`smart_search` name=`...` (id=...) args:``{...}``

という形式でログに残す。このスクリプトはその行を集計し、
「LLM が実際にどのバックエンドを選んだか」を実測する。

旧形式（``- hybrid_search (id=...)``）のログも、ツール名から
バックエンドを逆引きして集計する（過去ログとの比較のため）。

使い方::

    python scripts/analyze_backend_usage.py
    python scripts/analyze_backend_usage.py --log-dir logs --since 20260801
"""

from __future__ import annotations

import argparse
import re
from collections import Counter
from pathlib import Path

# 新形式: server=`...` tool=`...`
NEW_FORMAT = re.compile(r"^- server=`(?P<server>[^`]*)` tool=`(?P<tool>[^`]*)`")

# 旧形式: - <tool_name> (id=...)
OLD_FORMAT = re.compile(r"^- (?P<tool>[A-Za-z_][A-Za-z0-9_]*) \(id=")

# 旧形式ログにはサーバー名が無いため、ツール名から推定する
TOOL_TO_SERVER = {
    "index_path": "Hybrid RAG MCP Server",
    "vector_search": "Hybrid RAG MCP Server",
    "meta_search": "Hybrid RAG MCP Server",
    "semantic_search": "Hybrid RAG MCP Server",
    "hybrid_search": "Hybrid RAG MCP Server",
    "delete_document": "Hybrid RAG MCP Server",
    "list_documents": "Hybrid RAG MCP Server",
    "update_document": "Hybrid RAG MCP Server",
    "smart_search": "Graph RAG MCP Server",
    "search_graph": "Graph RAG MCP Server",
    "explore_graph": "Graph RAG MCP Server",
    "find_path": "Graph RAG MCP Server",
    "find_entry_points": "Graph RAG MCP Server",
    "get_source_text": "Graph RAG MCP Server",
    "get_edge_source_text": "Graph RAG MCP Server",
    "parse_sysml_file": "SysML v2 Checker",
    "parse_sysml_text": "SysML v2 Checker",
    "lint_sysml_file": "SysML v2 Checker",
    "lint_sysml_text": "SysML v2 Checker",
    "get_ast_json": "SysML v2 Checker",
    "analyze_sysml_complete": "SysML v2 Checker",
    "get_server_info": "SysML v2 Checker",
}


def parse_log(path: Path) -> list[tuple[str, str]]:
    """1 ファイルから (server, tool) の並びを取り出す。"""
    calls: list[tuple[str, str]] = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        m = NEW_FORMAT.match(line)
        if m:
            calls.append((m.group("server"), m.group("tool")))
            continue
        m = OLD_FORMAT.match(line)
        if m:
            tool = m.group("tool")
            calls.append((TOOL_TO_SERVER.get(tool, "(unknown)"), tool))
    return calls


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--log-dir", default="logs", help="会話ログのディレクトリ")
    parser.add_argument("--since", default="", help="この文字列以降のファイル名だけ対象にする（例: 20260801）")
    args = parser.parse_args()

    log_dir = Path(args.log_dir)
    if not log_dir.is_dir():
        print(f"ログディレクトリが見つかりません: {log_dir}")
        return 1

    files = sorted(p for p in log_dir.glob("*.md") if p.name >= args.since)
    if not files:
        print("対象ログがありません。")
        return 1

    servers: Counter[str] = Counter()
    tools: Counter[tuple[str, str]] = Counter()
    sessions_with_calls = 0

    for path in files:
        calls = parse_log(path)
        if calls:
            sessions_with_calls += 1
        for server, tool in calls:
            servers[server] += 1
            tools[(server, tool)] += 1

    total = sum(servers.values())
    print(f"対象ログ: {len(files)} ファイル（うちツール呼び出しあり: {sessions_with_calls}）")
    print(f"総ツール呼び出し数: {total}")
    if not total:
        return 0

    print("\n== バックエンド選択率 ==")
    for server, count in servers.most_common():
        print(f"  {server:<28} {count:>5}  ({count / total:6.1%})")

    print("\n== ツール別 ==")
    for (server, tool), count in tools.most_common():
        print(f"  {server:<28} {tool:<26} {count:>5}")

    missing = [s for s in TOOL_TO_SERVER.values() if s not in servers]
    for server in sorted(set(missing)):
        print(f"\n注意: '{server}' は一度も選択されていません。")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
