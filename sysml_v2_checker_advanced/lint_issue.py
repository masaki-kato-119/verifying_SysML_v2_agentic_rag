"""LintIssue: リンターで検出された問題を表すデータクラス。

linter.py と各 linter_rules/*.py の両方から参照されるため、循環importを避けて
独立モジュールに置く。"""

import sys
from dataclasses import dataclass, field
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
        rule: この指摘を生成したチェックメソッド名（`__post_init__`が
            呼び出し元フレームから自動取得する。詳細は`__post_init__`参照）
    """
    severity: str
    message: str
    node: Optional[Dict] = None
    line: Optional[int] = None
    rule: Optional[str] = field(default=None, init=False)

    def __post_init__(self) -> None:
        """呼び出し元（`linter.py`/`linter_rules/*.py`内の`_check_*`メソッド等）の
        関数名を`rule`として自動取得する。

        `LintIssue(...)`の構築箇所は161件あり（2026-09-03、Group1 b3b調査時点）、
        全箇所に`rule=`引数を手で追加するのは非現実的かつミスの温床になるため、
        呼び出し元フレームから自動取得する設計にした（`linter_rules/*.py`は
        無変更のまま`rule`が付与される）。`sys._getframe`はCPython固有のAPIだが、
        本プロジェクトはCPython前提（`.venv`もCPython）のため許容する。
        フレーム取得に失敗した場合（将来的な実行環境の違い等）は`rule=None`のまま
        グレースフルに動作する。
        """
        try:
            # フレーム0=__post_init__自身、フレーム1=dataclass自動生成の__init__、
            # フレーム2=実際の呼び出し元（例: `_check_import`）。
            caller_frame = sys._getframe(2)
            self.rule = caller_frame.f_code.co_name
        except (ValueError, AttributeError):
            self.rule = None

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
            重大度・メッセージ・ルール識別子・element_id・source_rangeを含む辞書
        """
        entry = (
            element_index.get(id(self.node))
            if element_index is not None and self.node is not None
            else None
        )
        return {
            "severity": self.severity,
            "message": self.message,
            "rule": self.rule,
            "element_id": entry.get("element_id") if entry else None,
            "source_range": entry.get("source_range") if entry else None,
        }
