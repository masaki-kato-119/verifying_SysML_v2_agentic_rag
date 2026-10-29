"""複数ファイルのモデル（model_files.py、ScopeResolver の other_asts、MCP の lint_sysml_file）。

どの例も、参照実装（Pilot 0.62.0）がフォルダごと検証したときに同じ判定をすることを確かめた形
（2026-10-22、sysml_models/eval/linter_gen の AGV モデルと probe）。
"""

from pathlib import Path

import pytest

from sysml_v2_checker_advanced.model_files import load_other_files, model_files
from sysml_v2_checker_advanced.semantic_model import lint_text_with_locations

DEFS = """package Defs {
    private import ScalarValues::*;
    item def Order { attribute id : String; }
    port def CmdPort { in item order : Order; }
    part def Vehicle {
        attribute maxSpeed : Real;
        port cmd : CmdPort;
    }
    private part def Hidden;
}
part def Top;
private part def TopPrivate;
private import ScalarValues::*;
"""

BEHAVIOR = """package Behavior {
    private import Defs::*;
    action def Plan { in order : Order; }
    action mission {
        action plan : Plan;
        action drive;
    }
    item def Go;
    state def Modes {
        entry; then idle;
        state idle;
        state moving;
        transition first idle accept Go then moving;
    }
}
"""


def _errors(text: str, *others: str) -> list:
    from sysml_v2_checker_advanced.parser import parse_sysml

    ast, issues, dicts = lint_text_with_locations(text, other_asts=[parse_sysml(o) for o in others])
    assert ast.get("type") != "error"
    return sorted((d["line"], d["message"]) for d in dicts if d["severity"] == "error")


def _structure(body: str) -> str:
    return "package Structure {\n    private import Defs::*;\n    private import Behavior::*;\n" + body + "\n}\n"


def test_correct_cross_file_references_are_clean():
    text = _structure("""    part v : Vehicle {
        attribute redefines maxSpeed = 1.5;
        perform mission.plan;
        exhibit state modes : Modes;
    }
    part t : Top;
    part tp : TopPrivate;""")
    assert _errors(text, DEFS, BEHAVIOR) == []


@pytest.mark.parametrize("body, reference", [
    ("    part v : Vehicl;", "Vehicl"),  # ほかのファイルの型の名前の誤記
    ("    part v : Vehicle { attribute redefines maxSped = 1.5; }", "maxSped"),  # 継承した feature
    ("    part v : Vehicle { perform mission.plann; }", "plann"),  # ほかのファイルの action の中
    ("    part v : Vehicle;\n    part w : Vehicle;\n    connect v.cmd to w.cmmd;", "cmmd"),  # 連鎖の先
    ("    part h : Hidden;", "Hidden"),  # private なメンバーは import で見えない
    ("    part y : Defs::Nope;", "Defs::Nope"),
    # ほかのファイルの最上位の import は、そのファイルの中だけに効く
    ("    attribute s : String;", "String"),
])
def test_mistakes_against_other_files_are_found(body, reference):
    messages = [message for _line, message in _errors(_structure(body), DEFS, BEHAVIOR)]
    assert any(f"'{reference}'" in m for m in messages), messages


def test_same_file_mistakes_are_found_when_importing_other_files():
    # 以前は、中身を知らないパッケージの import があると、解決できない名前をすべて「不明」にしていた
    text = BEHAVIOR.replace("then moving;", "then movng;").replace("accept Go", "accept Goo")
    messages = [message for _line, message in _errors(text, DEFS)]
    assert any("'movng'" in m for m in messages), messages
    assert any("'Goo'" in m for m in messages), messages


def test_interface_end_with_end_name_is_resolved():
    text = """package P {
    port def PD;
    part def A { port p : PD; }
    interface def I { end x : PD; end y : PD; }
    part s {
        part a : A;
        part b : A;
        interface i : I connect x ::> a.nosuch to y ::> b.p;
    }
}
"""
    assert [message for _line, message in _errors(text)] == ["Couldn't resolve reference to Feature 'nosuch'."]


