"""graphrag.model_validator のSysMLモデル検証ロジック。優先度: GraphRAG(t6_add_tests_graphrag_gaps)。

query_engine は本物の GraphQueryEngine ではなく、query_graph/get_source_text の
戻り値を差し替えられる軽量スタブに固定する(実物は ChunkStorage 等に依存し重く、
このモジュール自身のロジックとは無関係)。LLM呼び出しは無い。
"""

import networkx as nx
import pytest
from graphrag.model_validator import SysMLModelValidator


class _StubQueryEngine:
    def __init__(self, query_graph_responses=None, source_texts=None):
        self.query_graph_responses = query_graph_responses or {}
        self.source_texts = source_texts or {}
        self.query_graph_calls = []

    def query_graph(self, query, max_nodes=5, explore_depth=1):
        self.query_graph_calls.append((query, max_nodes, explore_depth))
        return self.query_graph_responses.get(
            query, {"success": True, "matched_nodes": []}
        )

    def get_source_text(self, node_name, max_chunks=5):
        return self.source_texts.get(node_name, [])


@pytest.fixture
def graph():
    g = nx.DiGraph()
    g.add_node("port definition")
    g.add_node("port usage")
    g.add_node("constraint c1")
    g.add_node("requirement r1")
    return g


@pytest.fixture
def engine():
    return _StubQueryEngine()


@pytest.fixture
def validator(graph, engine):
    return SysMLModelValidator(graph, query_engine=engine)


# ---- _extract_concepts ----


@pytest.mark.parametrize(
    "text,expected",
    [
        ("part def Wheel { }", {"Wheel"}),
        ("action def Drive { }", {"Drive"}),
        ("PART DEF Engine {}", {"Engine"}),  # 大文字小文字を無視
        ("requirement def R1 { }", {"R1"}),
        ("no sysml elements here", set()),
    ],
)
def test_extract_concepts_matches_known_patterns(validator, text, expected):
    assert set(validator._extract_concepts(text)) == expected


def test_extract_concepts_deduplicates_repeated_definitions(validator):
    text = "part def Wheel { } part def Wheel { }"

    concepts = validator._extract_concepts(text)

    assert concepts == ["Wheel"]


def test_extract_concepts_collects_multiple_kinds(validator):
    text = "part def Wheel {} action def Drive {} constraint def MaxSpeed {}"

    concepts = set(validator._extract_concepts(text))

    assert concepts == {"Wheel", "Drive", "MaxSpeed"}


# ---- _semantic_comparison ----


def test_semantic_comparison_marks_matched_concept(graph):
    engine = _StubQueryEngine(
        query_graph_responses={"Wheel": {"success": True, "matched_nodes": ["port definition"]}}
    )
    validator = SysMLModelValidator(graph, query_engine=engine)

    result = validator._semantic_comparison("part def Wheel { }")

    assert len(result["matched_concepts"]) == 1
    assert result["matched_concepts"][0]["concept"] == "Wheel"
    assert result["matched_concepts"][0]["matched_nodes"] == ["port definition"]
    assert result["unmatched_concepts"] == []


def test_semantic_comparison_falls_back_to_similar_concepts(graph):
    engine = _StubQueryEngine(
        query_graph_responses={
            "Wheel": {"success": True, "matched_nodes": []},
        }
    )
    # _find_similar_concepts は別クエリ(同じconcept文字列)でquery_graphを呼ぶ。
    engine.query_graph_responses["Wheel"] = {"success": True, "matched_nodes": []}
    validator = SysMLModelValidator(graph, query_engine=engine)
    # 2回目の呼び出し(similar検索, explore_depth=2)で一致ありに差し替える
    original_query_graph = engine.query_graph

    def query_graph_with_similar(query, max_nodes=5, explore_depth=1):
        if explore_depth == 2:
            return {"success": True, "matched_nodes": ["port usage"]}
        return original_query_graph(query, max_nodes, explore_depth)

    engine.query_graph = query_graph_with_similar

    result = validator._semantic_comparison("part def Wheel { }")

    assert result["matched_concepts"] == []
    assert len(result["similar_concepts"]) == 1
    assert result["similar_concepts"][0]["concept"] == "Wheel"
    assert result["unmatched_concepts"] == []


