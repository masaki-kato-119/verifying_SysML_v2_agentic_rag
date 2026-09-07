"""LintIssue: リンターで検出された問題を表すデータクラス。

linter.py と各 linter_rules/*.py の両方から参照されるため、循環importを避けて
独立モジュールに置く。"""

import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Optional


# ルール別 confidence の実測テーブル。`scripts/recheck_local_only.py --rule-stats`
# が 730 件コーパスの参照実装比較から生成したものを、レビューしたうえでここへ
# 取り込む（生成方法と数値の意味は同スクリプトの `build_rule_agreement` を参照）。
_RULE_CONFIDENCE_PATH = Path(__file__).with_name("rule_confidence.json")
_rule_confidence_document: Optional[Dict[str, Any]] = None


def _rule_confidence() -> Dict[str, Any]:
    """confidence テーブルを読む（初回のみ。以後はキャッシュ）。

    テーブルが無い・壊れている場合は空として扱い、confidence を出さないだけに
    する。チェッカー本体の動作は confidence の有無に依存しない。
    """
    global _rule_confidence_document
    if _rule_confidence_document is None:
        try:
            _rule_confidence_document = json.loads(
                _RULE_CONFIDENCE_PATH.read_text(encoding="utf-8")
            )
        except (OSError, ValueError):
            _rule_confidence_document = {}
    return _rule_confidence_document


_RULE_NAME_PREFIX = "_check_"
# リンターの入口。ここより外側は呼び出し側のコードなので探索を打ち切る。
_LINTER_ENTRY_POINT = "lint"
# 再帰走査の深さぶんだけフレームを遡ることがあるので余裕を持たせる。
_RULE_FRAME_SEARCH_LIMIT = 200


def _caller_rule_name(base_depth: int) -> Optional[str]:
    """呼び出し元スタックを外側へ辿り、最初に見つかる `_check_*` を rule とする。

    素朴に1段だけ遡る実装だと、`_check_*` メソッドの内側に定義したローカル関数
    （AST を再帰走査する `walk` など）から `LintIssue` を作ったときに rule が
    `walk` になり、**別々のルールが同じ名前へ潰れる**。2026-09-07 に 730 件
    コーパスのルール別集計を取ったところ、実際に2つのルール
    （`_check_verify_requirement_placement` と
    `_check_package_level_feature_redefinition`）が `walk` に潰れていた。

    rule は confidence テーブルのキーであり、Viewer の Finding の同一性判定
    （`viewer/frontend/app.js` の `element_id::rule::message`）にも使われるため、
    名前が一意でないと「どのルールの数字か」「どの指摘へのレビュー状態か」が
    決まらなくなる。

    `_check_*` が見つからないまま `lint` まで辿り着いた場合は、従来どおり
    `base_depth` のフレーム名を返す（`lint` が直接構築する型システムの指摘が
    これに当たり、rule は `lint` のままになる）。
    """
    fallback: Optional[str] = None
    for depth in range(base_depth, base_depth + _RULE_FRAME_SEARCH_LIMIT):
        try:
            name = sys._getframe(depth).f_code.co_name
        except ValueError:  # スタックの底に達した
            break
        if fallback is None:
            fallback = name
        if name.startswith(_RULE_NAME_PREFIX):
            return name
        if name == _LINTER_ENTRY_POINT:
            break
    return fallback


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

        2026-09-07: 1段だけ遡ると`_check_*`内のローカル関数名を拾ってしまうため、
        `_caller_rule_name`が`_check_*`まで外側へ辿るようにした（理由は同関数の
        docstringを参照）。
        """
        try:
            # `_caller_rule_name`から見て、フレーム0=`_caller_rule_name`自身、
            # フレーム1=`__post_init__`、フレーム2=dataclass自動生成の`__init__`、
            # フレーム3=実際の呼び出し元（例: `_check_import`）。
            self.rule = _caller_rule_name(base_depth=3)
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
            重大度・メッセージ・ルール識別子・element_id・source_range・
            confidenceを含む辞書
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
            "confidence": self.confidence(),
        }

    def confidence(self) -> Optional[Dict[str, Any]]:
        """このルールが参照実装とどれだけ一致したかの実測値（測っていなければNone）。

        構想書§12-4「AIは結論だけでなく、対象、根拠、影響、確信度を示す」に
        対応する。数値の供給源は**730件コーパスの参照実装比較の実測のみ**で、
        LLMにもヒューリスティックにも由来しない（GraphRAG側のconfidenceは
        0.9/0.6/0.3のベタ書き等、測定に基づかない手置きの定数なので流用しない）。

        値だけでなく `basis`・`caveat`・単独発火の内訳を必ず一緒に返す。
        `value` は「参照実装も同じファイルを不正と判定した割合」であって
        「同じ箇所を同じ理由で指摘した割合」ではなく、一致率の**上限**である。
        呼び出し側が数値だけを切り出して提示できてしまうと、この区別が
        利用者へ伝わらない。

        単独発火が閾値（テーブルの `min_samples`）に満たないルールは
        テーブルに載っておらず、Noneが返る。**推定で埋めない**（「未測定」と
        「測ったが低い」を混同させないため）。
        """
        if not self.rule:
            return None
        document = _rule_confidence()
        measured = document.get("rules", {}).get(self.rule)
        if not measured:
            return None
        return {
            "value": measured["value"],
            "sole_agree": measured["sole_agree"],
            "sole_disagree": measured["sole_disagree"],
            "basis": document.get("basis"),
            "caveat": document.get("caveat"),
            "measured_at": document.get("generated_at"),
        }
