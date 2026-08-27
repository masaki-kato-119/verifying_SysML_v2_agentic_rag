"""パース成功する最小 SysML を lint_sysml（SysMLAdvancedLinter）まで通す結合テスト。

同梱の test_sysml.sysml は現行パーサと一部構文が合わず error になり得るため、
ここではパーサが受理する本文をテスト内に明示する。
"""

from sysml_v2_checker_advanced.parser import lint_sysml, parse_sysml

_VALID_MINIMAL = """
package TestPackage {
    part def Vehicle {
        attribute mass : Real;
    }
    part testVehicle : Vehicle {
    }
}
"""


def test_parse_sysml_then_lint_minimal():
    ast = parse_sysml(_VALID_MINIMAL.strip(), strict=True)
    assert ast.get("type") == "package"
    issues = lint_sysml(ast)
    assert isinstance(issues, list)
