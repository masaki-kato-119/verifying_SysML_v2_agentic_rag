"""段階 A（eval/pilot_parity/ROADMAP.md）: 文法の穴、パース後の lint 継続、正しいモデルでの誤検出。

どの例も Pilot 0.62.0 がクリーン（またはエラー）と判定した形（eval/pilot_parity の verified / probe）。
"""

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
