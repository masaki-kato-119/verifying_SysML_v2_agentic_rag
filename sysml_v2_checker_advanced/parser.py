"""
SysML v2 Advanced Checker Parser

パーサー機能

既定パーサーはANTLR4ベースの実装（antlr_transformer.parse_sysml_antlr）を使用する。
"""

from typing import Dict, List

from .antlr_transformer import parse_sysml_antlr
from .linter import LintIssue


def parse_sysml(text: str, strict: bool = True) -> Dict:
    """
    SysMLテキストをパースしてASTを返す

    Args:
        text: SysML v2のテキスト
        strict: 後方互換のために残しているパラメータ（現在は無視される）。

    Returns:
        パース済みのAST、またはエラーの場合は{"type": "error", "message": "..."}
    """
    return parse_sysml_antlr(text)


def lint_sysml(ast: Dict, known_external_types: set | None = None) -> List[LintIssue]:
    """
    ASTをリンターでチェック

    Args:
        ast: パース済みのAST
        known_external_types: 他ファイル（`import`経由）に実在する型名の集合。1ファイル単位の
            チェックでは解決できないクロスファイル型参照を、既知の外部型名
            として扱うことで「存在しない型」の誤検出を避ける。省略時
            （デフォルトNone）は単体ファイル動作のままとなる。

    Returns:
        検出された問題のリスト
    """
    from .linter import SysMLAdvancedLinter
    linter = SysMLAdvancedLinter()
    return linter.lint(ast, known_external_types=known_external_types)
