"""代入・呼び出し・注釈・subject の位置の規則（2026-10-23、eval/pilot_parity/BASELINE.md）。

どの例も Pilot 0.63.0（MCP サーバ）に通し、行と文言が同じになることを確かめた形。
"""

from sysml_v2_checker_advanced.semantic_model import lint_text_with_locations


def _errors(text: str) -> list:
    _ast, _issues, dicts = lint_text_with_locations(text)
    return sorted((d["line"], d["message"].split(" [")[0]) for d in dicts if d["severity"] == "error")


def _lines(text: str, prefix: str) -> list:
    return sorted(line for line, message in _errors(text) if message.startswith(prefix))


_ASSIGN = """package V {
    part def PD {
        attribute a;
        protected attribute b;
        private attribute c;
    }
    part p : PD;
    attribute t = PD::b;
    attribute u = PD::c;
    action def A {
        assign p.a := null;
        assign p.b := null;
        assign p.zz := null;
        assign zz2 := null;
    }
    action def B {
        state st;
        calc cc;
        constraint co;
        ref action ra;
        perform action pa;
        exhibit state es;
        use case uc;
        constant attribute cst;
        assign st := null;
        assign cc := null;
        assign co := null;
        assign ra := null;
        assign pa := null;
        assign es := null;
        assign uc := null;
        assign cst := null;
    }
    part def P { attribute pa2; action pact; }
    part pp : P;
    enum def E { e1; }
    attribute def AD { attribute k; }
    attribute ad : AD;
    action def C {
        assign pp.pa2 := null;
        assign pp.pact := null;
        assign pp := null;
        assign E::e1 := null;
        assign ad.k := null;
        assign ad := null;
    }
    action {
        attribute i := 0;
        assign i := 1;
        measurement = i;
        assign measurement := 2;
    }
}
"""


def test_assignment_target_is_resolved_like_an_expression():
    # 代入先の連鎖の protected・private のメンバーは見えない。`PD::b` も（`::` の誤りではなく）未解決。
    # キーワードの無い `measurement = i;` は feature の宣言
    assert [e for e in _errors(_ASSIGN) if e[1].startswith("Couldn't")] == [
        (8, "Couldn't resolve reference to Element 'PD::b'."),
        (9, "Couldn't resolve reference to Element 'PD::c'."),
        (12, "Couldn't resolve reference to Element 'b'."),
        (13, "Couldn't resolve reference to Element 'zz'."),
        (14, "Couldn't resolve reference to Element 'zz2'."),
    ]


def test_referent_must_be_time_varying():
    # 合成の action・calc・state・case は変わらない。属性の定義・列挙・パッケージが持つものも変わらない。
    # 名前の無い action の中の attribute は occurrence が持つ
    assert _lines(_ASSIGN, "Referent must be time varying") == [25, 26, 31, 41, 42, 43, 44, 45]


_INVOKE = """package V {
    private import ScalarValues::*;
    part def Sys;
    requirement def RR { subject s : Sys; attribute m : Real; in attribute k : Real; }
    calc def F { in x : Real; in y : Real; return r : Real; }
    calc def G { in x : Real; out o : Real; return r : Real; }
    constraint def CD { in c : Real; }
    calc def H :> F { in z : Real; }
    calc def K { inout x : Real; in ref y : Sys; return r : Real; }
    requirement def NoSubject { attribute e : Real; }
    part sys : Sys;
    requirement rr : RR;
    calc f : F;
    attribute v1 = F(1.0, 2.0);
    attribute v2 = F(1.0, 2.0, 3.0);
    attribute v4 = G(1.0, 2.0);
    attribute v5 = CD(1.0, 2.0);
    attribute v6 = RR(sys, 1.0);
    attribute v7 = RR(sys, 1.0, 2.0);
    attribute v8 = rr(sys, 1.0, 2.0);
    attribute v9 = f(1.0, 2.0, 3.0);
    attribute v12 = F(x = 1.0, y = 2.0);
    attribute v13 = F(x = 1.0, w = 2.0);
    attribute v16 = K(1.0, sys, 3.0);
    attribute v17 = RR(m = 1.0);
    attribute v18 = F(1.0,
                      2.0,
                      3.0);
    constraint c1 { CD(1.0, 2.0) }
    attribute v19 = H(1.0, 2.0, 3.0);
    attribute v20 = NoSubject(sys);
}
"""


def test_invocation_arguments_correspond_to_input_parameters():
    # 位置の引数は subject と方向のある引数に順に対応する。`out` に当たれば方向の食い違いも。
    # 特化した定義（H）と、ライブラリの subject を継承する要件（NoSubject）は確かめない（Pilot は 30 行目の H も
    # 誤りにする: H の `in z` は F の x を順番に再定義するので入力は 2 つ。31 行目は Pilot も通す）
    assert _lines(_INVOKE, "Must correspond to one input parameter") == [15, 16, 17, 19, 20, 21, 23, 24, 25, 28, 29]
    assert _lines(_INVOKE, "Redefining feature must have a compatible direction") == [16]
    assert _lines(_INVOKE, "Couldn't resolve reference to Feature 'w'") == [23]


