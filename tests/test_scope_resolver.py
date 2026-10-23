"""スコープつき名前解決（sysml_v2_checker_advanced/scope_resolver.py、段階 B）。

どの例も、参照実装（Pilot 0.62.0）が同じ判定をすることを確かめた形
（eval/pilot_parity のコーパス、KerML の xpect テスト、tests/fixtures/reference_conformance）。
"""

import pytest

from sysml_v2_checker_advanced.antlr_transformer import parse_sysml_with_semantic_model_recovering
from sysml_v2_checker_advanced.scope_resolver import (
    inaccessible_features,
    kind_violations,
    unresolved_references,
)


def _unresolved(text: str) -> list:
    ast, _model, errors = parse_sysml_with_semantic_model_recovering(text)
    assert errors == []
    return sorted(reference for _node, reference, _kind in unresolved_references(ast))


@pytest.mark.parametrize("text, expected", [
    # private import は外へ見せない（KerML Import_Private）
    ("package Q { package P1 { part def A; } package P2 { private import P1::*; } "
     "public import P2::*; part y : A; part y1 : P2::A; }", ["A", "P2::A"]),
    # public import は再公開する
    ("package Q { package P1 { part def A; } package P2 { public import P1::*; } "
     "private import P2::*; part y : A; part y1 : P2::A; }", []),
    # private なメンバーは修飾名で見えない
    ("package Q { package P { private part def A; public part def B; } part a : P::A; part b : P::B; }",
     ["P::A"]),
    # 兄弟のパッケージの import は見えない（reference_conformance s2e）
    ("package Q { package A { private import ScalarValues::*; } package B { attribute x : Boolean; } }",
     ["Boolean"]),
    # 可視性の無い import は参照実装では構文エラーで、効かない
    ("package Q { import ScalarValues::*; attribute x : String; }", ["String"]),
    # import の対象は、それより前の import で見える名前も使える
    ("package Q { private import RiskMetadata::*; private import RiskLevelEnum::*; }", []),
    # `::**` は名前空間そのものも取り込む（KerML Import_Recursive6）
    ("package Q { package P { part def C { part def C1; } } public import P::C::**; "
     "part x1 : C1; part x4 : C; }", []),
    # 短い名前（reference_conformance / ShortNameSpecification）
    ("package S { requirement def <'SN-R001'> MassLimit; package <SNSUB> Sub { part def Inner; } }"
     "package U { private import S::*; private import S::'SN-R001'; part i : S::SNSUB::Inner; }", []),
])
def test_imports_visibility_and_short_names(text, expected):
    assert _unresolved(text) == expected


@pytest.mark.parametrize("text, expected", [
    # 定義は usage を特化できない（`Couldn't resolve reference to Classifier`）
    ("package Q { part seatBelt; part def B :> seatBelt; }", ["seatBelt"]),
    # パッケージは型にならない
    ("package Q { package P; part x : P; }", ["P"]),
    # 継承した feature の再定義は解決する。名前の無い `:>> x` は自分自身を指さない
    ("package Q { part def V { attribute mass; } part v : V { attribute :>> mass = 1; "
     "attribute :>> nosuch = 2; } }", ["nosuch"]),
    # 型のない interface の中の flow は end 名がライブラリ由来なので判定しない。flow の `of Q` の Q は
    # パッケージで型ではない（参照実装は `Couldn't resolve reference to Type 'Q'.`。2026-10-22 に確認。
    # 参照実装は source.x・target.x の x も出すが、自作は end 名の先を判定しない）
    ("package Q { part def V { part t; part e; interface connect t to e { "
     "flow of Q from source.x to target.x; } } }", ["Q"]),
    # 名前のある自己参照（`part p4 :> p4;`）は自分自身に解決する
    ("package Q { part p4 :> p4; }", []),
    # 特化の無い metadata def（#g1）は基底型を加えないので、中の再定義を確かめる（参照実装は
    # `Couldn't resolve reference to Feature 'priority'.`。2026-10-22 に確認）
    ("package Q { metadata def g1; #g1 requirement a { attribute :>> priority = 1; } }", ["priority"]),
])
def test_kinds_and_inheritance(text, expected):
    assert _unresolved(text) == expected


