"""sysml_v2_checker_advanced.linter の優先テスト（LintIssue・実 AST 経由の lint）。"""

from sysml_v2_checker_advanced.linter import LintIssue, SysMLAdvancedLinter
from sysml_v2_checker_advanced.parser import lint_sysml, parse_sysml


def test_lint_issue_to_dict():
    issue = LintIssue(severity="warning", message="msg", line=3)
    d = issue.to_dict()
    assert d == {"severity": "warning", "message": "msg", "line": 3}


def test_linter_lint_accepts_minimal_package_ast():
    ast = parse_sysml("package P { part def A; }", strict=True)
    assert ast.get("type") == "package"
    linter = SysMLAdvancedLinter()
    issues = linter.lint(ast)
    assert isinstance(issues, list)


def test_lint_sysml_type_def_and_part_with_attribute():
    """パース可能な範囲で attribute / type_def を含み、lint が完走する。"""
    src = """
    package X {
        type def T;
        part def P {
            attribute n : Integer;
        }
    }
    """
    ast = parse_sysml(src, strict=True)
    assert ast.get("type") == "package"
    issues = lint_sysml(ast)
    assert isinstance(issues, list)
    for iss in issues:
        assert hasattr(iss, "severity") and hasattr(iss, "message")


def test_lint_sysml_multi_part_definitions():
    ast = parse_sysml(
        """
        package P {
            part def A;
            part def B { attribute mass : Real; }
        }
        """,
        strict=True,
    )
    assert ast.get("type") == "package"
    issues = lint_sysml(ast)
    assert isinstance(issues, list)


def test_lint_sysml_port_def_and_part_port():
    """port_def / part 内 port でリンタの port 関連ルールを通す。"""
    src = """
    package P {
        port def Prt;
        part def X {
            port p : Prt;
        }
    }
    """
    ast = parse_sysml(src, strict=True)
    assert ast.get("type") == "package"
    issues = lint_sysml(ast)
    assert isinstance(issues, list)
    assert all(hasattr(i, "severity") for i in issues)


def test_lint_sysml_action_def():
    ast = parse_sysml("package P { action def Act; }", strict=True)
    assert ast.get("type") == "package"
    issues = lint_sysml(ast)
    assert isinstance(issues, list)


def test_lint_sysml_type_def():
    ast = parse_sysml("package P { type def T; }", strict=True)
    assert ast.get("type") == "package"
    assert isinstance(lint_sysml(ast), list)


def test_lint_sysml_state_def():
    ast = parse_sysml("package P { state def S; }", strict=True)
    assert ast.get("type") == "package"
    assert isinstance(lint_sysml(ast), list)


def test_lint_sysml_requirement_def():
    ast = parse_sysml("package P { requirement def R1; }", strict=True)
    assert ast.get("type") == "package"
    assert isinstance(lint_sysml(ast), list)


def test_lint_sysml_action_def_param_undefined_type_reports_once():
    """package 配下の走査が二重に行われ、action_def のパラメータ型チェックが
    同一メッセージで2件出ていた回帰を固定する。

    型名には BUILTIN_TYPES に依存しない架空の型（NoSuchType）を使う。
    "Real" を使うと、BUILTIN_TYPES に "Real" を追加する別修正と組み合わせた際に
    「存在しない型」ではなくなり本テストの前提が崩れる（実際に組み合わせて確認済み）。
    """
    ast = parse_sysml("package P { action def Act { in x : NoSuchType; } }", strict=True)
    assert ast.get("type") == "package"
    issues = lint_sysml(ast)
    assert len(issues) == 1
    assert issues[0].severity == "error"
    assert "Act" in issues[0].message
    assert "NoSuchType" in issues[0].message


def test_lint_sysml_part_def_child_part_instance_undefined_type_reports_once():
    """_check_part_def の子パート型チェックと _check_part_instance が同じ事実を
    別々に検出し、ERROR/WARNING 計2件（package 走査の重複と合わせて計4件）に
    なっていた回帰を固定する。"""
    ast = parse_sysml("package P { part def Foo { part x : Bar; } }", strict=True)
    assert ast.get("type") == "package"
    issues = lint_sysml(ast)
    assert len(issues) == 1
    assert issues[0].severity == "error"
    assert "Bar" in issues[0].message


