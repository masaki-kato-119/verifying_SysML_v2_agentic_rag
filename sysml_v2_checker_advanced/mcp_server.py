"""
SysML v2 Advanced Checker MCP Server

fastmcpを使用してSysML v2チェッカーをMCPサーバーとして公開
"""

import re
import sys
from pathlib import Path
from typing import Any, Dict, Optional

# パッケージのルートディレクトリをPythonパスに追加
current_dir = Path(__file__).parent
parent_dir = current_dir.parent
if str(parent_dir) not in sys.path:
    sys.path.insert(0, str(parent_dir))

from fastmcp import FastMCP  # noqa: E402

# 上でリポジトリルートをsys.pathに追加済みのため、常にこの絶対importで解決できる。
# 以前はImportError時に`from parser import ...`へフォールバックしていたが、
# 前者が失敗する状況(パッケージ自体が壊れている等)では後者も同じ原因で
# 失敗するため、実質デッドコードだった(SYSML_CHECKER_STANDALONE_AUDIT参照)。
from sysml_v2_checker_advanced.model_files import (  # noqa: E402
    OtherFiles,
    load_other_files,
    model_files,
)
from sysml_v2_checker_advanced.parser import parse_sysml  # noqa: E402
from sysml_v2_checker_advanced.semantic_model import (  # noqa: E402
    build_semantic_model,
    lint_text_with_locations,
    semantic_model_to_json_dict,
)
from sysml_v2_checker_advanced.utils import ast_to_json  # noqa: E402

# MCPサーバーインスタンスを作成
mcp = FastMCP("SysML v2 Advanced Checker")

@mcp.tool()
def parse_sysml_file(file_path: str) -> Dict[str, Any]:
    """
    SysMLファイルをパースしてASTを返す
    
    Args:
        file_path: SysMLファイルのパス
        
    Returns:
        パース結果（AST）とメタデータを含む辞書
    """
    try:
        # ファイルの存在確認
        path = Path(file_path)
        if not path.exists():
            return {
                "success": False,
                "error": f"ファイル '{file_path}' が見つかりません",
                "ast": None
            }
        
        # ファイル読み込み
        text = path.read_text(encoding="utf-8")
        
        # パース実行
        ast = parse_sysml(text)
        
        if ast.get("type") == "error":
            return {
                "success": False,
                "error": f"パースエラー: {ast.get('message')}",
                "ast": None
            }
        
        return {
            "success": True,
            "error": None,
            "ast": ast,
            "file_path": str(path.absolute()),
            "file_size": len(text)
        }
        
    # MCPツール境界: 想定外の例外もクライアントへのエラー応答に変換するため意図的に広く捕捉する
    except Exception as e:  # noqa: BLE001
        return {
            "success": False,
            "error": f"予期しないエラー: {str(e)}",
            "ast": None
        }

@mcp.tool()
def parse_sysml_text(sysml_text: str) -> Dict[str, Any]:
    """
    SysMLテキストを直接パースしてASTを返す
    
    Args:
        sysml_text: SysMLのテキスト内容
        
    Returns:
        パース結果（AST）とメタデータを含む辞書
    """
    try:
        # パース実行
        ast = parse_sysml(sysml_text)
        
        if ast.get("type") == "error":
            return {
                "success": False,
                "error": f"パースエラー: {ast.get('message')}",
                "ast": None
            }
        
        return {
            "success": True,
            "error": None,
            "ast": ast,
            "text_length": len(sysml_text)
        }
        
    # MCPツール境界: 想定外の例外もクライアントへのエラー応答に変換するため意図的に広く捕捉する
    except Exception as e:  # noqa: BLE001
        return {
            "success": False,
            "error": f"予期しないエラー: {str(e)}",
            "ast": None
        }

def _other_files(file_path: Optional[str], directory: Optional[str]) -> OtherFiles:
    """一緒に検証するほかのファイル（model_files の決まり。参照実装の validate_sysml と同じ）。"""
    base = Path(directory) if directory else (Path(file_path).parent if file_path else None)
    return load_other_files(model_files(file_path, directory), base=base)


