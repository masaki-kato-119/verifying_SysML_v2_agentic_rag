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
}

# まだ一致しないもの → 担当タスク
PENDING = {
    "r02_builtin_without_import.sysml": "e2_builtin_and_unit_import_visibility",
    "r03_unit_without_import.sysml": "e2_builtin_and_unit_import_visibility",
    "r04_flow_end_not_feature_chain.sysml": "e4_flow_end_resolution",
    "r05_flow_end_not_accessible.sysml": "e4_flow_end_resolution",
    "r06_undefined_trigger.sysml": "e5_trigger_and_event_reference",
    "r07_event_not_occurrence.sysml": "e5_trigger_and_event_reference",
    "r08_import_without_visibility.sysml": "e3_grammar_conformance",
    "r09_actor_at_package_level.sysml": "e3_grammar_conformance",
    "r10_constraint_result_semicolon.sysml": "e3_grammar_conformance",
    "r11_transition_body_accept_valid.sysml": "e3_grammar_conformance",
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
            marks.append(pytest.mark.xfail(strict=True, reason=f"未対応: {PENDING[name]}"))
        yield pytest.param(name, expected, id=Path(name).stem, marks=marks)


def test_every_fixture_has_an_expectation():
    on_disk = {p.name for p in FIXTURE_DIR.glob("*.sysml")}
    assert on_disk == set(REFERENCE_HAS_ERROR), "フィクスチャと期待値の表が食い違っている"
    assert set(PENDING) <= set(REFERENCE_HAS_ERROR)


@pytest.mark.parametrize("name, reference_has_error", list(_params()))
def test_error_presence_matches_reference(name: str, reference_has_error: bool):
    text = (FIXTURE_DIR / name).read_text(encoding="utf-8")
    assert _self_has_error(text) == reference_has_error
