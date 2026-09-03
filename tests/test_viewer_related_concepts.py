"""viewer.backend.related_concepts の単体テスト（Group4 b16, R1-2）。

MCPサーバーへの実接続なしに、検索語の組み立て・結果整形ロジックだけを検証する
（実接続を伴う統合テストは tests/test_viewer_backend_api.py 側）。
"""

from __future__ import annotations

from viewer.backend.related_concepts import element_query_terms, search_related_concepts


def test_element_query_terms_strips_type_suffix_and_underscores():
    assert element_query_terms("requirement_usage", "req1") == ["requirement", "req1"]


def test_element_query_terms_drops_duplicate_when_label_equals_type_term():
    assert element_query_terms("part_def", "part") == ["part"]


def test_element_query_terms_handles_empty_type_and_label():
    assert element_query_terms("", "") == []


class _StubResult:
    def __init__(self, data):
        self.data = data


async def test_search_related_concepts_returns_first_hit_term():
    calls = []

    async def fake_call_tool(name, args):
        calls.append((name, args["query"]))
        if args["query"] == "requirement":
            return _StubResult({
                "success": True,
                "matched_nodes_with_text": [
                    {"node": "requirement", "score": 1.0, "match_type": "exact", "source_texts": ["..."]},
                ],
            })
        return _StubResult({"success": True, "matched_nodes_with_text": []})

    result = await search_related_concepts(fake_call_tool, "requirement_usage", "req1")

    assert result["available"] is True
    assert result["query_term"] == "requirement"
    assert result["concepts"] == [
        {"concept": "requirement", "score": 1.0, "match_type": "exact", "source_texts": ["..."]}
    ]
    # 型由来の語("requirement")で1件目にヒットしたため、ラベル("req1")までは試さない。
    assert calls == [("search_graph", "requirement")]


async def test_search_related_concepts_falls_back_to_label_when_type_term_misses():
    async def fake_call_tool(name, args):
        if args["query"] == "part":
            return _StubResult({"success": True, "matched_nodes_with_text": []})
        return _StubResult({
            "success": True,
            "matched_nodes_with_text": [
                {"node": "myEngine", "score": 0.5, "match_type": "partial", "source_texts": []}
            ],
        })

    result = await search_related_concepts(fake_call_tool, "part_def", "myEngine")

    assert result["query_term"] == "myEngine"
    assert result["concepts"][0]["concept"] == "myEngine"


async def test_search_related_concepts_reports_unavailable_on_call_failure():
    async def failing_call_tool(name, args):
        raise RuntimeError("server not running")

    result = await search_related_concepts(failing_call_tool, "part_def", "myEngine")

    assert result["available"] is False
    assert result["concepts"] == []


async def test_search_related_concepts_returns_empty_when_no_terms():
    async def unused_call_tool(name, args):
        raise AssertionError("検索語が無い場合はcall_toolを呼んではいけない")

    result = await search_related_concepts(unused_call_tool, "", "")
    assert result == {"available": True, "query_term": None, "concepts": []}
