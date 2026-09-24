"""Semantic Model の関係エッジ（sysml_v2_checker_advanced/semantic_model.py）の
新規ユニットテスト。Phase 2第1弾: specialization/subsetting/redefinition/
feature_typing のみを対象とする（拡張仕様書8章、2026-09-03のPhase 2再検討で
linter.pyには一切手を入れない設計に変更）。

connection/satisfy/verify系エッジとresolution_statusの3値分類は未実装
（次段階）。
"""

from __future__ import annotations

from sysml_v2_checker_advanced.antlr_transformer import parse_sysml_antlr
from sysml_v2_checker_advanced.semantic_model import build_semantic_model

_SAMPLE = """
package Vehicle {
    part def Machine {
        attribute mass : Real;
    }
    part def Engine :> Machine {
        attribute power : Real;
    }
    part myEngine : Engine;
}
"""


def test_linter_py_is_not_modified_by_this_feature():
    """build_semantic_model()はlinter.pyの既存挙動に影響しない
    （lint_sysml(ast)の指摘内容が変わらないこと）を確認する。"""
    from sysml_v2_checker_advanced.parser import lint_sysml

    ast = parse_sysml_antlr(_SAMPLE.strip())
    issues_before = [(i.severity, i.message) for i in lint_sysml(ast)]

    build_semantic_model(_SAMPLE.strip())

    issues_after = [(i.severity, i.message) for i in lint_sysml(ast)]
    assert issues_before == issues_after


def test_subsetting_edge_resolves_to_base_part_def():
    _, model = build_semantic_model(_SAMPLE.strip())
    edge = next(e for e in model["edges"] if e["from_id"] == "$root::Engine" and e["kind"] == "subsetting")
    assert edge["to_id"] == "$root::Machine"
    assert edge["resolved"] is True


def test_feature_typing_edge_resolves_to_local_part_def():
    _, model = build_semantic_model(_SAMPLE.strip())
    edge = next(e for e in model["edges"] if e["from_id"] == "$root::myEngine")
    assert edge["kind"] == "feature_typing"
    assert edge["to_id"] == "$root::Engine"
    assert edge["resolved"] is True


# --- 型付けの多重度ラベル（表現力強化h3） ----------------------------------

def test_feature_typing_edge_has_multiplicity_label_when_explicit():
    text = """
    package P {
        part def Engine;
        part engines : Engine[1..4];
    }
    """
    _, model = build_semantic_model(text.strip())
    edge = next(e for e in model["edges"] if e["from_id"] == "$root::engines" and e["kind"] == "feature_typing")
    assert edge["label"] == "1..4"


def test_feature_typing_edge_has_no_label_without_explicit_multiplicity():
    """多重度を明示しないfeature_typingエッジは"label"キー自体を持たない
    （h2の暗黙遷移と同様、ラベル無しの矢印のみ描画される）。"""
    _, model = build_semantic_model(_SAMPLE.strip())
    edge = next(e for e in model["edges"] if e["from_id"] == "$root::myEngine")
    assert "label" not in edge


def test_feature_typing_edge_shows_single_value_multiplicity():
    text = """
    package P {
        part def Engine;
        part engine : Engine[4];
    }
    """
    _, model = build_semantic_model(text.strip())
    edge = next(e for e in model["edges"] if e["from_id"] == "$root::engine" and e["kind"] == "feature_typing")
    assert edge["label"] == "4"


def test_builtin_type_reference_is_unresolved_external():
    """組み込み型(Real等)はASTノードを持たないため to_id=None だが、
    linter自身がエラー扱いしない参照のため resolution_status は
    "unresolved_external"（拡張仕様書8.2章）。
    """
    # 2026-09-24: import 無しの組み込み型は参照実装0.62.0でエラー（Couldn't resolve reference to Type 'X'.）。
    # import していれば external、していなければ lint と同じくエラー
    imported = _SAMPLE.strip().replace("package Vehicle {", "package Vehicle { private import ScalarValues::*;", 1)
    _, model = build_semantic_model(imported)
    edge = next(e for e in model["edges"] if e["from_id"] == "$root::Machine::mass")
    assert edge["kind"] == "feature_typing"
    assert edge["reference_text"] == "Real"
    assert edge["resolved"] is False
    assert edge["to_id"] is None
    assert edge["resolution_status"] == "unresolved_external"

    _, model = build_semantic_model(_SAMPLE.strip())
    edge = next(e for e in model["edges"] if e["from_id"] == "$root::Machine::mass")
    assert edge["resolution_status"] == "unresolved_error"