@pytest.mark.parametrize("text, expected", [
    # 単位と式の中の名前（reference_conformance r03）
    ("package Q { private import ISQ::*; attribute m : MassValue = 1 [kg]; "
     "constraint c { noSuch == true } }", ["kg", "noSuch"]),
    # ISQ::mass を継承した feature の中でも、kg は型のメンバーにはなりえない
    ("package Q { private import ISQ::*; part def V { attribute mass :> ISQ::mass; } "
     "part v : V { attribute :>> mass = 1500 [kg]; } }", ["kg"]),
    # 連鎖の先の protected は見えない（KerML VisibilityTests_Protected_FeatureChain）
    ("package Q { part def C { public part b; protected part c; } part x : C; "
     "attribute y = x.b; attribute z = x.c; }", ["c"]),
    # 列挙の値は型付けで継承されない（`ModeKind::idle` と書く）
    ("package Q { enum def K { idle; } attribute m : K = idle; attribute n : K = K::idle; }", ["idle"]),
    # ラムダの引数、トリガーのペイロード、null は名前ではない
    ("package Q { part def D { attribute m; } part d : D[*]; attribute s = d->collect {in p : D; p.m}; "
     "attribute def Sig { attribute on; } state def S { state a; state b; "
     "transition first a accept sig : Sig if sig.on then b; } attribute z = null; }", []),
])
def test_names_in_expressions(text, expected):
    assert _unresolved(text) == expected


def test_filters_select_imported_members_by_metadata():
    text = (
        "package Q { metadata def Safety; part def v { part def s { @Safety; } part def a; } "
        "package F { public import v::**; filter @Safety; part def x :> s; part def y :> a; } }"
    )
    assert _unresolved(text) == ["a"]


def test_expose_imports_all_members_and_comments_have_names():
    text = (
        "package Q { package P { public part p1; private part p2; } "
        "view def V { view v { expose P::*; alias vp1 for p1; alias vp2 for p2; } } "
        "comment cmt /* x */ comment c2 about cmt /* y */ }"
    )
    assert _unresolved(text) == []


def test_unknown_names_from_other_files_are_not_reported():
    ast, _model, _errors = parse_sysml_with_semantic_model_recovering(
        "package Q { private import Other::*; part x : Thing; }")
    assert unresolved_references(ast, external_names={"Other", "Thing"}) == []


def test_usage_typed_by_another_usage():
    # reference_conformance k09: `An attribute must be typed by attribute definitions.`
    ast, _model, _errors = parse_sysml_with_semantic_model_recovering(
        "package Q { part def V { attribute b : ScalarValues::Real; attribute a : b; } }")
    assert [message for _node, message in kind_violations(ast)] == [
        "An attribute must be typed by attribute definitions."]


@pytest.mark.parametrize("text, expected", [
    # `verify X;`（requirement 無し）は参照。定義を指すのは誤り（参照実装で確認、2026-10-16）
    ("package Q { requirement def R; requirement r0 : R; verification def V { objective { "
     "verify R; verify r0; verify nope : R; verify requirement fresh : R; } } }", ["R", "nope"]),
    # `exhibit s;`（state 無し）も参照
    ("package Q { state def S0; part q { exhibit state s0 : S0; exhibit nosuchState; } }", ["nosuchState"]),
    # satisfy の参照先の名前は、後ろの satisfy から引けない
    ("package Q { part s; satisfy Spec::'R-010' by s; satisfy 'R-010' by s; }", ["R-010", "Spec::'R-010'"]),
    # 前置メタデータ（定義にも付く）
    ("package Q { #logical part def C; }", ["logical"]),
    # 引用符の中の . は連鎖の区切りではない（指摘には元の書き方〈引用符つき〉で出る）
    ("package Q { requirement r :> Spec::'1.1'; }", ["Spec::'1.1'"]),
    # 接続の端の連鎖の 2 番目以降
    ("package Q { part def A { part b; } part def S { part a : A; part c : A; "
     "connect a.b to c.nosuch; } }", ["nosuch"]),
])
def test_referencing_forms_and_end_chains(text, expected):
    assert _unresolved(text) == sorted(expected)


def _inaccessible(text: str) -> list:
    ast, _model, errors = parse_sysml_with_semantic_model_recovering(text)
    assert errors == []
    return sorted(reference for _node, reference in inaccessible_features(ast))


