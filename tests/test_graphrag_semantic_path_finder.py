"""graphrag.semantic_path_finder の直接探索フォールバックとLLM推論のテスト。優先度: GraphRAG(t6_add_tests_graphrag_gaps)。

graph_query_engine は本物の GraphQueryEngine ではなく、find_path の戻り値を
自由に制御できる軽量スタブに差し替える(実物は ChunkStorage 等に依存し重い)。
LLMクライアントは HybridRAG のテストと同様、chat.completions.create をモックし、
実際のOpenAI呼び出しを一切発生させない。
"""

import networkx as nx
import pytest
from graphrag.semantic_path_finder import SemanticPathFinder

from graphrag import semantic_path_finder as spf_module


class _StubQueryEngine:
    """find_path の戻り値を (start, end) キーで差し替えられるスタブ。"""

    def __init__(self, responses=None, raise_on=None):
        self.responses = responses or {}
        self.raise_on = raise_on or set()
        self.calls = []

    def find_path(self, start, end, max_depth=3):
        self.calls.append((start, end, max_depth))
        if (start, end) in self.raise_on:
            raise RuntimeError("path lookup failed")
        return self.responses.get((start, end), {"success": False, "path": None})


@pytest.fixture
def graph():
    g = nx.DiGraph()
    g.add_edge("requirement", "constraint", relation="satisfies")
    g.add_edge("requirement", "port definition", relation="related")
    g.add_edge("constraint", "port usage", relation="related")
    g.add_edge("port definition", "port usage", relation="related")
    return g


# ---- find_semantic_path: 入力検証 ----


def test_find_semantic_path_errors_when_start_missing(graph):
    engine = _StubQueryEngine()
    finder = SemanticPathFinder(graph, engine)

    result = finder.find_semantic_path("nonexistent", "constraint")

    assert result["type"] == "error"
    assert result["confidence"] == 0.0
    assert engine.calls == []  # ノード検証で早期リターンし、探索は呼ばれない


def test_find_semantic_path_errors_when_end_missing(graph):
    engine = _StubQueryEngine()
    finder = SemanticPathFinder(graph, engine)

    result = finder.find_semantic_path("requirement", "nonexistent")

    assert result["type"] == "error"
    assert result["confidence"] == 0.0


# ---- find_semantic_path: 直接探索優先 ----


def test_find_semantic_path_returns_direct_path_when_found(graph):
    engine = _StubQueryEngine(
        responses={("requirement", "constraint"): {"success": True, "path": ["requirement", "constraint"]}}
    )
    finder = SemanticPathFinder(graph, engine)

    result = finder.find_semantic_path("requirement", "constraint")

    assert result["type"] == "direct"
    assert result["path"] == ["requirement", "constraint"]
    assert result["confidence"] == 1.0
    assert result["method"] == "graph_traversal"


def test_find_semantic_path_falls_back_to_semantic_when_direct_path_absent(graph):
    engine = _StubQueryEngine()  # 常に success: False
    finder = SemanticPathFinder(graph, engine)

    result = finder.find_semantic_path("requirement", "port usage")

    assert result["type"] == "semantic"
    assert result["start"] == "requirement"
    assert result["end"] == "port usage"


def test_find_semantic_path_falls_back_when_direct_search_raises(graph):
    engine = _StubQueryEngine(raise_on={("requirement", "port usage")})
    finder = SemanticPathFinder(graph, engine)

    result = finder.find_semantic_path("requirement", "port usage")

    assert result["type"] == "semantic"


# ---- _find_semantic_relationship: キャッシュ ----


def test_find_semantic_relationship_caches_result(graph):
    engine = _StubQueryEngine()
    finder = SemanticPathFinder(graph, engine)

    first = finder._find_semantic_relationship("requirement", "port usage")
    calls_after_first = len(engine.calls)
    second = finder._find_semantic_relationship("requirement", "port usage")

    assert first is second
    assert len(engine.calls) == calls_after_first  # 2回目はエンジンを呼ばない


def test_find_semantic_relationship_uses_simple_inference_without_llm_client(graph):
    engine = _StubQueryEngine()
    finder = SemanticPathFinder(graph, engine)

    result = finder._find_semantic_relationship("requirement", "port usage")

    assert result["method"] == "simple_inference + graph_verification"


# ---- _infer_bridge_concepts_simple (実グラフでのロジック検証) ----


def test_infer_bridge_concepts_simple_finds_common_neighbor(graph):
    engine = _StubQueryEngine()
    finder = SemanticPathFinder(graph, engine)

    # constraint -> port usage と port definition -> port usage の両方が存在するため、
    # "port usage" は両者の共通の後続ノード(共通隣接)として見つかるはず
    bridges = finder._infer_bridge_concepts_simple("constraint", "port definition")

    assert "port usage" in bridges