def test_resolved_edge_has_resolved_status():
    _, model = build_semantic_model(_SAMPLE.strip())
    edge = next(e for e in model["edges"] if e["from_id"] == "$root::Engine" and e["kind"] == "subsetting")
    assert edge["resolution_status"] == "resolved"


def test_genuinely_broken_reference_is_unresolved_error():
    """このファイル内にも標準ライブラリにも見つからない参照は
    resolution_status="unresolved_error"（=lintも実際にエラー報告する）。
    """
    text = """
    package P {
        part broken : NoSuchTypeAtAll;
    }
    """
    _, model = build_semantic_model(text.strip())
    edge = next(e for e in model["edges"] if e["from_id"] == "$root::broken")
    assert edge["resolution_status"] == "unresolved_error"


def test_resolution_status_does_not_contradict_lint_errors():
    """resolution_status="unresolved_error"のエッジは、同じASTに対する
    lint_sysml()が実際にerror severityの指摘を出すことと整合する
    （拡張仕様書8.2章の要件：Viewer側の未解決表示とlintのエラー判定を
    矛盾させない）。
    """
    from sysml_v2_checker_advanced.parser import lint_sysml

    text = """
    package P {
        part broken : NoSuchTypeAtAll;
    }
    """
    ast, model = build_semantic_model(text.strip())
    error_edges = [e for e in model["edges"] if e["resolution_status"] == "unresolved_error"]
    assert error_edges

    issues = lint_sysml(ast)
    assert any(i.severity == "error" for i in issues)


def test_error_ast_returns_empty_edges():
    ast, model = build_semantic_model("this is not valid sysml {{{")
    assert ast.get("type") == "error"
    assert model["edges"] == []


def test_multitype_produces_multiple_feature_typing_edges():
    text = """
    package P {
        part def A;
        part def B;
        item i : A, B;
    }
    """
    _, model = build_semantic_model(text.strip())
    typing_edges = [e for e in model["edges"] if e["from_id"] == "$root::i" and e["kind"] == "feature_typing"]
    resolved_targets = {e["to_id"] for e in typing_edges}
    assert resolved_targets == {"$root::A", "$root::B"}


# --- connection / satisfy / verify エッジ（p2b2, 2026-09-03） -----------------


def test_simple_binary_connect_usage_produces_a_single_edge_between_both_ends():
    """表現力強化: 2項かつ本体を持たないconnect_usageは、自身を起点にする
    2本のエッジではなく、両端を直接結ぶ1本のエッジとして表現する
    （connectorの箱自体をボックスとして描画しない設計に合わせる）。"""
    text = """
    package P {
        part a;
        part b;
        connect a to b;
    }
    """
    _, model = build_semantic_model(text.strip())
    connection_edges = [e for e in model["edges"] if e["kind"] == "connection"]
    assert len(connection_edges) == 1
    edge = connection_edges[0]
    assert edge["from_id"] == "$root::a"
    assert edge["to_id"] == "$root::b"
    assert edge["resolved"] is True


def test_binary_connect_usage_with_body_keeps_two_edges_from_its_own_box():
    """本体（`{ ... }`）を持つconnect_usageは、中の要素を消さないよう
    従来通り自身を起点にした2本のエッジのまま表現する（1本への折りたたみは
    しない）。"""
    text = """
    package P {
        part a;
        part b;
        connect a to b {
            doc /* note */
        }
    }
    """
    _, model = build_semantic_model(text.strip())
    connection_edges = [e for e in model["edges"] if e["kind"] == "connection"]
    assert len(connection_edges) == 2
    assert {e["from_id"] for e in connection_edges} == {"$root/connect_usage#0"}
    assert {e["to_id"] for e in connection_edges} == {"$root::a", "$root::b"}


def test_nary_connect_produces_one_connection_edge_per_end():
    text = """
    package P {
        part a;
        part b;
        part c;
        connect (a, b, c);
    }
    """
    _, model = build_semantic_model(text.strip())
    connection_edges = [e for e in model["edges"] if e["kind"] == "connection"]
    assert {e["to_id"] for e in connection_edges} == {"$root::a", "$root::b", "$root::c"}


def test_binding_connector_produces_a_single_connection_edge_between_both_ends():
    text = """
    package P {
        part a;
        part b;
        bind a = b;
    }
    """
    _, model = build_semantic_model(text.strip())
    connection_edges = [e for e in model["edges"] if e["kind"] == "connection"]
    assert len(connection_edges) == 1
    assert connection_edges[0]["from_id"] == "$root::a"
    assert connection_edges[0]["to_id"] == "$root::b"


