"""sysml_v2_checker_advanced のスモークテスト。"""

import json

from sysml_v2_checker_advanced.constants import (
    BUILTIN_TYPES,
    SEVERITY_ERROR,
    SEVERITY_INFO,
    SEVERITY_WARNING,
)
from sysml_v2_checker_advanced.utils import ast_to_json


def test_constants_builtin_types():
    assert "String" in BUILTIN_TYPES
    assert SEVERITY_ERROR == "error"
    assert SEVERITY_WARNING == "warning"
    assert SEVERITY_INFO == "info"


def test_constants_builtin_types_scalar_values():
    """SysML v2 標準ライブラリ ScalarValues の基本型が揃っていること。"""
    for scalar_type in (
        "Real",
        "Rational",
        "Complex",
        "Natural",
        "Positive",
    ):
        assert scalar_type in BUILTIN_TYPES


def test_linter_does_not_flag_real_action_param_type():
    """`in x : Real;` のような action パラメータで誤検出しないこと。

    修正前は BUILTIN_TYPES に Real が無く、ごく普通のモデルでも
    「存在しない型 'Real' を参照しています」という誤検出が発生していた。
    """
    from sysml_v2_checker_advanced.linter import SysMLAdvancedLinter
    from sysml_v2_checker_advanced.parser import parse_sysml

    src = (
        "package P {\n"
        "    action def DoSomething {\n"
        "        in x : Real;\n"
        "    }\n"
        "}\n"
    )
    ast = parse_sysml(src, strict=True)
    linter = SysMLAdvancedLinter()
    issues = linter.lint(ast)

    assert not any(
        "Real" in issue.message and "存在しない型" in issue.message
        for issue in issues
    )


def test_linter_does_not_crash_on_port_usage_without_type():
    """d72_bare_interface_usage_missing: `port ref :>> participant { }`の
    ように型節（`: ID`）を省略したport_usage（type_name=None）で
    AttributeError: 'NoneType' object has no attribute 'startswith'が
    発生していた（`node.get("type_name", "")`はキーが存在しつつ値が
    Noneのケースでデフォルト値を返さない）。Interfaces.sysmlが本タスク
    で初めて完全パース成功し、この経路に到達したことで顕在化した。"""
    from sysml_v2_checker_advanced.linter import SysMLAdvancedLinter
    from sysml_v2_checker_advanced.parser import parse_sysml

    src = "part def P { port ref :>> participant { } }"
    ast = parse_sysml(src, strict=True)
    linter = SysMLAdvancedLinter()
    issues = linter.lint(ast)  # クラッシュしないことを確認する

    assert isinstance(issues, list)


def test_ast_to_json_roundtrip():
    ast = {"type": "root", "children": [{"type": "leaf", "name": "x"}]}
    s = ast_to_json(ast, pretty=False)
    assert json.loads(s) == ast


def test_parse_sysml_minimal_comment():
    """空に近い入力でもパーサがエラーハンドリングする（クラッシュしない）。"""
    from sysml_v2_checker_advanced.parser import parse_sysml

    out = parse_sysml("", strict=True)
    assert isinstance(out, dict)


def test_parse_sysml_sample_file():
    """リポジトリ同梱の test_sysml.sysml をパース（構文エラーなら error 辞書）。"""
    from pathlib import Path

    from sysml_v2_checker_advanced.parser import parse_sysml

    p = Path(__file__).resolve().parents[1] / "test_sysml.sysml"
    text = p.read_text(encoding="utf-8")
    out = parse_sysml(text, strict=True)
    assert isinstance(out, dict)
    assert "type" in out