def test_connection_end_heads_are_checked_on_the_end_line():
    # 参照実装は端の先頭の名前を出し、`x ::> a.p` の端は端の行に出す
    text = """package P {
    port def PD;
    part def A { port p : PD; }
    interface def I { end x : PD; end y : PD; }
    part s {
        part a : A;
        part b : A;
        connect a.p to nob.p;
        connect a to nob2;
        interface i : I
            connect x ::> a.p to y ::> nob3.p;
        bind a.p = nob4.p;
    }
}
"""
    assert _errors(text) == [
        (8, "Couldn't resolve reference to Feature 'nob'."),
        (9, "Couldn't resolve reference to Feature 'nob2'."),
        (11, "Couldn't resolve reference to Feature 'nob3'."),
        (12, "Couldn't resolve reference to Feature 'nob4'."),
    ]


def test_accept_type_is_reported_on_the_accept_line():
    text = """package P {
    item def Go;
    state def S {
        entry; then idle;
        state idle;
        state moving;
        transition t
            first idle
            accept Goo
            then moving;
    }
}
"""
    errors = _errors(text)
    assert [(line, message.split(" accept ")[0]) for line, message in errors] == [
        (9, "Couldn't resolve reference to Type 'Goo'.")]
    assert "item def Goo;" in errors[0][1]  # 古い規則のヒントを引き継ぐ


def test_named_end_has_the_members_of_its_subsetted_feature():
    # `connect lugNut ::> wheel.lugNut` の端 lugNut は wheel.lugNut のメンバーを持つ
    # （held-out の SysML-v2-Release Vehicle_Example）
    text = """package P {
    port def LP;
    port def CP { port p1 : LP; }
    part def Wheel { port lugNut : CP; }
    part def Hub { port shank : CP; }
    interface def WH { end lugNut : CP; end shank : CP; }
    interface def F { end a : LP; end b : LP; }
    part s {
        part wheel : Wheel;
        part hub : Hub;
        interface wh : WH connect lugNut ::> wheel.lugNut to shank ::> hub.shank {
            interface f : F connect a ::> lugNut.p1 to b ::> shank.p1;
            interface g : F connect a ::> lugNut.p2 to b ::> shank.p1;
        }
    }
}
"""
    assert _errors(text) == [(13, "Couldn't resolve reference to Feature 'p2'.")]


def test_named_ends_of_nary_connection_are_members():
    # `connect (x ::> a.p, y ::> b.p)` の x・y（held-out の Arrowhead_Framework_Example）
    text = """package P {
    item def M;
    port def MP { out item m : M; }
    part def A { port p : MP; }
    part a : A;
    part b : A;
    connection c connect (x ::> a.p, y ::> b.p) {
        flow of M from x.m to y.m;
        flow of M from x.m to z.m;
    }
}
"""
    assert _errors(text) == [(9, "Couldn't resolve reference to Feature 'z'.")]


def test_model_files_follow_validate_sysml_rules(tmp_path: Path):
    (tmp_path / "a.sysml").write_text(DEFS, encoding="utf-8")
    (tmp_path / "b.sysml").write_text(BEHAVIOR, encoding="utf-8")
    sub = tmp_path / "sub"
    sub.mkdir()
    (sub / "c.sysml").write_text("package C;", encoding="utf-8")
    (tmp_path / "broken.sysml").write_text("package Broken { part x }", encoding="utf-8")
    target = str(tmp_path / "b.sysml")
    # file_path だけ: 同じフォルダ（サブフォルダは含めない）
    assert [p.name for p in model_files(target)] == ["a.sysml", "broken.sysml"]
    # directory: サブフォルダも含める
    assert [p.name for p in model_files(target, str(tmp_path))] == ["a.sysml", "broken.sysml", "c.sysml"]
    # "" は 1 ファイルだけ
    assert model_files(target, "") == []
    others = load_other_files(model_files(target), base=tmp_path)
    # 構文エラーのファイルは、エラー回復で読めた部分を使う（参照実装と同じく、ほかのファイルに見せる）
    assert others.loaded == ["a.sysml", "broken.sysml"] and others.partial == ["broken.sysml"]
    assert others.unparsable == []