def test_connect_usage_end_multiplicity_becomes_edge_label():
    """表現力強化h3: `connect [0..1] a to [1..*] b;`のような各endの前に
    付く多重度を、折りたたまれた1本のconnectionエッジのラベルへ、両端分を
    まとめて表示する（各endの多重度がそれぞれ`[...]`で区別できる形）。"""
    text = """
    package P {
        part a;
        part b;
        connect [0..1] a to [1..*] b;
    }
    """
    _, model = build_semantic_model(text.strip())
    connection_edges = [e for e in model["edges"] if e["kind"] == "connection"]
    assert len(connection_edges) == 1
    assert connection_edges[0]["label"] == "[0..1] [1..*]"


def test_binding_connector_end_multiplicity_becomes_edge_label():
    """`binding [connMult] bind [leftMult] a = [rightMult] b;`のうち、h3が
    ラベル表示するのはleft/rightの各end多重度のみ（コネクタ自身のconnMultは
    end固有の情報ではないため対象外）。"""
    text = """
    package P {
        part a;
        part b;
        binding bind [0..*] a = b;
    }
    """
    _, model = build_semantic_model(text.strip())
    connection_edges = [e for e in model["edges"] if e["kind"] == "connection"]
    assert len(connection_edges) == 1
    assert connection_edges[0]["label"] == "[0..*]"


def test_binary_connector_label_includes_name_when_present():
    """表現力強化: 折りたたまれた2項connectorに名前/型名（`connection_usage`の
    `name`/`type_name`、UMLの関連名に相当）がある場合はラベルに含める。"""
    text = """
    package P {
        part a;
        part b;
        connection :MatesWith connect a to b;
    }
    """
    _, model = build_semantic_model(text.strip())
    connection_edges = [e for e in model["edges"] if e["kind"] == "connection"]
    assert len(connection_edges) == 1
    assert connection_edges[0]["label"] == "MatesWith"


def test_connect_usage_without_end_multiplicity_has_no_label():
    _, model = build_semantic_model(
        """
        package P {
            part a;
            part b;
            connect a to b;
        }
        """.strip()
    )
    connection_edges = [e for e in model["edges"] if e["kind"] == "connection"]
    assert all("label" not in e for e in connection_edges)


def test_satisfy_requirement_usage_produces_satisfy_edge():
    text = """
    package P {
        part system;
        requirement def Req1;
        satisfy requirement req1 : Req1 by system;
    }
    """
    _, model = build_semantic_model(text.strip())
    satisfy_edges = [e for e in model["edges"] if e["kind"] == "satisfy"]
    assert len(satisfy_edges) == 1
    assert satisfy_edges[0]["from_id"] == "$root::req1"
    assert satisfy_edges[0]["to_id"] == "$root::system"
    assert satisfy_edges[0]["resolved"] is True


def test_verify_requirement_usage_produces_verify_edge():
    text = """
    package P {
        part system;
        requirement def Req1;
        requirement req1 : Req1;
        verify req1 by system;
    }
    """
    _, model = build_semantic_model(text.strip())
    verify_edges = [e for e in model["edges"] if e["kind"] == "verify"]
    assert len(verify_edges) == 1
    assert verify_edges[0]["to_id"] == "$root::system"
    assert verify_edges[0]["resolved"] is True


# --- transition（表現力強化Stage 2, Group A e1） --------------------------
# 実在するコーパス(tests/fixtures/sysml_corpus/working/real_state_transition.sysml)
# と同じ文法パターンを使い、合成dictではなく実際のパース結果で検証する
# （AST形状の想定違いを早期に検出するため）。

_STATE_MACHINE_SAMPLE = """
state def AdvancedSwitch {
    entry; then Off;

    state Off;
    state On;

    transition first Off
        accept TurnOn
        then On;

    transition OnToOff
        first On
        accept TurnOff
        then Off;
}
"""


def test_explicit_transition_resolves_source_and_target():
    _, model = build_semantic_model(_STATE_MACHINE_SAMPLE.strip())
    edge = next(e for e in model["edges"] if e["kind"] == "transition" and e["from_id"] == "$root::AdvancedSwitch::Off")
    assert edge["to_id"] == "$root::AdvancedSwitch::On"
    assert edge["resolved"] is True
    assert edge["resolution_status"] == "resolved"


