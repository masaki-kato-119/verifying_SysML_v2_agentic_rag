"""
SysML v2 Advanced Checker Package

より完全なSysML v2文法に対応したAST＋高度ルールチェッカー

機能:
- 完全なSysML v2文法のサポート（package, part, action, type, connection, requirement, port, state等）
- ASTベースの構造解析（ANTLR4パーサー使用、Java不要）
- 参照整合性チェック（存在しない型・要素の参照検出）
- 型チェック（型の一貫性検証）
- 接続チェック（from/toの参照検証）
- 要件定義の参照チェック（satisfiedBy検証）
- ポート定義のチェック（継承の型参照検証）
- 多重度の形式検証（[n..m]の範囲チェック、無効な形式の検出）
- 名前空間の解決チェック（import/exposeのパス解決）
- ステートマシン関連のチェック（state_def, transition, initial/final）
- 継承の整合性チェック（循環継承の検出）
- ASTのJSON化（RAG + GPT統合用）
- コマンドラインリンター対応（CI/CD統合可能）

使用例:
    # Python APIから
    from sysml_v2_checker_advanced import parse_sysml, lint_sysml
    ast = parse_sysml(sysml_text)
    issues = lint_sysml(ast)

**公開契約について**: このプロジェクトの公開インターフェースは
``sysml_v2_checker_advanced/mcp_server.py``（MCPサーバー、stdio経由）と、
この ``__init__.py`` が ``__all__`` でエクスポートするPython API
（``parse_sysml``/``lint_sysml``/``LintIssue``/``ast_to_json``/
``BUILTIN_TYPES``等）です。それ以外の内部モジュール
（``antlr_transformer``/``type_system``/``expression_type_inference``や
``linter.py`` のプライベートメソッド群）は実装詳細であり、安定性は
保証されません。
"""

from .constants import BUILTIN_TYPES, SEVERITY_ERROR, SEVERITY_INFO, SEVERITY_WARNING
from .linter import LintIssue
from .parser import lint_sysml, parse_sysml
from .utils import ast_to_json

__all__ = [
    'parse_sysml',
    'lint_sysml', 
    'LintIssue',
    'ast_to_json',
    'BUILTIN_TYPES',
    'SEVERITY_ERROR',
    'SEVERITY_WARNING', 
    'SEVERITY_INFO'
]