def test_infer_bridge_concepts_simple_finds_direct_common_neighbor():
    g = nx.DiGraph()
    g.add_edge("a", "shared")
    g.add_edge("b", "shared")
    engine = _StubQueryEngine()
    finder = SemanticPathFinder(g, engine)

    bridges = finder._infer_bridge_concepts_simple("a", "b")

    assert "shared" in bridges


def test_infer_bridge_concepts_simple_returns_empty_when_unrelated():
    g = nx.DiGraph()
    g.add_node("isolated_a")
    g.add_node("isolated_b")
    engine = _StubQueryEngine()
    finder = SemanticPathFinder(g, engine)

    assert finder._infer_bridge_concepts_simple("isolated_a", "isolated_b") == []


# ---- _infer_bridge_concepts_with_llm ----


def test_infer_bridge_concepts_with_llm_uses_generate_method(graph):
    class _GenerateClient:
        def generate(self, prompt):
            # "- word" 形式は単語境界で1語しか拾えない仕様(下記の
            # test_extract_concepts_from_response_bullet_format_only_captures_first_word
            # 参照)なので、複数語のノードは引用符付きで返す。
            return '- constraint\n- "port definition"'

    engine = _StubQueryEngine()
    finder = SemanticPathFinder(graph, engine, llm_client=_GenerateClient())

    concepts = finder._infer_bridge_concepts_with_llm("requirement", "port usage")

    assert "constraint" in concepts
    assert "port definition" in concepts


def test_infer_bridge_concepts_with_llm_uses_openai_style_chat_client(graph, monkeypatch):
    from unittest.mock import MagicMock

    # hasattr(client, 'generate') が先にチェックされるため、単純な MagicMock() を
    # そのまま使うと自動生成された 'generate' 属性が真になり、意図した
    # chat.completions 経路をテストできない。'generate' を持たないスタブにする。
    class _ChatOnlyClient:
        def __init__(self):
            self.chat = MagicMock()

    response = MagicMock()
    response.choices = [MagicMock(message=MagicMock(content='- constraint\n- "port definition"'))]
    client = _ChatOnlyClient()
    client.chat.completions.create.return_value = response

    engine = _StubQueryEngine()
    finder = SemanticPathFinder(graph, engine, llm_client=client)

    concepts = finder._infer_bridge_concepts_with_llm("requirement", "port usage")

    assert "constraint" in concepts
    assert "port definition" in concepts
    client.chat.completions.create.assert_called_once()
    kwargs = client.chat.completions.create.call_args.kwargs
    assert kwargs["model"] == spf_module.config.LLM_MODEL
    assert kwargs["reasoning_effort"] == "low"
    assert kwargs["max_completion_tokens"] == 900


def test_infer_bridge_concepts_with_llm_falls_back_when_client_has_no_known_interface(graph):
    class _UselessClient:
        pass

    engine = _StubQueryEngine()
    finder = SemanticPathFinder(graph, engine, llm_client=_UselessClient())

    concepts = finder._infer_bridge_concepts_with_llm("requirement", "port usage")

    # 簡易版と同じ結果になるはず
    assert concepts == finder._infer_bridge_concepts_simple("requirement", "port usage")


def test_infer_bridge_concepts_with_llm_falls_back_when_client_raises(graph):
    class _BoomClient:
        def generate(self, prompt):
            raise RuntimeError("api down")

    engine = _StubQueryEngine()
    finder = SemanticPathFinder(graph, engine, llm_client=_BoomClient())

    concepts = finder._infer_bridge_concepts_with_llm("requirement", "port usage")

    assert concepts == finder._infer_bridge_concepts_simple("requirement", "port usage")


# ---- _extract_concepts_from_response ----


def test_extract_concepts_from_response_parses_bullet_list(graph):
    engine = _StubQueryEngine()
    finder = SemanticPathFinder(graph, engine)

    concepts = finder._extract_concepts_from_response("- constraint\n- requirement\n- unknownnode")

    assert concepts == ["constraint", "requirement"]  # グラフに存在しないものは除外


def test_extract_concepts_from_response_bullet_format_only_captures_first_word(graph):
    """挙動確認(既知の制約): "- " 形式の正規表現は単語境界(\\w+)しか拾わないため、

    "- port definition" のようにスペースを含む複数語ノード名は "port" までしか
    キャプチャされず、"port"単体はグラフに存在しないため最終的に除外される。
    複数語の概念をLLM出力から拾わせたい場合は引用符付き("- \"port definition\"")
    または "concept: 説明" 形式で返させる必要がある。
    """
    engine = _StubQueryEngine()
    finder = SemanticPathFinder(graph, engine)

    concepts = finder._extract_concepts_from_response("- port definition")

    assert concepts == []


