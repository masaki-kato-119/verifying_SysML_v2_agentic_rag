"""標準ライブラリの公開名の索引（library_index.json / library_index.py）のテスト。

索引の元データ（eval/sysml_reference/sysml.library）は gitignore 対象で、テスト環境に
あるとは限らない。ここでは同梱の索引だけを使い、リンターが頼る性質を固定する。
各名前の実在は 2026-09-24 に参照実装（0.62.0）で確かめたもの
（tests/fixtures/reference_conformance/s1_*.sysml も参照）。
"""

from sysml_v2_checker_advanced import library_index


def test_public_import_is_followed_transitively():
    # ISQ は ISQBase・ISQMechanics などを public import で再公開している
    assert library_index.resolve_qualified_name("ISQ::MassValue") is True
    assert library_index.resolve_qualified_name("ISQ::mass") is True


def test_missing_member_is_reported_as_missing():
    assert library_index.resolve_qualified_name("ISQ::Mass") is False
    assert library_index.resolve_qualified_name("ScalarValues::Bool") is False


def test_private_import_is_not_reexported():
    # ISQ は `private import ScalarValues::Real;` するだけ
    assert library_index.resolve_qualified_name("ISQ::Real") is False


def test_kerml_libraries_are_indexed():
    # KerML で書かれたライブラリ（SysML 用パーサーでは読めない）も索引に入っている
    for name in ("ScalarValues::Boolean", "ScalarValues::Real", "Base::Anything", "Occurrences::Occurrence"):
        assert library_index.resolve_qualified_name(name) is True, name


def test_short_names_and_quoted_names():
    assert library_index.resolve_qualified_name("SI::kg") is True
    assert library_index.resolve_qualified_name("SI::'m/s'") is True


def test_type_members_and_non_library_names_are_unverifiable():
    # パッケージ直下の名前まで確かめられれば、その先は True（検証しない）
    assert library_index.resolve_qualified_name("ISQ::MassValue::num") is True
    # 先頭がライブラリのパッケージでなければ判定しない
    assert library_index.resolve_qualified_name("MyPackage::Thing") is None


def test_nested_library_packages():
    assert library_index.resolve_qualified_name("KerML::Kernel") is True
    assert library_index.resolve_qualified_name("KerML::Kernel::Class") is True


def test_suggestion_prefers_value_types():
    assert library_index.suggest("ISQ::Mass")[0] == "ISQ::MassValue"
    assert library_index.suggest("ISQ::Speed")[0] == "ISQ::SpeedValue"