def _scope_fields(others: OtherFiles, file_path: Optional[str], directory: Optional[str]) -> Dict[str, Any]:
    """結果の scope / loaded / unparsable_files / note（どのファイルと一緒に検証したか）。"""
    if not others.loaded and not others.unparsable:
        note = ("このファイル（テキスト）だけで検証しました。ほかのファイルの定義を参照しているなら、"
                "そのエラーはモデルの誤りとは限りません（directory を指定してください）。")
        return {"scope": "file", "loaded": [], "partial_files": [], "unparsable_files": [], "note": note}
    fields: Dict[str, Any] = {
        "scope": "directory",
        "directory": str(Path(directory).absolute()) if directory else str(Path(file_path).parent.absolute()),
        "loaded": others.loaded,
        "partial_files": others.partial,
        "unparsable_files": others.unparsable,
    }
    notes = []
    if others.partial:
        notes.append("構文エラーのあるファイルは、エラー回復で読めた部分だけを使いました（partial_files）。"
                     "そのファイルの定義への参照は、構文エラーを直すまで正しく確かめられないことがあります。")
    if others.unparsable:
        notes.append("構文エラーのため読めなかったファイルがあります（unparsable_files）。その中の定義への"
                     "参照は未解決になります。先にそのファイルの構文エラーを直してください。")
    if notes:
        fields["note"] = "".join(notes)
    return fields


_SYNTAX_POSITION = re.compile(r"\(line (\d+), column (\d+)\)")

# 構文エラーのあるテキストへの注意（2026-11-05）。以前は構文エラーがあると success=False と 1 つの
# 文字列だけを返し、行ごとの構文エラーも意味の指摘も返さなかった。LLM の初稿の 77% に参照実装の
# 構文エラーがある（eval/pilot_parity の 2 つ目の held-out）ので、エラー回復で読めた部分も検証して返す。
# 構文エラーより後ろの指摘は、参照実装と自作でエラー回復の仕方が違うため一致しないことがある
# （LLM の初稿では 96% 一致、要素をまとめて落とす書き方のファイルでは 52%。RESULTS.md の「構文エラーのあと」）
_SYNTAX_NOTE = ("構文エラーが {n} 件あります。先に構文エラー（syntax_error が true の指摘）を直してください。"
                "最初の構文エラー（{first} 行目）より後ろの指摘（after_syntax_error が true）は、エラー回復で"
                "読めた部分にもとづく暫定のもので、構文エラーを直すと変わることがあります。")


def _syntax_issues(message: str) -> list:
    """パースエラーの文字列（`; ` 区切り）を、行の付いた指摘に分ける。"""
    out = []
    for part in (message or "").split("; "):
        if not part.strip():
            continue
        match = _SYNTAX_POSITION.search(part)
        out.append({"severity": "error", "message": part, "rule": "parse", "element_id": None,
                    "source_range": None, "line": int(match.group(1)) if match else None, "syntax_error": True})
    return out


def _lint_result(text: str, others: OtherFiles, file_path: Optional[str], directory: Optional[str]) -> Dict[str, Any]:
    # パースとリント。指摘に行番号を付けるため、source_range を持つ経路でパースする。構文エラーがあっても
    # エラー回復で読めた部分を検証する（recover）
    ast, issues, issue_dicts = lint_text_with_locations(text, other_asts=others.asts, recover=True)
    syntax = _syntax_issues(ast.get("message", "")) if ast.get("type") == "error" else []
    # 自作の文法は参照実装より寛容で、`import X::*;`（可視性の無い import）などは読めたうえで
    # _check_official_syntax_constraints が指摘する。参照実装では構文エラーなので、構文エラーとして数える
    for data in issue_dicts:
        if data.get("rule") == "_check_official_syntax_constraints" and data.get("severity") == "error":
            data["syntax_error"] = True
    official = [d for d in issue_dicts if d.get("syntax_error")]
    note_extra = None
    if syntax or official:
        lines = [i["line"] for i in syntax + official if i.get("line") is not None]
        first = min(lines) if lines else 1
        for data in issue_dicts:
            if not data.get("syntax_error"):
                data["after_syntax_error"] = data.get("line") is None or data["line"] > first
        note_extra = _SYNTAX_NOTE.format(n=len(syntax) + len(official), first=first)
    all_issues = syntax + issue_dicts

    # 問題の集計
    summary = {
        "total": len(all_issues),
        "errors": len([i for i in all_issues if i.get("severity") == "error"]),
        "warnings": len([i for i in all_issues if i.get("severity") == "warning"]),
        "info": len([i for i in all_issues if i.get("severity") == "info"]),
        "syntax_errors": len(syntax) + len(official),
    }
    result = {
        "success": True,
        "error": None,
        "issues": all_issues,
        "summary": summary,
        **_scope_fields(others, file_path, directory),
    }
    if note_extra:
        result["note"] = note_extra + (result.get("note") or "")
    return result