def test_semantic_comparison_marks_unmatched_when_nothing_found(graph, engine):
    validator = SysMLModelValidator(graph, query_engine=engine)

    result = validator._semantic_comparison("part def GhostConcept { }")

    assert result["matched_concepts"] == []
    assert result["similar_concepts"] == []
    assert result["unmatched_concepts"] == ["GhostConcept"]


def test_semantic_comparison_handles_no_concepts_in_text(validator):
    result = validator._semantic_comparison("nothing to see here")

    assert result == {"matched_concepts": [], "unmatched_concepts": [], "similar_concepts": []}


# ---- _find_similar_concepts ----


def test_find_similar_concepts_returns_nodes_with_fixed_similarity(graph):
    engine = _StubQueryEngine(
        query_graph_responses={"Wheel": {"success": True, "matched_nodes": ["port definition", "port usage"]}}
    )
    validator = SysMLModelValidator(graph, query_engine=engine)

    similar = validator._find_similar_concepts("Wheel")

    assert similar == [
        {"node": "port definition", "similarity": 0.7},
        {"node": "port usage", "similarity": 0.7},
    ]


def test_find_similar_concepts_returns_empty_when_query_fails(validator):
    assert validator._find_similar_concepts("Wheel") == []


# ---- _get_constraint_info / _check_constraint_satisfaction ----


def test_get_constraint_info_includes_node_attributes_and_source_texts(graph):
    graph.nodes["constraint c1"]["description"] = "max speed constraint"
    engine = _StubQueryEngine(source_texts={"constraint c1": ["speed must not exceed 100"]})
    validator = SysMLModelValidator(graph, query_engine=engine)

    info = validator._get_constraint_info("constraint c1")

    assert info["node"] == "constraint c1"
    assert info["attributes"]["description"] == "max speed constraint"
    assert info["source_texts"] == ["speed must not exceed 100"]


def test_check_constraint_satisfaction_true_when_constraint_name_in_model_text(validator):
    constraint_info = {"node": "constraint c1", "source_texts": []}

    assert validator._check_constraint_satisfaction("uses constraint c1 here", constraint_info) is True


def test_check_constraint_satisfaction_true_when_source_text_appears_in_model(validator):
    constraint_info = {"node": "constraint c1", "source_texts": ["speed limit applies"]}

    assert validator._check_constraint_satisfaction("the speed limit applies to this part", constraint_info) is True


def test_check_constraint_satisfaction_false_when_nothing_matches(validator):
    constraint_info = {"node": "constraint c1", "source_texts": ["unrelated text"]}

    assert validator._check_constraint_satisfaction("totally different content", constraint_info) is False


# ---- _detect_constraint_violations ----


def test_detect_constraint_violations_flags_unsatisfied_constraint_nodes(graph, engine):
    validator = SysMLModelValidator(graph, query_engine=engine)

    violations = validator._detect_constraint_violations("no relevant content")

    violated_nodes = {v["constraint"] for v in violations}
    assert violated_nodes == {"constraint c1", "requirement r1"}
    assert all(v["violation_type"] == "constraint_not_satisfied" for v in violations)


def test_detect_constraint_violations_excludes_satisfied_constraint(graph, engine):
    validator = SysMLModelValidator(graph, query_engine=engine)

    violations = validator._detect_constraint_violations("this model references constraint c1 explicitly")

    violated_nodes = {v["constraint"] for v in violations}
    assert "constraint c1" not in violated_nodes
    assert "requirement r1" in violated_nodes


def test_detect_constraint_violations_empty_when_no_constraint_nodes_in_graph():
    g = nx.DiGraph()
    g.add_node("port definition")
    engine = _StubQueryEngine()
    validator = SysMLModelValidator(g, query_engine=engine)

    assert validator._detect_constraint_violations("anything") == []


# ---- _check_specification_compliance ----