def test_interface_end_owner_qualified_path_is_not_flagged():
    """`connect` の所有者付きエンドパスを「存在しない」と誤検出しない。

    2026-09-07、ルール別一致率の実測で `_check_interface_usage` の confidence が
    0.200 と最下位群にあり、local_only_error の最大要因だった。原因は、
    `tankAssy.fuelTankPort`（パーサーは `.` を `::` へ正規化する）のような
    所有者付きパスを、入れ子を保持しない平坦なシンボル表で引こうとして必ず
    失敗していたこと。`fuelTankPort` を持つのは `tankAssy` 自身ではなく
    その型の `FuelTankAssembly` なので、解決には型解決が要る。

    参照実装は解決できるこの形をクリーンと判定する（2026-09-07に実測）。
    xpect の valid フィクスチャ validation/valid/InterfaceUsage.sysml と同じ形。
    """
    from sysml_v2_checker_advanced.parser import lint_sysml, parse_sysml

    src = """
    package P {
        port def FuelOutPort;
        port def FuelInPort;
        part def FuelTankAssembly { port fuelTankPort : FuelOutPort; }
        part def Engine { port engineFuelPort : FuelInPort; }
        interface def FuelInterface {
            end supplierPort : FuelOutPort;
            end consumerPort : FuelInPort;
        }
        part vehicle {
            part tankAssy : FuelTankAssembly;
            part eng : Engine;
            interface FuelInterface connect
                supplierPort ::> tankAssy.fuelTankPort to
                consumerPort ::> eng.engineFuelPort;
        }
    }
    """
    issues = lint_sysml(parse_sysml(src))
    assert [i.message for i in issues if i.rule == "_check_interface_usage"] == []


def test_interface_end_simple_name_that_does_not_exist_is_still_flagged():
    """単純名なら型解決なしで不在を断定できるので、検出は維持する。

    参照実装も `Couldn't resolve reference to Feature 'noSuchThing'.` を返す
    （2026-09-07に実測）。所有者付きパスを見送ったぶん検出漏れは増えるが、
    ここまで捨てると制約そのものが無くなってしまう。
    """
    from sysml_v2_checker_advanced.parser import lint_sysml, parse_sysml

    src = """
    package P {
        port def FuelOutPort;
        port def FuelInPort;
        interface def FuelInterface {
            end supplierPort : FuelOutPort;
            end consumerPort : FuelInPort;
        }
        part vehicle {
            interface FuelInterface connect
                supplierPort ::> noSuchThing to
                consumerPort ::> alsoNoSuchThing;
        }
    }
    """
    issues = [i for i in lint_sysml(parse_sysml(src)) if i.rule == "_check_interface_usage"]
    assert len(issues) == 2


def test_allocation_end_owner_qualified_path_is_not_flagged():
    """`allocate` の所有者付きエンドパスを「存在しない」と誤検出しない。

    interface 側（test_interface_end_owner_qualified_path_is_not_flagged）と
    同じ原因で、判定も `_end_reference_is_missing` を共有している。allocation
    についても別途参照実装へ問い合わせ、同じ境界であることを実測した
    （2026-09-07。`allocate l.component to p.assembly.element;` はクリーン、
    `l.noSuchPart` と単純名の `noSuchThing` はエラー）。

    xpect の simpletests/AllocationTest.sysml（`// XPECT noErrors`）と同じ形。
    """
    from sysml_v2_checker_advanced.parser import lint_sysml, parse_sysml

    src = """
    package P {
        part def Logical { part component; }
        part def Physical { part assembly { part element; } }
        part l : Logical { part :>> component; }
        part p : Physical { part :>> assembly { part :>> element; } }
        allocation def Logical_to_Physical {
            end logical : Logical;
            end physical : Physical;
        }
        allocate l.component to p.assembly.element;
    }
    """
    issues = lint_sysml(parse_sysml(src))
    assert [i.message for i in issues if i.rule == "_check_allocation_usage"] == []


def test_allocation_end_simple_name_that_does_not_exist_is_still_flagged():
    """単純名の不在は型解決なしで断定できるので検出を維持する。

    参照実装も `Couldn't resolve reference to Feature 'noSuchThing'.` を
    2件返す（2026-09-07に実測）。
    """
    from sysml_v2_checker_advanced.parser import lint_sysml, parse_sysml

    src = """
    package P {
        part def Logical;
        part def Physical;
        allocation def Logical_to_Physical {
            end logical : Logical;
            end physical : Physical;
        }
        allocation a1 : Logical_to_Physical allocate noSuchThing to alsoNoSuchThing;
    }
    """
    issues = [i for i in lint_sysml(parse_sysml(src)) if i.rule == "_check_allocation_usage"]
    assert len(issues) == 2


