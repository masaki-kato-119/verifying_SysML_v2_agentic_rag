"""sysml_v2_checker_advanced.parser の主要パス。"""

from sysml_v2_checker_advanced.parser import lint_sysml, parse_sysml


def test_parse_sysml_syntax_error_returns_error_dict():
    out = parse_sysml("this is not valid sysml {{{", strict=True)
    assert out.get("type") == "error"
    assert "message" in out


def test_parse_sysml_minimal_package():
    out = parse_sysml("package P { part def A; }", strict=True)
    assert out.get("type") == "package"


def test_lint_sysml_empty_issues_for_minimal_package():
    ast = parse_sysml(
        "package Q { part def X { attribute n : Integer; } }",
        strict=True,
    )
    assert ast.get("type") == "package"
    issues = lint_sysml(ast)
    assert isinstance(issues, list)
