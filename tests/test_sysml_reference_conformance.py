"""公式実装（OMG SysML v2 Pilot Implementation 0.62.0）との判定一致の回帰テスト。

tests/fixtures/reference_conformance/ の各ファイルについて、「エラーの有無」が
公式実装と一致することを確かめる。期待値は scripts/probe_reference.py で公式実装に
与えて実測したもの（エラー文言や件数までは合わせない）。

r01〜r12 はフェーズ2評価（LLMにSysML v2を書かせ、公式実装で判定した評価）の
最小再現で、出典は SysMLv2_pilot/sysml-mcp-server/eval/phase2/repro/。
s1* などは各項目の境界を公式実装で測ったもの。
まだ一致しないものは、対応するBlackboardタスク
（plan: sysml_checker_false_negatives）を reason に書いて strict な xfail にしてある。
直ると XPASS でこのテストが落ちるので、そのときは PENDING から外すこと。

公式実装を呼ばずに済むよう、期待値はこのファイルに固定している。フィクスチャを
足したら probe_reference.py で実測し、REFERENCE_HAS_ERROR に書き足すこと。
"""

from pathlib import Path

import pytest

from sysml_v2_checker_advanced.parser import lint_sysml, parse_sysml

FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures" / "reference_conformance"

# ファイル名 → 公式実装がエラーを出すか（2026-09-24 実測）
REFERENCE_HAS_ERROR = {
    "r01_lib_member_not_found.sysml": True,  # Couldn't resolve reference to Type 'ISQ::Mass'.
    "r02_builtin_without_import.sysml": True,  # Couldn't resolve reference to Type 'Boolean'.
    "r03_unit_without_import.sysml": True,  # Couldn't resolve reference to Element 'kg'.
    "r04_flow_end_not_feature_chain.sysml": True,  # Cannot identify flow end (use dot notation)
    "r05_flow_end_not_accessible.sysml": True,  # Couldn't resolve reference to Feature 'addSugar'.
    "r06_undefined_trigger.sysml": True,  # Couldn't resolve reference to Type 'TimerEvent'.
    "r07_event_not_occurrence.sysml": True,  # Must reference an occurrence.
    "r08_import_without_visibility.sysml": True,  # mismatched input 'import' expecting '}'
    "r09_actor_at_package_level.sysml": True,  # mismatched input 'actor' expecting '}'
    "r10_constraint_result_semicolon.sysml": True,  # extraneous input ';' expecting '}'
    "r11_transition_body_accept_valid.sysml": False,
    "r12_correct_forms_valid.sysml": False,
    # e1（S1）の境界。標準ライブラリの修飾名・import・subsets/redefines（2026-09-24 実測）
    "s1a_qualified_missing.sysml": True,  # Couldn't resolve reference to Type 'ISQ::Mass'.
    "s1b_qualified_exists_without_import.sysml": False,
    "s1c_private_import_not_reexported.sysml": True,  # Couldn't resolve reference to Type 'ISQ::Real'.
    "s1d_import_missing_member.sysml": True,  # Couldn't resolve reference to Membership 'ISQ::Mass'.
    "s1e_import_missing_namespace_wildcard.sysml": True,  # Couldn't resolve reference to Namespace 'ISQ::Nope'.
    "s1f_import_def_members_wildcard.sysml": False,
    "s1g_alias_member.sysml": False,
    "s1h_subsets_library_feature.sysml": False,
    "s1i_subsets_missing_library_feature.sysml": True,  # Couldn't resolve reference to Feature 'ISQ::massX'.
    "s1j_type_member_path.sysml": False,  # 型のメンバーまで降りる修飾名は検証不能として通す
    "s1k_nested_package.sysml": False,
    "s1l_quoted_unit.sysml": False,
    "s1m_kerml_member.sysml": True,  # Couldn't resolve reference to Type 'ScalarValues::Bool'.
    "s1n_redefines_missing.sysml": True,  # Couldn't resolve reference to Feature 'ISQ::massY'.
    "s1o_specializes_missing_def.sysml": True,  # Couldn't resolve reference to Classifier 'Parts::PartX'.
    "s1p_specializes_existing_def.sysml": False,
    # e2（S2）の境界。import していない組み込み型・単位、import の見え方（2026-09-24 実測）
    "s2a_builtin_wildcard_import.sysml": False,
    "s2b_builtin_member_import.sysml": False,
    "s2c_builtin_qualified.sysml": False,
    "s2d_outer_import_visible_in_nested.sysml": False,
    "s2e_sibling_import_not_visible.sysml": True,  # Couldn't resolve reference to Type 'Boolean'.
    "s2f_reexport_via_local_package.sysml": False,
    "s2g_isq_does_not_export_real.sysml": True,  # Couldn't resolve reference to Type 'Real'.
    "s2h_isq_exports_value_types.sysml": False,
    "s2i_unit_with_si_import.sysml": False,
    "s2j_unit_qualified.sysml": False,
    "s2k_unit_partly_qualified.sysml": True,  # Couldn't resolve reference to Element 's'.
    "s2l_unknown_name_with_library_import.sysml": True,  # Couldn't resolve reference to Type 'Nope'.
    "s2m_library_feature_unqualified.sysml": False,
    "s2n_import_inside_definition.sysml": False,
    "s2o_local_unit.sysml": False,
    "s2p_recursive_import.sysml": False,
    "s2q_builtin_used_in_def_specialization.sysml": True,  # Couldn't resolve reference to Classifier 'Boolean'.
    "s2r_builtin_in_param.sysml": True,  # Couldn't resolve reference to Type 'Real'.
    "s2s_uscustomary_unit.sysml": False,
    "s2t_import_after_use.sysml": False,
    # e3（S6・S7）の境界。import の可視性、actor の置き場所、結果の式の `;`、遷移の本体（2026-09-24 実測）
    "g1a_bare_import_top_level.sysml": True,  # missing EOF at 'import'
    "g1b_bare_import_in_part_def.sysml": True,  # mismatched input 'import' expecting '}'
    "g1c_public_import_ok.sysml": False,
    "g2a_actor_in_part_def.sysml": True,  # mismatched input 'actor' expecting '}'
    "g2b_actor_in_use_case_def.sysml": True,  # Subject must be first parameter.
    "g2c_actor_in_requirement_def.sysml": True,  # Subject must be first parameter.
    "g2d_actor_in_analysis_def.sysml": True,  # Subject must be first parameter.
    "g2e_actor_in_use_case_usage.sysml": True,  # Subject must be first parameter.
    "g2f_actor_in_part_usage.sysml": True,  # mismatched input 'actor' expecting '}'
    "g2g_actor_in_verification_def.sysml": True,  # Subject must be first parameter.
    "g2h_actor_in_action_def.sysml": True,  # no viable alternative at input 'actor'
    "g3a_calc_result_semicolon.sysml": True,  # extraneous input ';' expecting '}'
    "g3b_calc_result_no_semicolon.sysml": False,
    "g3c_constraint_usage_semicolon.sysml": True,  # extraneous input ';' expecting '}'
    "g3d_assert_constraint_semicolon.sysml": True,  # extraneous input ';' expecting '}'
    "g3e_require_constraint_semicolon.sysml": True,  # no viable alternative at input 'require'
    "g3f_expression_not_last.sysml": True,  # mismatched input ';' expecting '}'
    "g3g_return_semicolon.sysml": False,
    "g4a_transition_body_accept.sysml": False,
    "g4b_transition_body_action.sysml": False,
    "g4c_transition_body_doc.sysml": False,
    "g4d_transition_body_attribute.sysml": False,
}