def test_named_explicit_transition_resolves_source_and_target():
    _, model = build_semantic_model(_STATE_MACHINE_SAMPLE.strip())
    edge = next(e for e in model["edges"] if e["kind"] == "transition" and e["from_id"] == "$root::AdvancedSwitch::On")
    assert edge["to_id"] == "$root::AdvancedSwitch::Off"
    assert edge["resolved"] is True


def test_implicit_transition_uses_enclosing_state_as_source():
    """`entry; then Off;`はsourceを持たない暗黙の初期遷移。Semantic Modelの
    parent_id（このtransitionを直接囲むstate def自身）を遷移元として使う。"""
    _, model = build_semantic_model(_STATE_MACHINE_SAMPLE.strip())
    implicit_edges = [
        e for e in model["edges"] if e["kind"] == "transition" and e["from_id"] == "$root::AdvancedSwitch"
    ]
    assert len(implicit_edges) == 1
    assert implicit_edges[0]["to_id"] == "$root::AdvancedSwitch::Off"
    assert implicit_edges[0]["resolved"] is True


def test_transition_count_matches_source_declarations():
    _, model = build_semantic_model(_STATE_MACHINE_SAMPLE.strip())
    transition_edges = [e for e in model["edges"] if e["kind"] == "transition"]
    # entry->Off(暗黙) + Off->On(明示,無名) + On->Off(明示,命名)の3件。
    assert len(transition_edges) == 3


def test_transition_to_unknown_target_is_unresolved_error():
    text = """
    state def S {
        state A;
        transition first A then NoSuchState;
    }
    """
    _, model = build_semantic_model(text.strip())
    edge = next(e for e in model["edges"] if e["kind"] == "transition" and e["from_id"] == "$root::S::A")
    assert edge["to_id"] is None
    assert edge["resolved"] is False
    assert edge["resolution_status"] == "unresolved_error"


# --- transitionのtrigger/guard/effectラベル（表現力強化h2） ---------------

_GUARDED_TRANSITION_SAMPLE = """
state def PowerState {
    state Off;
    state On;

    transition first Off
        accept TurnOn
        if powerLevel > 0.0
        do action logStart
        then On;
}
"""


def test_transition_label_includes_trigger_guard_effect():
    _, model = build_semantic_model(_GUARDED_TRANSITION_SAMPLE.strip())
    edge = next(e for e in model["edges"] if e["kind"] == "transition" and e["from_id"] == "$root::PowerState::Off")
    assert edge["label"] == "TurnOn [powerLevel > 0.0] / logStart"


def test_transition_label_absent_when_no_trigger_guard_effect():
    """暗黙遷移（entry; then Off;）はtrigger/guard/effectを一切持たないため、
    "label"キー自体を持たない（ラベル無しの遷移矢印のみ描画される）。"""
    _, model = build_semantic_model(_STATE_MACHINE_SAMPLE.strip())
    implicit_edge = next(
        e for e in model["edges"] if e["kind"] == "transition" and e["from_id"] == "$root::AdvancedSwitch"
    )
    assert "label" not in implicit_edge


def test_transition_label_trigger_only():
    _, model = build_semantic_model(_STATE_MACHINE_SAMPLE.strip())
    edge = next(e for e in model["edges"] if e["kind"] == "transition" and e["from_id"] == "$root::AdvancedSwitch::Off")
    assert edge["label"] == "TurnOn"


def test_existing_edge_kinds_unaffected_by_transition_support():
    """既存のspecialization等のエッジ抽出は、transition対応の追加によって
    無変更で動作する（回帰防止）。"""
    _, model = build_semantic_model(_SAMPLE.strip())
    assert not any(e["kind"] == "transition" for e in model["edges"])
    assert any(e["kind"] == "subsetting" for e in model["edges"])


# --- succession/succession_usage（表現力強化Stage 2, Group A e2） --------
# 実在するコーパス(tests/fixtures/sysml_corpus/working/binding_connector_succession.sysml
# の`first a then b;`、および対話的に確認した`succession NAME first A then B;`/
# `succession flow NAME from A to B;`)と同じ文法パターンで検証する。


def test_bare_succession_produces_succession_edge():
    """`first a then b;`という裸のsuccessionStmt形（isFlowキー自体を持たず、
    firstEnd/thenEndがconnectorEnd形）。"""
    text = """
    action def Act {
        action a;
        action b;
        first a then b;
    }
    """
    _, model = build_semantic_model(text.strip())
    edge = next(e for e in model["edges"] if e["kind"] == "succession")
    assert edge["from_id"] == "$root::Act::a"
    assert edge["to_id"] == "$root::Act::b"
    assert edge["resolved"] is True