@mcp.tool()
def lint_sysml_file(file_path: str, directory: Optional[str] = None) -> Dict[str, Any]:
    """
    SysMLファイルをリント（構文チェック）して問題を報告

    複数ファイルのモデルに対応する。directory を省略すると、同じフォルダの .sysml
    （サブフォルダは含めない）を一緒に読み込み、ファイルをまたぐ import・参照を解決する
    （ほかのファイルの要素の名前の誤記も見つける）。指摘は file_path のファイルについてだけ返す。

    Args:
        file_path: SysMLファイルのパス
        directory: 複数ファイルのモデルのフォルダ。フォルダ内（サブフォルダも含む）の .sysml を
            すべて一緒に読み込む。"" ならほかのファイルを読み込まない（1ファイルだけで検証）。

    Returns:
        リント結果と問題のリストを含む辞書。issues の各要素は重大度・メッセージ・
        rule・element_id・source_range に加え、指摘の行番号 `line`（1始まり。
        位置の分からない指摘は None）を持つ。scope は "file"（そのファイルだけで検証）か
        "directory"（ほかのファイルと一緒に検証）。loaded は一緒に読み込んだファイル、
        unparsable_files は構文エラーで読めなかったファイル。note は結果を読むときの注意。
        構文エラーがあると、行ごとの構文エラー（rule が "parse"、syntax_error が true）と、エラー回復で
        読めた部分の指摘を返す。最初の構文エラーより後ろの指摘は after_syntax_error が true（暫定）。
        summary.syntax_errors は構文エラーの件数
    """
    try:
        # ファイルの存在確認
        path = Path(file_path)
        if not path.exists():
            return {
                "success": False,
                "error": f"ファイル '{file_path}' が見つかりません",
                "issues": [],
                "summary": {"total": 0, "errors": 0, "warnings": 0, "info": 0}
            }

        # ファイル読み込み
        text = path.read_text(encoding="utf-8")
        result = _lint_result(text, _other_files(file_path, directory), file_path, directory)
        if result["success"]:
            result["file_path"] = str(path.absolute())
            result["file_size"] = len(text)
        return result

    # MCPツール境界: 想定外の例外もクライアントへのエラー応答に変換するため意図的に広く捕捉する
    except Exception as e:  # noqa: BLE001
        return {
            "success": False,
            "error": f"予期しないエラー: {str(e)}",
            "issues": [],
            "summary": {"total": 0, "errors": 0, "warnings": 0, "info": 0}
        }

@mcp.tool()
def lint_sysml_text(sysml_text: str, file_path: Optional[str] = None,
                    directory: Optional[str] = None) -> Dict[str, Any]:
    """
    SysMLテキストを直接リント（構文チェック）して問題を報告

    Args:
        sysml_text: SysMLのテキスト内容
        file_path: このテキストで置き換えるファイル（保存前の確認）。directory を省略すると、
            同じフォルダの .sysml を一緒に読み込む。
        directory: 複数ファイルのモデルのフォルダ。フォルダ内（サブフォルダも含む）の .sysml を
            すべて一緒に読み込む（file_path のファイルは除く）。file_path も directory も無ければ
            テキストだけで検証する。

    Returns:
        リント結果と問題のリストを含む辞書。issues の各要素は重大度・メッセージ・
        rule・element_id・source_range に加え、指摘の行番号 `line`（1始まり。
        位置の分からない指摘は None）を持つ。scope・loaded・unparsable_files・note は
        lint_sysml_file と同じ
    """
    try:
        result = _lint_result(sysml_text, _other_files(file_path, directory), file_path, directory)
        if result["success"]:
            result["text_length"] = len(sysml_text)
        return result

    # MCPツール境界: 想定外の例外もクライアントへのエラー応答に変換するため意図的に広く捕捉する
    except Exception as e:  # noqa: BLE001
        return {
            "success": False,
            "error": f"予期しないエラー: {str(e)}",
            "issues": [],
            "summary": {"total": 0, "errors": 0, "warnings": 0, "info": 0}
        }

