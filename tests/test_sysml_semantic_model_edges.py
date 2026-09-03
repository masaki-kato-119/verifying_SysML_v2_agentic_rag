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


def test_builtin_type_reference_is_unresolved():
    """組み込み型(Real等)はASTノードを持たないため、現段階では
    resolved=False, to_id=None として扱う（resolution_status 3値分類は
    次段階。今はunresolved_externalとの区別をしない）。
    """
    _, model = build_semantic_model(_SAMPLE.strip())
    edge = next(e for e in model["edges"] if e["from_id"] == "$root::Machine::mass")
    assert edge["kind"] == "feature_typing"
    assert edge["reference_text"] == "Real"
    assert edge["resolved"] is False
    assert edge["to_id"] is None


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