def test_check_specification_compliance_full_coverage_when_all_concepts_match():
    g = nx.DiGraph()
    g.add_node("Wheel")
    g.add_node("Drive")
    engine = _StubQueryEngine()
    validator = SysMLModelValidator(g, query_engine=engine)

    compliance = validator._check_specification_compliance("part def Wheel {} action def Drive {}")

    assert compliance["coverage"] == 1.0
    assert compliance["compliant"] is True
    assert compliance["issues"] == []


def test_check_specification_compliance_flags_low_coverage_as_noncompliant(graph, engine):
    validator = SysMLModelValidator(graph, query_engine=engine)

    compliance = validator._check_specification_compliance("part def GhostConcept {}")

    assert compliance["coverage"] == 0.0
    assert compliance["compliant"] is False
    assert compliance["issues"][0]["concept"] == "GhostConcept"


def test_check_specification_compliance_zero_coverage_when_no_concepts_extracted(validator):
    compliance = validator._check_specification_compliance("no sysml elements at all")

    assert compliance["coverage"] == 0.0
    assert compliance["compliant"] is False
    assert compliance["issues"] == []


# ---- _generate_recommendations ----


def test_generate_recommendations_lists_unmatched_concepts():
    validator = SysMLModelValidator(nx.DiGraph(), query_engine=_StubQueryEngine())
    results = {
        "semantic_comparison": {"unmatched_concepts": ["Wheel", "Drive"]},
        "constraint_violations": [],
        "specification_compliance": {"compliant": True},
    }

    recs = validator._generate_recommendations(results)

    assert any("Wheel" in r and "Drive" in r for r in recs)


def test_generate_recommendations_reports_constraint_violation_count():
    validator = SysMLModelValidator(nx.DiGraph(), query_engine=_StubQueryEngine())
    results = {
        "semantic_comparison": {"unmatched_concepts": []},
        "constraint_violations": [{"constraint": "c1"}, {"constraint": "c2"}],
        "specification_compliance": {"compliant": True},
    }

    recs = validator._generate_recommendations(results)

    assert any("2" in r for r in recs)


def test_generate_recommendations_reports_low_compliance_coverage():
    validator = SysMLModelValidator(nx.DiGraph(), query_engine=_StubQueryEngine())
    results = {
        "semantic_comparison": {"unmatched_concepts": []},
        "constraint_violations": [],
        "specification_compliance": {"compliant": False, "coverage": 0.4},
    }

    recs = validator._generate_recommendations(results)

    assert len(recs) == 1
    assert "40.0%" in recs[0]


def test_generate_recommendations_empty_when_everything_is_fine():
    validator = SysMLModelValidator(nx.DiGraph(), query_engine=_StubQueryEngine())
    results = {
        "semantic_comparison": {"unmatched_concepts": []},
        "constraint_violations": [],
        "specification_compliance": {"compliant": True},
    }

    assert validator._generate_recommendations(results) == []


# ---- validate_model (統合) ----


def test_validate_model_runs_all_checks_by_default(graph, engine):
    validator = SysMLModelValidator(graph, query_engine=engine)

    result = validator.validate_model("part def GhostConcept {}")

    assert result["success"] is True
    assert "semantic_comparison" in result
    assert result["constraint_violations"]  # デフォルトのグラフには制約ノードがある
    assert "specification_compliance" in result
    assert result["recommendations"]


def test_validate_model_skips_constraint_check_when_disabled(graph, engine):
    validator = SysMLModelValidator(graph, query_engine=engine)

    result = validator.validate_model(
        "part def GhostConcept {}", check_constraints=False
    )

    assert result["constraint_violations"] == []


def test_validate_model_skips_compliance_check_when_disabled(graph, engine):
    validator = SysMLModelValidator(graph, query_engine=engine)

    result = validator.validate_model(
        "part def GhostConcept {}", check_specification_compliance=False
    )

    assert result["specification_compliance"] == {}


# ---- __init__ default query_engine wiring ----


def test_init_builds_default_query_engine_when_none_given():
    g = nx.DiGraph()
    g.add_node("a")

    validator = SysMLModelValidator(g)

    assert validator.query_engine is not None
    assert validator.graph is g
