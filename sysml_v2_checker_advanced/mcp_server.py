"""
SysML v2 Advanced Checker MCP Server

fastmcpを使用してSysML v2チェッカーをMCPサーバーとして公開
"""

import sys
from pathlib import Path
from typing import Any, Dict

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
from sysml_v2_checker_advanced.parser import lint_sysml, parse_sysml  # noqa: E402
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

@mcp.tool()
def lint_sysml_file(file_path: str) -> Dict[str, Any]:
    """
    SysMLファイルをリント（構文チェック）して問題を報告
    
    Args:
        file_path: SysMLファイルのパス
        
    Returns:
        リント結果と問題のリストを含む辞書
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
        
        # パース実行
        ast = parse_sysml(text)
        
        if ast.get("type") == "error":
            return {
                "success": False,
                "error": f"パースエラー: {ast.get('message')}",
                "issues": [],
                "summary": {"total": 0, "errors": 0, "warnings": 0, "info": 0}
            }
        
        # リント実行
        issues = lint_sysml(ast)
        
        # 問題の集計
        summary = {
            "total": len(issues),
            "errors": len([i for i in issues if i.severity == "error"]),
            "warnings": len([i for i in issues if i.severity == "warning"]),
            "info": len([i for i in issues if i.severity == "info"])
        }
        
        return {
            "success": True,
            "error": None,
            "issues": [issue.to_dict() for issue in issues],
            "summary": summary,
            "file_path": str(path.absolute()),
            "file_size": len(text)
        }
        
    # MCPツール境界: 想定外の例外もクライアントへのエラー応答に変換するため意図的に広く捕捉する
    except Exception as e:  # noqa: BLE001
        return {
            "success": False,
            "error": f"予期しないエラー: {str(e)}",
            "issues": [],
            "summary": {"total": 0, "errors": 0, "warnings": 0, "info": 0}
        }

@mcp.tool()
def lint_sysml_text(sysml_text: str) -> Dict[str, Any]:
    """
    SysMLテキストを直接リント（構文チェック）して問題を報告
    
    Args:
        sysml_text: SysMLのテキスト内容
        
    Returns:
        リント結果と問題のリストを含む辞書
    """
    try:
        # パース実行
        ast = parse_sysml(sysml_text)
        
        if ast.get("type") == "error":
            return {
                "success": False,
                "error": f"パースエラー: {ast.get('message')}",
                "issues": [],
                "summary": {"total": 0, "errors": 0, "warnings": 0, "info": 0}
            }
        
        # リント実行
        issues = lint_sysml(ast)
        
        # 問題の集計
        summary = {
            "total": len(issues),
            "errors": len([i for i in issues if i.severity == "error"]),
            "warnings": len([i for i in issues if i.severity == "warning"]),
            "info": len([i for i in issues if i.severity == "info"])
        }
        
        return {
            "success": True,
            "error": None,
            "issues": [issue.to_dict() for issue in issues],
            "summary": summary,
            "text_length": len(sysml_text)
        }
        
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
        
        # パース実行
        ast = parse_sysml(text)
        
        if ast.get("type") == "error":
            return {
                "success": False,
                "error": f"パースエラー: {ast.get('message')}",
                "ast": None,
                "issues": [],
                "summary": {"total": 0, "errors": 0, "warnings": 0, "info": 0},
                "ast_json": None
            }
        
        # リント実行
        issues = lint_sysml(ast)
        
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
            "issues": [issue.to_dict() for issue in issues],
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
            "構文チェック（リント）",
            "AST生成（JSON形式）",
            "完全解析（パース + リント + AST）"
        ],
        "tools": [
            "parse_sysml_file",
            "parse_sysml_text", 
            "lint_sysml_file",
            "lint_sysml_text",
            "get_ast_json",
            "analyze_sysml_complete",
            "get_server_info"
        ]
    }

if __name__ == "__main__":
    # MCPサーバーを起動
    mcp.run()