def test_lint_sysml_nested_package_reference_resolves():
    """d101_element_existence_check_ignores_cross_file_symbols: packageノードが
    どのシンボル集合にも登録されておらず、`package Outer { package Inner {...}
    import Inner::*; }`のような**同一ファイル内**のネストpackage参照ですら
    「存在しないパッケージ」と誤検出していた回帰を固定する。

    型解決用のself.symbolsではなく専用のself.packagesへ登録しているため、
    パッケージ名を型名として参照した場合は依然エラーになることも確認する。"""
    wildcard = parse_sysml("package Outer { package Inner { part def P; } import Inner::*; }", strict=True)
    assert lint_sysml(wildcard) == []

    member = parse_sysml("package Outer { package Inner { part def P; } import Inner::P; }", strict=True)
    assert lint_sysml(member) == []

    # パッケージ名は「型」ではないため、型参照位置での使用は引き続き検出される。
    as_type = parse_sysml("package Outer { package Inner { part def P; } part x : Inner; }", strict=True)
    assert [i.message for i in lint_sysml(as_type)] != []


def test_lint_sysml_standard_library_import_not_flagged():
    """d101_element_existence_check_ignores_cross_file_symbols: 標準ライブラリの
    パッケージ名が21個しか列挙されておらず（実際は93個）、`import ISQ::*;`・
    `import SequenceFunctions::size;`のような正当な標準ライブラリ参照が
    「存在しないパッケージ/要素」と誤検出されていた（公式コーパスで225件）。

    ネストしたパッケージパス（`KerML::Kernel::*`）は、先頭セグメントが標準
    ライブラリなら配下を検証できないためスキップする（従来はワイルドカード側が
    最終セグメントのみで判定しており非ワイルドカード側と不整合だった）。
    実在しないパッケージが引き続き検出されることも確認する。"""
    for src in (
        "package P { import ISQ::*; }",
        "package P { import SequenceFunctions::size; }",
        "package P { import SpatialFrames::PositionOf; }",
        "package P { import KerML::Kernel::*; }",
    ):
        assert lint_sysml(parse_sysml(src, strict=True)) == [], src

    broken = parse_sysml("package P { import NoSuchPackage::*; }", strict=True)
    issues = lint_sysml(broken)
    assert len(issues) == 1
    assert "NoSuchPackage" in issues[0].message


def test_lint_sysml_imported_names_are_resolvable():
    """d102_qualified_type_lookup_missing_shortname_fallback: import文が
    シンボル知識に一切使われておらず、`private import Collections::KeyValuePair;`
    のように**明示的にimportした**標準ライブラリ型を継承すると「存在しない型」
    と誤検出していた（公式コーパスのlintエラー551件のうち大半がこれ由来）。

    SysML v2では明示importした名前はスコープに入るため、その名前への型参照は
    正当である。中身の見えないパッケージからのワイルドカードimportがある場合は、
    未解決の非修飾名の不在も証明できないため報告しない。
    """
    # 明示的にimportしたメンバー名は型参照として有効。
    explicit = "package P { private import Collections::KeyValuePair; attribute def SamplePair :> KeyValuePair; }"
    assert lint_sysml(parse_sysml(explicit, strict=True)) == []

    # importで持ち込んだ名前を起点とする修飾参照も検証不能なので報告しない。
    nested = (
        "package P { private import Objects::StructuredSpaceObject; "
        "item def Path :> StructuredSpaceObject::StructuredCurve; }"
    )
    assert lint_sysml(parse_sysml(nested, strict=True)) == []

    # 標準ライブラリパッケージ配下のメンバーも同様。
    stdlib = "package P { item def X :> SpatialFrames::SpatialFrame; }"
    assert lint_sysml(parse_sysml(stdlib, strict=True)) == []

    # 中身の見えないワイルドカードimportがあれば、非修飾の未解決名も報告しない。
    wildcard = "package P { private import Objects::*; item def X :> SomeOpaqueType; }"
    assert lint_sysml(parse_sysml(wildcard, strict=True)) == []