def test_transition_qualified_endpoint_is_not_flagged():
    """`then S2.S3;` のような修飾名の遷移先を「存在しない」と誤検出しない。

    2026-09-07、ルール別一致率で `_check_transition` の confidence は 0.250。
    ソースの `S2.S3` はパーサーが `S2::S3` へ正規化するが、シンボル表は
    入れ子を保持せず package 直下に平坦登録する（`StateTest::S3`）ため
    解決できず、公式サンプル StateTest.sysml の遷移を落としていた。

    参照実装は解決できる修飾名をクリーンと判定する（2026-09-07に実測。
    `then b.c` はクリーン、`then b.noSuch` はエラー）。
    """
    from sysml_v2_checker_advanced.parser import lint_sysml, parse_sysml

    src = """
    package P {
        state def S {
            state a;
            state b { state c; }
            transition first a then b.c;
        }
    }
    """
    issues = [i for i in lint_sysml(parse_sysml(src)) if i.rule == "_check_transition"]
    assert issues == []


def test_transition_implicit_done_state_is_not_flagged():
    """`then done;` はローカル宣言が無くても正当（標準ライブラリ側の暗黙の状態）。

    参照実装は `first start` も含めてクリーンと判定する（2026-09-07に実測）。
    StateTest.sysml の `accept Exit then done;` と StopWatchStates.sysml の
    `then done;` を落としていた原因。
    """
    from sysml_v2_checker_advanced.parser import lint_sysml, parse_sysml

    for src in (
        "package P { state def S { state a; transition first a then done; } }",
        "package P { state def S { state a; transition first start then a; } }",
    ):
        issues = [i for i in lint_sysml(parse_sysml(src)) if i.rule == "_check_transition"]
        assert issues == [], src


def test_transition_undeclared_simple_name_is_still_flagged():
    """未宣言の単純名は型解決なしで断定できるので検出を維持する。

    参照実装も `Couldn't resolve reference to Feature 'noSuchState'.` を返す
    （2026-09-07に実測）。
    """
    from sysml_v2_checker_advanced.parser import lint_sysml, parse_sysml

    src = "package P { state def S { state a; transition first a then noSuchState; } }"
    issues = [i for i in lint_sysml(parse_sysml(src)) if i.rule == "_check_transition"]
    assert len(issues) == 1
    assert "noSuchState" in issues[0].message


def test_allocation_typed_by_non_allocation_definition_is_flagged():
    """allocation は allocation definition で型付けしなければならない。

    2026-09-07以前は存在判定しか持たず、`part def`や`part usage`で型付けした形は
    「存在する」ため素通りしていた。参照実装は
    `An allocation must be typed by allocation definitions.` を返す
    （2026-09-07に実測。connection def / part def / part usage / attribute def /
    action def / port def / allocation **usage** の7種すべてでエラー、
    allocation def とその派生だけがクリーン）。
    """
    from sysml_v2_checker_advanced.parser import lint_sysml, parse_sysml

    src = """
    package P {
        part def B;
        part def C;
        part p {
            part b : B;
            part c : C;
            allocation x : B allocate b to c;
        }
    }
    """
    issues = [i for i in lint_sysml(parse_sysml(src)) if i.rule == "_check_allocation_usage"]
    assert len(issues) == 1
    assert "allocation definition" in issues[0].message


