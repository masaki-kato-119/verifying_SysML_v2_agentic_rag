"""スコープつき名前解決（sysml_v2_checker_advanced/scope_resolver.py、段階 B）。

どの例も、参照実装（Pilot 0.62.0）が同じ判定をすることを確かめた形
（eval/pilot_parity のコーパス、KerML の xpect テスト、tests/fixtures/reference_conformance）。
"""

import pytest

from sysml_v2_checker_advanced.antlr_transformer import parse_sysml_with_semantic_model_recovering
from sysml_v2_checker_advanced.scope_resolver import typed_by_usages, unresolved_references


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
    # 型のない interface の中の flow は end 名がライブラリ由来なので判定しない
    ("package Q { part def V { part t; part e; interface connect t to e { "
     "flow of Q from source.x to target.x; } } }", []),
    # 名前のある自己参照（`part p4 :> p4;`）は自分自身に解決する
    ("package Q { part p4 :> p4; }", []),
    # 意味的メタデータ（#g1）は基底型を加えるので、中の再定義は確かめない
    ("package Q { metadata def g1; #g1 requirement a { attribute :>> priority = 1; } }", []),
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
    assert [type_name for _node, type_name in typed_by_usages(ast)] == ["b"]