def test_lint_sysml_unknown_type_without_import_is_still_flagged():
    """d102の緩和が真の異常を見逃さないことを固定する（偽陰性ガード）。

    - importが一切無ければ、未知の型参照は引き続き検出される。
    - `import NoSuchPackage::*;`自体は引き続き検出される。これは実装中に
      実際に踏んだ回帰で、`_find_element_in_symbols`に緩和ルールを入れると
      「中身の見えないワイルドカードimport」が自分自身の存在チェックを
      成功させてしまい（循環）、golden setのsysml-broken-04が検出できなく
      なった。緩和は型/継承参照専用の_type_reference_existsに限定している。
    """
    no_import = parse_sysml("package P { item def X :> TotallyUnknown; }", strict=True)
    assert [i.message for i in lint_sysml(no_import)] != []

    broken_wildcard = parse_sysml("package P { import NoSuchPackage::*; }", strict=True)
    assert len(lint_sysml(broken_wildcard)) == 1


def test_lint_sysml_enum_def_is_a_type_and_specializes_attribute():
    """d103_enum_def_missing_from_type_system: `enum_def`が2箇所で型システムに
    配線されておらず、公式標準ライブラリ自身が使う正当な形が誤検出されていた。

    (a) linter.pyの`_collect_symbols`の型登録リストに`enum_def`が無く、
        `enum def Foo { A; B; } attribute y : Foo;`という**同一ファイル内で
        定義済み**のenum型参照ですら「存在しない型」になっていた
        （adas-sysmlv2-mainのADAS.sysmlで実際に4件発生していた）。
    (b) type_system.pyの`compatible_groups`に`{ATTRIBUTE, ENUMERATION}`と
        `{REQUIREMENT, CONSTRAINT}`が無く、`enum def LevelEnum :> Level`
        （RiskMetadata.sysml）や`requirement def RequirementCheck :>
        RequirementConstraintCheck`（Requirements.sysml）のような、SysML v2
        仕様上正当な特殊化が「互換性のない型カテゴリの特殊化」になっていた。

    importを一切書かないことで、d102のワイルドカードimport緩和に
    マスクされない状態で検証している。
    """
    # (a) enum型への属性参照
    as_type = "package P { part def X { enum def Foo { A; B; } attribute y : Foo; } }"
    assert lint_sysml(parse_sysml(as_type, strict=True)) == []

    # (b) enum def が attribute def を特殊化する
    enum_attr = "package P { attribute def Level :> Real; enum def LevelEnum :> Level { low; high; } }"
    assert lint_sysml(parse_sysml(enum_attr, strict=True)) == []

    # (b) requirement def が constraint def を特殊化する。
    # requirement定義には別途「docを書くことを推奨」というWARNINGが付くため、
    # ここでは対象の型カテゴリ互換性エラーが出ないことだけを確認する。
    req_constraint = (
        "package P { abstract constraint def RequirementConstraintCheck; "
        "abstract requirement def RequirementCheck :> RequirementConstraintCheck; }"
    )
    req_messages = [i.message for i in lint_sysml(parse_sysml(req_constraint, strict=True))]
    assert not [m for m in req_messages if "互換性のない型カテゴリ" in m], req_messages
    assert not [m for m in req_messages if "存在しない" in m], req_messages

    # 偽陰性ガード: 実在しない型はenum周りの緩和では通さない。
    unknown = "package P { part def X { attribute y : NoSuchEnum; } }"
    assert [i.message for i in lint_sysml(parse_sysml(unknown, strict=True))] != []


def test_lint_sysml_abstract_connection_def_may_have_no_ends():
    """d104_abstract_connection_def_zero_ends_false_positive:
    `abstract connection def Connection :> LinkObject, Part { doc ... }`
    （Connections.sysml等、公式標準ライブラリ自身の形）のように、抽象基底の
    connection定義はendを一切宣言せず具体的な子定義側で宣言するのが正当だが、
    `_check_connection_structure_advanced`がisAbstractを確認せず常に
    「コネクターエンドが0個しかありません」とエラーにしていた。

    非抽象で0個の場合は引き続きエラーになること（偽陰性ガード）も固定する。
    """
    abstract_def = "package P { abstract connection def C { doc /* base */ } }"
    assert lint_sysml(parse_sysml(abstract_def, strict=True)) == []

    concrete = "package P { connection def D { doc /* concrete */ } }"
    messages = [i.message for i in lint_sysml(parse_sysml(concrete, strict=True))]
    assert [m for m in messages if "コネクターエンド" in m], messages