def test_allocation_typed_by_allocation_definition_or_its_subtype_is_clean():
    """派生した allocation definition での型付けも正当（参照実装で実測）。"""
    from sysml_v2_checker_advanced.parser import lint_sysml, parse_sysml

    src = """
    package P {
        part def B;
        part def C;
        allocation def BC2 { end : B[1]; end : C[1]; }
        allocation def BC3 :> BC2;
        part p {
            part b : B;
            part c : C;
            allocation x : BC2 allocate b to c;
            allocation y : BC3 allocate b to c;
        }
    }
    """
    issues = [i for i in lint_sysml(parse_sysml(src)) if i.rule == "_check_allocation_usage"]
    assert issues == []


def test_interface_typed_by_non_interface_definition_is_flagged():
    """interface 側も同じ制約を持つ（参照実装のメッセージは
    `An interface must be typed by interface definitions.`）。"""
    from sysml_v2_checker_advanced.parser import lint_sysml, parse_sysml

    src = """
    package P {
        port def PO;
        port def PI;
        part def Q;
        part p {
            port a : PO;
            port b : PI;
            interface i : Q connect a to b;
        }
    }
    """
    issues = [i for i in lint_sysml(parse_sysml(src)) if i.rule == "_check_interface_usage"]
    assert len(issues) == 1
    assert "interface definition" in issues[0].message


def test_connection_def_inheriting_its_ends_is_not_flagged():
    """endを基底から継承する connection def を「end 0個」と誤検出しない。

    2026-09-07以前は `_check_connection_structure_advanced` が
    `connection_end_member` の子だけを数え、`isAbstract` しか除外していなかった
    ため、`connection def CD2 :> CD;` を落としていた。参照実装はこれを
    クリーンと判定する（実測）。

    endが本当に0個の形（`connection def CD;`）は参照実装も
    `Must have at least two related elements` を返すので、検出は
    `_check_at_least_two_related_elements` が引き続き担う。
    """
    from sysml_v2_checker_advanced.parser import lint_sysml, parse_sysml

    inherited = """
    package P {
        part def B;
        connection def CD { end : B[1]; end : B[1]; }
        connection def CD2 :> CD;
    }
    """
    assert lint_sysml(parse_sysml(inherited)) == []

    genuinely_empty = "package P { connection def CD; }"
    issues = lint_sysml(parse_sysml(genuinely_empty))
    assert len(issues) == 1, [i.message for i in issues]
    assert issues[0].rule == "_check_at_least_two_related_elements"


def test_empty_connection_def_is_reported_once_not_twice():
    """同じ事実を2つのルールが二重報告しない（参照実装も1件しか返さない）。

    `_check_connection_structure_advanced` と
    `_check_at_least_two_related_elements` が同じ「endが2個未満」を検査して
    いたため、`connection def CD;` に対して2件出ていた（2026-09-07に劣っている
    側を削除）。
    """
    from sysml_v2_checker_advanced.parser import lint_sysml, parse_sysml

    issues = lint_sysml(parse_sysml("package P { connection def CD; }"))
    rules = [i.rule for i in issues]
    assert rules.count("_check_at_least_two_related_elements") == 1
    assert "_check_connection_structure_advanced" not in rules


def test_import_of_nested_usage_path_is_not_flagged():
    """入れ子のusageを辿るimportを「存在しない」と誤検出しない。

    `public import vehicle1_c1::interior::seatBelt;`（13b-Safety and Security
    Features Element Group.sysml）の形。シンボル表は package 直下に平坦登録する
    ため多セグメントのパスは引けない（connectのエンド参照と同じ構造的原因）。

    参照実装は正当な入れ子パスをクリーンと判定する（2026-09-14に実測）。
    """
    from sysml_v2_checker_advanced.parser import lint_sysml, parse_sysml

    base = "package Q { part v1 { part interior { part alarm; part seatBelt; } } package U { %s } }"
    assert lint_sysml(parse_sysml(base % "public import v1::interior::seatBelt;")) == []
    assert lint_sysml(parse_sysml(base % "public import v1::interior::*;")) == []


