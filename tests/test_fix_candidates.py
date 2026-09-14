"""修正候補（sysml_v2_checker_advanced/fix_candidates.py、Viewer Phase C c4）。

候補は「提示のみ」で、適用・再パース・再検証はPhase Dの範囲。したがって
ここで固定するのは「どう書き換える案かが機械可読で正しく出るか」と
「但し書きが必ず付いてくるか」の2点。
"""

from __future__ import annotations

from sysml_v2_checker_advanced.fix_candidates import (
    CAVEAT,
    FixCandidate,
    use_definition_of_expected_kind,
    use_dot_for_nesting,
)
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


def test_wrong_kind_typing_suggests_the_sole_definition_in_the_file():
    """種別違いの型付け（d2）。正しい種別の定義が1つだけなら書き換え先は一意。

    `interface i : Q` の `Q` は part def なので使えない。参照実装は
    `An interface must be typed by interface definitions.` を返す
    （`_type_is_wrong_kind` のdocstringに実測記録あり）。
    """
    text = (
        "package P { port def PO; port def PI; part def Q;"
        " interface def GoodIF { end a : PO; end b : PI; }"
        " part p { port a : PO; port b : PI; interface i : Q connect a to b; } }"
    )
    issues = [i for i in lint_sysml(parse_sysml(text)) if i.rule == "_check_interface_usage"]
    assert len(issues) == 1

    suggestion = issues[0].to_dict()["suggestion"]
    assert suggestion["edit"] == {"find": "Q", "replace": "GoodIF"}
    assert suggestion["caveat"] == CAVEAT


def test_wrong_kind_typing_has_no_suggestion_when_definitions_compete():
    """正しい種別の定義が2つ以上あるなら、どれを指したかったのかは決まらない。

    候補を出さないだけで、指摘自体は従来どおり出る。
    """
    text = (
        "package P { part def Q; interface def IF1; interface def IF2;"
        " part p { interface i : Q; } }"
    )
    issues = [i for i in lint_sysml(parse_sysml(text)) if i.rule == "_check_interface_usage"]
    assert len(issues) == 1
    assert issues[0].to_dict()["suggestion"] is None


def test_allocation_wrong_kind_typing_shares_the_same_candidate():
    """allocation 側も同じ形（ルール実装も候補の組み立ても共有している）。"""
    text = (
        "package P { part def B; part def C;"
        " allocation def L2P { end x : B[1]; end y : C[1]; }"
        " part p { part b : B; part c : C; allocation x : B allocate b to c; } }"
    )
    issues = [i for i in lint_sysml(parse_sysml(text)) if i.rule == "_check_allocation_usage"]
    assert len(issues) == 1
    assert issues[0].to_dict()["suggestion"]["edit"] == {"find": "B", "replace": "L2P"}


def test_wrong_kind_candidate_is_dropped_when_find_would_hit_the_declaration():
    """`find` が型節より前に当たってしまう形では候補を作らない。

    `edit` の契約は「source_range 内の**最初の** find を置き換える」。
    型名が宣言のキーワードや usage 名の一部にも現れると、型ではなく
    そちらを書き換えてしまう（`interface` の中の `e` など）。
    """
    assert use_definition_of_expected_kind("i", "e", "GoodIF", "interface definition") is None
    assert use_definition_of_expected_kind("Qx", "Q", "GoodIF", "interface definition") is None
    assert (
        use_definition_of_expected_kind("i", "Q", "GoodIF", "interface definition") is not None
    )


def test_package_level_redefinition_advises_subsets_without_an_edit():
    """`redefines` → `subsets` は**助言のみ**にする（d2）。

    直し方は参照実装で実測済み（`subsets` はクリーン）だが、意味が変わる
    ので当てられる形にはしない。加えてASTは `:>>` と `redefines` を同じ
    kind へ正規化していて、元の綴りが分からない以上 `find` も作れない。
    理由は `subset_instead_of_redefine` のdocstring参照。
    """
    text = "package P { part def W; part wheel : W; part wheel1 : W redefines wheel; }"
    issues = [
        i
        for i in lint_sysml(parse_sysml(text))
        if i.rule == "_check_package_level_feature_redefinition"
    ]
    assert len(issues) == 1

    suggestion = issues[0].to_dict()["suggestion"]
    assert suggestion["edit"] is None
    assert "subsets" in suggestion["detail"]
    assert suggestion["caveat"] == CAVEAT
