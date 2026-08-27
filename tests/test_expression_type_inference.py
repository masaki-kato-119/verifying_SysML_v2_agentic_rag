"""sysml_v2_checker_advanced.expression_type_inference のユニットテスト。"""

from sysml_v2_checker_advanced.expression_type_inference import ExpressionTypeInference
from sysml_v2_checker_advanced.type_system import TypeSystemFoundation


def test_infer_literal_and_string_expression():
    ts = TypeSystemFoundation()
    inf = ExpressionTypeInference(ts)
    assert inf.infer_expression_type(42) == "Integer"
    assert inf.infer_expression_type(3.14) == "Real"
    assert inf.infer_expression_type(True) == "Boolean"
    assert inf.infer_expression_type('"hello"') == "String"


def test_infer_structured_literal_and_binary():
    ts = TypeSystemFoundation()
    inf = ExpressionTypeInference(ts)
    assert (
        inf.infer_expression_type({"type": "literal", "value": 10}) == "Integer"
    )
    add = {
        "type": "binary_operation",
        "operator": "+",
        "left": {"type": "literal", "value": 1},
        "right": {"type": "literal", "value": 2},
    }
    assert inf.infer_expression_type(add) == "Integer"


def test_infer_with_symbol_table():
    ts = TypeSystemFoundation()
    inf = ExpressionTypeInference(ts)
    t = inf.infer_expression_type(
        {"type": "variable_reference", "name": "x"},
        context={"x": "Integer"},
    )
    assert t == "Integer"


def test_infer_comparison_and_logical():
    ts = TypeSystemFoundation()
    inf = ExpressionTypeInference(ts)
    cmp_expr = {
        "type": "binary_operation",
        "operator": "==",
        "left": {"type": "literal", "value": 1},
        "right": {"type": "literal", "value": 2},
    }
    assert inf.infer_expression_type(cmp_expr) == "Boolean"
    log_expr = {
        "type": "binary_operation",
        "operator": "and",
        "left": {"type": "literal", "value": True},
        "right": {"type": "literal", "value": False},
    }
    assert inf.infer_expression_type(log_expr) == "Boolean"


def test_infer_unary_not():
    ts = TypeSystemFoundation()
    inf = ExpressionTypeInference(ts)
    u = {
        "type": "unary_operation",
        "operator": "not",
        "operand": {"type": "literal", "value": True},
    }
    assert inf.infer_expression_type(u) == "Boolean"