def test_import_with_a_missing_segment_is_still_flagged():
    """セグメントのどれかが存在しなければ検出は維持する。

    参照実装も葉・中間・根のいずれが欠けてもエラーにする（2026-09-14に実測）。
    所有関係までは見ないので `b::x`（xはaの下）は取りこぼすが、それは
    「検出漏れは許容、偽陽性は出さない」方針による意図的なもの。
    """
    from sysml_v2_checker_advanced.parser import lint_sysml, parse_sysml

    base = "package Q { part v1 { part interior { part alarm; part seatBelt; } } package U { %s } }"
    for stmt in (
        "public import v1::interior::noSuchLeaf;",
        "public import v1::noSuchMid::seatBelt;",
        "public import noSuchRoot::interior::seatBelt;",
    ):
        assert len(lint_sysml(parse_sysml(base % stmt))) == 1, stmt


def test_import_does_not_validate_itself_through_opaque_import_names():
    """importが自分自身を正当化しないこと（循環の回帰ガード）。

    `lint()` は `self.types.update(self.opaque_import_names)`（linter.py:163）で
    **import由来の名前そのもの**を `self.types` へ混ぜる。
    `_import_target_is_type_name` がそれを除外しないと、
    `import v1::interior::noSuchLeaf;` の `noSuchLeaf` が「型として存在する」と
    判定され、import が自分自身を正当化してしまう（2026-09-14に実際に踏んだ）。

    `_find_element_in_symbols` に緩和を入れてはならない理由（linter.py:649-655、
    golden set の sysml-broken-04）と同じ循環で、入口が違うだけ。
    """
    from sysml_v2_checker_advanced.linter import SysMLAdvancedLinter
    from sysml_v2_checker_advanced.parser import parse_sysml

    src = (
        "package Q { part v1 { part interior { part seatBelt; } } "
        "package U { public import v1::interior::noSuchLeaf; } }"
    )
    linter = SysMLAdvancedLinter()
    issues = linter.lint(parse_sysml(src))

    # import由来の名前は self.types に入っている（この前提が崩れたらテストの意味も変わる）
    assert "noSuchLeaf" in linter.types
    # それでも「型として存在する」とは見なさない
    assert linter._import_target_is_type_name("noSuchLeaf") is False
    assert len(issues) == 1


def test_qualified_reference_through_a_package_wildcard_import_is_not_flagged():
    """ワイルドカードimportを持つpackage経由の修飾参照を誤検出しない。

    `package P2a { public import P1::*; } ... part x : P2a::A;` の形。
    AはP1のメンバーだがP2aのimportで可視になっている。公式サンプル
    QualifiedNameImportTest.sysml 自身が "The following should not fail." と
    書いており、CircularImport.sysml の `part y : P1::B;` も同じ形。

    参照実装はどちらもクリーンと判定する（2026-09-14に実測）。
    """
    from sysml_v2_checker_advanced.parser import lint_sysml, parse_sysml

    via_import = (
        "package Q { package P1 { part def A; } "
        "package P2 { package P2a { public import P1::*; } part x : P2a::A; } }"
    )
    assert lint_sysml(parse_sysml(via_import)) == []

    circular = (
        "package Q { package P1 { public import P2::*; part def A; } "
        "package P2 { public import P1::*; part def B; } part y : P1::B; }"
    )
    assert lint_sysml(parse_sysml(circular)) == []


def test_qualified_reference_through_a_package_without_imports_is_still_flagged():
    """緩和はワイルドカードimportを持つpackageに限る。

    importを持たないpackage経由の誤った修飾参照（`P2b::A` で A は P1 のもの）は
    参照実装もエラーにするので、検出を維持する（2026-09-14に実測）。
    これを区別しないと「修飾名なら一律に検証不能」になり、制約が失われる。
    """
    from sysml_v2_checker_advanced.parser import lint_sysml, parse_sysml

    src = (
        "package Q { package P1 { part def A; } "
        "package P2 { package P2b { part def Z; } part x : P2b::A; } }"
    )
    issues = lint_sysml(parse_sysml(src))
    assert len(issues) == 1
    assert "P2b::A" in issues[0].message
