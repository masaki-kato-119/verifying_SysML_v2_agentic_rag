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
     ["A flow definition can have at most two ends.",  # Pilot 0.63.0 の文言
      "A flow definition can have at most two ends."]),
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


# 再定義の方向（Pilot 0.63.0 で確かめた組み合わせ、2026-10-23）: (説明, テキスト, 誤りの数)
_DIRECTION_CASES = [
    ('explicit in <- in', 'package D { private import ScalarValues::*; calc def C { in attribute x : Real; return r : Real; } calc c : C { in attribute :>> x = 1.0; } }', 0),
    ('explicit in <- out', 'package D { private import ScalarValues::*; calc def C { in attribute x : Real; return r : Real; } calc c : C { out attribute :>> x = 1.0; } }', 1),
    ('explicit in <- inout', 'package D { private import ScalarValues::*; calc def C { in attribute x : Real; return r : Real; } calc c : C { inout attribute :>> x = 1.0; } }', 1),
    ('explicit in <- none', 'package D { private import ScalarValues::*; calc def C { in attribute x : Real; return r : Real; } calc c : C {  attribute :>> x = 1.0; } }', 1),
    ('explicit out <- in', 'package D { private import ScalarValues::*; calc def C { out attribute x : Real; return r : Real; } calc c : C { in attribute :>> x = 1.0; } }', 1),
    ('explicit out <- out', 'package D { private import ScalarValues::*; calc def C { out attribute x : Real; return r : Real; } calc c : C { out attribute :>> x = 1.0; } }', 0),
    ('explicit out <- inout', 'package D { private import ScalarValues::*; calc def C { out attribute x : Real; return r : Real; } calc c : C { inout attribute :>> x = 1.0; } }', 1),
    ('explicit out <- none', 'package D { private import ScalarValues::*; calc def C { out attribute x : Real; return r : Real; } calc c : C {  attribute :>> x = 1.0; } }', 1),
    ('explicit inout <- in', 'package D { private import ScalarValues::*; calc def C { inout attribute x : Real; return r : Real; } calc c : C { in attribute :>> x = 1.0; } }', 0),
    ('explicit inout <- out', 'package D { private import ScalarValues::*; calc def C { inout attribute x : Real; return r : Real; } calc c : C { out attribute :>> x = 1.0; } }', 0),
    ('explicit inout <- inout', 'package D { private import ScalarValues::*; calc def C { inout attribute x : Real; return r : Real; } calc c : C { inout attribute :>> x = 1.0; } }', 0),
    ('explicit inout <- none', 'package D { private import ScalarValues::*; calc def C { inout attribute x : Real; return r : Real; } calc c : C {  attribute :>> x = 1.0; } }', 1),
    ('explicit none <- in', 'package D { private import ScalarValues::*; calc def C {  attribute x : Real; return r : Real; } calc c : C { in attribute :>> x = 1.0; } }', 0),
    ('explicit none <- out', 'package D { private import ScalarValues::*; calc def C {  attribute x : Real; return r : Real; } calc c : C { out attribute :>> x = 1.0; } }', 0),
    ('explicit none <- inout', 'package D { private import ScalarValues::*; calc def C {  attribute x : Real; return r : Real; } calc c : C { inout attribute :>> x = 1.0; } }', 0),
    ('explicit none <- none', 'package D { private import ScalarValues::*; calc def C {  attribute x : Real; return r : Real; } calc c : C {  attribute :>> x = 1.0; } }', 0),
    ('action redefine by name same dir', 'package D { item def I; action def S { in item a : I; out item b : I; } action s : S { in item :>> a; } }', 0),
    ('action positional ok', 'package D { item def I; action def S { in item a : I; out item b : I; } action s : S { in item a; out item b; } }', 0),
    ('action positional swapped', 'package D { item def I; action def S { in item a : I; out item b : I; } action s : S { out item b; in item a; } }', 2),
    ('action positional first only out', 'package D { item def I; action def S { in item a : I; out item b : I; } action s : S { out item b; } }', 1),
    ('action explicit redefine out b', 'package D { item def I; action def S { in item a : I; out item b : I; } action s : S { out item :>> b; } }', 1),
    ('calc no-dir binding', 'package D { private import ScalarValues::*; calc def C { in x : Real; return r : Real; } calc c : C { :>> x = 1.0; } }', 1),
    ('calc in binding', 'package D { private import ScalarValues::*; calc def C { in x : Real; return r : Real; } calc c : C { in :>> x = 1.0; } }', 0),
    ('calc positional in', 'package D { private import ScalarValues::*; calc def C { in x : Real; in y : Real; return r : Real; } calc c : C { in y = 2.0; } }', 0),
    ('part attr redef no dir', 'package D { private import ScalarValues::*; part def P { in attribute x : Real; } part p : P { attribute :>> x = 1.0; } }', 1),
    ('port in redef no dir', 'package D { private import ScalarValues::*; port def Q { in attribute x : Real; } part p { port q : Q { attribute :>> x = 1.0; } } }', 1),
    ('def specialization redef no dir', 'package D { private import ScalarValues::*; calc def C { in x : Real; return r : Real; } calc def C2 :> C { :>> x = 1.0; } }', 1),
    ('action def param redef no dir', 'package D { item def I; action def S { in item a : I; } action def T :> S { item :>> a; } }', 1),
    ('perform no dir', 'package D { item def I; action def S { in item a : I; } part p { perform action s : S { item :>> a; } } }', 1),
]


@pytest.mark.parametrize("name, text, n", _DIRECTION_CASES, ids=[c[0] for c in _DIRECTION_CASES])
def test_redefining_feature_direction(name, text, n):
    assert _messages(text) == ["Redefining feature must have a compatible direction"] * n


def test_conjugated_port_flips_directions():
    # 共役のポート（~P）の中では P の feature の方向が反転する（Pilot 0.63.0 で確認）
    text = ("package C { port def OutPort { out ref anout; in ref anin; } part p { "
            "port a : ~OutPort { in ref redefines anout; out ref redefines anin; } "
            "port b : ~OutPort { out ref redefines anout; } } }")
    assert _messages(text) == ["Redefining feature must have a compatible direction"]


def test_binding_override_and_constant_redefinition():
    # `=` / `:=` の値は上書きできない（default は上書きできる）。継承の途中のキーワードの無い束縛も見る。
    # constant の feature の再定義・部分集合は constant（Pilot 0.63.0 で確認、2026-10-23）
    text = 'package B {\n    private import ScalarValues::*;\n    part def P {\n        attribute a : Real = 1.0;\n        attribute b : Real default 1.0;\n        constant attribute c : Real default 1.0;\n        attribute d : Real;\n    }\n    part p1 : P {\n        :>> a = 2.0;\n        :>> b = 2.0;\n        :>> c = 2.0;\n        :>> d = 2.0;\n    }\n    part p2 : P {\n        attribute sub :> a;\n        attribute csub :> c;\n        constant attribute csub2 :> c;\n    }\n    part p3 :> p1 {\n        :>> d = 3.0;\n        :>> b = 3.0;\n    }\n}\n'
    binding = "Cannot override a binding feature value"
    constant = "Subsetting/redefining feature must be constant if subsetted/redefined feature is constant"
    assert _messages(text) == sorted([binding, constant, constant, binding, binding])