def test_extract_concepts_from_response_parses_colon_format(graph):
    engine = _StubQueryEngine()
    finder = SemanticPathFinder(graph, engine)

    concepts = finder._extract_concepts_from_response("constraint: connects requirement and port usage")

    assert concepts == ["constraint"]


def test_extract_concepts_from_response_parses_quoted_concepts(graph):
    engine = _StubQueryEngine()
    finder = SemanticPathFinder(graph, engine)

    concepts = finder._extract_concepts_from_response('the bridge is "constraint" here')

    assert concepts == ["constraint"]


def test_extract_concepts_from_response_limits_to_five(graph):
    g = nx.DiGraph()
    names = [f"node{i}" for i in range(10)]
    for n in names:
        g.add_node(n)
    engine = _StubQueryEngine()
    finder = SemanticPathFinder(g, engine)
    response = "\n".join(f"- {n}" for n in names)

    concepts = finder._extract_concepts_from_response(response)

    assert len(concepts) == 5


# ---- _verify_bridge_concepts ----


def test_verify_bridge_concepts_skips_concept_not_in_graph(graph):
    engine = _StubQueryEngine()
    finder = SemanticPathFinder(graph, engine)

    verified = finder._verify_bridge_concepts("requirement", "port usage", ["not_a_node"])

    assert verified == []


def test_verify_bridge_concepts_high_confidence_when_both_paths_exist(graph):
    engine = _StubQueryEngine(
        responses={
            ("requirement", "constraint"): {"success": True, "path": ["requirement", "constraint"]},
            ("constraint", "port usage"): {"success": True, "path": ["constraint", "port usage"]},
        }
    )
    finder = SemanticPathFinder(graph, engine)

    verified = finder._verify_bridge_concepts("requirement", "port usage", ["constraint"])

    assert verified[0]["confidence"] == 0.9
    assert verified[0]["start_to_bridge"] is True
    assert verified[0]["bridge_to_end"] is True


def test_verify_bridge_concepts_medium_confidence_when_one_path_exists(graph):
    engine = _StubQueryEngine(
        responses={("requirement", "constraint"): {"success": True, "path": ["requirement", "constraint"]}}
    )
    finder = SemanticPathFinder(graph, engine)

    verified = finder._verify_bridge_concepts("requirement", "port usage", ["constraint"])

    assert verified[0]["confidence"] == 0.6


def test_verify_bridge_concepts_low_confidence_when_no_path_exists(graph):
    engine = _StubQueryEngine()  # 常に失敗
    finder = SemanticPathFinder(graph, engine)

    verified = finder._verify_bridge_concepts("requirement", "port usage", ["constraint"])

    assert verified[0]["confidence"] == 0.3
    assert verified[0]["source"] == "graph_exists"


def test_verify_bridge_concepts_treats_path_lookup_exception_as_no_path(graph):
    engine = _StubQueryEngine(raise_on={("requirement", "constraint")})
    finder = SemanticPathFinder(graph, engine)

    verified = finder._verify_bridge_concepts("requirement", "port usage", ["constraint"])

    assert verified[0]["start_to_bridge"] is False


def test_verify_bridge_concepts_sorts_by_confidence_descending(graph):
    engine = _StubQueryEngine(
        responses={
            ("requirement", "port definition"): {"success": True, "path": ["requirement", "port definition"]},
            ("port definition", "port usage"): {"success": True, "path": ["port definition", "port usage"]},
        }
    )
    finder = SemanticPathFinder(graph, engine)

    verified = finder._verify_bridge_concepts(
        "requirement", "port usage", ["constraint", "port definition"]
    )

    confidences = [v["confidence"] for v in verified]
    assert confidences == sorted(confidences, reverse=True)
    assert verified[0]["concept"] == "port definition"


# ---- _calculate_semantic_confidence ----


def test_calculate_semantic_confidence_empty_is_zero(graph):
    engine = _StubQueryEngine()
    finder = SemanticPathFinder(graph, engine)

    assert finder._calculate_semantic_confidence([]) == 0.0


def test_calculate_semantic_confidence_averages_bridge_confidences(graph):
    engine = _StubQueryEngine()
    finder = SemanticPathFinder(graph, engine)

    avg = finder._calculate_semantic_confidence([{"confidence": 0.9}, {"confidence": 0.3}])

    assert avg == pytest.approx(0.6)