def test_named_succession_usage_first_then_produces_succession_edge():
    """`succession s1 first A then B;`という名前付きsuccession_usage形
    （isFlow=False、firstEnd/thenEndがconnectorEnd形）。"""
    text = """
    action def Act {
        action step1;
        action step2;
        succession s1 first step1 then step2;
    }
    """
    _, model = build_semantic_model(text.strip())
    edge = next(e for e in model["edges"] if e["kind"] == "succession")
    assert edge["from_id"] == "$root::Act::step1"
    assert edge["to_id"] == "$root::Act::step2"
    assert edge["resolved"] is True


def test_succession_usage_flow_form_produces_succession_edge():
    """`succession flow f1 from A to B;`というisFlow=True形
    （fromEnd/toEndが素の参照文字列）。"""
    text = """
    action def Act {
        action step1;
        action step2;
        succession flow f1 from step1 to step2;
    }
    """
    _, model = build_semantic_model(text.strip())
    edge = next(e for e in model["edges"] if e["kind"] == "succession")
    assert edge["from_id"] == "$root::Act::step1"
    assert edge["to_id"] == "$root::Act::step2"
    assert edge["resolved"] is True


def test_succession_to_unknown_target_is_unresolved_error():
    text = """
    action def Act {
        action step1;
        first step1 then NoSuchAction;
    }
    """
    _, model = build_semantic_model(text.strip())
    edge = next(e for e in model["edges"] if e["kind"] == "succession")
    assert edge["to_id"] is None
    assert edge["resolved"] is False
    assert edge["resolution_status"] == "unresolved_error"


# --- flow（表現力強化Stage 2, Group A e3） --------------------------------


def test_flow_short_form_resolves_owner_actions():
    """`flow step1.x to step2.y;`のowner.port形式は、シンボル表にownerまでしか
    登録されていないため、ownerレベルで解決する
    （`_resolve_reference`のドット区切りフォールバック）。"""
    text = """
    action def Act {
        action step1 { out item x; }
        action step2 { in item y; }
        flow step1.x to step2.y;
    }
    """
    _, model = build_semantic_model(text.strip())
    edge = next(e for e in model["edges"] if e["kind"] == "flow")
    assert edge["from_id"] == "$root::Act::step1"
    assert edge["to_id"] == "$root::Act::step2"
    assert edge["resolved"] is True


def test_flow_from_form_resolves_owner_actions():
    """`flow from step1.x to step2.y;`という`from`キーワード付きの完全形。"""
    text = """
    action def Act {
        action step1 { out item x; }
        action step2 { in item y; }
        flow from step1.x to step2.y;
    }
    """
    _, model = build_semantic_model(text.strip())
    edge = next(e for e in model["edges"] if e["kind"] == "flow")
    assert edge["from_id"] == "$root::Act::step1"
    assert edge["to_id"] == "$root::Act::step2"
    assert edge["resolved"] is True


def test_flow_to_unknown_owner_is_unresolved_error():
    text = """
    action def Act {
        action step1 { out item x; }
        flow step1.x to noSuchAction.y;
    }
    """
    _, model = build_semantic_model(text.strip())
    edge = next(e for e in model["edges"] if e["kind"] == "flow")
    assert edge["to_id"] is None
    assert edge["resolved"] is False


# --- flow_usage（別のAST形状、2026-09-04追加。以前は未対応で0件だった） ----
# `flow 'X'.'Y' to 'Z'.'W';`は、片方の参照が`::`区切りの名前空間修飾を
# 含む場合（例: `LDW::step2.sig2`のような、外部パッケージ配下の要素への
# 参照）、flow_from_stmt/flow_short_stmtとは別の"flow_usage"型
# （from_end/to_end、"::"区切り）に正規化されることが実際のADASモデルの
# 調査で判明した。この形状は以前一切エッジ抽出されていなかった。


def test_flow_usage_with_qualified_target_resolves_owner_actions():
    """片方が`::`修飾された参照(`Ext::step2.y`)を持つ場合に
    `flow_usage`型になる。ownerである`step1`/`Ext`まではフォールバックで
    解決を試みる（`Ext`自体は未定義の外部名前空間のためunresolved_error）。"""
    text = """
    action def Act {
        action step1 { out item x; }
        flow step1.x to Ext::step2.y;
    }
    """
    _, model = build_semantic_model(text.strip())
    edge = next(e for e in model["edges"] if e["kind"] == "flow")
    assert edge["from_id"] == "$root::Act::step1"
    assert edge["to_id"] is None
    assert edge["resolved"] is False