@pytest.mark.parametrize("text, expected", [
    # 接続の端で `::` を使って feature をたどる（左が usage でも定義でも）
    ("package Q { part def V { part engine; part wheel; } part def S { part a : V; part b : V; "
     "connect a.engine to b.engine; connect a::engine to b.engine; connect V::engine to b.wheel; } }",
     ["V::engine", "a::engine"]),
    # 部分集合の先は、左が usage のときだけ。再定義と、左が定義のものは通る
    ("package Q { part def V { part engine; part wheel; } part v : V; part x :> v::engine; "
     "part y :> v.engine; part def C :> V { part :>> V::engine; part w2 :> V::wheel; } "
     "part c2 : V { part :>> v::engine; } }", ["v::engine"]),
    # 両端が同じ定義の feature なら通る。別々の定義はエラー
    ("package Q { part def Car { part tank; part engine; } part def Eng { part engine; } "
     "allocate Car::tank to Car::engine; allocate Car::tank to Eng::engine; }", ["Car::tank", "Eng::engine"]),
    # 入れ子の usage の中から外側の feature を端に使う（connect・flow・succession は不可、message と値の式は可）
    ("package Q { attribute def Cmd; part def Pi { event occurrence sent; port p; } "
     "part def Sh { event occurrence rcv; port p; } part def F { part pilot : Pi; part ship : Sh; "
     "part sub { message m of Cmd from pilot.sent to ship.rcv; connect pilot to ship; ref part p2 = pilot; } "
     "action act { flow from pilot.p to ship.p; first pilot then ship; } } }",
     ["pilot", "pilot", "pilot.p", "ship", "ship", "ship.p"]),
    # 入れ子の定義の中からは、値の式と message の端でも外側の feature を使えない
    ("package Q { attribute def Cmd; part def Pi { event occurrence sent; } part def Sh { event occurrence rcv; } "
     "part def F { part pilot : Pi; part ship : Sh; occurrence def Seq { ref part p2 = pilot; "
     "message m of Cmd from pilot.sent to ship.rcv; } } }", ["pilot", "pilot.sent", "ship.rcv"]),
    # 列挙の値は feature のアクセスではない
    ("package Q { enum def E { e1; e2; } part e1 { attribute x : E; bind e1.x = E::e2; } }", []),
])
def test_accessible_features(text, expected):
    assert _inaccessible(text) == sorted(expected)


def _kinds(text: str) -> list:
    ast, _model, errors = parse_sysml_with_semantic_model_recovering(text)
    assert errors == []
    return sorted(message for _node, message in kind_violations(ast))


@pytest.mark.parametrize("text, expected", [
    # 種類の違う定義・usage を型にする（参照実装で確認、2026-10-16）
    ("package Q { private import ISQ::*; attribute def AD; part def PD; port def Pt; "
     "part x : AD; attribute z : PD; attribute m : ISQ::mass; port q : PD; port q2 : ~Pt; }",
     ["A port must be typed by port definitions.", "An attribute must be typed by attribute definitions.",
      "An attribute must be typed by attribute definitions.",
      "An occurrence, item or part must be typed by occurrence definitions."]),
    # 型が解決できないときは種類のエラーを重ねない（原因の未解決参照だけを出す）
    ("package Q { part y : Typo; attribute w : Typo2; }", []),
    # state / action の型は Behavior（action def で型付けした state も通る。k24）
    ("package Q { action def D; state def S { state s : D; } }", []),
    # 型がちょうど 1 つでなければならない usage
    ("package Q { requirement def R1; requirement def R2; requirement r : R1, R2; }",
     ["A requirement must be typed by one requirement definition."]),
    # 再定義の先から継承した型が解決できない（行の違う連鎖は出す）
    ("package Q { part def V { port pp : PortDefTypo; } part v2 : V { port :>> pp; } }",
     ["A port must be typed by port definitions."]),
    # 参照先の種類と、参照先から継承する型
    ("package Q { action def A; part pp; part def Sys; part sys : Sys; requirement r; "
     "perform pp; action a1 : A; perform a1; satisfy sys by r; }",
     ["A requirement must be typed by one requirement definition.", "Must reference a requirement.",
      "Must reference an action."]),
    # 前置メタデータが metadata def でない・抽象
    ("package Q { part def NotMeta; abstract metadata def AbsMeta; #NotMeta part a; @AbsMeta; }",
     ["A metadata usage must be typed by one metadata definition.", "Must have a concrete type"]),
    # individual は individual def がちょうど 1 つ（ほかの型が混ざってもよい）
    ("package Q { part def Wheel; individual part def Wheel1 :> Wheel; part def Car { part w : Wheel; } "
     "part c : Car { individual w1 : Wheel1 :>> w; individual w2 : Wheel :>> w; } }",
     ["An individual must be typed by one individual definition."]),
    # 継承した型が分からなくても、明示の型が種類違いなら誤り
    ("package Q { item def Heat; abstract flow def F { attribute heat : Heat :>> payload; } }",
     ["An attribute must be typed by attribute definitions."]),
    # 型付きの接続は、型の定義の端の型も持つ
    ("package Q { part def Tire { part bead; } part def Wheel { part rim; } "
     "connection def Seat { end part bead : BeadTypo; end part rim : Wheel; } "
     "part def W { part t : Tire; part w : Wheel; connection seat : Seat connect t.bead to w.rim; } }",
     ["A usage must be typed by definitions."]),
])
def test_kind_violations(text, expected):
    assert _kinds(text) == sorted(expected)


