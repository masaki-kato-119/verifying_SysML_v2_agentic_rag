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
    assert set(result.keys()) == {
        "severity", "message", "rule", "element_id", "source_range", "confidence",
        "suggestion",
    }
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


def test_rule_skips_local_helper_functions_inside_a_check_method():
    """2026-09-07: `_check_*` の内側に定義した再帰走査のローカル関数（`walk`）
    から LintIssue を作っても、ruleは `walk` ではなく外側の `_check_*` になる。

    730件コーパスのルール別集計で、実際に2つのルールが `walk` へ潰れているのを
    検出した。ruleは confidence テーブルのキーであり Viewer の Finding の
    同一性判定にも使われるため、名前が一意でないと成立しない。
    """
    # どちらも `walk` というローカル関数の中で LintIssue を構築するルール。
    verify_placement = "package P { requirement def R { verify r; } }"
    ast = parse_sysml_with_semantic_model(verify_placement)[0]
    rules = {issue.to_dict()["rule"] for issue in lint_sysml(ast)}
    assert "_check_verify_requirement_placement" in rules
    assert "walk" not in rules

    package_redefine = "package P { part wheel; part wheel1 redefines wheel; }"
    ast = parse_sysml_with_semantic_model(package_redefine)[0]
    rules = {issue.to_dict()["rule"] for issue in lint_sysml(ast)}
    assert "_check_package_level_feature_redefinition" in rules
    assert "walk" not in rules


def test_confidence_comes_with_its_basis_and_caveat_not_a_bare_number():
    """2026-09-07、Viewer Phase C C1: confidenceは実測テーブルから引く。

    値だけを返さないのが要点。`value` は「参照実装も同じファイルを不正と
    判定した割合」であって「同じ箇所を同じ理由で指摘した割合」ではないため、
    呼び出し側が数値だけを切り出して提示できないよう basis/caveat/内訳を
    必ず添えて返す。
    """
    text = "package P { import NoSuchPackage::NoSuchThing; }"
    ast = parse_sysml_with_semantic_model(text)[0]
    issues = [i for i in lint_sysml(ast) if i.rule == "_check_import"]
    assert issues, "このテストは_check_importが発火する前提"

    confidence = issues[0].to_dict()["confidence"]
    assert set(confidence) == {
        "value", "sole_agree", "sole_disagree", "basis", "caveat", "measured_at",
    }
    assert 0.0 <= confidence["value"] <= 1.0
    assert confidence["sole_agree"] + confidence["sole_disagree"] >= 3
    assert confidence["basis"] and confidence["caveat"]


def test_confidence_is_none_for_rules_without_measurement():
    """測っていないルールは推定で埋めず None のままにする。

    「未測定」と「測ったが低い」を混同させないための約束であり、
    表示側（viewer/frontend/app.js）はこの区別を出し分ける。
    """
    from sysml_v2_checker_advanced.lint_issue import LintIssue

    issue = LintIssue(severity="warning", message="計測対象外のルール")
    assert issue.to_dict()["rule"] == "test_confidence_is_none_for_rules_without_measurement"
    assert issue.to_dict()["confidence"] is None


def test_issue_with_no_node_returns_none_fields_even_with_index():
    text = "package P { part broken : NoSuchTypeAtAll; }"
    ast, model = parse_sysml_with_semantic_model(text)
    element_index = build_element_index(model["nodes"])

    from sysml_v2_checker_advanced.lint_issue import LintIssue

    issue = LintIssue(severity="error", message="synthetic", node=None)
    result = issue.to_dict(element_index)
    assert result["element_id"] is None
    assert result["source_range"] is None
