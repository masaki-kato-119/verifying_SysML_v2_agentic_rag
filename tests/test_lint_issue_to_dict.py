"""LintIssue.to_dict() + semantic_model.build_element_index() の新規テスト
（拡張仕様書9章、Phase 3）。

to_dict() は element_index を省略した既存呼び出し（`issue.to_dict()`）を
引き続きサポートする。以前は常に None だった "line" キーは削除され、
"element_id"/"source_range" に置き換わっている（拡張仕様書13章で確認済みの
通り、"line" キーに依存する既存呼び出し元はリポジトリ内に存在しない）。
"""

from __future__ import annotations

from sysml_v2_checker_advanced.antlr_transformer import parse_sysml_with_semantic_model
from sysml_v2_checker_advanced.parser import lint_sysml
from sysml_v2_checker_advanced.semantic_model import build_element_index


def test_to_dict_without_index_returns_none_fields():
    text = "package P { part broken : NoSuchTypeAtAll; }"
    ast, _ = parse_sysml_with_semantic_model(text)
    issues = lint_sysml(ast)
    assert issues

    result = issues[0].to_dict()
    assert set(result.keys()) == {"severity", "message", "rule", "element_id", "source_range"}
    assert result["element_id"] is None
    assert result["source_range"] is None


def test_to_dict_with_element_index_resolves_element_id_and_source_range():
    text = "package P { part broken : NoSuchTypeAtAll; }"
    ast, model = parse_sysml_with_semantic_model(text)
    issues = lint_sysml(ast)
    element_index = build_element_index(model["nodes"])

    result = issues[0].to_dict(element_index)
    assert result["element_id"] == "$root::broken"
    assert result["source_range"] is not None
    assert result["source_range"]["start_line"] == 1


def test_element_index_requires_same_ast_object_graph():
    """別々にparseした2つのastは、内容が同じでもノードのオブジェクト
    同一性が異なるため、element_indexの突合は成立しない（既知の制約）。
    """
    text = "package P { part broken : NoSuchTypeAtAll; }"
    ast_a, _ = parse_sysml_with_semantic_model(text)
    _, model_b = parse_sysml_with_semantic_model(text)

    issues_from_a = lint_sysml(ast_a)
    element_index_from_b = build_element_index(model_b["nodes"])

    result = issues_from_a[0].to_dict(element_index_from_b)
    assert result["element_id"] is None


def test_rule_is_captured_from_the_actual_check_method_via_real_lint():
    """2026-09-03、Group1 b3b: ruleは`_check_*`等の実際のチェックメソッド名を
    呼び出し元フレームから自動取得する（linter_rules/*.pyの161箇所の
    LintIssue構築を1件も変更せずに済ませる設計。lint_issue.py参照）。"""
    text = "package P { part def A { attribute x : NoSuchType; } }"
    ast = parse_sysml_with_semantic_model(text)[0]
    issues = lint_sysml(ast)
    assert issues
    assert issues[0].to_dict()["rule"] == "_check_attribute_def"


def test_issue_with_no_node_returns_none_fields_even_with_index():
    text = "package P { part broken : NoSuchTypeAtAll; }"
    ast, model = parse_sysml_with_semantic_model(text)
    element_index = build_element_index(model["nodes"])

    from sysml_v2_checker_advanced.lint_issue import LintIssue

    issue = LintIssue(severity="error", message="synthetic", node=None)
    result = issue.to_dict(element_index)
    assert result["element_id"] is None
    assert result["source_range"] is None