@mcp.tool()
def get_ast_json(file_path: str, pretty: bool = True) -> Dict[str, Any]:
    """
    SysMLファイルのASTをJSON形式で取得（RAG用）
    
    Args:
        file_path: SysMLファイルのパス
        pretty: JSON整形するかどうか
        
    Returns:
        AST JSON文字列とメタデータを含む辞書
    """
    try:
        # ファイルの存在確認
        path = Path(file_path)
        if not path.exists():
            return {
                "success": False,
                "error": f"ファイル '{file_path}' が見つかりません",
                "ast_json": None
            }
        
        # ファイル読み込み
        text = path.read_text(encoding="utf-8")
        
        # パース実行
        ast = parse_sysml(text)
        
        if ast.get("type") == "error":
            return {
                "success": False,
                "error": f"パースエラー: {ast.get('message')}",
                "ast_json": None
            }
        
        # AST to JSON
        ast_json = ast_to_json(ast, pretty=pretty)
        
        return {
            "success": True,
            "error": None,
            "ast_json": ast_json,
            "file_path": str(path.absolute()),
            "file_size": len(text)
        }
        
    # MCPツール境界: 想定外の例外もクライアントへのエラー応答に変換するため意図的に広く捕捉する
    except Exception as e:  # noqa: BLE001
        return {
            "success": False,
            "error": f"予期しないエラー: {str(e)}",
            "ast_json": None
        }

@mcp.tool()
def analyze_sysml_complete(file_path: str) -> Dict[str, Any]:
    """
    SysMLファイルの完全解析（パース + リント + AST JSON）
    
    Args:
        file_path: SysMLファイルのパス
        
    Returns:
        完全な解析結果を含む辞書
    """
    try:
        # ファイルの存在確認
        path = Path(file_path)
        if not path.exists():
            return {
                "success": False,
                "error": f"ファイル '{file_path}' が見つかりません",
                "ast": None,
                "issues": [],
                "summary": {"total": 0, "errors": 0, "warnings": 0, "info": 0},
                "ast_json": None
            }
        
        # ファイル読み込み
        text = path.read_text(encoding="utf-8")
        
        # パースとリント。指摘に行番号を付けるため、source_range を持つ経路でパースする
        ast, issues, issue_dicts = lint_text_with_locations(text)
        
        if ast.get("type") == "error":
            return {
                "success": False,
                "error": f"パースエラー: {ast.get('message')}",
                "ast": None,
                "issues": [],
                "summary": {"total": 0, "errors": 0, "warnings": 0, "info": 0},
                "ast_json": None
            }
        
        # 問題の集計
        summary = {
            "total": len(issues),
            "errors": len([i for i in issues if i.severity == "error"]),
            "warnings": len([i for i in issues if i.severity == "warning"]),
            "info": len([i for i in issues if i.severity == "info"])
        }
        
        # AST to JSON
        ast_json = ast_to_json(ast, pretty=True)
        
        return {
            "success": True,
            "error": None,
            "ast": ast,
            "issues": issue_dicts,
            "summary": summary,
            "ast_json": ast_json,
            "file_path": str(path.absolute()),
            "file_size": len(text)
        }
        
    # MCPツール境界: 想定外の例外もクライアントへのエラー応答に変換するため意図的に広く捕捉する
    except Exception as e:  # noqa: BLE001
        return {
            "success": False,
            "error": f"予期しないエラー: {str(e)}",
            "ast": None,
            "issues": [],
            "summary": {"total": 0, "errors": 0, "warnings": 0, "info": 0},
            "ast_json": None
        }