def test_lint_sysml_qualified_reference_rooted_at_wildcard_import():
    """d105_qualified_reference_rooted_at_wildcard_imported_name:
    d102の緩和が拾えていなかった2つのサブケースを固定する。

    (a) 修飾名の先頭セグメントが**ワイルドカードimport由来**の場合
        （ShapeItems.sysmlの`item def Path :> StructuredSpaceObject::
        StructuredCurve;`は`private import Objects::*;`由来）。名前自体が
        検証不能なら配下のメンバーも検証不能という推論で緩和する。
    (b) usage の`type_name`は「型」参照なのに要素用の
        `_find_element_in_symbols`で引いていた6箇所（interface/allocation/
        calculation/constraint/assert constraint/satisfy requirement usage）。
        d102で継承5箇所に適用したのと同じ是正。

    偽陰性ガードとして、ワイルドカードimportが無い場合に未知の修飾名が
    引き続き検出されること、`import NoSuchPackage::*;`が引き続き検出される
    ことも固定する（d102で踏んだ循環回帰の再発防止）。
    """
    # (a) ワイルドカードimport由来の名前を起点とする修飾参照
    wildcard_rooted = (
        "package P { private import Objects::*; "
        "item def Path :> StructuredSpaceObject::StructuredCurve; }"
    )
    assert lint_sysml(parse_sysml(wildcard_rooted, strict=True)) == []

    # (b) usage の type_name が明示importで解決できる
    usage_type = (
        "package P { private import Constraints::ConstraintCheck; "
        "part def X { constraint c : ConstraintCheck; } }"
    )
    assert lint_sysml(parse_sysml(usage_type, strict=True)) == []

    # 偽陰性ガード: ワイルドカードimportが無ければ未知の修飾名は検出される。
    no_wildcard = parse_sysml("package P { item def Path :> NoSuchRoot::Member; }", strict=True)
    assert [i.message for i in lint_sysml(no_wildcard)] != []

    # 偽陰性ガード: 実在しないパッケージのワイルドカードimportは引き続き検出。
    assert len(lint_sysml(parse_sysml("package P { import NoSuchPackage::*; }", strict=True))) == 1


def test_lint_sysml_transition_endpoints_accept_action_usage():
    """d106_transition_source_target_rejects_action_usage:
    `_find_state_in_symbols`が`state_def`/`state_usage`だけを受理し、かつ
    型解決用の`self.symbols`のみを走査していたため、`action start: Action
    :>> startShot`のような**action usage**（`self.element_refs`に登録される）
    をtransitionのsource/targetに使う形（Actions.sysmlの
    `transition aTransition first start ... then done;`）を
    「ステートが存在しません」と誤検出していた。

    SysML v2ではTransitionUsageのsource/targetはOccurrenceUsageであり、
    ステートに限らずaction/occurrence usageも参照できる。一方、属性や
    ポートまで許すと検出力が落ちるためoccurrence系に限定している。
    """
    action_endpoints = (
        "action def A { action start; action done; "
        "state aState { transition aTransition first start then done; } }"
    )
    messages = [i.message for i in lint_sysml(parse_sysml(action_endpoints, strict=True))]
    assert not [m for m in messages if "ステート" in m], messages

    # 偽陰性ガード（golden setのsysml-broken-06と同形）: 実在しない参照先は
    # 引き続き検出される。
    broken = "state def Switch { state Off; transition first Off accept TurnOn then NonExistentState; }"
    broken_messages = [i.message for i in lint_sysml(parse_sysml(broken, strict=True))]
    assert [m for m in broken_messages if "ターゲットステート" in m], broken_messages
