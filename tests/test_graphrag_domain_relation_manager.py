"""graphrag.domain_relation_manager のドメイン別関係語彙解決のテスト。優先度: GraphRAG。

UniversalRelationManager/DomainRelationManagerは文字列照合だけの純粋関数的な
プラグインレジストリで、これまでテストが無かった。完全一致優先・部分一致
フォールバック、汎用関係がドメイン特化関係より優先される検索順序、
ドメイン切替・カスタム関係の追加/削除を検証する。

バグ: get_relations/get_domain_relations/get_all_relationsが`dict.copy()`のみで
返しており、内側のlistはクラス変数と共有されたままだった。呼び出し側が返り値の
リストをin-place変更すると、UNIVERSAL_RELATIONS/DOMAIN_RELATIONSというクラス
変数（全インスタンス・プロセス全体で共有）が永続的に汚染されてしまう。
各メソッドでリストも複製するように修正した（下記の*_returns_a_copy系テストが
回帰テスト）。
"""

import pytest
from graphrag.domain_relation_manager import (
    DomainRelationManager,
    UniversalRelationManager,
)

# ---- UniversalRelationManager ----


def test_get_relations_returns_a_copy_not_the_class_dict():
    manager = UniversalRelationManager()

    relations = manager.get_relations()
    relations["is-a"].append("mutated")

    assert "mutated" not in manager.UNIVERSAL_RELATIONS["is-a"]


@pytest.mark.parametrize(
    "vocab,expected",
    [
        ("is a", "is-a"),
        ("IS AN", "is-a"),
        ("  type  ", "is-a"),
        ("part of", "part-of"),
        ("utilizes", "uses"),
        ("requires", "depends-on"),
        ("define", "defines"),
        ("realizes", "implements"),
    ],
)
def test_get_relation_type_exact_match(vocab, expected):
    manager = UniversalRelationManager()

    assert manager.get_relation_type(vocab) == expected


def test_get_relation_type_falls_back_to_substring_match():
    manager = UniversalRelationManager()

    # "instance-of-something" は語彙 "instance-of" を部分文字列として含む
    assert manager.get_relation_type("instance-of-something") == "is-a"


def test_get_relation_type_returns_none_for_unknown_vocabulary():
    manager = UniversalRelationManager()

    assert manager.get_relation_type("completely unrelated phrase") is None


# ---- DomainRelationManager: get_all_relations ----


def test_default_domain_is_universal_and_has_no_domain_extras():
    manager = DomainRelationManager()

    all_relations = manager.get_all_relations()

    assert all_relations == UniversalRelationManager().get_relations()


def test_get_all_relations_merges_domain_specific_relations():
    manager = DomainRelationManager(domain="sysml_v2")

    all_relations = manager.get_all_relations()

    assert "has_parameter" in all_relations
    assert "is-a" in all_relations  # 汎用関係も維持される


def test_get_all_relations_includes_custom_relations():
    manager = DomainRelationManager()
    manager.add_custom_relations({"my-custom": ["foo", "bar"]})

    assert manager.get_all_relations()["my-custom"] == ["foo", "bar"]


# ---- switch_domain ----


@pytest.mark.parametrize("domain", ["sysml_v2", "software_architecture", "business_process", "universal"])
def test_switch_domain_accepts_known_domains(domain):
    manager = DomainRelationManager()

    manager.switch_domain(domain)

    assert manager.active_domain == domain


def test_switch_domain_raises_for_unknown_domain():
    manager = DomainRelationManager()

    with pytest.raises(ValueError, match="Unknown domain"):
        manager.switch_domain("no_such_domain")


# ---- custom relations management ----


def test_add_and_remove_custom_relations():
    manager = DomainRelationManager()
    manager.add_custom_relations({"custom-a": ["x"], "custom-b": ["y"]})

    manager.remove_custom_relations(["custom-a"])

    assert "custom-a" not in manager.custom_relations
    assert "custom-b" in manager.custom_relations


def test_remove_custom_relations_ignores_unknown_relation_type():
    manager = DomainRelationManager()

    manager.remove_custom_relations(["never-added"])  # should not raise

    assert manager.custom_relations == {}


# ---- get_relation_type: search order and domain-specific matches ----


def test_get_relation_type_prefers_universal_over_domain_specific():
    """汎用関係が先に照合されるため、"requires"は('depends-on'であり、
    sysml_v2の'requires_input'ではない。"""
    manager = DomainRelationManager(domain="sysml_v2")

    assert manager.get_relation_type("requires") == "depends-on"


def test_get_relation_type_finds_domain_specific_vocabulary():
    manager = DomainRelationManager(domain="sysml_v2")

    assert manager.get_relation_type("splits into") == "splits_into"


def test_get_relation_type_matches_domain_relation_type_name_directly():
    manager = DomainRelationManager(domain="sysml_v2")

    assert manager.get_relation_type("has_parameter") == "has_parameter"


def test_get_relation_type_returns_none_when_domain_has_no_match():
    manager = DomainRelationManager(domain="software_architecture")

    assert manager.get_relation_type("splits into") is None


def test_get_relation_type_finds_custom_relation_after_universal_and_domain():
    manager = DomainRelationManager(domain="universal")
    manager.add_custom_relations({"my-custom": ["gizmo"]})

    assert manager.get_relation_type("gizmo") == "my-custom"


def test_get_relation_type_returns_none_when_nothing_matches():
    manager = DomainRelationManager(domain="sysml_v2")

    assert manager.get_relation_type("xyzzy_no_match") is None


# ---- get_domain_relations / get_available_domains ----


def test_get_domain_relations_returns_copy_for_known_domain():
    manager = DomainRelationManager(domain="sysml_v2")

    relations = manager.get_domain_relations()
    relations["has_parameter"].append("mutated")

    assert "mutated" not in manager.DOMAIN_RELATIONS["sysml_v2"]["has_parameter"]


def test_get_domain_relations_is_empty_for_universal_domain():
    manager = DomainRelationManager(domain="universal")

    assert manager.get_domain_relations() == {}


def test_get_available_domains_lists_universal_and_all_registered_domains():
    manager = DomainRelationManager()

    domains = manager.get_available_domains()

    assert domains == ["universal", "sysml_v2", "software_architecture", "business_process"]