@mcp.tool()
def get_semantic_model_file(file_path: str) -> Dict[str, Any]:
    """
    SysMLファイルのSemantic Modelを取得（stable ID・source range・参照エッジ）

    AST（パース木そのもの）と異なり、Semantic Modelは各要素へ再解析に依存しない
    安定したID（stable_id）、元テキスト上の位置（source_range）、および
    specialization/feature_typing/connection/satisfy/verify等の参照エッジを
    付与した索引（SysMLv2_SemanticModel_拡張仕様書.md 4,6,7,8章）。
    Viewer等でテキスト⇔図の同期やトレーサビリティを実現する土台。

    Args:
        file_path: SysMLファイルのパス

    Returns:
        Semantic Model（ノード索引・エッジ）とメタデータを含む辞書
    """
    try:
        path = Path(file_path)
        if not path.exists():
            return {
                "success": False,
                "error": f"ファイル '{file_path}' が見つかりません",
                "semantic_model": None
            }

        text = path.read_text(encoding="utf-8")
        ast, model = build_semantic_model(text)

        if ast.get("type") == "error":
            return {
                "success": False,
                "error": f"パースエラー: {ast.get('message')}",
                "semantic_model": None
            }

        return {
            "success": True,
            "error": None,
            "semantic_model": semantic_model_to_json_dict(model),
            "file_path": str(path.absolute()),
            "file_size": len(text)
        }

    # MCPツール境界: 想定外の例外もクライアントへのエラー応答に変換するため意図的に広く捕捉する
    except Exception as e:  # noqa: BLE001
        return {
            "success": False,
            "error": f"予期しないエラー: {str(e)}",
            "semantic_model": None
        }

@mcp.tool()
def get_semantic_model_text(sysml_text: str) -> Dict[str, Any]:
    """
    SysMLテキストのSemantic Modelを直接取得（stable ID・source range・参照エッジ）

    get_semantic_model_fileと同じSemantic Model（拡張仕様書4,6,7,8章）を、
    ファイルではなくテキストから直接構築する。

    Args:
        sysml_text: SysMLのテキスト内容

    Returns:
        Semantic Model（ノード索引・エッジ）とメタデータを含む辞書
    """
    try:
        ast, model = build_semantic_model(sysml_text)

        if ast.get("type") == "error":
            return {
                "success": False,
                "error": f"パースエラー: {ast.get('message')}",
                "semantic_model": None
            }

        return {
            "success": True,
            "error": None,
            "semantic_model": semantic_model_to_json_dict(model),
            "text_length": len(sysml_text)
        }

    # MCPツール境界: 想定外の例外もクライアントへのエラー応答に変換するため意図的に広く捕捉する
    except Exception as e:  # noqa: BLE001
        return {
            "success": False,
            "error": f"予期しないエラー: {str(e)}",
            "semantic_model": None
        }

@mcp.tool()
def get_server_info() -> Dict[str, Any]:
    """
    SysML v2 Advanced Checker MCPサーバーの情報を取得

    Returns:
        サーバー情報を含む辞書
    """
    return {
        "name": "SysML v2 Advanced Checker MCP Server",
        "version": "1.0.0",
        "description": "SysML v2ファイルのパース、リント、AST生成を行うMCPサーバー",
        "capabilities": [
            "SysMLファイルのパース",
            "SysMLテキストの直接パース",
            "構文チェック（リント。複数ファイルのモデルはフォルダごと名前解決）",
            "AST生成（JSON形式）",
            "完全解析（パース + リント + AST）",
            "Semantic Model生成（stable ID・source range・参照エッジ）"
        ],
        "tools": [
            "parse_sysml_file",
            "parse_sysml_text",
            "lint_sysml_file",
            "lint_sysml_text",
            "get_ast_json",
            "analyze_sysml_complete",
            "get_semantic_model_file",
            "get_semantic_model_text",
            "get_server_info"
        ]
    }

if __name__ == "__main__":
    # MCPサーバーを起動
    mcp.run()