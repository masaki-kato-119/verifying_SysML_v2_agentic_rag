"""Findingに添える修正候補（Viewer Phase C の c4、構想書§11 Phase Dへの橋渡し）。

## スコープ

**提示のみ。** 候補の適用・再パース・再検証は構想書§11のPhase Dの範囲であり、
ここでは行わない。したがってこのモジュールが返すのは「どう書き換える案か」を
機械可読で表したデータだけで、テキストを書き換える処理は持たない。

## なぜ全ルールを埋めないのか

意味ルールで確立した方針（実測できた範囲に限る／取りこぼしは許容するが誤りは
出さない）と同じ。**書き換え方が一意に決まるルールにだけ候補を付ける。**
候補が無いFindingは`suggestion=None`のままで良く、UI側は「候補なし」を
そのまま表示する。もっともらしいだけの候補は、指摘そのものの信頼を削る。

## なぜルール名キーの一覧表ではなく構築箇所で付けるのか

`rule`（`LintIssue.__post_init__`が自動取得する）をキーにした表にすると、
候補を組み立てる関数がFindingのnodeしか見られない。しかし多くの候補は
「そのルールが何を根拠に落としたか」を知らないと作れない
（例: accessible feature pathでは**どの`::`境界**を不正と判断したかが必要で、
node全体からは復元できない）。ルール側は既にその情報を持っているので、
`LintIssue(..., suggestion=...)`として渡す。

`rule`を161箇所へ手で足すのを避けた判断とは前提が違う。`rule`は全Findingに
必要な普遍的な属性だが、候補は少数のルールにだけ付ける任意項目なので、
構築箇所を触る範囲が小さく収まる。文言と組み立てはこのモジュールへ集約し、
ルール側は1行呼ぶだけにしてある（候補の言い回しを一箇所でレビューできる）。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence, Tuple

# 候補は必ず提案として提示する。UI側が但し書きを落とせないよう、値と同じ
# 辞書に入れて返す（confidenceと同じ考え方。lint_issue.py参照）。
CAVEAT = (
    "修正候補は提案であって正解とは限りません。意味が変わる場合があるので、"
    "適用する前に必ず内容を確認してください。"
)


@dataclass(frozen=True)
class FixCandidate:
    """1件の修正候補。

    Attributes:
        title: 何をする候補かの一行。
        detail: なぜそう直すのかの説明。
        find: 書き換え対象の文字列（省略時は書き換え案を持たない助言だけの候補）。
        replace: `find`をこれに置き換える。
    """

    title: str
    detail: str
    find: Optional[str] = None
    replace: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """`LintIssue.to_dict()`が返す形。

        `edit`は「そのFindingの`source_range`の中に現れる最初の`find`を
        `replace`へ置き換える」という意味に決めてある。トークン単位の正確な
        列位置をリンター側で計算せずに済み、Phase Dで差分を作るときは
        source_rangeの範囲だけを見れば適用できる。
        """
        edit = None
        if self.find is not None and self.replace is not None:
            edit = {"find": self.find, "replace": self.replace}
        return {
            "title": self.title,
            "detail": self.detail,
            "edit": edit,
            "caveat": CAVEAT,
        }


def _rebuild_reference(segments: Sequence[Tuple[str, Optional[str]]]) -> str:
    """`segments`（`(名前, 直前の区切り)`の列）を参照文字列へ戻す。"""
    parts: List[str] = []
    for position, (name, separator) in enumerate(segments):
        if position > 0 and separator:
            parts.append(separator)
        parts.append(name)
    return "".join(parts)


def use_dot_for_nesting(
    segments: Sequence[Tuple[str, Optional[str]]], index: int
) -> Optional[FixCandidate]:
    """accessible feature path違反に対する候補: `index`番目の`::`を`.`へ変える。

    ルールのメッセージ自身が "use dot notation for nesting" と指示している
    とおり、書き換え方は一意に決まる。ただし**どの`::`境界**かはルールだけが
    知っているので、その位置を受け取る。

    Args:
        segments: 参照の`(名前, 直前の区切り)`の列。
        index: `::`を`.`へ変える対象セグメントの位置（1以上）。

    Returns:
        候補。参照が復元できない場合はNone（候補を作らない）。
    """
    if index < 1 or index >= len(segments):
        return None
    before = _rebuild_reference(segments)
    rewritten = list(segments)
    rewritten[index] = (segments[index][0], ".")
    after = _rebuild_reference(rewritten)
    if before == after:
        return None
    nested_name = segments[index][0]
    owner_name = segments[index - 1][0]
    return FixCandidate(
        title=f"`{before}` の `::` を `.` に変える",
        detail=(
            f"`{nested_name}` は型ではなく `{owner_name}` の中のfeatureなので、"
            f"入れ子をたどるには `.` を使う（`::` は名前空間限定のための記法）。"
        ),
        find=before,
        replace=after,
    )
