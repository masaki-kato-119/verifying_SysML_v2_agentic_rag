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
