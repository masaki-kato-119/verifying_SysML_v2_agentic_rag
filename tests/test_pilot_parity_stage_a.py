"""段階 A（eval/pilot_parity/ROADMAP.md）: 文法の穴、パース後の lint 継続、正しいモデルでの誤検出。

どの例も Pilot 0.62.0 がクリーン（またはエラー）と判定した形（eval/pilot_parity の verified / probe）。
"""

import pytest

from sysml_v2_checker_advanced.semantic_model import lint_text_with_locations


def _errors(text: str, **kwargs):
    ast, _issues, dicts = lint_text_with_locations(text, **kwargs)
    return ast, [(d["line"], d["rule"]) for d in dicts if d["severity"] == "error"]


def test_initial_value_and_default_with_colon_equals_parse():
    ast, errors = _errors(
        "package P {\n"
        "    attribute def A { attribute x : A := 1; attribute y : A default := 2; }\n"
        "}\n"
    )
    assert ast.get("type") != "error"
    assert errors == []


def test_port_inside_state_def_parses():
    ast, _errors_ = _errors("package P { port def Q; state def S { port p : Q; } }\n")
    assert ast.get("type") != "error"


def test_recover_lints_the_readable_part_after_a_parse_error():
    text = (
        "package P {\n"
        "    part x : NoSuchType;\n"
        "    part def D { %%% }\n"
        "}\n"
    )
    ast, errors = _errors(text, recover=True)
    assert ast.get("type") == "error"  # 呼び出し側はパースエラーを従来どおり受け取る
    assert any(line == 2 for line, _rule in errors)
    _ast, without = _errors(text)
    assert without == []  # 既定（recover=False）は従来どおり lint しない


def test_short_name_import_and_qualified_reference_resolve():
    _ast, errors = _errors(
        "package Spec {\n"
        "    requirement def <'SN-R001'> MassLimit;\n"
        "    package <SNSUB> Sub { part def InnerPart; }\n"
        "}\n"
        "package User {\n"
        "    private import Spec::*;\n"
        "    private import Spec::'SN-R001';\n"
        "    part inner : Spec::SNSUB::InnerPart;\n"
        "}\n"
    )
    assert errors == []


def test_flow_in_untyped_interface_may_use_library_end_names():
    _ast, errors = _errors(
        "package P {\n"
        "    item def Fuel;\n"
        "    port def FuelPort { out item fuelSupply : Fuel; }\n"
        "    part def Tank { port fuelOut : FuelPort; }\n"
        "    part def Engine { port fuelIn : ~FuelPort; }\n"
        "    part def V {\n"
        "        part tank : Tank;\n"
        "        part eng : Engine;\n"
        "        interface connect tank.fuelOut to eng.fuelIn {\n"
        "            flow of Fuel from source.fuelSupply to target.fuelSupply;\n"
        "        }\n"
        "    }\n"
        "}\n"
    )
    assert errors == []


# フォルダ単位のコーパス（sysmod・advent-of-sysml-v2）で見つかった文法の穴。どれも参照実装は構文エラーも
# 名前解決のエラーも出さない（2026-10-23 に確認）。
_GRAMMAR_HOLES = [
    ('A_trailing_comma', 'package HA {\n    private import ScalarValues::*;\n    attribute qs : String[*] = ("a", "b", );\n}\n'),
    ('B_directed_kinds', 'package HB {\n    concern def CD;\n    requirement def RD;\n    use case def UD;\n    verification def VD;\n    action def P {\n        in concern c1 : CD;\n        out concern c2 : CD;\n        out use case u1[*] : UD;\n        out requirement r1 : RD;\n        in requirement r2 : RD;\n        out verification v1[*] : VD;\n    }\n}\n'),
    ('C_prefix_defs', "package HC {\n    metadata def m;\n    #m occurrence def <OS> 'Some Occurrence';\n    #m use case def U1 { }\n    #m concern def C1 { }\n    #HC::m occurrence def O2;\n}\n"),
    ('D_usecase_qualified', 'package HD {\n    package UseCases { use case def U; }\n    part def Sys { use case u : UseCases::U; }\n    part s : Sys {\n        use case :>> u : UseCases::U { }\n        use case w : UseCases::U { }\n    }\n}\n'),
    ('E_redefine_then_type', 'package HE {\n    occurrence def Project;\n    action def A {\n        ref occurrence project :>> this : Project;\n    }\n}\n'),
    ('F_interface_nameless_qualified', 'package HF {\n    package Ifs { port def P; interface def I { end a : P; end b : P; } }\n    part q {\n        port x : Ifs::P;\n        port y : Ifs::P;\n        interface :Ifs::I\n            connect x to y;\n    }\n}\n'),
    ('H_defined_by', 'package HH {\n    part def D;\n    part def E :> D;\n    part def S { part d : D; }\n    part s : S {\n        part dd redefines d defined by E;\n    }\n}\n'),
    ('I_interface_shortname', 'package HI {\n    port def P;\n    interface def I { end a : P; end b : P; }\n    part q {\n        port xs[*] : P;\n        port ys[*] : P;\n        interface <asis> links[1..*] : I\n            connect xs to ys { }\n    }\n}\n'),
    ('J_mult_before_type', 'package HJ {\n    use case def U;\n    occurrence def O;\n    part def S {\n        use case us [0..*] : U { }\n        use case vs[*] : U;\n        occurrence os[*] : O;\n    }\n}\n'),
    ('K_succession_mult', 'package HK {\n    action def A {\n        action a1;\n        action a2;\n        action a3;\n        first [0..1] a1 then [0..1] a2;\n        first [0..1]a2 then a3;\n    }\n}\n'),
    ('L_loop_action', 'package HL {\n    attribute def Flag;\n    action def A {\n        attribute flying : Boolean;\n        first start then cycle;\n        action cycle loop {\n            first start then done;\n        } until flying;\n        first cycle then done;\n    }\n    private import ScalarValues::*;\n}\n'),
]


@pytest.mark.parametrize("name, text", _GRAMMAR_HOLES)
def test_grammar_holes_from_the_folder_corpus(name, text):
    ast, errors = _errors(text)
    assert ast.get("type") != "error", ast.get("message")
    assert errors == []


def test_frame_without_a_name_and_with_redefinitions_parses():
    # `frame concern :T;`・`frame x :>> A::b :> C::d;`（参照実装は構文エラーを出さない。x が無ければ名前解決のエラー）
    ast, _errors_ = _errors("package HG { concern def CC; requirement def R { concern k : CC; } "
                            "requirement r : R { frame concern :CC; frame k :>> R::k :> R::k; } }\n")
    assert ast.get("type") != "error", ast.get("message")


def test_short_name_of_the_enclosing_type_may_qualify_its_feature():
    # 囲む型自身のメンバーは短い名前で `PRJ::company` と書ける。外からは `Must be an accessible feature`
    # （参照実装で確認、2026-10-23。sysmod の `stakeholder :>> c = PRJ::logisticCompany;`）
    inside = ("package V { part def Person; concern def Cn { ref part sh : Person; } "
              "occurrence def <PRJ> 'My Project' { ref part company : Person; "
              "concern c : Cn { ref part :>> sh = PRJ::company; } part y = PRJ::company; } }\n")
    outside = ("package V { part def Person; occurrence def <PRJ> 'My Project' { ref part company : Person; } "
               "occurrence def Other { ref part company2 : Person; } "
               "occurrence o : Other { ref part :>> company2 = PRJ::company; } }\n")
    assert _errors(inside)[1] == []
    assert [rule for _line, rule in _errors(outside)[1]] == ["_check_accessible_feature_paths"]
