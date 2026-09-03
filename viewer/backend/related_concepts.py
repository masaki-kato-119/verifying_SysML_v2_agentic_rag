"""選択要素からGraphRAGへの検索クエリ組み立てと結果整形（Group4 b16, R1-2）。

MCPクライアントのI/O（rag_client.py）から切り離した純粋なロジック部分。
GraphRAGサーバー未起動でも単体テストできるよう、ここでは
`call_tool(name, args) -> {"data": ...}` 相当の呼び出し可能オブジェクトだけを
引数に取る（fastmcp.Client.call_toolと同じ形）。
"""

from __future__ import annotations

import re
from typing import Any, Awaitable, Callable, Dict, List, Optional

# SysMLの型名接尾辞("_def"/"_usage"/"_instance")はGraphRAG側の語彙
# （SysML v2言語仕様書から抽出された単語、例:"part"/"requirement"）とは
# 一致しないため、検索前に取り除く。アンダースコアは空白に変換する
# （複合語の型名、例:"binding_connector" → "binding connector"）。
_TYPE_SUFFIX_RE = re.compile(r"(_def|_usage|_instance)$")


def element_query_terms(element_type: str, label: str) -> List[str]:
    """要素の型・ラベルから検索語の候補を優先順で返す。

    GraphRAGのノード名は仕様書から抽出された単語単位のメタモデル語彙
    （例:"part"/"requirement"/"attribute"）であり、モデル中のインスタンス名
    （例:"myEngine"）と一致することは期待しにくい。そのため型由来の語を
    優先し、ヒットしなければラベルでも試す（呼び出し側が順に試す前提）。
    """
    type_term = _TYPE_SUFFIX_RE.sub("", element_type or "").replace("_", " ").strip()
    terms = []
    if type_term:
        terms.append(type_term)
    if label and label.strip() and label.strip() != type_term:
        terms.append(label.strip())
    return terms


CallTool = Callable[[str, Dict[str, Any]], Awaitable[Any]]


async def search_related_concepts(call_tool: CallTool, element_type: str, label: str) -> Dict[str, Any]:
    """GraphRAGの`search_graph`ツールを検索語候補の順に試し、最初にヒットした
    結果を返す（`viewer.backend.rag_client.get_rag_client()`が返す
    `Client.call_tool`をそのまま渡せる）。

    Returns:
        {"available": True, "query_term": 使った検索語（ヒットなしならNone）,
         "concepts": [{"concept","score","match_type","source_texts"}, ...]}
        呼び出し自体が失敗した場合（GraphRAGサーバー未起動等）は
        {"available": False, "error": str, "concepts": []}。
    """
    terms = element_query_terms(element_type, label)
    if not terms:
        return {"available": True, "query_term": None, "concepts": []}

    last_term: Optional[str] = None
    for term in terms:
        last_term = term
        try:
            result = await call_tool("search_graph", {"query": term, "mode": "query", "max_nodes": 5})
        except Exception as e:  # noqa: BLE001 - MCP境界: サーバー未起動等も含め呼び出し側へエラーとして伝える
            return {"available": False, "error": str(e), "concepts": []}

        data = getattr(result, "data", result)
        if not isinstance(data, dict) or not data.get("success", True):
            continue
        matched = data.get("matched_nodes_with_text") or []
        if matched:
            concepts = [
                {
                    "concept": m.get("node"),
                    "score": m.get("score"),
                    "match_type": m.get("match_type"),
                    "source_texts": m.get("source_texts", []),
                }
                for m in matched
            ]
            return {"available": True, "query_term": term, "concepts": concepts}

    return {"available": True, "query_term": last_term, "concepts": []}