def test_definitions_before_a_syntax_error_in_another_file_are_visible():
    # 参照実装は、構文エラーのあるファイルの回復で読めた部分の要素をほかのファイルに見せる
    # （AGV の probe m02: 別のファイルの action の中のセミコロン抜けのあとも、その前の定義は解決する）
    broken = """package Behavior {
    action def Plan;
    action mission {
        action plan : Plan;
        first start;
        then plan
        then done;
    }
}
"""
    from sysml_v2_checker_advanced.model_files import parse_other_file

    other, errors = parse_other_file(broken)
    assert errors and other is not None
    text = "package S {\n    private import Behavior::*;\n    part p { perform mission.plan; perform mission.plann; }\n}\n"
    ast, _issues, dicts = lint_text_with_locations(text, other_asts=[other])
    assert [d["message"] for d in dicts if d["severity"] == "error"] == [
        "Couldn't resolve reference to Feature 'plann'."]


def test_mcp_lint_sysml_file_reads_the_folder(tmp_path: Path):
    # MCP サーバ（fastmcp）を読めない環境では、この 1 件だけ飛ばす（名前解決の試験は fastmcp に依らない）
    try:
        from sysml_v2_checker_advanced import mcp_server
    except ImportError as exc:
        pytest.skip(f"MCP サーバを読み込めない: {exc}")
    lint = getattr(mcp_server.lint_sysml_file, "fn", mcp_server.lint_sysml_file)
    (tmp_path / "Defs.sysml").write_text(DEFS, encoding="utf-8")
    (tmp_path / "Behavior.sysml").write_text(BEHAVIOR, encoding="utf-8")
    target = tmp_path / "Structure.sysml"
    target.write_text(_structure("    part v : Vehicle { perform mission.plan; }"), encoding="utf-8")

    result = lint(str(target))
    assert result["success"] and result["summary"]["errors"] == 0, result["issues"]
    assert result["scope"] == "directory" and result["loaded"] == ["Behavior.sysml", "Defs.sysml"]

    single = lint(str(target), directory="")
    assert single["scope"] == "file" and single["summary"]["errors"] > 0

    text_lint = getattr(mcp_server.lint_sysml_text, "fn", mcp_server.lint_sysml_text)
    replaced = text_lint(_structure("    part v : Vehicl;"), file_path=str(target))
    assert any("'Vehicl'" in i["message"] for i in replaced["issues"]), replaced["issues"]


def test_flow_end_may_name_the_enclosing_interface():
    # interface の本体の flow の端が、その interface 自身の名前から始まる形は参照実装で通る
    # （フォルダ単位のコーパスの SysML-v2-Release ServerSequenceRealization-3）
    text = """package P {
    item def Msg;
    port def PP { in ref m : Msg; }
    interface def PI { end source : ~PP; end target : PP; }
    part a { port p : ~PP; }
    part b { port p : PP; }
    interface pi : PI connect a.p to b.p {
        flow f from pi.source.m to pi.target.m;
    }
}
"""
    assert _errors(text) == []


