"""構文エラーのあるテキストの MCP lint（2026-11-05、eval/pilot_parity の「構文エラーのあと」）。

以前は構文エラーがあると success=False と 1 つの文字列だけを返した。今は行ごとの構文エラーと、
エラー回復で読めた部分の指摘を返し、最初の構文エラーより後ろの指摘に after_syntax_error を付ける。
"""

from sysml_v2_checker_advanced import mcp_server

lint_text = getattr(mcp_server.lint_sysml_text, "fn", mcp_server.lint_sysml_text)


def test_parse_error_returns_lined_syntax_issue_and_recovered_findings():
    text = ("package P {\n"
            "  part def A;\n"
            "  part a : Missing1;\n"
            "  part b : A { attribute x = 1 }\n"  # `;` が無い（構文エラー）
            "  part c : Missing2;\n"
            "}\n")
    result = lint_text(text)
    assert result["success"] is True
    syntax = [i for i in result["issues"] if i.get("syntax_error")]
    assert syntax and all(i["rule"] == "parse" for i in syntax)
    assert {i["line"] for i in syntax} == {4}
    assert result["summary"]["syntax_errors"] == len(syntax)
    by_line = {i["line"]: i for i in result["issues"] if not i.get("syntax_error")}
    assert by_line[3]["after_syntax_error"] is False  # 構文エラーより前は確か
    assert by_line[5]["after_syntax_error"] is True   # 後ろは暫定
    assert "構文エラー" in result["note"]


def test_import_without_visibility_counts_as_syntax_error():
    # 自作の文法は読めるが、参照実装では構文エラー（可視性の無い import）
    text = "package P {\n  import ScalarValues::*;\n  attribute m : Real;\n}\n"
    result = lint_text(text)
    assert result["summary"]["syntax_errors"] == 1
    official = [i for i in result["issues"] if i.get("syntax_error")]
    assert official[0]["line"] == 2
    assert all(i.get("after_syntax_error") for i in result["issues"] if not i.get("syntax_error"))


def test_valid_text_has_no_syntax_fields():
    result = lint_text("package P { part def A; part a : A; }")
    assert result["success"] is True
    assert result["summary"]["syntax_errors"] == 0
    assert all("after_syntax_error" not in i for i in result["issues"])