# まだ一致しないもの → 担当タスク（または一致させない理由）
PENDING = {
    "r04_flow_end_not_feature_chain.sysml": "e4_flow_end_resolution",
    "r05_flow_end_not_accessible.sysml": "e4_flow_end_resolution",
    "r06_undefined_trigger.sysml": "e5_trigger_and_event_reference",
    "r07_event_not_occurrence.sysml": "e5_trigger_and_event_reference",
    # 既知の近似（直す予定は無い）: import の置き場所を区別せず、ファイル内の
    # どこかで import した名前はファイル全体で見えるとみなす。参照実装は兄弟の
    # パッケージの import を見せない。linter._collect_library_visible_names 参照
    "s2e_sibling_import_not_visible.sysml": "近似: import の名前空間を区別しない",
}


def _self_has_error(text: str) -> bool:
    """MCP ツール lint_sysml_text と同じ経路での判定。"""
    ast = parse_sysml(text)
    if ast.get("type") == "error":
        return True
    return any(issue.severity == "error" for issue in lint_sysml(ast))


def _params():
    for name, expected in sorted(REFERENCE_HAS_ERROR.items()):
        marks = []
        if name in PENDING:
            marks.append(pytest.mark.xfail(strict=True, reason=PENDING[name]))
        yield pytest.param(name, expected, id=Path(name).stem, marks=marks)


def test_every_fixture_has_an_expectation():
    on_disk = {p.name for p in FIXTURE_DIR.glob("*.sysml")}
    assert on_disk == set(REFERENCE_HAS_ERROR), "フィクスチャと期待値の表が食い違っている"
    assert set(PENDING) <= set(REFERENCE_HAS_ERROR)


@pytest.mark.parametrize("name, reference_has_error", list(_params()))
def test_error_presence_matches_reference(name: str, reference_has_error: bool):
    text = (FIXTURE_DIR / name).read_text(encoding="utf-8")
    assert _self_has_error(text) == reference_has_error