def test_reference_positions_found_by_the_folder_corpus():
    # フォルダ単位のコーパスでファイルをまたぐ誤記を見逃した位置（2026-10-22）。どれも参照実装と同じ指摘
    text = """package G {
    private import ScalarValues::*;
    item def Sig;
    item def Msg { attribute x : Real; }
    port def MP { out item m : Msg; }
    part def Eng { port fp : MP; attribute d : Real; }
    calc def Vel { in a : Real; return : Real; }
    part car {
        part e : Eng;
        part c : Eng;
        flow f1 of Msgg from c.fp.m to e.fp.m;
        attribute v : Real = Vell(1.0);
        attribute w : Real = Vel(1.0);
        item s : Msg = new Msgx();
        ref part sub :> c.noo;
        action act {
            action r1 accept Sigg via c.fp;
            action r2 accept Sig via c.fp;
        }
        flow f3 of Msg
            from c.fp.m to e.fp.mx;
    }
}
"""
    assert _errors(text) == [
        (11, "Couldn't resolve reference to Type 'Msgg'."),        # flow の `of T`
        (12, "Couldn't resolve reference to Element 'Vell'."),      # 式の中の呼び出し
        (12, "Must invoke a behavior or a behavioral feature"),     # 呼び出す名前が無い（Pilot 0.63.0 も重ねる）
        (14, "Couldn't resolve reference to Element 'Msgx'."),      # new T(...)
        (15, "Couldn't resolve reference to Feature 'noo'."),       # 部分集合の先の連鎖
        (17, "Couldn't resolve reference to Type 'Sigg'."),         # action の中の accept
        (21, "Couldn't resolve reference to Feature 'mx'."),        # flow の端は端の行に出す
    ]


def test_library_functions_need_an_import():
    # 参照実装は import していないライブラリの関数の呼び出しを未解決にする
    text = """package H {
    private import ScalarValues::*;
    package Inner { calc def Acc { in a : Real; return : Real; } }
    part p {
        attribute a1 : Real = sqrt(2.0);
        attribute a3 : Real = Inner::Acc(1.0);
        attribute a4 : Real = Inner::Accx(1.0);
    }
}
"""
    assert _errors(text) == [(5, "Couldn't resolve reference to Element 'sqrt'."),
                             (5, "Must invoke a behavior or a behavioral feature"),
                             (7, "Couldn't resolve reference to Element 'Inner::Accx'."),
                             (7, "Must invoke a behavior or a behavioral feature")]


def test_prefix_metadata_base_type_and_lambda_parameter_chains():
    # `#service port p1` は baseType（global_sd）のメンバーを持つ。特化の無い metadata は何も足さない。
    # ラムダの型のある引数の連鎖は、その型から確かめる
    text = """package M {
    private import Metaobjects::SemanticMetadata;
    private import ControlFunctions::forAll;
    port def SD { out item retall; }
    port global_sd : SD;
    metadata def <service> SDM :> SemanticMetadata { :>> baseType = global_sd meta SysML::PortUsage; }
    metadata def <tag> Tag;
    part a {
        #service port p1;
        #tag port p2 { out item q; }
    }
    part b {
        attribute y = a.p1.retal;
        attribute z = a.p2.qq;
    }
    part def W { attribute r; }
    part def A { part wheel : W; }
    constraint def C { in xs : A[4]; xs->forAll {in ref w: A; w.wheel.rr > 0} }
}
"""
    assert [(line, message) for line, message in _errors(text) if "resolve" in message] == [
        (13, "Couldn't resolve reference to Feature 'retal'."),
        (14, "Couldn't resolve reference to Feature 'qq'."),
        (18, "Couldn't resolve reference to Feature 'rr'."),
    ]


def test_expression_chain_kind_word_and_arrow_calls():
    # 式の中の連鎖の先: 2 つ（`a.bx`）は Element、3 つ以上は Feature（参照実装、2026-10-23 に確認）。
    # `->` の呼び出しの名前も、import していなければ未解決
    text = """package K {
    private import ScalarValues::*;
    private import SequenceFunctions::size;
    part def C { attribute m : Real; }
    part def B { part c : C; attribute n : Real; }
    part def A { part b : B; }
    part a : A;
    attribute v1 = a.bx;
    attribute v2 = a.b.nx;
    attribute v4 = a.bx.c.m;
    constraint k1 { a.bx == a.b.c.m }
    attribute u = a->size();
    attribute w = a->isEmpty();
}
"""
    assert _errors(text) == [
        (8, "Couldn't resolve reference to Element 'bx'."),
        (9, "Couldn't resolve reference to Feature 'nx'."),
        (10, "Couldn't resolve reference to Feature 'bx'."),
        (11, "Couldn't resolve reference to Element 'bx'."),
        (13, "Couldn't resolve reference to Element 'isEmpty'."),
    ]
