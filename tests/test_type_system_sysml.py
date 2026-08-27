"""sysml_v2_checker_advanced.type_system のユニットテスト。"""

import pytest

from sysml_v2_checker_advanced.type_system import TypeCategory, TypeInfo, TypeSystemFoundation


def test_type_info_post_init_lists():
    t = TypeInfo(name="T", category=TypeCategory.PART)
    assert t.specializations == []
    assert t.generalizations == []


def test_register_and_get():
    ts = TypeSystemFoundation()
    ts.register_type(TypeInfo(name="MyPart", category=TypeCategory.PART, namespace="ns"))
    assert "MyPart" in ts.types


def test_register_duplicate_same_namespace_raises():
    ts = TypeSystemFoundation()
    ts.register_type(TypeInfo(name="Dup", category=TypeCategory.ITEM, namespace="n"))
    with pytest.raises(ValueError):
        ts.register_type(TypeInfo(name="Dup", category=TypeCategory.PART, namespace="n"))


def test_is_compatible_builtin():
    ts = TypeSystemFoundation()
    assert ts.is_compatible_types("String", "String") is True
