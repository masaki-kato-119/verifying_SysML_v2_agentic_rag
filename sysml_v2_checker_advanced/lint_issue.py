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
        line: 行番号（オプション。実際にこの値を設定する呼び出し元はなく、
            常にNoneのまま。位置情報が必要な場合は to_dict(element_index)
            経由で source_range を使うこと）
    """
    severity: str
    message: str
    node: Optional[Dict] = None
    line: Optional[int] = None

    def to_dict(self, element_index: Optional[Dict[int, Dict]] = None) -> Dict:
        """
        辞書形式に変換

        Args:
            element_index: `id(node) -> {"element_id": stable_id, "source_range": {...}}`
                の事前構築済み索引（省略時は element_id/source_range とも None）。
                `sysml_v2_checker_advanced.semantic_model.build_element_index()` で、
                この LintIssue が指す `node` と同じ ast から構築した
                semantic_model を渡して作る（拡張仕様書9章）。circular import
                を避けるため、ここでは semantic_model.py を import しない
                （呼び出し側が索引を構築して渡す設計）。

        Returns:
            重大度・メッセージ・element_id・source_rangeを含む辞書
        """
        entry = (
            element_index.get(id(self.node))
            if element_index is not None and self.node is not None
            else None
        )
        return {
            "severity": self.severity,
            "message": self.message,
            "element_id": entry.get("element_id") if entry else None,
            "source_range": entry.get("source_range") if entry else None,
        }
