"""3 つ目の held-out（研究に使っていない公開リポジトリ）で見つかった文法の穴・名前解決・個別の規則
（2026-11-05、eval/pilot_parity/BASELINE.md の「3 つ目の held-out の修正」）。

どの例も Pilot 0.63.0（scripts/probe_reference.py）に通し、エラーの有無と行・文言が同じになることを確かめた形。
"""

import pytest

from sysml_v2_checker_advanced.antlr_transformer import parse_sysml_antlr
from sysml_v2_checker_advanced.semantic_model import lint_text_with_locations


def _errors(text: str) -> list:
    ast, _issues, dicts = lint_text_with_locations(text)
    assert ast.get("type") != "error", ast.get("message")
    return sorted((d["line"], d["message"].split("。")[0].split(" 型の種類")[0].split(" 標準")[0])
                  for d in dicts if d["severity"] == "error")


# --- 文法（参照実装は構文エラーを出さない） ------------------------------------------------

@pytest.mark.parametrize("line", [
    "item <'DS-1'> credentials : K;",
    "enum def E { enum <S> 'spoofing'; enum 'MI-1'; }",
    "assert constraint <'C-1'> c1 { }",
    "flow <'DF-01'> f of K from a.b to c.d;",
    "part <p1>;",
    "abstract #m part def D { }",
    "derived #m attribute g : ScalarValues::Integer;",
    "#m #n occurrence <'F-2'> o[0..1] { }",
    "requirement x; requirement def D { end #m requirement ::> x; }",
    "view v : StandardViewDefinitions::GeneralView { }",
    "action def G; part def A { action g : G[1]; } part b : A { perform action :>> g[1]; }",
    "perform action g redefines g : G, H;",
    "requirement def R { frame Q::c; frame c { doc /* x */ } }",
    "state def S { state a { state b; } state c; transition a.b then c; transition Actions::Action::start then c; }",
    "view v { render rendering : R :>> asTableCell { } render rendering :>> asTable; }",
    "attribute a = (x as T).value ?? \"missing\";",
    "part p { private doc d /* text */ }",
    "metadata def M { ref item :>> f = owner.metadata; }",
    "action a { send \"Command\" via p; }",
    "@tag1 : T { }",
    "view v { expose d::c::*[istype SysML::PortUsage]; filter istype SysML::PartUsage; }",
    "calc c { s->ControlFunctions::forAll({in o; o istype Feature}) }",
    "abstract flow f [*] : T;",
    "attribute t : Real ['°C'];",
    "viewpoint vp { view def V { } }",
    "part def C { part p; } part c : C { connection : M connect p ::> e to q ::> q; }",
    "port boundPort : SignalPort = sourcePort;",
    "enum e [*] : E;",
    "assert constraint c : T [*] :> d { }",
    "enum def E { enum Development = 1 { doc /* x */ } }",
])
def test_grammar_accepts(line):
    ast = parse_sysml_antlr("package P {\n" + line + "\n}\n")
    assert ast.get("type") != "error", ast.get("message")


def test_short_names_resolve():
    text = """package P {
    enum def E { enum <S> 'spoofing'; enum 'MI-1'; }
    attribute x : E = E::S;
    attribute y : E = E::'MI-1';
    attribute z : E = E::spoofing;
    item def K;
    part p { item <'DS-1'> cred : K; }
    part q { ref item r :> p.'DS-1'; }
}
"""
    assert _errors(text) == []


def test_transition_without_first_names_the_source():
    # `first` の無い形の名前に見えるものは始点（参照実装は未解決を出す。自作は遷移の規則の文言）
    errors = _errors("package P { state def S { state off; transition initial then off; } }")
    assert len(errors) == 1 and errors[0][0] == 1 and "'initial'" in errors[0][1]


# --- 名前解決 ------------------------------------------------------------------------------------

