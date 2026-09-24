"""sequence ビューに描かれない message の warning（e7、仕様書 S8）のテスト。

公式の可視化の sequence ビューは、message の両端が各ライフラインの event occurrence の
ときだけメッセージを描く。2026-09-24 に SysMLv2_pilot の render（sequence ビュー）で
5つの書き方を描かせ、図が空になるかを確かめた結果を固定する。どの書き方も参照実装は
エラーを出さないので、この指摘は warning であって error ではない。
"""

import pytest

from sysml_v2_checker_advanced.parser import lint_sysml, parse_sysml

_HEAD = "item def Msg;\n"

# 名前 → (モデル, 図が空になるか)
CASES = {
    "lifelines": (
        "part def A; part def B;\n"
        "part def ATM { part a : A; part b : B; message m of Msg from a to b; }",
        True,
    ),
    "event_occurrences": (
        "part def A; part def B;\n"
        "part def ATM { part a : A { event occurrence sendM; } part b : B { event occurrence recvM; }\n"
        "    message m of Msg from a.sendM to b.recvM; }",
        False,
    ),
    "ports": (
        "port def P; part def A { port p : P; } part def B { port q : P; }\n"
        "part def ATM { part a : A; part b : B; message m of Msg from a.p to b.q; }",
        True,
    ),
    "mixed_one_event": (
        "part def A; part def B;\n"
        "part def ATM { part a : A { event occurrence sendM; } part b : B; message m of Msg from a.sendM to b; }",
        True,
    ),
    "event_on_def": (
        "part def A { event occurrence sendM; } part def B { event occurrence recvM; }\n"
        "part def ATM { part a : A; part b : B; message m of Msg from a.sendM to b.recvM; }",
        False,
    ),
}


def _sequence_warnings(text: str):
    issues = lint_sysml(parse_sysml(_HEAD + text))
    assert not [i for i in issues if i.severity == "error"], "どの書き方も参照実装ではエラー0件"
    return [i for i in issues if "sequence ビュー" in i.message]


@pytest.mark.parametrize("name", sorted(CASES))
def test_warns_exactly_when_the_sequence_view_would_be_empty(name):
    text, blank = CASES[name]
    warnings = _sequence_warnings(text)
    assert bool(warnings) == blank
    assert all(w.severity == "warning" for w in warnings)


def test_event_occurrence_declaration_draws_no_warning_at_all():
    """`event occurrence x;` は正しい宣言。以前は「参照サブセッティングを持つことが
    推奨」という warning が常に出て、誤った形（`event x;`）へ誘導していた。"""
    text, _ = CASES["event_occurrences"]
    assert lint_sysml(parse_sysml(_HEAD + text)) == []
