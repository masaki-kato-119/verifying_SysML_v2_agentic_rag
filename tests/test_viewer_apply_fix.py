"""修正候補の適用（viewer/apply_fix.py、構想書§11 Phase D）。

Phase C の c4 は提示のみだった。ここはテキストを書き換える側なので、
**間違った位置に当ててモデルを壊さないこと**が最優先の検証対象。
"""

from __future__ import annotations

import pytest

from viewer.apply_fix import FixApplicationError, apply_fix_candidate


def test_end_offset_is_inclusive_so_the_last_character_is_reachable():
    """`source_range.end_offset` は終端の文字を**含む**（ANTLRの`stop.stop`）。

    `[start:end]` と書くと最後の1文字が落ちて `find` を見失う。2026-09-07に
    実際に読み違えた箇所なので、境界そのものをテストで固定する。
    """
    text = "package Q { part def A { part g = f::a; } }"
    start = text.index("f::a")
    # end_offset は最後の文字 'a' の位置（= start + 3）。排他なら start + 4。
    source_range = {"start_offset": start, "end_offset": start + 3}
    result = apply_fix_candidate(text, source_range, {"find": "f::a", "replace": "f.a"})
    assert "part g = f.a;" in result
    assert "f::a" not in result


def test_replacement_is_confined_to_the_source_range():
    """同じ文字列がファイル中の別の場所にあっても巻き込まない。

    範囲を限るのが `fix_candidates.py` が定めた契約そのもの。
    """
    text = "package Q { part x = f::a; part def A { part g = f::a; } }"
    second = text.rindex("f::a")
    source_range = {"start_offset": second, "end_offset": second + 3}
    result = apply_fix_candidate(text, source_range, {"find": "f::a", "replace": "f.a"})
    # 1つ目はそのまま、2つ目だけが置き換わる
    assert result.count("f::a") == 1
    assert result.index("f::a") < result.index("f.a")


def test_missing_target_raises_instead_of_silently_returning_the_input():
    """範囲内に `find` が無ければ例外。**黙って元のテキストを返さない**。

    「適用したのに何も変わらない」は利用者から見て成功と区別が付かず、
    Phase D が見せるべき差分も空になってしまう。
    """
    text = "package Q { part g = f.a; }"
    start = text.index("f.a")
    with pytest.raises(FixApplicationError, match="見つかりません"):
        apply_fix_candidate(text, {"start_offset": start, "end_offset": start + 2},
                            {"find": "f::a", "replace": "f.a"})


def test_advice_only_candidates_and_malformed_ranges_are_rejected():
    """書き換え案を持たない候補・壊れた範囲は適用しない。"""
    text = "package Q { }"
    with pytest.raises(FixApplicationError, match="書き換え案"):
        apply_fix_candidate(text, {"start_offset": 0, "end_offset": 1}, None)
    with pytest.raises(FixApplicationError, match="find/replace"):
        apply_fix_candidate(text, {"start_offset": 0, "end_offset": 1}, {"find": "x"})
    with pytest.raises(FixApplicationError, match="範囲外"):
        apply_fix_candidate(text, {"start_offset": 0, "end_offset": 999},
                            {"find": "p", "replace": "q"})
    with pytest.raises(FixApplicationError, match="start_offset"):
        apply_fix_candidate(text, {}, {"find": "p", "replace": "q"})


def test_applying_the_real_candidate_clears_the_finding():
    """実際の候補を当てると、その指摘が消えることまで確認する。

    候補が「もっともらしいだけ」でないことの検証。xpect の
    FeaturePath_Invalid.sysml と同じ形。
    """
    from sysml_v2_checker_advanced.antlr_transformer import parse_sysml_with_semantic_model
    from sysml_v2_checker_advanced.parser import lint_sysml
    from sysml_v2_checker_advanced.semantic_model import build_element_index

    text = "package Q { part def F { part a : A; } part f : F; part def A { part g = f::a; } }"
    ast, model = parse_sysml_with_semantic_model(text)
    issues = [i.to_dict(build_element_index(model["nodes"])) for i in lint_sysml(ast)]
    with_suggestion = [i for i in issues if i["suggestion"]]
    assert with_suggestion, "このテストは候補付きの指摘が出る前提"

    finding = with_suggestion[0]
    new_text = apply_fix_candidate(
        text, finding["source_range"], finding["suggestion"]["edit"]
    )
    assert lint_sysml(parse_sysml_with_semantic_model(new_text)[0]) == []


def test_applying_the_retype_candidate_clears_the_wrong_kind_finding():
    """d2 で増やした候補（種別違いの型付け）も、当てると指摘が消える。

    `find` が型名という短い文字列なので、`source_range` 内の先頭が宣言側の
    語に当たらないことまで含めて実経路で確かめる。
    """
    from sysml_v2_checker_advanced.antlr_transformer import parse_sysml_with_semantic_model
    from sysml_v2_checker_advanced.parser import lint_sysml
    from sysml_v2_checker_advanced.semantic_model import build_element_index

    text = (
        "package P { port def PO; port def PI; part def Q;"
        " interface def GoodIF { end a : PO; end b : PI; }"
        " part p { port a : PO; port b : PI; interface i : Q connect a to b; } }"
    )
    ast, model = parse_sysml_with_semantic_model(text)
    element_index = build_element_index(model["nodes"])
    findings = [
        i.to_dict(element_index)
        for i in lint_sysml(ast)
        if i.rule == "_check_interface_usage"
    ]
    assert len(findings) == 1

    new_text = apply_fix_candidate(
        text, findings[0]["source_range"], findings[0]["suggestion"]["edit"]
    )
    assert "interface i : GoodIF connect a to b;" in new_text
    after = [
        i
        for i in lint_sysml(parse_sysml_with_semantic_model(new_text)[0])
        if i.rule == "_check_interface_usage"
    ]
    assert after == []