def test_unresolved_prefix_metadata_does_not_hide_the_body():
    text = """package P {
    private import PLEML::*;
    #featureConfiguration occurrence c {
        #feature occurrence :>> platformStack[1];
    }
}
"""
    errors = _errors(text)
    assert (4, "Couldn't resolve reference to Feature 'platformStack'.") in errors
    assert (4, "Couldn't resolve reference to Type 'feature'.") in errors


def test_dependency_ends_are_checked():
    text = """package P {
    part a; part c { part d; }
    dependency a to Q::'x';
    dependency a to c.d;
    #refinement dependency a to a;
}
"""
    errors = _errors(text)
    assert (3, "Couldn't resolve reference to Element 'Q::x'.") in errors
    assert [e for e in errors if e[0] == 4] == []
    assert len([e for e in errors if e[0] == 5]) == 1  # `#refinement` の未解決を 2 回出さない


def test_satisfying_a_requirement_twice_still_checks_its_type():
    text = """package P {
    requirement 'r2' : Unknown;
    part a { part b; part c; }
    satisfy 'r2' by a.b;
    satisfy 'r2' by a.c;
}
"""
    errors = _errors(text)
    assert (4, "A requirement must be typed by one requirement definition.") in errors
    assert (5, "A requirement must be typed by one requirement definition.") in errors


def test_frame_takes_the_type_of_the_concern():
    text = """package P {
    concern c1 : Unknown;
    concern def CD;
    concern c2 : CD;
    requirement def R { frame c1; frame c2; }
}
"""
    assert (5, "A requirement must be typed by one requirement definition.") in _errors(text)
    assert len([e for e in _errors(text) if e[0] == 5]) == 1


def test_attribute_typed_by_anything_is_valid():
    text = "package P { attribute d : Base::Anything; attribute c :> d : ScalarValues::Real; }"
    assert _errors(text) == []


# --- 個別の規則 ----------------------------------------------------------------------------------

@pytest.mark.parametrize("body, expected", [
    ("private import SI::*; attribute t : Real [s];", ["Must have a Natural value"]),
    ("attribute t : Real [zz];", ["Couldn't resolve reference to Element 'zz'.", "Must have a Natural value"]),
    ("attribute n : Natural = 3; part p[n];", []),
    ("attribute n : Integer; part p[n];", ["Must have a Natural value"]),
    ("part p[1..*]; part q[2];", []),
    # 型の中の feature は値でなく型（整数か）で判定される（MultiplicityTest.sysml、参照実装はエラーなし）
    ("attribute def A { attribute i : Integer; attribute x : A[i]; }", []),
    ("part def D { attribute r : Real; part q[r]; }", ["Must have a Natural value"]),
])
def test_multiplicity_bound_must_be_natural(body, expected):
    text = "package P { private import ScalarValues::*;\n" + body + "\n}"
    assert sorted(m for line, m in _errors(text) if line == 2) == sorted(expected)


def test_metadata_body_must_redefine_a_feature_of_its_type():
    text = """package P {
    metadata def M { attribute level : ScalarValues::Integer; }
    part x {
        @Risk {
            totalRisk = 1;
        }
        @M {
            lvl = 2;
            level = 3;
        }
    }
}
"""
    errors = _errors(text)
    for line, name in ((5, "totalRisk"), (8, "lvl")):
        assert (line, f"Couldn't resolve reference to Feature '{name}'.") in errors
        assert (line, "Must redefine an owning-type feature") in errors
    assert [e for e in errors if e[0] == 9] == []


def test_constructor_arguments_correspond_to_features():
    text = """package P {
    item t; item b;
    item x = new Pubx(t, b);
    item def Pub { ref item topic; }
    item y : Pub = new Pub(tpc = t);
    item z : Pub = new Pub(topic = t);
    item w : Pub = new Pub(t, b, t);
}
"""
    errors = _errors(text)
    assert errors.count((3, "Must correspond to one feature of the instantiated type")) == 2
    assert (5, "Couldn't resolve reference to Feature 'tpc'.") in errors
    assert (5, "Must correspond to one feature of the instantiated type") in errors
    assert [e for e in errors if e[0] in (6, 7)] == []
