"""参照実装の個別の検証ルール（sysml_v2_checker_advanced/validation_rules.py、段階 D）。

どの例も参照実装の xpect テスト（validation/invalid）か、Pilot 0.62.0 で確かめた形。
"""

import pytest

from sysml_v2_checker_advanced.antlr_transformer import parse_sysml_with_semantic_model_recovering
from sysml_v2_checker_advanced.validation_rules import validation_violations


def _messages(text: str) -> list:
    ast, _model, errors = parse_sysml_with_semantic_model_recovering(text)
    assert errors == []
    return sorted(message for _node, message in validation_violations(ast))


@pytest.mark.parametrize("text, expected", [
    # objective は 1 つまで。型・特化の先が持つ objective も数える（CaseSubjectObjective_Invalid）
    ("package Q { case def C { objective o1; objective o2; } case c : C { objective o3; } "
     "case def C2 { objective o4; } }",
     ["Only one objective is allowed.", "Only one objective is allowed."]),
    # enum の attribute は型を 1 つだけ
    ("package Q { enum def E { a; } attribute def A; attribute x : E, A; attribute y : A; }",
     ["An enumeration attribute cannot have more than one type."]),
    # flow def の端は 2 つまで（継承した端も数える）
    ("package Q { abstract flow def H { end a; } flow def I :> H { end a; end b; end c; } flow def J :> I; "
     "flow def K { end a; end b; } }",
     ["A flow connection definition can have at most two ends.",
      "A flow connection definition can have at most two ends."]),
    # interface の端は port
    ("package Q { interface def IF { end port a; end part b; } }", ["An interface end must be a port."]),
    # port def と port の中の port 以外の usage は ref
    ("package Q { part def B; port def PD { part b2 : B; ref part b3 : B; attribute x; port pp; } "
     "part q { port pu : PD { part b4 : B; } } }",
     ["Nested usages in a port usage (other than ports) must be referential.",
      "Owned usages of a port definition (other than ports) must be referential."]),
    # filter の条件とメタデータの値はモデルの水準で評価できる式。new はよい（verified/structure の @Icon）
    ("package Q { metadata def A { attribute z; } calc def f { in x; } "
     "filter f((as A).z); filter new A(); @A { z = f(1); } @A { z = new A(); } }",
     ["Must be model-level evaluable", "Must be model-level evaluable", "Must have a Boolean result"]),
    # individual def は 1 つまで
    ("package Q { individual part def A1; individual part def B1; individual two : A1, B1; }",
     ["At most one individual definition is allowed."]),
])
def test_validation_violations(text, expected):
    assert _messages(text) == sorted(expected)