@pytest.mark.parametrize("text, expected", [
    # 参照する usage は参照先の宣言名を持つ（`torqueGenerator.generateTorque`。held-out training/38）
    ("package Q { action def G; part def T { perform action generateTorque : G; } "
     "part t : T { perform generateTorque; } part e { part ok = t.generateTorque; } }", []),
    # `perform a.b;` は連鎖。先頭が無ければ先頭を報告（`perform transportTask.receiveCommand;`）
    ("package Q { part p { perform nope.x; } }", ["nope"]),
    # state の `do x { out temp; }` は既存の action を参照する（held-out Vehicle Example）
    ("package Q { action def ST { out temp; } part def V { perform action senseTemperature : ST; "
     "exhibit state s { state h { do senseTemperature { out temp; } state n; state d; "
     "transition t first n accept when senseTemperature.temp > 1 then d; } } } }", []),
    # accept の名前と受け取るもの（`triggerResponse.incomingInquiry`）
    ("package Q { item def M; action def PM { in m : M; } action def A { action triggerResponse accept inq : M; "
     "action pm : PM { in m = triggerResponse.inq; } } }", []),
    # require は既存の制約・要件を参照し、その中身を持つ
    ("package Q { constraint c0 { attribute x; x >= 1 } requirement def R { require c0 { x = 2; } } }", []),
    # ラムダの本体で宣言した名前（`->forAll {in i; private s1 : T = ...; s1.t > 0}`）
    ("package Q { attribute def T { attribute t; } attribute xs : T[*]; "
     "constraint c { (1..2)->forAll {in i : ScalarValues::Integer; private s1 : T = xs#(i); s1.t > 0} } }", []),
    # 型付きの usage の本体の型なしの引数は、型の同名の引数を暗黙に再定義する
    ("package Q { part def Image { attribute ok : ScalarValues::Boolean; } action def Focus { out image : Image; } "
     "action def Take { action focus : Focus { out image; } action shoot; first focus if focus.image.ok then shoot; } }",
     []),
    # message の受け取るもの（`m.fc`）
    ("package Q { item def F; part a { event occurrence s; } part b { event occurrence r; } "
     "occurrence def X { message m of fc : F from a.s to b.r; message m2 of fc2 : F = m.fc from a.s to b.r; } }", []),
    # variation の中のキーワードの無い variant は既存の usage を参照する（held-out Variability Examples）
    ("package Q { part def Engine; part engine : Engine { port autoPort; } part v6 :> engine; "
     "variation part def EC :> Engine { variant v6 { port :>> autoPort; } } }", []),
    # 部分集合の先が 2 つ（`:> vc, v1`）
    ("package Q { individual part def V1; individual part v1 : V1 { snapshot t0 { } } part vc; "
     "individual part v2 : V1 :> vc, v1 { snapshot c :> t0; } }", []),
])
def test_held_out_forms(text, expected):
    assert _unresolved(text) == sorted(expected)
