"""Semantic Model の関係エッジ（sysml_v2_checker_advanced/semantic_model.py）の
新規ユニットテスト。Phase 2第1弾: specialization/subsetting/redefinition/
feature_typing のみを対象とする（拡張仕様書8章、2026-09-03のPhase 2再検討で
linter.pyには一切手を入れない設計に変更）。

connection/satisfy/verify系エッジとresolution_statusの3値分類は未実装
（次段階）。
"""

from __future__ import annotations

from sysml_v2_checker_advanced.antlr_transformer import parse_sysml_antlr
from sysml_v2_checker_advanced.semantic_model import build_semantic_model

_SAMPLE = """
package Vehicle {
    part def Machine {
        attribute mass : Real;
    }
    part def Engine :> Machine {
        attribute power : Real;
    }
    part myEngine : Engine;
}
"""


def test_linter_py_is_not_modified_by_this_feature():
    """build_semantic_model()はlinter.pyの既存挙動に影響しない
    （lint_sysml(ast)の指摘内容が変わらないこと）を確認する。"""
    from sysml_v2_checker_advanced.parser import lint_sysml

    ast = parse_sysml_antlr(_SAMPLE.strip())
    issues_before = [(i.severity, i.message) for i in lint_sysml(ast)]

    build_semantic_model(_SAMPLE.strip())

    issues_after = [(i.severity, i.message) for i in lint_sysml(ast)]
    assert issues_before == issues_after


def test_subsetting_edge_resolves_to_base_part_def():
    _, model = build_semantic_model(_SAMPLE.strip())
    edge = next(e for e in model["edges"] if e["from_id"] == "$root::Engine" and e["kind"] == "subsetting")
    assert edge["to_id"] == "$root::Machine"
    assert edge["resolved"] is True


def test_feature_typing_edge_resolves_to_local_part_def():
    _, model = build_semantic_model(_SAMPLE.strip())
    edge = next(e for e in model["edges"] if e["from_id"] == "$root::myEngine")
    assert edge["kind"] == "feature_typing"
    assert edge["to_id"] == "$root::Engine"
    assert edge["resolved"] is True


def test_builtin_type_reference_is_unresolved_external():
    """組み込み型(Real等)はASTノードを持たないため to_id=None だが、
    linter自身がエラー扱いしない参照のため resolution_status は
    "unresolved_external"（拡張仕様書8.2章）。
    """
    _, model = build_semantic_model(_SAMPLE.strip())
    edge = next(e for e in model["edges"] if e["from_id"] == "$root::Machine::mass")
    assert edge["kind"] == "feature_typing"
    assert edge["reference_text"] == "Real"
    assert edge["resolved"] is False
    assert edge["to_id"] is None
    assert edge["resolution_status"] == "unresolved_external"


def test_resolved_edge_has_resolved_status():
    _, model = build_semantic_model(_SAMPLE.strip())
    edge = next(e for e in model["edges"] if e["from_id"] == "$root::Engine" and e["kind"] == "subsetting")
    assert edge["resolution_status"] == "resolved"


def test_genuinely_broken_reference_is_unresolved_error():
    """このファイル内にも標準ライブラリにも見つからない参照は
    resolution_status="unresolved_error"（=lintも実際にエラー報告する）。
    """
    text = """
    package P {
        part broken : NoSuchTypeAtAll;
    }
    """
    _, model = build_semantic_model(text.strip())
    edge = next(e for e in model["edges"] if e["from_id"] == "$root::broken")
    assert edge["resolution_status"] == "unresolved_error"


def test_resolution_status_does_not_contradict_lint_errors():
    """resolution_status="unresolved_error"のエッジは、同じASTに対する
    lint_sysml()が実際にerror severityの指摘を出すことと整合する
    （拡張仕様書8.2章の要件：Viewer側の未解決表示とlintのエラー判定を
    矛盾させない）。
    """
    from sysml_v2_checker_advanced.parser import lint_sysml

    text = """
    package P {
        part broken : NoSuchTypeAtAll;
    }
    """
    ast, model = build_semantic_model(text.strip())
    error_edges = [e for e in model["edges"] if e["resolution_status"] == "unresolved_error"]
    assert error_edges

    issues = lint_sysml(ast)
    assert any(i.severity == "error" for i in issues)


def test_error_ast_returns_empty_edges():
    ast, model = build_semantic_model("this is not valid sysml {{{")
    assert ast.get("type") == "error"
    assert model["edges"] == []


def test_multitype_produces_multiple_feature_typing_edges():
    text = """
    package P {
        part def A;
        part def B;
        item i : A, B;
    }
    """
    _, model = build_semantic_model(text.strip())
    typing_edges = [e for e in model["edges"] if e["from_id"] == "$root::i" and e["kind"] == "feature_typing"]
    resolved_targets = {e["to_id"] for e in typing_edges}
    assert resolved_targets == {"$root::A", "$root::B"}


# --- connection / satisfy / verify エッジ（p2b2, 2026-09-03） -----------------


def test_connect_usage_produces_connection_edges_to_both_ends():
    text = """
    package P {
        part a;
        part b;
        connect a to b;
    }
    """
    _, model = build_semantic_model(text.strip())
    connection_edges = [e for e in model["edges"] if e["kind"] == "connection"]
    assert len(connection_edges) == 2
    assert {e["from_id"] for e in connection_edges} == {"$root/connect_usage#0"}
    assert {e["to_id"] for e in connection_edges} == {"$root::a", "$root::b"}
    assert all(e["resolved"] for e in connection_edges)


def test_nary_connect_produces_one_connection_edge_per_end():
    text = """
    package P {
        part a;
        part b;
        part c;
        connect (a, b, c);
    }
    """
    _, model = build_semantic_model(text.strip())
    connection_edges = [e for e in model["edges"] if e["kind"] == "connection"]
    assert {e["to_id"] for e in connection_edges} == {"$root::a", "$root::b", "$root::c"}


def test_binding_connector_produces_connection_edges():
    text = """
    package P {
        part a;
        part b;
        bind a = b;
    }
    """
    _, model = build_semantic_model(text.strip())
    connection_edges = [e for e in model["edges"] if e["kind"] == "connection"]
    assert {e["to_id"] for e in connection_edges} == {"$root::a", "$root::b"}


def test_satisfy_requirement_usage_produces_satisfy_edge():
    text = """
    package P {
        part system;
        requirement def Req1;
        satisfy requirement req1 : Req1 by system;
    }
    """
    _, model = build_semantic_model(text.strip())
    satisfy_edges = [e for e in model["edges"] if e["kind"] == "satisfy"]
    assert len(satisfy_edges) == 1
    assert satisfy_edges[0]["from_id"] == "$root::req1"
    assert satisfy_edges[0]["to_id"] == "$root::system"
    assert satisfy_edges[0]["resolved"] is True


def test_verify_requirement_usage_produces_verify_edge():
    text = """
    package P {
        part system;
        requirement def Req1;
        requirement req1 : Req1;
        verify req1 by system;
    }
    """
    _, model = build_semantic_model(text.strip())
    verify_edges = [e for e in model["edges"] if e["kind"] == "verify"]
    assert len(verify_edges) == 1
    assert verify_edges[0]["to_id"] == "$root::system"
    assert verify_edges[0]["resolved"] is True
