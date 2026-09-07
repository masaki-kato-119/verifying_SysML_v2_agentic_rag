"""修正候補（sysml_v2_checker_advanced/fix_candidates.py、Viewer Phase C c4）。

候補は「提示のみ」で、適用・再パース・再検証はPhase Dの範囲。したがって
ここで固定するのは「どう書き換える案かが機械可読で正しく出るか」と
「但し書きが必ず付いてくるか」の2点。
"""

from __future__ import annotations

from sysml_v2_checker_advanced.fix_candidates import CAVEAT, FixCandidate, use_dot_for_nesting
from sysml_v2_checker_advanced.parser import lint_sysml, parse_sysml


def test_candidate_without_an_edit_still_carries_its_caveat():
    """書き換え案を持たない助言だけの候補でも、但し書きは必ず付く。"""
    candidate = FixCandidate(title="題", detail="説明").to_dict()
    assert candidate["edit"] is None
    assert candidate["caveat"] == CAVEAT


def test_use_dot_for_nesting_rewrites_only_the_flagged_separator():
    """package限定の`::`は残し、指摘された境界だけを`.`に変える。

    `Pkg::a::b` の先頭の `::` は名前空間限定として正当なので、ここまで
    `.` にしてしまうと別の誤りを作る。
    """
    segments = [("Pkg", None), ("a", "::"), ("b", "::")]
    candidate = use_dot_for_nesting(segments, 2)
    assert candidate is not None
    assert candidate.to_dict()["edit"] == {"find": "Pkg::a::b", "replace": "Pkg::a.b"}


def test_use_dot_for_nesting_returns_none_for_out_of_range_positions():
    """位置が復元できないときは候補を作らない（もっともらしい嘘を出さない）。"""
    segments = [("A", None), ("x", "::")]
    assert use_dot_for_nesting(segments, 0) is None
    assert use_dot_for_nesting(segments, 5) is None


def test_accessible_feature_path_finding_carries_the_rewrite():
    """実lint経由。FeaturePath_Invalid.sysml と同じ形。

    XPECT注釈が指示している修正（`f::a` を dot notation にする）と、
    候補の書き換え案が一致することを確認する。
    """
    text = (
        "package Q { part def F { part a : A; } part f : F; "
        "part def A { part g = f::a; } }"
    )
    ast = parse_sysml(text)
    issues = [i for i in lint_sysml(ast) if i.rule == "_check_accessible_feature_paths"]
    assert issues, "このテストは accessible feature path ルールが発火する前提"

    suggestion = issues[0].to_dict()["suggestion"]
    assert suggestion["edit"] == {"find": "f::a", "replace": "f.a"}
    assert suggestion["caveat"] == CAVEAT


def test_rules_without_a_deterministic_rewrite_have_no_suggestion():
    """候補を付けていないルールは None のまま。

    全ルールを埋めない方針（fix_candidates.py のモジュールdocstring）を固定する。
    もっともらしいだけの候補は指摘そのものの信頼を削るため、書き換え方が
    一意に決まらないルールには付けない。
    """
    ast = parse_sysml("package P { part broken : NoSuchTypeAtAll; }")
    issues = lint_sysml(ast)
    assert issues
    assert all(issue.to_dict()["suggestion"] is None for issue in issues)
