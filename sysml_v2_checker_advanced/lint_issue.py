"""LintIssue: リンターで検出された問題を表すデータクラス。

linter.py と各 linter_rules/*.py の両方から参照されるため、循環importを避けて
独立モジュールに置く。"""

from dataclasses import dataclass
from typing import Dict, Optional


@dataclass
class LintIssue:
    """
    リンターで検出された問題を表すデータクラス
    
    Attributes:
        severity: 重大度（"error", "warning", "info"）
        message: エラーメッセージ
        node: 問題が発生したASTノード（オプション）
        line: 行番号（オプション）
    """
    severity: str
    message: str
    node: Optional[Dict] = None
    line: Optional[int] = None
    
    def to_dict(self) -> Dict:
        """
        辞書形式に変換
        
        Returns:
            重大度、メッセージ、行番号を含む辞書
        """
        return {
            "severity": self.severity,
            "message": self.message,
            "line": self.line
        }