_ANNOTATE = """package V {
    metadata def OnlyParts { :> annotatedElement : SysML::PartUsage; }
    metadata def OnlyDefs { :> annotatedElement : SysML::Definition; }
    metadata def Both { :> annotatedElement : SysML::PartUsage; :> annotatedElement : SysML::ActionDefinition; }
    metadata def Sub :> OnlyParts;
    metadata def Feat { :> annotatedElement : SysML::Usage; }
    part def PD { @OnlyParts; }
    part p1 { @OnlyParts; }
    item i1 { @OnlyParts; }
    part def PD2 { @OnlyDefs; }
    part p2 { @OnlyDefs; }
    action def AD { @Both; }
    part p3 { @Both; }
    item i3 { @Both; }
    part def PD4 { @Sub; }
    #OnlyParts part p5;
    #OnlyParts part def PD5;
    metadata m6 : OnlyParts about PD;
    metadata m7 : OnlyParts about p1;
    attribute a8 { @Feat; }
    part def PD8 { @Feat; }
    package Q { @OnlyParts; }
    port p9 { @OnlyParts; }
    part p10 : PD { @Feat; }
    @OnlyParts;
    requirement r { @OnlyParts; }
    ref part rp { @OnlyParts; }
    metadata def Unrestricted;
    part def PD11 { @Unrestricted; }
    metadata def MetaOnly { :> annotatedElement : SysML::MetadataDefinition; }
    #MetaOnly metadata def MD;
    occurrence def OD { @OnlyParts; }
    enum def E { @OnlyParts; e1; }
}
"""


def test_metadata_annotated_element_restriction():
    # 制約が複数ならどれかに当たればよい。特化したメタデータの定義も同じ制約。`#M`・`about` も
    assert [e for e in _errors(_ANNOTATE)] == [
        (7, "Cannot annotate PartDefinition"),
        (9, "Cannot annotate ItemUsage"),
        (11, "Cannot annotate PartUsage"),
        (14, "Cannot annotate ItemUsage"),
        (15, "Cannot annotate PartDefinition"),
        (17, "Cannot annotate PartDefinition"),
        (18, "Cannot annotate PartDefinition"),
        (21, "Cannot annotate PartDefinition"),
        (22, "Cannot annotate Package"),
        (23, "Cannot annotate PortUsage"),
        (25, "Cannot annotate Package"),
        (26, "Cannot annotate RequirementUsage"),
        (32, "Cannot annotate OccurrenceDefinition"),
        (33, "Cannot annotate EnumerationDefinition"),
    ]


_SUBJECT = """package V {
    part def Vehicle; part def Person;
    use case def Enter { subject vehicle : Vehicle; actor driver : Person; }
    use case def Top {
        subject vehicle : Vehicle;
        actor driver : Person;
        include use case e1 : Enter { actor :>> driver = Top::driver; }
        include use case e2 : Enter { subject :>> vehicle = vehicle; actor :>> driver = Top::driver; }
        include use case e3 : Enter { in x : Person; }
        use case u4 : Enter { actor :>> driver; }
        include use case e5 : Enter;
        include use case e6 : Enter { attribute a; }
        include use case e7 : Enter {
            actor d2 : Person;
        }
    }
    use case def Own { actor a : Person; subject s : Vehicle; }
    requirement def R { in x : Person; subject s : Vehicle; }
    requirement def R2 { subject s : Vehicle; in x : Person; }
    requirement r3 : R2 { in :>> x; }
    case def C { actor a : Person; }
    requirement def R4 { stakeholder st : Person; subject s : Vehicle; }
    requirement def R5 { in x : Person; }
    concern def C1 { stakeholder st : Person; }
    verification def VD { objective { } subject s : Vehicle; }
    analysis def AD { return r : Person; subject s : Vehicle; }
    viewpoint def VP { stakeholder st : Person; }
    use case def U1 { out o : Person; subject s : Vehicle; }
}
"""


def test_subject_must_be_first_parameter():
    # subject が無ければ要素の行（`include use case e7 : Enter {` の行）。先頭が `out` なら出さない
    # （参照実装は方向の食い違いを出す）
    lines = sorted(d["line"] for d in lint_text_with_locations(_SUBJECT)[2]
                   if d["severity"] == "error" and "8.2.2.21" in d["message"])
    assert lines == [7, 9, 10, 13, 17, 18, 20, 21, 22, 23, 24, 27]
