"""修正候補の適用（構想書§11 Phase D）。

Phase C の c4 は**提示のみ**で、適用ボタンを意図的に置かなかった。ここはその
境界を越える部分なので、「適用前に差分・再パース・再検証を見せる」という
Phase D の条件と、§12-5 Human authority（最終決定は人間が持つ）を壊さないよう、
**テキストを作るところまで**をこのモジュールが担う。確定するかどうかの判断は
呼び出し側（UI）に残す。

適用の契約（`sysml_v2_checker_advanced/fix_candidates.py` が定めたもの）:
Finding の `source_range` が示す範囲内に現れる最初の `find` を `replace` に
置き換える。範囲を限ることで、同じ文字列がファイル中の別の場所にあっても
巻き込まない。
"""

from typing import Dict, Optional, Tuple


class FixApplicationError(Exception):
    """候補を適用できなかった（安全に適用できる形でなかった）。"""


def _slice_bounds(text: str, source_range: Dict) -> Tuple[int, int]:
    """`source_range` から Python のスライス境界を得る。

    **`end_offset` は終端の文字を含む。** ANTLR の `stop.stop` をそのまま
    入れているため（`antlr_transformer.py` の `_extract_source_range`）。
    したがってスライスは `[start_offset : end_offset + 1]` であり、
    `[start:end]` と書くと最後の1文字が落ちる。

    2026-09-07に実際にこれを読み違え、「source_range が find を覆っていない」と
    誤認した。具体例: `part g = f::a;` で find=`f::a`、source_range は
    offset 73..76。`src[73:76]` は `'f::'` だが `src[73:77]` が `'f::a'`。
    """
    start = source_range.get("start_offset")
    end = source_range.get("end_offset")
    if not isinstance(start, int) or not isinstance(end, int):
        raise FixApplicationError("source_range に start_offset/end_offset がありません")
    if start < 0 or end < start or end + 1 > len(text):
        raise FixApplicationError(
            f"source_range がテキストの範囲外です（{start}..{end}、長さ {len(text)}）"
        )
    return start, end + 1


def apply_fix_candidate(text: str, source_range: Dict, edit: Optional[Dict]) -> str:
    """候補を適用した新しいテキストを返す（元のテキストは変更しない）。

    適用できない場合は `FixApplicationError` を投げる。**黙って元のテキストを
    返さない**: 「適用したのに何も変わらなかった」という状態は、利用者から見ると
    成功と区別が付かず、Phase D が見せるべき差分も空になってしまう。
    """
    if not edit:
        raise FixApplicationError("この候補は書き換え案を持っていません（助言のみ）")
    find = edit.get("find")
    replace = edit.get("replace")
    if find is None or replace is None:
        raise FixApplicationError("候補の edit に find/replace がありません")

    start, stop = _slice_bounds(text, source_range)
    target = text[start:stop]
    position = target.find(find)
    if position == -1:
        raise FixApplicationError(
            f"source_range の範囲内に {find!r} が見つかりません（範囲の中身: {target!r}）"
        )
    absolute = start + position
    return text[:absolute] + replace + text[absolute + len(find):]