def test_flow_usage_resolves_when_both_ends_are_local():
    text = """
    package P {
        action def Helper {
            action step2 { in item y; }
        }
        action def Act {
            action step1 { out item x; }
            flow step1.x to Helper::step2.y;
        }
    }
    """
    _, model = build_semantic_model(text.strip())
    edge = next(e for e in model["edges"] if e["kind"] == "flow")
    assert edge["from_id"] == "$root::Act::step1"
    assert edge["to_id"] == "$root::Helper"
    assert edge["resolved"] is True
    assert edge["resolution_status"] == "resolved"


# --- accept_actionの`actionName`解決（フォローアップ、2026-09-04追加） ----
# accept_action（`action 'X' accept 'Y' via ...;`）は`_assign_semantic_ids`が
# 見る"name"を持たず、実際の名前は"actionName"フィールドにある。そのため
# `linter.py`のシンボル表にも一切現れず、通常の`_resolve_reference`経路では
# 絶対に解決できない（`linter.py`には手を入れない方針のため、Semantic Model
# 側に補助索引を持たせて対応した）。


def test_flow_from_accept_action_resolves_to_the_accept_action_itself():
    text = """
    part def Other {
        attribute someAttr : Real;
    }
    part def X {
        port p;
        part o : Other;
        perform action outer {
            action getSignal accept sig : Real via p;
            flow getSignal.sig to o.someAttr;
        }
    }
    """
    _, model = build_semantic_model(text.strip())
    edge = next(e for e in model["edges"] if e["kind"] == "flow")
    accept_action_id = next(
        sid for sid, e in model["nodes"].items() if e["type"] == "accept_action"
    )
    assert edge["from_id"] == accept_action_id
    assert edge["to_id"] == "$root::X::o"
    assert edge["resolved"] is True
    assert edge["resolution_status"] == "resolved"


def test_flow_to_accept_action_also_resolves():
    """accept_actionはfrom側だけでなくto側の参照としても解決できる
    （`_resolve_reference`のextra_symbolsフォールバックはfrom/to両方に
    渡しているため）。"""
    text = """
    part def Source {
        attribute value : Real;
    }
    part def X {
        port p;
        part s : Source;
        perform action outer {
            action getSignal accept sig : Real via p;
            flow s.value to getSignal.sig;
        }
    }
    """
    _, model = build_semantic_model(text.strip())
    edge = next(e for e in model["edges"] if e["kind"] == "flow")
    accept_action_id = next(
        sid for sid, e in model["nodes"].items() if e["type"] == "accept_action"
    )
    assert edge["from_id"] == "$root::X::s"
    assert edge["to_id"] == accept_action_id
    assert edge["resolved"] is True


def test_flow_from_accept_action_to_undeclared_external_stays_unresolved():
    """accept_action自体は解決できても、相手側が未定義の外部名前空間
    （このモデル内に存在しない`Ext`）であれば、従来通り未解決のまま
    （accept_actionの解決を追加したことで、無関係な既存の未解決判定が
    誤って"resolved"に変わってしまわないことの確認）。"""
    text = """
    part def X {
        port p;
        perform action outer {
            action getSignal accept sig : Real via p;
            flow getSignal.sig to Ext::somewhere.value;
        }
    }
    """
    _, model = build_semantic_model(text.strip())
    edge = next(e for e in model["edges"] if e["kind"] == "flow")
    accept_action_id = next(
        sid for sid, e in model["nodes"].items() if e["type"] == "accept_action"
    )
    assert edge["from_id"] == accept_action_id
    assert edge["to_id"] is None
    assert edge["resolved"] is False


def test_flow_usage_and_flow_short_stmt_are_both_kind_flow():
    """flow_usage（新規対応）とflow_short_stmt（既存対応）は、AST形状こそ
    異なるが、Semantic Model上は同じ"flow"種別のエッジとして扱われる
    （Graph IR/View IR/SVGレンダラー側の変更が不要であることの確認）。"""
    text = """
    action def Act {
        action step1 { out item x; }
        action step2 { in item y; }
        flow step1.x to step2.y;
        flow step1.x to Ext::step2.y;
    }
    """
    _, model = build_semantic_model(text.strip())
    flow_edges = [e for e in model["edges"] if e["kind"] == "flow"]
    assert len(flow_edges) == 2
