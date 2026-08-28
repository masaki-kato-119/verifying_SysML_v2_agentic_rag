"""ANTLR4ベースのSysML v2パーサー（sysml_v2_checker_advanced/antlr/SysMLMin.g4）
の出力AST形状を固定する回帰テスト。

フェーズ4（parser.pyの既定パーサー切り替え）完了に伴い、`parse_sysml`
（parser.py）は本ファイルがテストする`parse_sysml_antlr`をそのまま使う。
そのため「旧Lark実装との比較」というこのファイルの当初の目的は終えており、
以降は単一パーサーのAST出力形状をロックする回帰テストとして機能する。
各テストのdocstring/コメントには、移行過程で発見した旧Lark実装（既に削除済み）
特有のバグや制約を歴史的な記録として残している箇所がある
（「旧実装は...」という記述は現在は存在しないコードについての説明）。

sysml_v2_checker_advanced/antlr/README.md および COVERAGE.md も参照。
"""

from pathlib import Path

import pytest

from sysml_v2_checker_advanced.antlr_transformer import parse_sysml_antlr
from sysml_v2_checker_advanced.parser import lint_sysml as lint_ast

CORPUS_DIR = Path(__file__).resolve().parent / "fixtures" / "sysml_corpus"


def test_antlr_parser_reports_error_dict_on_unsupported_syntax():
    """構文的に無効な入力は例外を投げず、error辞書形式で失敗する。"""
    ast = parse_sysml_antlr("package P { this is not @@@ valid sysml {{{ }")
    assert ast.get("type") == "error"
    assert "message" in ast


# --- 式（KerMLExpressions.xtext由来の演算子優先順位） -----------------------------
#
# linter.pyは式の中身を検証しないため（calculation_def/constraint_def/
# assert_constraint_usageのチェック関数はname/inheritance/type_nameしか読まない）、
# ここでは新パーサー自身が正しい構文木を組み立てることだけを固定する。
# 単項マイナスを乗除より弱く結合する形で実装してしまい `-x > 0` が `-(x > 0)` と
# 解釈される回帰を一度作り込んだため、特に単項マイナスの優先順位を明示的に固定する。

def test_antlr_expression_operator_precedence():
    ast = parse_sysml_antlr("constraint def C { x + 1 * 2 > 3.5; }")
    expr = ast["children"][0]["children"][0]["expression"]
    # (x + (1 * 2)) > 3.5
    assert expr == {
        "type": "binary_expr",
        "op": ">",
        "left": {
            "type": "binary_expr",
            "op": "+",
            "left": {"type": "name_ref", "reference": "x"},
            "right": {
                "type": "binary_expr",
                "op": "*",
                "left": {"type": "literal", "literal_type": "int", "value": 1},
                "right": {"type": "literal", "literal_type": "int", "value": 2},
            },
        },
        "right": {"type": "literal", "literal_type": "real", "value": 3.5},
    }


def test_antlr_unary_minus_binds_tighter_than_relational():
    """`-x > 0` は `(-x) > 0` であって `-(x > 0)` ではない（回帰）。"""
    ast = parse_sysml_antlr("constraint def C { -x > 0; }")
    expr = ast["children"][0]["children"][0]["expression"]
    assert expr["type"] == "binary_expr"
    assert expr["op"] == ">"
    assert expr["left"] == {
        "type": "unary_expr",
        "op": "-",
        "operand": {"type": "name_ref", "reference": "x"},
    }


def test_antlr_parenthesized_expression_overrides_precedence():
    ast = parse_sysml_antlr("constraint def C { (x + 1) * 2 == 3; }")
    expr = ast["children"][0]["children"][0]["expression"]
    # ((x + 1) * 2) == 3 -- 括弧はグルーピングのみで、AST上には出てこない。
    assert expr["op"] == "=="
    assert expr["left"] == {
        "type": "binary_expr",
        "op": "*",
        "left": {
            "type": "binary_expr",
            "op": "+",
            "left": {"type": "name_ref", "reference": "x"},
            "right": {"type": "literal", "literal_type": "int", "value": 1},
        },
        "right": {"type": "literal", "literal_type": "int", "value": 2},
    }


def test_antlr_string_and_boolean_literals():
    ast = parse_sysml_antlr('constraint def C { name == "hello"; }')
    expr = ast["children"][0]["children"][0]["expression"]
    assert expr["right"] == {"type": "literal", "literal_type": "string", "value": "hello"}

    ast2 = parse_sysml_antlr("constraint def C { flag == true; }")
    expr2 = ast2["children"][0]["children"][0]["expression"]
    assert expr2["right"] == {"type": "literal", "literal_type": "boolean", "value": True}


# --- case/view/viewpoint/rendering/metadata (8.2.2.22-27) ------------------------
#
# 旧Lark実装はこの一群で複数のバグを抱えていた（例: view_defはidentification
# 辞書をstr()した文字列がnameに入る、viewpoint_def/rendering_defはnameが
# 常に空文字列）。新パーサーではこれらのバグを継承せず、正しい名前が
# 取れることを固定する。

@pytest.mark.parametrize(
    "text,expected_type,expected_name",
    [
        ("view def SystemView;", "view_def", "SystemView"),
        ("viewpoint def SafetyViewpoint;", "viewpoint_def", "SafetyViewpoint"),
        ("rendering def Diagram;", "rendering_def", "Diagram"),
        ("use case uc;", "use_case_usage", "uc"),
    ],
)
def test_antlr_case_view_metadata_names_are_not_buggy(text, expected_type, expected_name):
    ast = parse_sysml_antlr(text)
    node = ast["children"][0]
    assert node["type"] == expected_type
    assert node["name"] == expected_name  # 旧Lark実装ではここが "" になるバグがあった


def test_antlr_walking_skeleton_minimal_package():
    ast = parse_sysml_antlr("package Empty { }")
    assert ast == {"type": "package", "name": "Empty", "shortName": None, "children": []}


# --- トップレベルはpackageで包まなくてよい（暗黙のルート名前空間） -------------
#
# real_coffee_sequence.sysml 等の実サンプルが `private import ...;` のように
# package でくくらず書けているのはこのため。旧Lark実装(grammar.py:16
# `start: top_level_stmt*`)と同じ規約に合わせ、`{"type": "root", ...}` で包む
# 条件（package単体1個のときだけ包まない）も含めて一致させている。

def test_antlr_empty_input_wraps_in_root():
    assert parse_sysml_antlr("") == {"type": "root", "children": []}


def test_antlr_quoted_name_with_spaces():
    """スペースを含む単一引用符名（`'Coffee Brewing Sequence'`）を宣言名として使える。

    real_coffee_sequence.sysml / real_coffee_v4.sysml のブロッカーの一つだった。
    """
    ast = parse_sysml_antlr("action def 'Coffee Brewing Sequence' { in x : Real; }")
    assert ast["children"][0]["name"] == "Coffee Brewing Sequence"


def test_antlr_single_non_package_element_still_wraps_in_root():
    ast = parse_sysml_antlr("part def A;")
    assert ast == {
        "type": "root",
        "children": [
            {
                "type": "part_def",
                "name": "A",
                "shortName": None,
                "inheritance": None,
                "isAbstract": False,
                "isIndividual": False,
                "children": [],
            }
        ],
    }


# 旧known_broken/*.sysml（connect_to.sysml等の小規模ケースとreal_*.sysmlの
# 実サンプル5個）は、フェーズ4切り替えに伴い tests/fixtures/sysml_corpus/
# working/ へ移動し、tests/test_sysml_corpus.py の汎用テストで
# パース成功・lint非クラッシュの両方を検証している（旧来はこのファイルで
# 個別にparse_sysml_antlrを呼んで確認していたが、working/への統合により
# 重複を解消した）。


# --- expose / connection def の出力形状 -----------------------------------------
#
# expose の単一名形（`expose Q;`）は追加フィールド（wildcard/children）を
# 持ち、connection def は他の全ての_def（part_def等）と同じフラットな
# childrenリストを使う（8.2.2.13、AST_SCHEMA.md参照）。新パーサー自身の
# 出力形状を直接固定する。

def test_antlr_expose_simple_produces_compatible_superset_of_old_lark():
    """旧Lark実装の {"type":"special_stmt","children":[{"type":"expose",
    "qualified_name":...}]}} という入れ子は再現しつつ、wildcard/childrenフィールドを
    追加している（linter.pyのcheck_functionsは未知キーを無視するため無害）。
    """
    ast = parse_sysml_antlr("expose Q;")
    assert ast == {
        "type": "root",
        "children": [
            {
                "type": "special_stmt",
                "children": [
                    {"type": "expose", "qualified_name": "Q", "wildcard": False, "children": []}
                ],
            }
        ],
    }
    issues = lint_ast(ast)
    assert len(issues) == 1  # Qが未定義のためエラーになる想定


def test_antlr_connection_def_uses_flat_children_not_old_lark_nesting():
    """connection defは旧Lark実装のdefinition_member/connection_body_itemという
    入れ子を意図的に踏襲せず、他の全ての_def（part_def等）と同じフラットな
    childrenリストにしている（COVERAGE.md参照）。
    """
    ast = parse_sysml_antlr("connection def C { attribute x : Real; }")
    assert ast == {
        "type": "root",
        "children": [
            {
                "type": "connection_def",
                "name": "C",
                "inheritance": None,
                "isAbstract": False,
                "children": [
                    {
                        "type": "attribute_usage",
                        "name": "x",
                        "shortName": None,
                        "type_name": "Real",
                        "multiplicity": None,
                        "inheritance": None,
                        "isAbstract": False,
                        "isConstant": False,
                        "isDerived": False,
                        "visibility": None,
                        "redefines": [],
                        "value": None,
                        "defaultValue": None,
                        "children": [],
                    }
                ],
            }
        ],
    }
    lint_ast(ast)  # クラッシュしないことを確認


# --- comment / documentation / textual representation (8.2.2.4) ------------------
#
# 新パーサー自身の出力が正しく組み立てられることを直接固定する。

def test_antlr_comment_with_identification():
    ast = parse_sysml_antlr("comment MyComment /* a note */")
    assert ast["children"][0] == {
        "type": "comment",
        "identification": {"type": "identification", "name": "MyComment"},
        "about": None,
        "locale": None,
        "body": "a note",
        "children": [],
    }


def test_antlr_comment_without_identification():
    ast = parse_sysml_antlr("comment /* a note */")
    node = ast["children"][0]
    assert node["identification"] is None
    assert node["body"] == "a note"
    issues = lint_ast(ast)
    assert issues == []  # identificationは省略可能なのでエラーにならない


def test_antlr_documentation_stmt_with_name_passes_lint():
    ast = parse_sysml_antlr("doc D /* documentation text */")
    node = ast["children"][0]
    assert node == {
        "type": "documentation",
        "identification": {"type": "identification", "name": "D"},
        "locale": None,
        "body": "documentation text",
        "children": [],
    }
    assert lint_ast(ast) == []


def test_antlr_documentation_stmt_without_name_passes_lint():
    """d7_documentation_stmt_optional_name: identificationは仕様上任意であり、
    公式SysML v2標準ライブラリはほぼ全ての要素で名前無しのdocを使う
    （CONFORMANCE_REPORT_2026-08-20.md参照）。以前はsimpleNameが文法上
    必須で、名前無しdocはrequirementBodyElement専用のdocMember規則
    でしか使えなかった。"""
    ast = parse_sysml_antlr("doc /* documentation text */")
    node = ast["children"][0]
    assert node == {
        "type": "documentation",
        "identification": None,
        "locale": None,
        "body": "documentation text",
        "children": [],
    }
    assert lint_ast(ast) == []


def test_antlr_requirement_doc_no_longer_requires_identification():
    """d7_documentation_stmt_optional_name: requirementBodyElementはdocMemberを
    廃止しdocumentationStmtへ統一した。以前はrequirement内のdocが常に
    「identification必須」エラー+「bodyが空」警告の2件を出していたが
    （b5のsysml-broken-22、既知の制約として記録）、今はdocumentationStmt側の
    identification必須チェック自体を撤廃したため0件になる。"""
    ast = parse_sysml_antlr("requirement def R {\n    doc /* some text */\n}\n")
    assert lint_ast(ast) == []


def test_antlr_textual_representation_stmt():
    ast = parse_sysml_antlr('language "Markdown" /* some spec text */')
    node = ast["children"][0]
    assert node == {
        "type": "textual_representation",
        "identification": None,
        "language": "Markdown",
        "locale": None,
        "body": "some spec text",
        "children": [],
    }


def test_antlr_comment_about_and_locale():
    """`comment about C /* ... */`・`comment cmt_cmt about cmt /* ... */`
    （Comments.sysml/CommentTest.sysml）のように、コメント対象を明示する
    `about`節と、ロケール注釈`locale`節を持つことがある（2026-08-28、
    参照実装比較レポートP1-5で発見）。`about`はpartBodyElement内にも
    書ける。"""
    ast = parse_sysml_antlr("part def C; comment about C /* about a def */")
    node = ast["children"][-1]
    assert node["about"] == "C"
    assert node["locale"] is None

    named_ast = parse_sysml_antlr(
        'part def C { comment about C locale "en_US" /* ... */ }'
    )
    named_node = named_ast["children"][0]["children"][0]
    assert named_node["about"] == "C"
    assert named_node["locale"] == "en_US"


def test_antlr_documentation_and_textual_representation_locale():
    """`doc locale "en_US" /* ... */`（CommentTest.sysml）のようなロケール
    注釈（2026-08-28、参照実装比較レポートP1-5で発見）。裸の
    `locale "en_US" /* ... */`（キーワード無し）も同様。"""
    doc_ast = parse_sysml_antlr('doc locale "en_US" /* text */')
    assert doc_ast["children"][0]["locale"] == "en_US"

    bare_ast = parse_sysml_antlr('locale "en_US" /* text */')
    assert bare_ast["children"][0] == {
        "type": "documentation",
        "identification": None,
        "locale": "en_US",
        "body": "text",
        "children": [],
    }

    rep_ast = parse_sysml_antlr('language "OCL" locale "en_US" /* text */')
    assert rep_ast["children"][0]["locale"] == "en_US"
    assert rep_ast["children"][0]["language"] == "OCL"


# --- multiplicity (8.2.2.6.6) -----------------------------------------------------
#
# 旧Lark実装は `[0..1]` を8.2.2.6.6準拠の深い入れ子（multiplicity_range等）で
# 返すが、実測したところ upper の値抽出にバグがあり、`[0..1]` の upper が
# 常に 0 になる（lowerと同じ値になってしまう）ことを確認した。新パーサーは
# より単純な「レガシーsize辞書」形式を使い、この不具合を継承しない。
# is_ordered/is_unique（`ordered`/`nonunique`修飾子）を追加した際、無指定時の
# デフォルト（is_ordered=False, is_unique=True。KerMLの既定値）も常に含める
# ように仕様を確定した。

def test_antlr_multiplicity_range():
    ast = parse_sysml_antlr("part def A; part def B; part b : B[0..1];")
    part_b = ast["children"][2]
    assert part_b["multiplicity"] == {
        "size": {"min": 0, "max": 1},
        "is_ordered": False,
        "is_unique": True,
    }
    assert lint_ast(ast) == []


def test_antlr_multiplicity_single_value_means_exact_count():
    ast = parse_sysml_antlr("part def A; part def B; part b : B[3];")
    part_b = ast["children"][2]
    assert part_b["multiplicity"]["size"] == {"min": 3, "max": 3}


def test_antlr_multiplicity_star_upper_bound():
    ast = parse_sysml_antlr("part def A; part def B; part b : B[0..*];")
    part_b = ast["children"][2]
    assert part_b["multiplicity"]["size"] == {"min": 0, "max": "*"}


def test_antlr_multiplicity_invalid_range_is_detected_by_linter():
    """[5..1] のような下限>上限を、新パーサーの単純な形でも正しく検出できる
    （旧Lark実装のupperバグでは検出できていなかったはずの回帰）。"""
    ast = parse_sysml_antlr("part def A; part def B; part b : B[5..1];")
    issues = lint_ast(ast)
    assert len(issues) == 1
    assert issues[0].severity == "error"


def test_antlr_attribute_usage_multiplicity():
    ast = parse_sysml_antlr("part def A { attribute x : Real[1..3]; }")
    attr = ast["children"][0]["children"][0]
    assert attr["multiplicity"]["size"] == {"min": 1, "max": 3}


def test_antlr_multiplicity_ordered_nonunique_modifiers():
    """`[n..m] ordered nonunique;` のような修飾子を正しく解釈できる。

    旧Lark実装はこの構文自体はパースできるが、is_ordered/is_uniqueを
    "multiplicity"型dictへ直接埋め込み、しかも`_check_multiplicity`はこれらを
    一切検証しない（装飾的フィールド）。新パーサーも同じ場所（"multiplicity"の
    "size"辞書の隣）に置くが、8.2.2.6.6準拠の別フィールド"multiplicity_part"
    （実質未使用のコードパス、AST_SCHEMA.md §3.14参照）は使わない。
    """
    ordered_only = parse_sysml_antlr("part def A; part def B; part b : B[0..1] ordered;")
    assert ordered_only["children"][2]["multiplicity"] == {
        "size": {"min": 0, "max": 1},
        "is_ordered": True,
        "is_unique": True,
    }

    nonunique_only = parse_sysml_antlr("part def A; part def B; part b : B[0..1] nonunique;")
    assert nonunique_only["children"][2]["multiplicity"] == {
        "size": {"min": 0, "max": 1},
        "is_ordered": False,
        "is_unique": False,
    }

    both = parse_sysml_antlr("part def A; part def B; part b : B[0..*] ordered nonunique;")
    assert both["children"][2]["multiplicity"] == {
        "size": {"min": 0, "max": "*"},
        "is_ordered": True,
        "is_unique": False,
    }


# --- connection def の end member (8.2.2.13) --------------------------------------

def test_antlr_connection_def_end_members():
    """`connection def C { end a : PortA; end b : PortB; }`。旧Lark実装は
    パースできるがconnection_body_itemという入れ子で包む
    （AST_SCHEMA.md §3.8で説明済みの理由により踏襲しない、フラットな形）。
    """
    ast = parse_sysml_antlr("connection def C { end a : PortA; end b : PortB; }")
    conn = ast["children"][0]
    assert conn["children"] == [
        {
            "type": "connection_end_member", "name": "a", "endName": "a", "kind": None,
            "isRef": False, "type_name": "PortA", "multiplicity": None, "endMultiplicity": None,
            "redefines": [], "children": [],
        },
        {
            "type": "connection_end_member", "name": "b", "endName": "b", "kind": None,
            "isRef": False, "type_name": "PortB", "multiplicity": None, "endMultiplicity": None,
            "redefines": [], "children": [],
        },
    ]
    lint_ast(ast)  # クラッシュしないことを確認


def test_antlr_connection_end_member_keyword_and_redefine():
    """d58_end_prefixed_connector_end_declaration: Flows.sysmlの`end
    occurrence source: Occurrence :>> Message::source, FlowTransfer::
    source;`のように、`occurrence`/`port`/`item`キーワード・redefine節
    （複数可）・bodyがend memberに一切未対応だった。"""
    src = (
        "connection def C { end occurrence source: Occurrence :>> "
        "Message::source, FlowTransfer::source; }"
    )
    ast = parse_sysml_antlr(src)
    node = ast["children"][0]["children"][-1]
    assert node["type"] == "connection_end_member"
    assert node["name"] == "source"
    assert node["kind"] == "occurrence"
    assert node["type_name"] == "Occurrence"
    assert [r["kind"] for r in node["redefines"]] == ["redefines"]
    assert node["redefines"][0]["targets"] == ["Message::source", "FlowTransfer::source"]


def test_antlr_connection_end_member_outer_name_and_body():
    """d58_end_prefixed_connector_end_declaration: CausationConnections.
    sysmlの`end theCauses [*] occurrence theCause :> causes :>> source {
    doc ... }`のように、connector end自体の別名（内側featureの名前とは
    別）・複数のredefine節・bodyを伴う形。"""
    src = (
        "connection def C { end theCauses [*] occurrence theCause "
        ":> causes :>> source { doc /* c */ } }"
    )
    ast = parse_sysml_antlr(src)
    node = ast["children"][0]["children"][-1]
    assert node["type"] == "connection_end_member"
    assert node["name"] == "theCause"
    assert node["endName"] == "theCauses"
    assert node["endMultiplicity"]["size"] == {"min": "*", "max": "*"}
    assert [r["kind"] for r in node["redefines"]] == ["subsets", "redefines"]
    assert len(node["children"]) == 1


def test_antlr_connection_end_member_conjugated_type():
    """`end p2: ~P;`（ConjugationTest.sysml）のような共役ポート参照。
    portUsageは既に対応していたが非対称だった（2026-08-28、参照実装比較
    レポートP1-4で発見）。"""
    ast = parse_sysml_antlr("interface def I { end p1: P; end p2: ~P; }")
    plain, conjugated = ast["children"][0]["children"]
    assert plain["type_name"] == "P"
    assert conjugated["type_name"] == "~P"


# --- calculation usage / constraint usage / satisfy requirement usage ------------
# (8.2.2.19, 8.2.2.20, 8.2.2.21.2)

def test_antlr_calculation_usage_and_constraint_usage():
    ast = parse_sysml_antlr("calc def Calc; calc x : Calc;")
    calc_usage = ast["children"][1]
    assert calc_usage == {
        "type": "calculation_usage",
        "name": "x",
        "shortName": None,
        "type_name": "Calc",
        "multiplicity": None,
        "isAbstract": False,
        "isRef": False,
        "visibility": None,
        "redefines": [],
        "children": [],
    }
    assert lint_ast(ast) == []


def test_antlr_satisfy_requirement_usage_bare_and_typed():
    bare = parse_sysml_antlr("assert satisfiedBy x;")
    assert bare["children"][0] == {
        "type": "satisfy_requirement_usage",
        "is_negated": False,
        "name": "x",
        "type_name": None,
        "by": None,
        "children": [],
    }

    typed = parse_sysml_antlr("assert not satisfiedBy requirement w : R;")
    assert typed["children"][0] == {
        "type": "satisfy_requirement_usage",
        "is_negated": True,
        "name": "w",
        "type_name": "R",
        "by": None,
        "children": [],
    }


# --- state machine: entry/do/exit action と transition (8.2.2.18) ----------------
#
# _check_state_actions（linter.py:3535）はentry_action/do_action/exit_actionに
# "kind"フィールド（"entry"/"do"/"exit"）を要求する。これが無いと
# 「kind = 'None' が設定されていますが、'entry' である必要があります」という
# エラーになる（フェーズ2で最初にentry_actionを実装した際、実はこのエラーが
# 出ていた。ここでkindフィールドを追加して解消した）。

def test_antlr_entry_do_exit_action_have_correct_kind_and_pass_lint():
    ast = parse_sysml_antlr(
        "state def S { entry action A; do action D; exit action E; }"
    )
    state = ast["children"][0]
    kinds = {child["type"]: child["kind"] for child in state["children"]}
    assert kinds == {"entry_action": "entry", "do_action": "do", "exit_action": "exit"}
    assert lint_ast(ast) == []


def test_antlr_bare_entry_action_without_reference():
    ast = parse_sysml_antlr("state def S { entry; }")
    entry = ast["children"][0]["children"][0]
    assert entry == {"type": "entry_action", "kind": "entry", "action_reference": None, "type_name": None, "redefines": [], "children": []}


def test_antlr_transition_minimal_source_and_target():
    ast = parse_sysml_antlr(
        "state def S { state def A; state def B; transition first A then B; }"
    )
    transition = ast["children"][0]["children"][2]
    assert transition["source"] == "A"
    assert transition["target"] == "B"
    assert transition["trigger"] is None
    assert transition["guard"] is None
    assert transition["effect"] is None
    assert lint_ast(ast) == []


def test_antlr_transition_full_form_with_trigger_guard_effect():
    ast = parse_sysml_antlr(
        "state def S { state def A; state def B; "
        "transition T1 first A accept Trig if x > 0 do action Y then B; }"
    )
    transition = ast["children"][0]["children"][2]
    assert transition["name"] == "T1"
    assert transition["trigger"] == {"kind": "trigger", "reference": "Trig"}
    assert transition["effect"] == {"kind": "effect", "action_reference": "Y"}
    guard = transition["guard"]
    assert guard["kind"] == "guard"
    assert guard["expression"] == {
        "type": "binary_expr",
        "op": ">",
        "left": {"type": "name_ref", "reference": "x"},
        "right": {"type": "literal", "literal_type": "int", "value": 0},
    }
    assert lint_ast(ast) == []


def test_antlr_transition_accept_when_and_at_triggers():
    """`accept when EXPR`（変化トリガー）/`accept at EXPR`（時刻トリガー）は
    既存の単純な信号参照トリガーとは別の代替（2026-08-28、参照実装比較
    レポートP0-5で発見。`5-State-based Behavior-1a.sysml`で確認）。"""
    when_ast = parse_sysml_antlr(
        "state def S { state def A; state def B; "
        "transition first A accept when x > 0 then B; }"
    )
    when_transition = when_ast["children"][0]["children"][2]
    assert when_transition["trigger"] == {
        "kind": "trigger",
        "trigger_kind": "when",
        "expression": {
            "type": "binary_expr",
            "op": ">",
            "left": {"type": "name_ref", "reference": "x"},
            "right": {"type": "literal", "literal_type": "int", "value": 0},
        },
    }
    assert lint_ast(when_ast) == []

    at_ast = parse_sysml_antlr(
        "state def S { state def A; state def B; "
        "transition first A accept at t then B; }"
    )
    at_transition = at_ast["children"][0]["children"][2]
    assert at_transition["trigger"] == {
        "kind": "trigger",
        "trigger_kind": "at",
        "expression": {"type": "name_ref", "reference": "t"},
    }


def test_antlr_transition_do_inline_send_effect():
    """`do send new 'Over Temp'() to target;`のようなインラインsendアクション
    （2026-08-28、参照実装比較レポートP0-5で発見）。既存の`do action Y`
    （既存アクション参照）とは別の代替。"""
    ast = parse_sysml_antlr(
        "state def S { state def A; state def B; "
        "transition first A do send new Signal() to B then B; }"
    )
    transition = ast["children"][0]["children"][2]
    effect = transition["effect"]
    assert effect["kind"] == "effect"
    assert effect["send"]["to"] == "B"
    assert effect["send"]["via"] is None
    assert effect["send"]["payload"]["type"] == "new_instance"
    assert lint_ast(ast) == []


def test_antlr_transition_undefined_source_state_is_detected():
    """transitionのsource/targetは_find_state_in_symbolsでstate_defとして
    登録された名前しか見つけられない（bare `state X;` usageは未対応）。"""
    ast = parse_sysml_antlr(
        "state def S { state def B; transition first NoSuchState then B; }"
    )
    issues = lint_ast(ast)
    assert len(issues) == 1
    assert "NoSuchState" in issues[0].message


def test_antlr_nested_state_def():
    ast = parse_sysml_antlr("state def S { state def Sub; }")
    assert ast == {
        "type": "root",
        "children": [
            {
                "type": "state_def",
                "name": "S",
                "inheritance": None,
                "isAbstract": False,
                "children": [
                    {
                        "type": "state_def",
                        "name": "Sub",
                        "inheritance": None,
                        "isAbstract": False,
                        "children": [],
                    }
                ],
            }
        ],
    }


# --- decision/fork/join/merge・代入文・send action (8.2.2.17, Section 7.17) ------
#
# control nodeと代入文の設計判断はAST_SCHEMA.md §3.20参照。
# send actionはworking/send_action.sysmlでも検証済み。


def test_antlr_decision_bare_and_named():
    ast = parse_sysml_antlr("action def Act { decision; decision D; }")
    children = ast["children"][0]["children"]
    assert children[0] == {"type": "decision_node", "name": None, "children": []}
    assert children[1] == {"type": "decision_node", "name": "D", "children": []}
    lint_ast(ast)  # クラッシュしないことを確認


def test_antlr_fork_join_merge_bare():
    ast = parse_sysml_antlr("action def Act { fork; join; merge; }")
    children = ast["children"][0]["children"]
    assert [c["type"] for c in children] == ["fork_node", "join_node", "merge_node"]
    assert all(c["name"] is None and c["children"] == [] for c in children)


def test_antlr_decision_with_nested_body():
    """control nodeのbodyはactionBodyElementの反復を許可し、代入・send action
    をネストできる（旧Lark実装のflow_node_bodyより実用上広い。AST_SCHEMA.md参照）。"""
    ast = parse_sysml_antlr("action def Act { decision D { x = 1; send p to q; } }")
    decision = ast["children"][0]["children"][0]
    assert decision["name"] == "D"
    assert decision["children"] == [
        {
            "type": "assignment_stmt",
            "name": "x",
            "operator": "=",
            "value": {"type": "literal", "literal_type": "int", "value": 1},
        },
        {"type": "send_action", "name": None, "payload": "p", "target": "q", "target_type": "to"},
    ]


def test_antlr_assignment_stmt_eq_and_walrus():
    ast = parse_sysml_antlr("action def Act { x = 1; y := a + b; }")
    x_assign, y_assign = ast["children"][0]["children"]
    assert x_assign == {
        "type": "assignment_stmt",
        "name": "x",
        "operator": "=",
        "value": {"type": "literal", "literal_type": "int", "value": 1},
    }
    assert y_assign == {
        "type": "assignment_stmt",
        "name": "y",
        "operator": ":=",
        "value": {
            "type": "binary_expr",
            "op": "+",
            "left": {"type": "name_ref", "reference": "a"},
            "right": {"type": "name_ref", "reference": "b"},
        },
    }


def test_antlr_send_action_all_forms():
    """working/send_action.sysmlと同一内容（名前付き/to/viaの3形式）を直接検証する。"""
    text = (
        "action def Act { action snd send x to y; send x to y; send x via y; }"
    )
    ast = parse_sysml_antlr(text)
    assert ast["children"][0]["children"] == [
        {"type": "send_action", "name": "snd", "payload": "x", "receiver": "y"},
        {"type": "send_action", "name": None, "payload": "x", "target": "y", "target_type": "to"},
        {"type": "send_action", "name": None, "payload": "x", "target": "y", "target_type": "via"},
    ]


def test_antlr_send_action_double_colon_qualified_payload():
    """d100_send_action_double_colon_qualified_payload_missing: 実モデル
    （adas-sysmlv2-main）のADAS.sysmlの`send FCW::'FCWの作動を判定する'.
    '警報' via '警報出力';`のように、send文のpayload参照が`::`（パッ
    ケージ限定）と`.`（フィーチャアクセス）を混在させる場合に受理でき
    なかった（d92/d94/d95/d98/d99と同根）。payloadのみ`qualifiedName`
    から`namespacePath`へ差し替えた。既存の単一セグメント形との共存も
    確認する。"""
    ast = parse_sysml_antlr("action def A { send FCW::'B'.'C' via port2; }")
    node = ast["children"][0]["children"][0]
    assert node == {
        "type": "send_action",
        "name": None,
        "payload": "FCW::B::C",
        "target": "port2",
        "target_type": "via",
    }


def test_antlr_action_def_separates_params_from_control_flow_children():
    """param型の子はparamsへ、それ以外(decision_node/assignment_stmt等)は
    childrenへ分離される（旧Lark実装 action_def_stmt と同じ振る舞い。
    linter.pyのcontrol node/send actionチェックはchildrenしか見ないため必須）。"""
    ast = parse_sysml_antlr("action def Act { in item x : T; decision D; y = 2; }")
    action = ast["children"][0]
    assert action["params"] == [
        {
            "type": "param",
            "direction": "in",
            "is_item": True,
            "kind": "item",
            "name": "x",
            "type_spec": {"name": "T"},
            "type_name": "T",
            "multiplicity": None,
            "redefines": [],
            "value": None,
            "defaultValue": None,
            "children": [],
        }
    ]
    assert [c["type"] for c in action["children"]] == ["decision_node", "assignment_stmt"]


# --- accept action / perform action / message / if-else / action usage --------
# (real_sequence_diagram.sysml の残ブロッカー解消。COVERAGE.md / AST_SCHEMA.md §3.20参照)


def test_antlr_accept_action_with_type():
    text = "action def Act { accept response : ConnectionResponse via client; }"
    ast = parse_sysml_antlr(text)
    assert ast["children"][0]["children"][0] == {
        "type": "accept_action",
        "message": "response",
        "message_type": "ConnectionResponse",
        "port": "client",
    }


def test_antlr_named_accept_action_bare_body():
    """d95_named_accept_action_bare_body_missing: 実モデル
    （adas-sysmlv2-main）のADAS.sysmlの`action '外界取得' accept scene
    : Items::'外界' via 'レンズ';`のように、ネストしたアクションノード
    に`action`キーワード+名前という名前付きプレフィックスを伴い、本体
    自体が波括弧なしの単一`accept ...;`文である形（d91のassign/while
    同型パターン）が一切未対応だった。加えてmessageType節が`::`区切り
    （`Parts::'方向指示器'::'指示状態'`という3階層も実在）を受理できな
    かった（d94と同根）ため、`namespacePath`へ差し替えた。既存の裸形
    （名前・`then`いずれも無し、messageTypeは単一セグメント）との共存
    も確認する。"""
    ast = parse_sysml_antlr(
        "action def A { action '外界取得' accept scene : "
        "Parts::'方向指示器'::'指示状態' via 'レンズ'; }"
    )
    node = ast["children"][0]["children"][0]
    assert node == {
        "type": "accept_action",
        "message": "scene",
        "message_type": "Parts::方向指示器::指示状態",
        "port": "レンズ",
        "actionName": "外界取得",
    }

    bare_ast = parse_sysml_antlr("action def Act { accept response : ConnectionResponse via client; }")
    assert bare_ast["children"][0]["children"][0] == {
        "type": "accept_action",
        "message": "response",
        "message_type": "ConnectionResponse",
        "port": "client",
    }


def test_antlr_perform_action():
    ast = parse_sysml_antlr("action def Act { perform logFailure; }")
    assert ast["children"][0]["children"][0] == {"type": "perform_action", "reference": "logFailure"}


def test_antlr_message_stmt():
    text = "action def Act { message requestMsg from client.sendRequest to server.receiveRequest; }"
    ast = parse_sysml_antlr(text)
    assert ast["children"][0]["children"][0] == {
        "type": "message",
        "name": "requestMsg",
        "from_end": "client.sendRequest",
        "to_end": "server.receiveRequest",
    }


def test_antlr_if_else_with_full_action_body():
    """旧Lark実装のif_stmtは式が未変換の生Treeを文字列化して返す不具合があり
    （比較対象なし）、bodyもflow_stmt/flow_control_stmtしか許可しない。
    新実装は正しい式dictとactionBodyElementの反復を許可する。"""
    ast = parse_sysml_antlr(
        "action def Act { if x > 0 { y = 1; } else { perform logFailure; } }"
    )
    if_stmt = ast["children"][0]["children"][0]
    assert if_stmt["type"] == "if_stmt"
    assert if_stmt["condition"] == {
        "type": "binary_expr",
        "op": ">",
        "left": {"type": "name_ref", "reference": "x"},
        "right": {"type": "literal", "literal_type": "int", "value": 0},
    }
    assert if_stmt["then"] == [
        {"type": "assignment_stmt", "name": "y", "operator": "=", "value": {"type": "literal", "literal_type": "int", "value": 1}}
    ]
    assert if_stmt["else"] == [{"type": "perform_action", "reference": "logFailure"}]


def test_antlr_if_without_else_has_none_else():
    ast = parse_sysml_antlr("action def Act { if x > 0 { y = 1; } }")
    if_stmt = ast["children"][0]["children"][0]
    assert if_stmt["else"] is None


def test_antlr_bare_guarded_target_succession_if_then_else():
    """d96_bare_guarded_target_succession_if_then_else_missing: 実モデル
    （adas-sysmlv2-main）のADAS.sysmlの`if '前方衝突を警告する'.'警告灯'
    then '前方衝突警告灯'::'警告灯をONにする'; else '前方衝突警告灯'::
    '警告灯をOFFにする';`のように、既存ノードの直後に続く、波括弧なし
    の`if <式> then <参照>;`+`else <参照>;`というガード付きsuccession
    短縮形（波括弧必須の既存`ifActionStmt`とは別物）が一切未対応
    だった。`if`直後の波括弧有無で両者が曖昧性なく共存することも
    確認する。参照対象は`::`区切りも実在するため`namespacePath`を
    使う（d94/d95と同じ考え方）。"""
    ast = parse_sysml_antlr(
        "action def A { if '前方衝突を警告する'.'警告灯' then "
        "'前方衝突警告灯'::'警告灯をONにする'; else "
        "'前方衝突警告灯'::'警告灯をOFFにする'; }"
    )
    guarded, default = ast["children"][0]["children"]
    assert guarded == {
        "type": "guarded_then_stmt",
        "guard": {"type": "name_ref", "reference": "前方衝突を警告する.警告灯"},
        "name": "前方衝突警告灯::警告灯をONにする",
    }
    assert default == {"type": "else_stmt", "name": "前方衝突警告灯::警告灯をOFFにする"}

    braced_ast = parse_sysml_antlr(
        "action def Act { if x > 0 { y = 1; } else { perform logFailure; } }"
    )
    braced_if = braced_ast["children"][0]["children"][0]
    assert braced_if["type"] == "if_stmt"


def test_antlr_action_usage_stmt_bare_matches_old_lark_shape_loosely():
    """空bodyのbare形は旧Lark実装でも構文エラーにはならないが、旧実装は
    `usage`サブ辞書に包む独自形かつbody内容を常に捨てる（1文でも書くと構文
    エラーになる既知の不具合）ため比較対象にしない。新実装は独自のフラットな
    形にし、実際に内容のあるbodyをサポートする。"""
    ast = parse_sysml_antlr("action def Act { action retryLoop { x = 1; } }")
    nested = ast["children"][0]["children"][0]
    assert nested == {
        "type": "action_usage",
        "name": "retryLoop",
        "shortName": None,
        "type_name": None,
        "multiplicity": None,
        "value": None,
        "guard": None,
        "isAbstract": False,
        "isRef": False,
        "isIndividual": False,
        "visibility": None,
        "redefines": [],
        "params": [],
        "children": [
            {"type": "assignment_stmt", "name": "x", "operator": "=", "value": {"type": "literal", "literal_type": "int", "value": 1}}
        ],
    }


def test_antlr_action_usage_stmt_equals_value():
    """d54_bare_action_keyword_feature_usage: Flows.sysmlの`private ref
    action thisConnection = self;`のように、他のusage規則（item/
    attribute/requirement等）には既にある`=`値代入がactionUsageStmtには
    無かった。"""
    ast = parse_sysml_antlr("part def P { private ref action thisConnection = self; }")
    node = ast["children"][0]["children"][-1]
    assert node["type"] == "action_usage"
    assert node["name"] == "thisConnection"
    assert node["isRef"] is True
    assert node["visibility"] == "private"
    assert node["value"] == {"type": "name_ref", "reference": "self"}


def test_antlr_connection_usage_typed_with_end_multiplicity():
    """d55_typed_connection_usage_missing: ShapeItems.sysmlの`connection
    :MatesWith connect [1] be to [1] be;`・Flows.sysmlの`connection
    :HappensDuring connect sourceEvent to [1] source;`のように、
    `connectUsage`（キーワード無し型）とは別に`connection`キーワード+型節+
    connectorEnd側multiplicityを伴う形が一切未実装だった。"""
    ast = parse_sysml_antlr("part def P { connection :MatesWith connect [1] be to [1] be; }")
    node = ast["children"][0]["children"][-1]
    assert node["type"] == "connection_usage"
    assert node["type_name"] == "MatesWith"
    assert node["firstMultiplicity"]["size"] == {"min": 1, "max": 1}
    assert node["firstEnd"] == {"type": "connector_end", "declared_name": None, "reference": "be"}
    assert node["thenMultiplicity"]["size"] == {"min": 1, "max": 1}
    assert node["thenEnd"] == {"type": "connector_end", "declared_name": None, "reference": "be"}

    no_first_mult = parse_sysml_antlr(
        "part def P { connection :HappensDuring connect sourceEvent to [1] source; }"
    )
    node2 = no_first_mult["children"][0]["children"][-1]
    assert node2["firstMultiplicity"] is None
    assert node2["firstEnd"]["reference"] == "sourceEvent"


def test_antlr_feature_usage_equals_value():
    """d56_feature_part_usage_equals_value: CauseAndEffect.sysmlの`ref
    :>> baseType = causes as SysML::Usage;`のように、他のusage規則
    （item/attribute/requirement等）には既にある`=`値代入がfeatureUsage
    には無かった。"""
    ast = parse_sysml_antlr("part def P { ref :>> baseType = causes as SysML::Usage; }")
    node = ast["children"][0]["children"][-1]
    assert node["type"] == "feature_usage"
    assert node["isRef"] is True
    assert node["redefines"] == [{"kind": "redefines", "target": "baseType"}]
    assert node["value"] == {
        "type": "as_cast",
        "base": {"type": "name_ref", "reference": "causes"},
        "type_name": "SysML::Usage",
        "children": [],
    }


def test_antlr_part_usage_equals_value():
    """d56_feature_part_usage_equals_value: Parts.sysmlの`ref part this :
    Part :>> Action::this, ownedPerformances::this = that as Part {
    ... }`のように、他のusage規則には既にある`=`値代入がpartUsageには
    無かった（既存の`expression`プレースホルダーフィールドを使う）。"""
    src = "part def P { ref part this : Part :>> Action::this, ownedPerformances::this = that as Part { } }"
    ast = parse_sysml_antlr(src)
    node = ast["children"][0]["children"][-1]
    assert node["type"] == "part_instance"
    assert node["name"] == "this"
    assert node["type_name"] == "Part"
    assert node["redefines"][0]["targets"] == ["Action::this", "ownedPerformances::this"]
    assert node["expression"] == {
        "type": "as_cast",
        "base": {"type": "name_ref", "reference": "that"},
        "type_name": "Part",
        "children": [],
    }


def test_antlr_part_usage_double_colon_qualified_type():
    """d97_usage_type_clause_double_colon_qualified_missing: 実モデル
    （adas-sysmlv2-main）のADAS.sysmlの`part 'LDW制御スイッチ' : Parts::
    'OnOffスイッチ' { ... }`のように、partUsageの型節が`::`区切り（他
    パッケージ参照）を伴う場合に受理できなかった（公式コーパスでは
    0件、実モデル特有）。型節を`ID`単体から`namespacePath`へ差し替えた
    （`.`/`::`両対応）。既存の単一ID型節との共存も確認する。"""
    ast = parse_sysml_antlr(
        "part def P { part 'LDW制御スイッチ' : Parts::'OnOffスイッチ' { } }"
    )
    node = ast["children"][0]["children"][-1]
    assert node["type_name"] == "Parts::OnOffスイッチ"

    plain_ast = parse_sysml_antlr("part def P { part x : SomeType; }")
    plain_node = plain_ast["children"][0]["children"][-1]
    assert plain_node["type_name"] == "SomeType"


def test_antlr_part_and_requirement_usage_short_name():
    """`part <'1'> b: B;`（PartTest.sysml）・`requirement <C1> ...`
    （EVSample.sysml）のようなShortName注釈（山括弧の短縮名）は、以前は
    一部のdef系規則にしか実装されておらずusage系規則には無かった
    （2026-08-28、参照実装比較レポートP1-1で発見。公式コーパスで
    part 5件・requirement 87件）。"""
    part_ast = parse_sysml_antlr("part def B; part <'1'> b: B;")
    part_node = part_ast["children"][-1]
    assert part_node["shortName"] == "'1'"
    assert part_node["name"] == "b"

    req_ast = parse_sysml_antlr("requirement def R; requirement <C1> r :> R : R;")
    req_node = req_ast["children"][-1]
    assert req_node["shortName"] == "C1"
    assert req_node["type_name"] == "R"
    assert lint_ast(req_ast) is not None


def test_antlr_state_body_element_doc_and_assert_constraint():
    """d57_state_body_element_documentation_stmt_missing: States.sysmlの
    `state def StateAction { doc /* ... */ ... assert constraint {...} }`
    のように、`doc`コメント・`assert constraint`のいずれも他の
    partBodyElement系には既に登録済みだがstateBodyElementには一切
    登録されていなかった。"""
    src = (
        "state def S { doc /* comment */ "
        "assert constraint {notEmpty(x) implies size(y) == size(z) - 1} }"
    )
    ast = parse_sysml_antlr(src)
    assert ast["type"] != "error"
    state_def = ast["children"][0]
    child_types = [c["type"] for c in state_def["children"]]
    assert "documentation" in child_types
    assert "constraint_stmt" in child_types


def test_antlr_state_body_element_bare_action_usage():
    """d66_state_body_element_action_usage_missing: States.sysmlの
    `action :>> subactions :> middle { doc ... }`のように、名前省略の
    裸の`action`usage形（actionUsageStmt自体は既に対応済み）が
    stateBodyElementに登録されておらずstate def本体内で使えなかった
    （9回目の登録漏れパターン）。"""
    src = "state def S { action :>> subactions :> middle { } }"
    ast = parse_sysml_antlr(src)
    assert ast["type"] != "error"
    state_def = ast["children"][0]
    action_usage = state_def["children"][0]
    assert action_usage["type"] == "action_usage"
    assert action_usage["name"] is None
    assert action_usage["redefines"] == [
        {"kind": "redefines", "target": "subactions"},
        {"kind": "subsets", "target": "middle"},
    ]


def test_antlr_action_usage_while_guard():
    """`action X while cond { ... }`のwhileガードは旧Lark実装に規則が無い
    新規拡張（WhileLoopActionUsageの簡略形。COVERAGE.md参照）。"""
    ast = parse_sysml_antlr("action def Act { action retryLoop while not isConnected { } }")
    nested = ast["children"][0]["children"][0]
    assert nested["guard"] == {
        "type": "unary_expr",
        "op": "not",
        "operand": {"type": "name_ref", "reference": "isConnected"},
    }


def test_antlr_assign_keyword_prefix_is_optional():
    """`assign x := 1;`（キーワード付き）と`x := 1;`（省略形）は同じAST形状になる。"""
    with_kw = parse_sysml_antlr("action def Act { assign x := 1; }")
    without_kw = parse_sysml_antlr("action def Act { x := 1; }")
    assert with_kw == without_kw


def test_antlr_action_usage_stmt_allowed_at_package_level():
    """`action_usage_stmt`は旧Lark実装でもpackage_member_elementとして
    トップレベルに書ける（grammar.py:29）。ここでは新実装でも同様に
    packageBodyElementへ追加した（real_sequence_diagram.sysmlの
    `action checkConnection { ... }`が該当）。"""
    ast = parse_sysml_antlr("package P { action checkConnection { x = 1; } }")
    assert ast["children"][0]["type"] == "action_usage"
    assert ast["children"][0]["name"] == "checkConnection"


def test_antlr_real_sequence_diagram_now_parses():
    """フェーズ2の主要ブロッカーだったreal_sequence_diagram.sysmlが解消した
    ことを直接固定する（tests/test_sysml_corpus.pyの汎用テストと重複する
    内容だが、このブロッカー解消が今回の作業の主目的だったため明示的に残す）。"""
    text = (CORPUS_DIR / "working" / "real_sequence_diagram.sysml").read_text(encoding="utf-8")
    ast = parse_sysml_antlr(text)
    assert ast.get("type") != "error"
    lint_ast(ast)  # クラッシュしないことを確認


# --- `::`区切り型参照 / 初期遷移の省略形 / bodyありのbare state usage ----------
# (real_state_transition.sysml の残ブロッカー解消。COVERAGE.md / AST_SCHEMA.md §3.22参照)


def test_antlr_attribute_usage_accepts_scoped_type_reference():
    """`attribute x : ScalarValues::Real;`のような`::`区切り型参照も、
    単純な`: Real`形と同じ`attribute_usage`ノードとしてパースできる。"""
    simple_text = "part def P { attribute powerLevel : Real; }"
    ast_simple = parse_sysml_antlr(simple_text)
    assert ast_simple["children"][0]["children"][0]["type_name"] == "Real"

    scoped_text = "part def P { attribute powerLevel : ScalarValues::Real; }"
    ast_scoped = parse_sysml_antlr(scoped_text)
    assert ast_scoped["children"][0]["children"][0]["type_name"] == "ScalarValues::Real"


def test_antlr_initial_transition_shorthand():
    """`entry; then Off;`は旧Lark実装ではentry自体が常に構文エラーになる
    既知バグ（state_entry.sysml参照）のため比較対象なし。独立した`then Off;`
    単体は旧実装でも成功するが、name/typeが壊れており（AST_SCHEMA.md §3.22）
    比較対象にしない。新実装ではsourceを持たないtransitionノードとして
    扱い、既存の_check_transitionが安全に処理できるようにする。"""
    ast = parse_sysml_antlr("state def S { entry; then Off; state Off; }")
    children = ast["children"][0]["children"]
    assert children[0] == {"type": "entry_action", "kind": "entry", "action_reference": None, "type_name": None, "redefines": [], "children": []}
    assert children[1] == {
        "type": "transition",
        "name": None,
        "source": None,
        "target": "Off",
        "trigger": None,
        "guard": None,
        "effect": None,
        "children": [],
    }
    lint_ast(ast)  # source=Noneでクラッシュしないことを確認


def test_antlr_state_usage_with_empty_body():
    ast = parse_sysml_antlr("state def S { state On { } }")
    on_usage = ast["children"][0]["children"][0]
    assert on_usage == {
        "type": "state_usage",
        "name": "On",
        "type_name": None,
        "multiplicity": None,
        "inheritance": None,
        "isAbstract": False,
        "isRef": False,
        "redefines": [],
        "children": [],
    }


def test_antlr_state_usage_with_body_content():
    """`state On { entry action X; ... }`のようにbodyにstateBodyElementの
    反復を許可し、実際にchildrenへ反映する。"""
    ast = parse_sysml_antlr(
        "state def S { state On { entry action setupSystem; do action run; exit action cleanup; } }"
    )
    on_usage = ast["children"][0]["children"][0]
    assert on_usage["name"] == "On"
    assert [c["type"] for c in on_usage["children"]] == ["entry_action", "do_action", "exit_action"]


def test_antlr_state_usage_ref_type_and_redefine():
    """d61_state_usage_ref_type_redefine_missing: Parts.sysmlの`abstract
    ref state exhibitedStates: StateAction[0..*] :> stateActions,
    performedActions { ... }`・States.sysmlの`ref state self: StateAction
    :>> Action::self, StatePerformance::self;`のように、`ref`修飾子・
    型節・redefine節（他のusage規則には既にある）がstateUsageには
    一切未対応だった。stateBodyElementにしか登録されておらず
    partBodyElementへの登録漏れ（8回目の再発）もあった。"""
    src = (
        "part def P { abstract ref state exhibitedStates: StateAction[0..*] "
        ":> stateActions, performedActions { } }"
    )
    ast = parse_sysml_antlr(src)
    node = ast["children"][0]["children"][-1]
    assert node["type"] == "state_usage"
    assert node["name"] == "exhibitedStates"
    assert node["type_name"] == "StateAction"
    assert node["isAbstract"] is True
    assert node["isRef"] is True
    assert node["redefines"][0]["targets"] == ["stateActions", "performedActions"]

    ref_only = parse_sysml_antlr(
        "part def P { ref state self: StateAction :>> Action::self, StatePerformance::self; }"
    )
    ref_node = ref_only["children"][0]["children"][-1]
    assert ref_node["type"] == "state_usage"
    assert ref_node["name"] == "self"
    assert ref_node["redefines"][0]["kind"] == "redefines"


def test_antlr_entry_do_exit_action_member_type_and_redefine():
    """d62_entry_do_exit_action_member_redefine_missing: States.sysmlの
    `entry action entryAction :>> 'entry';`・`do action doAction: Action
    :>> 'do';`・`exit action exitAction: Action :>> 'exit';`のように、
    型節・redefine節（対象は`entry`/`do`/`exit`自体が予約語のため
    QUOTED_NAMEで囲む）がいずれも未対応だった。"""
    src = (
        "state def S { entry action entryAction :>> 'entry'; "
        "do action doAction: Action :>> 'do'; "
        "exit action exitAction: Action :>> 'exit'; }"
    )
    ast = parse_sysml_antlr(src)
    entry, do, exit_ = ast["children"][0]["children"]
    assert entry == {
        "type": "entry_action", "kind": "entry", "action_reference": "entryAction",
        "type_name": None, "redefines": [{"kind": "redefines", "target": "entry"}], "children": [],
    }
    assert do == {
        "type": "do_action", "kind": "do", "action_reference": "doAction",
        "type_name": "Action", "redefines": [{"kind": "redefines", "target": "do"}], "children": [],
    }
    assert exit_ == {
        "type": "exit_action", "kind": "exit", "action_reference": "exitAction",
        "type_name": "Action", "redefines": [{"kind": "redefines", "target": "exit"}], "children": [],
    }


def test_antlr_bare_connection_usage_no_connect():
    """d63_bare_connection_allocation_message_usage_missing:
    Connections.sysmlの`abstract connection connections:
    Connection[0..*] nonunique :> linkObjects, parts { ... }`のように、
    `connect`を伴わない裸の`connection`usage形（itemUsage/partUsage等と
    同型）が一切未実装だった。既存の`connect`形（d55）との共存も確認。"""
    src = (
        "part def P { abstract connection connections: Connection[0..*] "
        "nonunique :> linkObjects, parts { } }"
    )
    ast = parse_sysml_antlr(src)
    node = ast["children"][0]["children"][-1]
    assert node["type"] == "connection_usage"
    assert node["name"] == "connections"
    assert node["type_name"] == "Connection"
    assert node["isAbstract"] is True
    assert node["multiplicity"]["is_ordered"] is False
    assert node["redefines"][0]["targets"] == ["linkObjects", "parts"]

    connect_form = parse_sysml_antlr(
        "connection def C { connection :MatesWith connect [1] be to [1] be; }"
    )
    connect_node = connect_form["children"][0]["children"][-1]
    assert connect_node["type"] == "connection_usage"
    assert connect_node["type_name"] == "MatesWith"


def test_antlr_bare_allocation_and_message_usage():
    """d63_bare_connection_allocation_message_usage_missing:
    Allocations.sysmlの`abstract allocation allocations:
    Allocation[0..*] nonunique :> binaryConnections { ... }`・
    Flows.sysmlの`abstract message messages: Message[0..*] nonunique
    :> transfers, actions { ... }`のように、`allocate`/`from`...`to`を
    伴わない裸のusage形が未対応だった。"""
    alloc_ast = parse_sysml_antlr(
        "part def P { abstract allocation allocations: Allocation[0..*] "
        "nonunique :> binaryConnections { } }"
    )
    alloc_node = alloc_ast["children"][0]["children"][-1]
    assert alloc_node["type"] == "allocation_usage"
    assert alloc_node["name"] == "allocations"
    assert alloc_node["type_name"] == "Allocation"
    assert alloc_node["redefines"][0]["target"] == "binaryConnections"

    message_ast = parse_sysml_antlr(
        "part def P { abstract message messages: Message[0..*] "
        "nonunique :> transfers, actions { } }"
    )
    message_node = message_ast["children"][0]["children"][-1]
    assert message_node["type"] == "message_usage"
    assert message_node["name"] == "messages"
    assert message_node["type_name"] == "Message"
    assert message_node["redefines"][0]["targets"] == ["transfers", "actions"]


def test_antlr_message_usage_of_payload_type():
    """`message publish_message of Publish[1];`（17b-Sequence-Modeling.sysml）
    のようなペイロード型節（2026-08-28、参照実装比較レポートP2-1で発見）。
    既存の`: ID`単一セグメント形とは別の代替（`::`区切り型参照にも対応）。"""
    ast = parse_sysml_antlr(
        "part def P { message publish_message of Pkg::Publish[1]; } "
        "item def Publish;"
    )
    node = ast["children"][0]["children"][0]
    assert node["type"] == "message_usage"
    assert node["name"] == "publish_message"
    assert node["type_name"] == "Pkg::Publish"
    assert node["multiplicity"]["size"] == {"min": 1, "max": 1}


def test_antlr_bare_flow_usage_no_from_to():
    """d67_bare_flow_usage_missing: Flows.sysmlの`abstract flow flows:
    Flow[0..*] nonunique :> messages, flowTransfers { ... }`のように、
    `of`/`from...to`を伴わない裸の`flow`usage形（connection/allocation/
    message等と同型、d63と同種のギャップ）が一切未対応だった。既存の
    `of`/`from...to`形（旧実装）との共存も確認する。"""
    src = (
        "part def P { abstract flow flows: Flow[0..*] "
        "nonunique :> messages, flowTransfers { } }"
    )
    ast = parse_sysml_antlr(src)
    node = ast["children"][0]["children"][-1]
    assert node["type"] == "flow_usage"
    assert node["name"] == "flows"
    assert node["type_name"] == "Flow"
    assert node["isAbstract"] is True
    assert node["redefines"][0]["targets"] == ["messages", "flowTransfers"]

    legacy_ast = parse_sysml_antlr("part def P { flow of X from a to b; }")
    legacy_node = legacy_ast["children"][0]["children"][-1]
    assert legacy_node == {
        "type": "flow_usage", "item_type": "X", "from_end": "a", "to_end": "b", "children": [],
    }


def test_antlr_bare_flow_short_form_outside_action_body():
    """d92_bare_flow_short_form_outside_action_body_missing: 実モデル
    （adas-sysmlv2-main）のFCW.sysml等の`flow '外界の映像を撮る'.'映像'
    to '前方障害物との距離を推定する'.'カメラ映像';`のように、`from`
    キーワードを省略しドット区切りの2端点を直接持つflow短縮形
    （`actionFlowStmt`のflowShort相当）が、action本体の外（part直下）
    で一切未対応だった。既存の`from`明示形・裸`flow;`形との共存も
    確認する。d98で端点の型を`qualifiedName`から`namespacePath`へ
    差し替えたため、出力は区切り文字を常に`::`へ正規化する（d81の
    既存方針）。"""
    ast = parse_sysml_antlr(
        "part def P { flow '外界の映像を撮る'.'映像' to "
        "'前方障害物との距離を推定する'.'カメラ映像'; }"
    )
    node = ast["children"][0]["children"][-1]
    assert node == {
        "type": "flow_usage",
        "item_type": None,
        "from_end": "外界の映像を撮る::映像",
        "to_end": "前方障害物との距離を推定する::カメラ映像",
        "children": [],
    }

    from_ast = parse_sysml_antlr("part def P { flow from a to b; }")
    from_node = from_ast["children"][0]["children"][-1]
    assert from_node == {
        "type": "flow_usage", "item_type": None, "from_end": "a", "to_end": "b", "children": [],
    }

    bare_ast = parse_sysml_antlr("part def P { flow; }")
    bare_node = bare_ast["children"][0]["children"][-1]
    assert bare_node == {
        "type": "flow_usage", "item_type": None, "from_end": None, "to_end": None, "children": [],
    }


def test_antlr_flow_connect_endpoint_double_colon_mixed():
    """d98_flow_connect_endpoint_double_colon_mixed_missing: 実モデル
    （adas-sysmlv2-main）のADAS.sysmlの`flow '前方衝突警報を通知する'::
    '前方衝突を警告する'.'警告音' to ...;`・`connect 'ハンドルスイッチ'
    ::'LDW制御スイッチ'.'LDW出力' to ...;`のように、flow/connect文の
    端点が`::`（パッケージ限定）と`.`（フィーチャアクセス）を混在させ
    る場合に受理できなかった。flowUsageのfromEnd/toEndは`qualifiedName`
    から`namespacePath`へ直接差し替え、connectUsageは他の多数箇所で
    共有される`connectorEnd`（`qualifiedName`前提の既存出力に依存）を
    変更せず、専用の`connectorEndPath`を新設して対応した。既存の単一
    区切りの形との共存も確認する。"""
    flow_ast = parse_sysml_antlr(
        "part def P { flow 'A'::'B'.'C' to 'D'.'E'; }"
    )
    flow_node = flow_ast["children"][0]["children"][-1]
    assert flow_node == {
        "type": "flow_usage",
        "item_type": None,
        "from_end": "A::B::C",
        "to_end": "D::E",
        "children": [],
    }

    connect_ast = parse_sysml_antlr(
        "part def P { connect 'A'::'B'.'C' to 'D'.'E'; }"
    )
    connect_node = connect_ast["children"][0]["children"][-1]
    assert connect_node == {
        "type": "connect_usage",
        "from_end": {"type": "connector_end", "declared_name": None, "reference": "A::B::C"},
        "to_end": {"type": "connector_end", "declared_name": None, "reference": "D::E"},
        "children": [],
    }

    plain_connect_ast = parse_sysml_antlr("part def P { connect end1 references a.b to c.d; }")
    plain_connect_node = plain_connect_ast["children"][0]["children"][-1]
    assert plain_connect_node == {
        "type": "connect_usage",
        "from_end": {"type": "connector_end", "declared_name": "end1", "reference": "a::b"},
        "to_end": {"type": "connector_end", "declared_name": None, "reference": "c::d"},
        "children": [],
    }


def test_antlr_perform_action_named_redefine_body():
    """d93_perform_action_named_redefine_body_missing: 実モデル
    （adas-sysmlv2-main）のADAS.sysmlの`perform action '外界の映像を
    出力する' { ... }`や`perform action 'LDWをONにする' redefines
    'スイッチをONにする' { ... }`のように、performアクションに`action`
    キーワード+名前(+任意でredefines節)+波括弧bodyを伴う形が一切
    未対応だった。加えてperformActionStmt自体がactionBodyElementにしか
    登録されておらずpartBodyElementへの登録漏れ（d32以降の同種パターン
    の再発）もあったため、part usageが直接performActionUsageを持てる
    公式仕様に合わせてpartBodyElementへも追加登録した。既存の裸参照形
    （名前・redefines・bodyいずれも無し）との共存も確認する。"""
    ast = parse_sysml_antlr(
        "part def P { perform action 'LDWをONにする' redefines "
        "'スイッチをONにする' { assign '状態' := 1; } }"
    )
    node = ast["children"][0]["children"][-1]
    assert node["type"] == "perform_action"
    assert node["name"] == "LDWをONにする"
    assert node["redefines"] == [{"kind": "redefines", "target": "スイッチをONにする"}]
    assert node["params"] == []
    assert node["children"] == [
        {
            "type": "assignment_stmt",
            "name": "状態",
            "operator": ":=",
            "value": {"type": "literal", "literal_type": "int", "value": 1},
        },
    ]

    unnamed_ast = parse_sysml_antlr("part def P { perform action { } }")
    unnamed_node = unnamed_ast["children"][0]["children"][-1]
    assert unnamed_node == {
        "type": "perform_action", "name": None, "redefines": [], "params": [], "children": [],
    }

    bare_ast = parse_sysml_antlr("part def P { perform y; }")
    bare_node = bare_ast["children"][0]["children"][-1]
    assert bare_node == {"type": "perform_action", "reference": "y"}


def test_antlr_double_colon_qualified_reference_targets():
    """d94_double_colon_qualified_reference_targets_missing: 実モデル
    （adas-sysmlv2-main）のADAS.sysmlの`perform FCW::'外界の映像を撮る';`
    やLDW.sysmlの`dependency '意図しない車線逸脱の予防' to '事故の予防'
    ::'車線逸脱による事故の予防';`のように、performの裸参照対象や
    dependencyのclient/supplier参照が`::`区切り（他パッケージ参照）を
    伴う場合に受理できなかった（内部の`.`区切り専用`qualifiedName`規則
    の流用が原因、`::`/`.`両対応の`namespacePath`へ差し替え）。加えて
    dependencyStmt自体がpackageBodyElementにしか登録されておらず
    partBodyElement（＝requirementBodyElementが委譲する先）への登録漏れ
    もあったため、合わせて追加登録した。既存の単一セグメント参照との
    共存も確認する。"""
    perform_ast = parse_sysml_antlr("part def P { perform FCW::'外界の映像を撮る'; }")
    perform_node = perform_ast["children"][0]["children"][-1]
    assert perform_node == {"type": "perform_action", "reference": "FCW::外界の映像を撮る"}

    dep_ast = parse_sysml_antlr(
        "package LDW { requirement '事故の予防' { requirement "
        "'意図しない車線逸脱の予防' { dependency '意図しない車線逸脱の"
        "予防' to '事故の予防'::'車線逸脱による事故の予防'; } } }"
    )
    dep_node = dep_ast["children"][0]["children"][0]["children"][-1]
    assert dep_node == {
        "type": "special_stmt",
        "children": [
            {
                "type": "dependency",
                "clients": ["意図しない車線逸脱の予防"],
                "suppliers": ["事故の予防::車線逸脱による事故の予防"],
                "prefixMetadata": [],
                "children": [],
            },
        ],
    }

    plain_perform = parse_sysml_antlr("action def Act { perform logFailure; }")
    assert plain_perform["children"][0]["children"][0] == {
        "type": "perform_action", "reference": "logFailure",
    }

    plain_dep = parse_sysml_antlr("part def A; part def B; dependency A to B;")
    assert plain_dep["children"][-1] == {
        "type": "special_stmt",
        "children": [
            {"type": "dependency", "clients": ["A"], "suppliers": ["B"], "prefixMetadata": [], "children": []}
        ],
    }


def test_antlr_range_expression():
    """d64_range_expression_missing: Interfaces.sysmlの`(1..size(seq))
    ->selectOne{in i; seq#(i) == value}`のように、`(a..b)`という範囲式
    （`multiplicityBracket`の`..`とは別）が一切未実装だった。既存の
    parenExpr/sequenceExprとの共存も確認する。"""
    ast = parse_sysml_antlr(
        "part def P { attribute a = (1..size(seq))->selectOne{in i; seq#(i) == value}; }"
    )
    value = ast["children"][0]["children"][-1]["value"]
    assert value["type"] == "arrow_lambda"
    receiver = value["receiver"]
    assert receiver["type"] == "range_expr"
    assert receiver["lower"] == {"type": "literal", "literal_type": "int", "value": 1}
    assert receiver["upper"]["type"] == "function_call"

    paren_ast = parse_sysml_antlr("part def P { attribute a = (x); }")
    assert paren_ast["children"][0]["children"][-1]["value"] == {"type": "name_ref", "reference": "x"}

    seq_ast = parse_sysml_antlr("part def P { attribute a = (x, y); }")
    assert seq_ast["children"][0]["children"][-1]["value"]["type"] == "sequence"


def test_antlr_bare_implicit_return_expression():
    """d68_bare_implicit_return_expression_missing: Interfaces.sysmlの
    `calc def excludingOnce { ... seq->excludingAt(position) }`のように、
    `return`キーワードも終端の`;`も伴わない裸の暗黙戻り値式（calc def
    本体の最後の文）が一切受理できなかった。終端の`;`を伴う既存形との
    共存も確認する。"""
    ast = parse_sysml_antlr(
        "calc def C { in x[1]; x->excludingAt(1) }"
    )
    result = ast["children"][0]["children"][-1]
    assert result["type"] == "result_expression_member"
    assert result["expression"]["type"] == "arrow_call"

    terminated_ast = parse_sysml_antlr("calc def C { in x[1]; x->excludingAt(1); }")
    terminated_result = terminated_ast["children"][0]["children"][-1]
    assert terminated_result["type"] == "result_expression_member"
    assert terminated_result["expression"]["type"] == "arrow_call"


def test_antlr_action_parameter_nested():
    """d69_action_parameter_nesting_missing: SampledFunctions.sysmlの
    `in calc calculation { in x; }`のように、calc種別のactionParameter
    自身のbody内にさらにactionParameterをネストする形が受理できな
    かった（従来のbodyはdocumentationStmt/bareDocCommentのみ）。"""
    ast = parse_sysml_antlr("calc def Sample { in calc calculation { in x; } }")
    outer = ast["children"][0]["children"][0]
    assert outer["type"] == "param"
    assert outer["kind"] == "calc"
    assert outer["name"] == "calculation"
    inner = outer["children"][0]
    assert inner == {
        "type": "param", "direction": "in", "is_item": False, "kind": None,
        "name": "x", "type_spec": None, "type_name": None, "multiplicity": None,
        "redefines": [], "value": None, "defaultValue": None, "children": [],
    }


def test_antlr_quantity_literal_unit_bracket():
    """d70_quantity_literal_unit_bracket_missing: ShapeItems.sysmlの
    `default 0 [m]`・SI.sysmlの`= 273.15 [K]`・USCustomaryUnits.sysmlの
    `= 229835/900 [K]`のように、数値リテラル（または算術式）に単位を
    角括弧で付与するquantity literal記法が一切未実装だった。単位は
    算術演算の結果全体に付与されることも確認する（`(a/b) [K]`の意味）。"""
    ast = parse_sysml_antlr("part def P { attribute a = 229835/900 [K]; }")
    value = ast["children"][0]["children"][-1]["value"]
    assert value == {
        "type": "quantity_literal",
        "value": {
            "type": "binary_expr", "op": "/",
            "left": {"type": "literal", "literal_type": "int", "value": 229835},
            "right": {"type": "literal", "literal_type": "int", "value": 900},
        },
        "unit": {"type": "name_ref", "reference": "K"},
        "children": [],
    }

    simple_ast = parse_sysml_antlr("part def P { attribute a = 0 [m]; }")
    simple_value = simple_ast["children"][0]["children"][-1]["value"]
    assert simple_value == {
        "type": "quantity_literal",
        "value": {"type": "literal", "literal_type": "int", "value": 0},
        "unit": {"type": "name_ref", "reference": "m"},
        "children": [],
    }


def test_antlr_quantity_literal_index_expr_unit():
    """d85_quantity_literal_index_expr_unit_missing: ISQSpaceTime.sysmlの
    `num#(1) [mRef.mRefs#(1)]`のように、d70のquantity literal記法の
    角括弧内が単純なnamespacePathではなく`#()`インデックスアクセスを
    伴う式のことがあり受理できなかった。単位節を`expression`へ拡張
    したことで、単純な単位（`unit`が`name_ref`）とも共存することを
    確認する。"""
    ast = parse_sysml_antlr(
        "attribute def D { attribute a = num#(1) [mRef.mRefs#(1)]; }"
    )
    value = ast["children"][0]["children"][-1]["value"]
    assert value["type"] == "quantity_literal"
    assert value["value"] == {
        "type": "index_access",
        "base": {"type": "name_ref", "reference": "num"},
        "index": {"type": "literal", "literal_type": "int", "value": 1},
        "children": [],
    }
    assert value["unit"] == {
        "type": "index_access",
        "base": {"type": "name_ref", "reference": "mRef.mRefs"},
        "index": {"type": "literal", "literal_type": "int", "value": 1},
        "children": [],
    }


def test_antlr_transition_accept_typed_via():
    """d86_transition_accept_typed_via_missing: Actions.sysmlの
    `transition aTransition first start accept apayload: Anything via
    receiver then done;`のように、transitionStmtの`accept`パラメータ
    に型節（`: Anything`）と`via`節（受信ポート/参照）が付く形が一切
    未対応だった。既存の型節・via節無し形との共存も確認する。"""
    typed_via_ast = parse_sysml_antlr(
        "state def S { transition aTransition first start accept "
        "apayload: Anything via receiver then done; }"
    )
    typed_via_node = typed_via_ast["children"][0]["children"][0]
    assert typed_via_node["trigger"] == {
        "kind": "trigger", "reference": "apayload",
        "type_name": "Anything", "via": "receiver",
    }

    bare_ast = parse_sysml_antlr("state def S { transition first Off accept turnOn then On; }")
    bare_node = bare_ast["children"][0]["children"][0]
    assert bare_node["trigger"] == {"kind": "trigger", "reference": "turnOn"}


def test_antlr_function_call_named_argument():
    """d87_function_call_named_argument_missing: TradeStudies.sysmlの
    `tradeStudyObjective(selectedAlternative = a)`のように、`new`式
    ではない通常の関数呼び出し（`functionCallExpr`）が名前付き引数を
    取れなかった（現行は位置引数のみ対応）。既存の位置引数形との共存
    も確認する（引数リストが`newArgument`と同型のラップされた要素に
    変わる破壊的変更を伴う）。"""
    named_ast = parse_sysml_antlr(
        "part def P { attribute a = tradeStudyObjective(selectedAlternative = x); }"
    )
    named_value = named_ast["children"][0]["children"][0]["value"]
    assert named_value == {
        "type": "function_call",
        "name": "tradeStudyObjective",
        "arguments": [
            {
                "type": "named_argument", "name": "selectedAlternative",
                "value": {"type": "name_ref", "reference": "x"}, "children": [],
            },
        ],
        "children": [],
    }

    positional_ast = parse_sysml_antlr(
        "part def P { attribute a = getDifference(input, stateSpace); }"
    )
    positional_value = positional_ast["children"][0]["children"][0]["value"]
    assert positional_value == {
        "type": "function_call",
        "name": "getDifference",
        "arguments": [
            {"type": "positional_argument", "value": {"type": "name_ref", "reference": "input"}, "children": []},
            {"type": "positional_argument", "value": {"type": "name_ref", "reference": "stateSpace"}, "children": []},
        ],
        "children": [],
    }


def test_antlr_type_keyword_as_namespace_path_segment():
    """d88_type_keyword_as_namespace_path_segment_missing: SysML.sysmlの
    `redefines type subsets Metadata::metadataItems;`のように、予約
    キーワード`type`がredefine対象（型参照位置、namespacePath）として
    使われる場合に受理できなかった（d82は宣言名としての`type`のみ
    対応済み）。既存の通常の識別子redefine対象との共存も確認する。"""
    ast = parse_sysml_antlr(
        "part def P { ref item conjugatedPortDefinition : "
        "ConjugatedPortDefinition[1..1] redefines type subsets "
        "Metadata::metadataItems; }"
    )
    node = ast["children"][0]["children"][0]
    assert node["redefines"] == [
        {"kind": "redefines", "target": "type"},
        {"kind": "subsets", "target": "Metadata::metadataItems"},
    ]

    plain_ast = parse_sysml_antlr(
        "part def P { attribute unit :>> UnitPowerFactor::unit = 1; }"
    )
    plain_node = plain_ast["children"][0]["children"][0]
    assert plain_node["redefines"] == [
        {"kind": "redefines", "target": "UnitPowerFactor::unit"},
    ]


def test_antlr_braced_default_expression():
    """d89_braced_default_expression_missing: Actions.sysmlの`in
    whileTest default {true} { doc ... }`のように、actionParameterの
    `default`値が波括弧で囲まれた式（`{true}`）を取る形が一切未対応
    だった。直後に続くactionParameter自体のbody（別の`{...}`）との
    区別、既存の裸の`default`形との共存も確認する。"""
    braced_ast = parse_sysml_antlr(
        "action def A { in whileTest default {true} { doc /* c */ } }"
    )
    braced_node = braced_ast["children"][0]["params"][0]
    assert braced_node["name"] == "whileTest"
    assert braced_node["defaultValue"] == {"type": "literal", "literal_type": "boolean", "value": True}
    assert braced_node["children"] == [
        {"type": "documentation", "identification": None, "locale": None, "body": "c", "children": []},
    ]

    bare_ast = parse_sysml_antlr(
        "action def A { in clock : Clock[1] default enclosingItem.localClock; }"
    )
    bare_node = bare_ast["children"][0]["params"][0]
    assert bare_node["defaultValue"] == {"type": "name_ref", "reference": "enclosingItem.localClock"}


def test_antlr_interaction_keyword_as_namespace_path_segment():
    """d90_interaction_keyword_as_namespace_path_segment_missing:
    SysML.sysmlの`redefines actionDefinition, interaction subsets
    Metadata::metadataItems;`のように、予約キーワード`interaction`が
    d88と同様にredefine対象（namespacePath）として使われる場合に
    受理できなかった。既存の通常の識別子redefine対象との共存も確認
    する。"""
    ast = parse_sysml_antlr(
        "part def P { derived ref item flowDefinition : "
        "Interaction[0..*] ordered redefines actionDefinition, "
        "interaction subsets Metadata::metadataItems; }"
    )
    node = ast["children"][0]["children"][0]
    assert node["redefines"] == [
        {
            "kind": "redefines",
            "target": "actionDefinition",
            "targets": ["actionDefinition", "interaction"],
        },
        {"kind": "subsets", "target": "Metadata::metadataItems"},
    ]

    plain_ast = parse_sysml_antlr(
        "part def P { attribute unit :>> UnitPowerFactor::unit = 1; }"
    )
    plain_node = plain_ast["children"][0]["children"][0]
    assert plain_node["redefines"] == [
        {"kind": "redefines", "target": "UnitPowerFactor::unit"},
    ]


def test_antlr_assign_then_perform_while_action_syntax():
    """d91_assign_then_perform_while_action_syntax_missing: Actions.sysml
    のLoopAction（`private action initialization assign index := 1; then
    private action whileLoop while index <= size(seq) { assign var :=
    seq#(index); then perform body; then assign index := index + 1; }`）
    のように、代入文自体への`action`キーワード+名前という名前付きプレ
    フィックス（公式のAssignmentNodeDeclarationが許す省略可能な
    ActionNodeUsageDeclaration）と、直前ノードとの暗黙の連鎖を表す先頭の
    裸`then`（対象参照を伴わない、公式のEmptySuccessionMember）が
    assignmentStmt/performActionStmt/actionUsageStmtのいずれにも一切
    未対応だった。既存の裸形（`then`・名前プレフィックスなし）との共存も
    確認する。"""
    ast = parse_sysml_antlr(
        "action def LoopAction { "
        "private action initialization assign index := 1; "
        "then private action whileLoop while index <= size(seq) { "
        "assign var := seq#(index); "
        "then perform body; "
        "then assign index := index + 1; "
        "} }"
    )
    body = ast["children"][0]["children"]
    initialization = body[0]
    assert initialization == {
        "type": "assignment_stmt",
        "name": "index",
        "operator": ":=",
        "value": {"type": "literal", "literal_type": "int", "value": 1},
        "visibility": "private",
        "actionName": "initialization",
    }

    while_loop = body[1]
    assert while_loop["type"] == "action_usage"
    assert while_loop["name"] == "whileLoop"
    assert while_loop["isThen"] is True
    assert while_loop["visibility"] == "private"

    inner = while_loop["children"]
    assert inner[0] == {
        "type": "assignment_stmt",
        "name": "var",
        "operator": ":=",
        "value": {
            "type": "index_access",
            "base": {"type": "name_ref", "reference": "seq"},
            "index": {"type": "name_ref", "reference": "index"},
            "children": [],
        },
    }
    assert inner[1] == {"type": "perform_action", "reference": "body", "isThen": True}
    assert inner[2]["type"] == "assignment_stmt"
    assert inner[2]["isThen"] is True

    bare_ast = parse_sysml_antlr("action def A { assign x := 1; perform y; }")
    bare_children = bare_ast["children"][0]["children"]
    assert bare_children[0] == {
        "type": "assignment_stmt",
        "name": "x",
        "operator": ":=",
        "value": {"type": "literal", "literal_type": "int", "value": 1},
    }
    assert bare_children[1] == {"type": "perform_action", "reference": "y"}


def test_antlr_action_parameter_reversed_type_order():
    """d71_action_parameter_reversed_type_order_missing: States.sysmlの
    `in transitionLinkSource[1]: StateAction :>> TransitionAction::
    transitionLinkSource;`のように、多重度を型節より先に置く逆順
    （`eventOccurrenceUsageStmt`がd47で対応した順序と同型）が
    actionParameterで受理できなかった。既存の通常順（型節→多重度）
    との共存も確認する。"""
    reversed_ast = parse_sysml_antlr(
        "action def A { in transitionLinkSource[1]: StateAction :>> "
        "TransitionAction::transitionLinkSource; }"
    )
    reversed_param = reversed_ast["children"][0]["params"][0]
    assert reversed_param["name"] == "transitionLinkSource"
    assert reversed_param["type_name"] == "StateAction"
    assert reversed_param["multiplicity"]["size"] == {"min": 1, "max": 1}

    normal_ast = parse_sysml_antlr("action def A { in point : Point[1]; }")
    normal_param = normal_ast["children"][0]["params"][0]
    assert normal_param["name"] == "point"
    assert normal_param["type_name"] == "Point"
    assert normal_param["multiplicity"]["size"] == {"min": 1, "max": 1}


def test_antlr_bare_interface_usage_no_connect():
    """d72_bare_interface_usage_missing: Interfaces.sysmlの`abstract
    interface interfaces: Interface[0..*] nonunique :> connections {
    ... }`のように、`connect`を伴わない裸のinterface usage形
    （connection/allocation/message/flow等と同型、d63/d67と同種の
    ギャップ）が一切未対応だった。既存の`connect`形との共存も確認する。"""
    bare_ast = parse_sysml_antlr(
        "package P { abstract interface interfaces: Interface[0..*] "
        "nonunique :> connections { } }"
    )
    node = bare_ast["children"][-1]
    assert node["type"] == "interface_usage"
    assert node["name"] == "interfaces"
    assert node["type_name"] == "Interface"
    assert node["isAbstract"] is True
    assert node["redefines"] == [{"kind": "subsets", "target": "connections"}]

    connect_ast = parse_sysml_antlr(
        "interface def IF { interface x : IFace connect a to b; }"
    )
    connect_node = connect_ast["children"][0]["children"][0]
    assert connect_node["type"] == "interface_usage"
    assert connect_node["type_name"] == "IFace"
    assert connect_node["interface_part"] is not None


def test_antlr_named_multiplicity_binding_connector():
    """d74_named_multiplicity_binding_connector_missing: ShapeItems.sysmlの
    `binding [1] bind [0..*] base.edges = [0..*] be;`（公式コーパス
    全体で51件）のように、名前付き(常に`binding`固定)+自体の多重度
    (常に`[1]`固定)+各end側の多重度を伴うbindingConnector形が一切
    未対応だった。既存の裸形（`bind a = b;`・body付き`bind a = b {
    ... }`）との共存も確認する。d99でleftEnd/rightEndの型を
    `connectorEnd`から`connectorEndPath`へ差し替えたため、出力は
    区切り文字を常に`::`へ正規化する（d81の既存方針）。"""
    named_ast = parse_sysml_antlr(
        "part def P { binding [1] bind [0..*] base.edges = [0..*] be; }"
    )
    named_node = named_ast["children"][0]["children"][0]
    assert named_node["type"] == "binding_connector"
    assert named_node["name"] == "binding"
    assert named_node["multiplicity"]["size"] == {"min": 1, "max": 1}
    assert named_node["leftMultiplicity"]["size"] == {"min": 0, "max": "*"}
    assert named_node["leftEnd"]["reference"] == "base::edges"
    assert named_node["rightMultiplicity"]["size"] == {"min": 0, "max": "*"}
    assert named_node["rightEnd"]["reference"] == "be"

    bare_ast = parse_sysml_antlr("part def P { bind payload = accepter.payload; }")
    bare_node = bare_ast["children"][0]["children"][0]
    assert bare_node["type"] == "binding_connector"
    assert bare_node["name"] is None
    assert bare_node["multiplicity"] is None
    assert bare_node["leftEnd"]["reference"] == "payload"
    assert bare_node["rightEnd"]["reference"] == "accepter::payload"

    body_ast = parse_sysml_antlr("part def P { bind start = done { doc /* c */ } }")
    body_node = body_ast["children"][0]["children"][0]
    assert body_node["type"] == "binding_connector"
    assert len(body_node["children"]) == 1
    assert body_node["children"][0]["type"] == "documentation"


def test_antlr_binding_connector_endpoint_double_colon_mixed():
    """d99_binding_connector_endpoint_double_colon_mixed_missing: 実
    モデル（adas-sysmlv2-main）のADAS.sysmlの`bind LDW::'レーンモデルを
    生成する'.'カメラ画角' = 'カメラ画角';`のように、`bind`文
    （bindingConnector）の端点が`::`（パッケージ限定）と`.`（フィー
    チャアクセス）を混在させる場合に受理できなかった。d98の
    `connectUsage`と同じ考え方で、端点を共有規則`connectorEnd`から
    専用の`connectorEndPath`（`.`/`::`両対応）へ差し替えた（共有
    `connectorEnd`自体は他の参照元への影響を避けるため変更しない）。"""
    ast = parse_sysml_antlr("part def P { bind LDW::'A'.'B' = 'C'; }")
    node = ast["children"][0]["children"][0]
    assert node["leftEnd"] == {"type": "connector_end", "declared_name": None, "reference": "LDW::A::B"}
    assert node["rightEnd"] == {"type": "connector_end", "declared_name": None, "reference": "C"}


def test_antlr_new_expr_positional_argument():
    """d73_new_expr_positional_argument_missing: SampledFunctions.sysmlの
    `new SamplePair(x, calculation(x))`のように、new式のnewArgument規則
    が名前付き引数(`name = expression`)のみ対応で位置引数(bare
    expression、カンマ区切り)を受理できなかった。既存の名前付き引数形
    との共存も確認する。"""
    positional_ast = parse_sysml_antlr(
        "calc def C { attribute a = new SamplePair(x, calculation(x)); }"
    )
    positional_value = positional_ast["children"][0]["children"][0]["value"]
    assert positional_value["type"] == "new_instance"
    assert positional_value["name"] == "SamplePair"
    assert positional_value["arguments"] == [
        {"type": "positional_argument", "value": {"type": "name_ref", "reference": "x"}, "children": []},
        {
            "type": "positional_argument",
            "value": {
                "type": "function_call", "name": "calculation",
                "arguments": [
                    {"type": "positional_argument", "value": {"type": "name_ref", "reference": "x"}, "children": []},
                ],
                "children": [],
            },
            "children": [],
        },
    ]

    named_ast = parse_sysml_antlr(
        "part def P { attribute a = new RiskLevel(probability = LevelEnum::low); }"
    )
    named_value = named_ast["children"][0]["children"][0]["value"]
    assert named_value["arguments"] == [
        {"type": "named_argument", "name": "probability", "value": {"type": "name_ref", "reference": "LevelEnum::low"}, "children": []},
    ]


def test_antlr_state_usage_at_package_body_level():
    """d75_state_usage_package_body_element_missing: States.sysmlの
    `abstract state stateActions: StateAction[0..*] nonunique :>
    actions { doc ... }`のように、既存の`stateUsage`規則
    （partBodyElement/stateBodyElementには登録済み）が
    `packageBodyElement`に登録されておらず、パッケージ直下で使えな
    かった（d67と同種の登録漏れ、11回目）。"""
    ast = parse_sysml_antlr(
        "package P { abstract state stateActions: StateAction[0..*] "
        "nonunique :> actions { } }"
    )
    node = ast["children"][-1]
    assert node["type"] == "state_usage"
    assert node["name"] == "stateActions"
    assert node["type_name"] == "StateAction"
    assert node["isAbstract"] is True
    assert node["redefines"] == [{"kind": "subsets", "target": "actions"}]


def test_antlr_calc_def_nested_in_calc_def():
    """d76_calculation_def_part_body_element_missing:
    SampledFunctions.sysmlの`private calc def Linear { ... }`のように、
    別の`calc def`本体内部にさらに`calc def`をネストする形が受理
    できなかった。`calculationDef`/`constraintDef`が`packageBodyElement`
    にしか登録されておらず、`calcBodyElement`が委譲する
    `partBodyElement`への登録漏れ（12回目の同種パターン）だった。"""
    ast = parse_sysml_antlr(
        "calc def Outer { private calc def Linear { in attribute x : Real; } }"
    )
    outer = ast["children"][0]
    assert outer["type"] == "calculation_def"
    assert outer["name"] == "Outer"
    inner = outer["children"][0]
    assert inner["type"] == "calculation_def"
    assert inner["name"] == "Linear"
    assert inner["visibility"] == "private"
    assert inner["children"][0]["name"] == "x"


def test_antlr_item_port_usage_at_package_body_level():
    """d77_item_port_usage_package_body_element_missing: Items.sysmlの
    `abstract item items : Item[0..*] nonunique :> objects { doc ... }`・
    Ports.sysmlの`abstract port ports : Port[0..*] nonunique :>
    objects { doc ... }`のように、既存の`itemUsage`/`portUsage`規則
    （partBodyElementには登録済み）が`packageBodyElement`に登録され
    ておらず、パッケージ直下で使えなかった（d67/d75と同種の登録漏れ、
    13・14回目）。"""
    item_ast = parse_sysml_antlr(
        "package P { abstract item items : Item[0..*] nonunique :> objects { } }"
    )
    item_node = item_ast["children"][-1]
    assert item_node["type"] == "item_usage"
    assert item_node["name"] == "items"
    assert item_node["type_name"] == "Item"
    assert item_node["redefines"] == [{"kind": "subsets", "target": "objects"}]

    port_ast = parse_sysml_antlr(
        "package P { abstract port ports : Port[0..*] nonunique :> objects { } }"
    )
    port_node = port_ast["children"][-1]
    assert port_node["type"] == "port_usage"
    assert port_node["name"] == "ports"
    assert port_node["type_name"] == "Port"
    assert port_node["redefines"] == [{"kind": "subsets", "target": "objects"}]


def test_antlr_action_parameter_default_keyword():
    """d78_action_parameter_default_keyword_missing: SpatialItems.sysmlの
    `in clock : Clock[1] default enclosingItem.localClock;`・
    Actions.sysmlの`in target : Occurrence[1] default that as
    Occurrence { doc ... }`のように、actionParameterが`=`値代入のみ
    対応で`default`キーワードには未対応だった。既存の`=`形との共存も
    確認する。"""
    default_ast = parse_sysml_antlr(
        "action def A { in clock : Clock[1] default enclosingItem.localClock; }"
    )
    default_param = default_ast["children"][0]["params"][0]
    assert default_param["name"] == "clock"
    assert default_param["value"] is None
    assert default_param["defaultValue"] == {
        "type": "name_ref", "reference": "enclosingItem.localClock",
    }

    body_ast = parse_sysml_antlr(
        "action def A { in target : Occurrence[1] default that as Occurrence { doc /* c */ } }"
    )
    body_param = body_ast["children"][0]["params"][0]
    assert body_param["defaultValue"]["type"] == "as_cast"
    assert body_param["children"][0]["type"] == "documentation"

    equals_ast = parse_sysml_antlr("action def A { in x = 1; }")
    equals_param = equals_ast["children"][0]["params"][0]
    assert equals_param["value"] == {"type": "literal", "literal_type": "int", "value": 1}
    assert equals_param["defaultValue"] is None


def test_antlr_scientific_notation_numeric_literal():
    """d79_scientific_notation_numeric_literal_missing: SIPrefixes.sysmlの
    `:>> conversionFactor = 1E-24;`・USCustomaryUnits.sysmlの
    `:>> conversionFactor = 4.046873E+03;`のように、指数表記の数値
    リテラル（仮数部+E/e+符号任意+指数部）が一切未対応だった。負の
    指数を伴う整数仮数部（`1E-24`）はint()では変換できないため実数値
    として扱う必要があることも確認する。既存の通常のint/real
    リテラルとの共存も確認する。"""
    negative_exp = parse_sysml_antlr("part def P { attribute a = 1E-24; }")
    assert negative_exp["children"][0]["children"][-1]["value"] == {
        "type": "literal", "literal_type": "real", "value": 1e-24,
    }

    positive_exp = parse_sysml_antlr("part def P { attribute a = 4.046873E+03; }")
    assert positive_exp["children"][0]["children"][-1]["value"] == {
        "type": "literal", "literal_type": "real", "value": 4046.873,
    }

    plain_int = parse_sysml_antlr("part def P { attribute a = 42; }")
    assert plain_int["children"][0]["children"][-1]["value"] == {
        "type": "literal", "literal_type": "int", "value": 42,
    }

    plain_real = parse_sysml_antlr("part def P { attribute a = 3.14; }")
    assert plain_real["children"][0]["children"][-1]["value"] == {
        "type": "literal", "literal_type": "real", "value": 3.14,
    }


def test_antlr_multiple_types_after_colon():
    """d80_multiple_types_after_colon_missing: SI.sysmlの`attribute <K>
    kelvin : ThermodynamicTemperatureUnit, TemperatureDifferenceUnit {
    ... }`・Actions.sysmlの`ref sentMessage :>> sentTransfer:
    MessageTransfer, MessageAction { ... }`のように、attribute/feature
    usageの型節（`:`の後）でカンマ区切りの複数型が受理されなかった。
    単一型の後方互換（`type_names`キーが付かないこと）も確認する。"""
    attr_ast = parse_sysml_antlr(
        "part def P { attribute <K> kelvin : ThermodynamicTemperatureUnit, "
        "TemperatureDifferenceUnit { } }"
    )
    attr_node = attr_ast["children"][0]["children"][0]
    assert attr_node["type_name"] == "ThermodynamicTemperatureUnit"
    assert attr_node["type_names"] == ["ThermodynamicTemperatureUnit", "TemperatureDifferenceUnit"]

    feature_ast = parse_sysml_antlr(
        "part def P { ref sentMessage :>> sentTransfer: MessageTransfer, MessageAction { } }"
    )
    feature_node = feature_ast["children"][0]["children"][0]
    assert feature_node["type_name"] == "MessageTransfer"
    assert feature_node["type_names"] == ["MessageTransfer", "MessageAction"]

    single_type_ast = parse_sysml_antlr("part def P { attribute x : Integer; }")
    single_type_node = single_type_ast["children"][0]["children"][0]
    assert single_type_node["type_name"] == "Integer"
    assert "type_names" not in single_type_node


def test_antlr_dotted_namespace_path_redefine_target():
    """d81_dotted_namespace_path_missing: Ports.sysmlの`ref :>>
    outgoingTransfersFromSelf :> interfacingPorts.
    incomingTransfersToSelf { ... }`のように、redefine対象が`.`区切り
    のパスを取る場合に受理できなかった（現行の`namespacePath`は`::`
    区切りのみ対応）。出力文字列は`::`区切りへ正規化されることと、
    既存の`::`区切りが引き続き正しく解釈されることを確認する。"""
    dotted_ast = parse_sysml_antlr(
        "part def P { ref :>> outgoingTransfersFromSelf :> "
        "interfacingPorts.incomingTransfersToSelf { } }"
    )
    dotted_node = dotted_ast["children"][0]["children"][0]
    assert dotted_node["redefines"] == [
        {"kind": "redefines", "target": "outgoingTransfersFromSelf"},
        {"kind": "subsets", "target": "interfacingPorts::incomingTransfersToSelf"},
    ]

    double_colon_ast = parse_sysml_antlr(
        "part def P { attribute unit :>> UnitPowerFactor::unit = 1; }"
    )
    double_colon_node = double_colon_ast["children"][0]["children"][0]
    assert double_colon_node["redefines"] == [
        {"kind": "redefines", "target": "UnitPowerFactor::unit"},
    ]


def test_antlr_type_keyword_as_identifier():
    """d82_type_keyword_as_identifier_missing: ImageMetadata.sysmlの
    `attribute type : String[0..1] { ... }`のように、予約キーワード
    `type`（`typeDef`専用）を宣言名として使う実例が受理できなかった。
    `typeDef`（`type def ...`）が引き続き正しく解釈されることも
    確認する。"""
    attr_ast = parse_sysml_antlr("part def P { attribute type : String[0..1] { } }")
    attr_node = attr_ast["children"][0]["children"][0]
    assert attr_node["type"] == "attribute_usage"
    assert attr_node["name"] == "type"
    assert attr_node["type_name"] == "String"

    type_def_ast = parse_sysml_antlr("type def MyType;")
    type_def_node = type_def_ast["children"][0]
    assert type_def_node["type"] == "type_def"
    assert type_def_node["name"] == "MyType"


def test_antlr_arrow_lambda_param_body_form():
    """d83_arrow_lambda_param_and_trailing_expr_missing:
    TradeStudies.sysmlの`studyAlternatives->selectOne {in ref a { doc
    ... } tradeStudyObjective(...)}`のように、arrow-lambda本体内の
    `lambdaParam`が`;`終端のみ対応で`{ doc ... }`というbody形には
    未対応だった（他のusage-keyword規則と同型のbody形を追加）。既存の
    `;`終端形との共存も確認する。"""
    body_form_ast = parse_sysml_antlr(
        "part def P { attribute a = x->selectOne {in ref a { doc /* c */ } y}; }"
    )
    body_form_value = body_form_ast["children"][0]["children"][0]["value"]
    assert body_form_value["type"] == "arrow_lambda"
    assert body_form_value["param"] == {"name": "a", "isRef": True, "typeName": None}

    semicolon_form_ast = parse_sysml_antlr(
        "part def P { attribute a = x->selectOne {in ref a; y}; }"
    )
    semicolon_form_value = semicolon_form_ast["children"][0]["children"][0]["value"]
    assert semicolon_form_value["param"] == {"name": "a", "isRef": True, "typeName": None}


def test_antlr_derived_modifier_keyword():
    """d84_derived_modifier_keyword_missing: SysML.sysmlの`derived ref
    item receiverArgument : Expression[0..1] subsets Metadata::
    metadataItems;`・`derived attribute isReference : Boolean[1];`の
    ように、`derived`修飾キーワード（他の修飾子と同じ位置、visibility
    の後・abstract/refより前）が一切未実装だった。既存の`derived`無し
    形との共存（`isDerived: False`）も確認する。"""
    item_ast = parse_sysml_antlr(
        "metadata def M { derived ref item receiverArgument : "
        "Expression[0..1] subsets Metadata::metadataItems; }"
    )
    item_node = item_ast["children"][0]["children"][0]
    assert item_node["type"] == "item_usage"
    assert item_node["isDerived"] is True
    assert item_node["isRef"] is True

    attr_ast = parse_sysml_antlr("part def P { derived attribute isReference : Boolean[1]; }")
    attr_node = attr_ast["children"][0]["children"][0]
    assert attr_node["type"] == "attribute_usage"
    assert attr_node["isDerived"] is True

    plain_ast = parse_sysml_antlr("part def P { attribute x : Integer; }")
    plain_node = plain_ast["children"][0]["children"][0]
    assert plain_node["isDerived"] is False


def test_antlr_real_state_transition_now_parses():
    """フェーズ2のもう一つの主要ブロッカーだったreal_state_transition.sysmlが
    解消したことを直接固定する。_find_state_in_symbolsがtype=="state_def"の
    ものしか見つけられないため、bare形のstate usage(Off/On)を参照する
    transitionは`ソース/ターゲットが見つからない`という既知の（linter.py側の
    未整備による）警告になる想定だが、クラッシュはしない。"""
    text = (CORPUS_DIR / "working" / "real_state_transition.sysml").read_text(encoding="utf-8")
    ast = parse_sysml_antlr(text)
    assert ast.get("type") != "error"
    lint_ast(ast)  # クラッシュしないことを確認


# --- COVERAGE.md低頻度項目: dependency/event occurrence/exhibit state/portion --
# (grammar.pyの102規則インベントリのうち残っていた低頻度項目。COVERAGE.md参照)


def test_antlr_dependency_single_and_multi_client_supplier():
    """working/dependency.sysmlも参照。複数client/supplier（カンマ区切り）も
    正しくリストに集約されることを直接確認する。identification（`dependency D
    from ...`の`D`部分）はASTに含めない仕様。"""
    single = "part def A; part def B; dependency A to B;"
    ast_single = parse_sysml_antlr(single)
    assert ast_single["children"][-1] == {
        "type": "special_stmt",
        "children": [
            {"type": "dependency", "clients": ["A"], "suppliers": ["B"], "prefixMetadata": [], "children": []}
        ],
    }

    multi = "part def A; part def X; part def B; part def Y; dependency A, X to B, Y;"
    ast_multi = parse_sysml_antlr(multi)
    dependency = ast_multi["children"][-1]["children"][0]
    assert dependency == {
        "type": "dependency",
        "clients": ["A", "X"],
        "suppliers": ["B", "Y"],
        "prefixMetadata": [],
        "children": [],
    }


def test_antlr_dependency_prefix_metadata_annotation():
    """`#refinement dependency X to Y;`のような#Typeプレフィックスメタデータ
    注釈（2026-08-28、参照実装比較レポートP0-4で発見。apollo-11-sysml-v2の
    公式サンプルで300件超使われている、最頻出パターン）。複数個も付けられる。"""
    ast = parse_sysml_antlr("part def A; part def B; #refinement dependency A to B;")
    dependency = ast["children"][-1]["children"][0]
    assert dependency["prefixMetadata"] == ["refinement"]

    multi_prefix = parse_sysml_antlr("part def A; part def B; #Foo #Bar::Baz dependency A to B;")
    dependency2 = multi_prefix["children"][-1]["children"][0]
    assert dependency2["prefixMetadata"] == ["Foo", "Bar::Baz"]


def test_antlr_metadata_usage_at_shorthand():
    """`@Classified { ... }`/`@Security;`という`metadata`キーワード省略の
    ショートハンド形（2026-08-28、参照実装比較レポートP0-4で発見）。
    `@`は以前lexerにトークンとして登録されておらず、遭遇すると
    token recognition errorになっていた（構文エラーより重症）。"""
    bare = parse_sysml_antlr("metadata def Classified; part def P { @Security; }")
    node = bare["children"][-1]["children"][-1]
    assert node == {
        "type": "metadata_usage",
        "name": "Security",
        "shortName": None,
        "inheritance": None,
        "isAbstract": False,
        "children": [],
    }
    with_body = parse_sysml_antlr(
        "metadata def Classified; part def P { @Classified { attribute level : Integer; } }"
    )
    lint_ast(with_body)
    node2 = with_body["children"][-1]["children"][-1]
    assert node2["type"] == "metadata_usage"
    assert node2["name"] == "Classified"
    assert len(node2["children"]) == 1


def test_antlr_event_occurrence_usage_is_new_construct():
    """`event occurrence A;`は旧Lark実装でも構文としては通るが、出力が
    生Tree混じりの断片で実用に耐えず、type文字列も`_stmt`付きでlinter.pyの
    `_check_event_occurrence_usage`が期待する形と一致しない別バグがある
    （AST_SCHEMA.md参照）。新実装ではクリーンな形にした。`_collect_symbols`の
    シンボル収集whitelistに`event_occurrence_usage`が無く
    `_check_event_occurrence_usage`が発火しないバグはlinter.py側で修正済み
    （AST_SCHEMA.md §3.29参照）。`ownedReferenceSubsetting`を持たせる構文が
    無いため、常に「参照サブセッティングが無い」というWARNINGが1件出る。"""
    ast = parse_sysml_antlr("event occurrence A;")
    assert ast["children"][0] == {
        "type": "event_occurrence_usage",
        "name": "A",
        "direction": None,
        "type_name": None,
        "defaultValue": None,
        "ownedReferenceSubsetting": None,
        "children": [],
    }
    issues = lint_ast(ast)
    assert len(issues) == 1
    assert issues[0].severity == "warning"


def test_antlr_event_occurrence_usage_multiplicity_type_and_body():
    """d47_event_occurrence_usage_body: StateSpaceRepresentation.sysmlの
    `event occurrence zeroCrossingEvents[0..*] : ZeroCrossingEventDef {
    /* ... */ }`のように、多重度・型節・bareなブロックコメントのみの
    bodyを伴う形。"""
    src = "event occurrence zeroCrossingEvents[0..*] : ZeroCrossingEventDef { /* comment */ }"
    ast = parse_sysml_antlr(src)
    node = ast["children"][0]
    assert node["type"] == "event_occurrence_usage"
    assert node["name"] == "zeroCrossingEvents"
    assert node["direction"] is None
    assert node["type_name"] == "ZeroCrossingEventDef"
    assert node["defaultValue"] is None
    assert len(node["children"]) == 1


def test_antlr_event_occurrence_usage_direction_and_default():
    """d47_event_occurrence_usage_body: Flows.sysmlの`in event occurrence
    sourceEvent [1] default thisConnection.start { doc /* ... */ }`のように、
    direction接頭辞・multiplicity・default節・doc付きbodyを伴う形。"""
    src = (
        "in event occurrence sourceEvent [1] default thisConnection.start "
        "{ doc /* comment */ }"
    )
    ast = parse_sysml_antlr(src)
    node = ast["children"][0]
    assert node["type"] == "event_occurrence_usage"
    assert node["name"] == "sourceEvent"
    assert node["direction"] == "in"
    assert node["type_name"] is None
    assert node["defaultValue"] is not None
    assert len(node["children"]) == 1


def test_antlr_exhibit_state_usage_is_new_construct():
    """`exhibit state A;`は旧Lark実装でも構文としては通るが、出力が生Tree
    混じりの断片で実用に耐えず、linter.py側に対応するチェック関数も無い
    （構文的完全性のみ）。"""
    ast = parse_sysml_antlr("exhibit state A;")
    assert ast["children"][0] == {
        "type": "exhibit_state_usage",
        "name": "A",
        "type_name": None,
        "children": [],
    }
    lint_ast(ast)


def test_antlr_exhibit_state_usage_type_clause_and_partbody():
    """`exhibit state 'vehicle states': 'Vehicle States';`
    （5-State-based Behavior-1a.sysml）のように、型節を伴い、かつ
    part def本体内にも書ける（2026-08-28、参照実装比較レポートP1-2で発見。
    以前はpackageBodyElementにしか登録されておらず型節も無かった）。"""
    ast = parse_sysml_antlr(
        "part def VehicleA { exhibit state 'vehicle states': 'Vehicle States'; }"
    )
    node = ast["children"][0]["children"][0]
    assert node == {
        "type": "exhibit_state_usage",
        "name": "vehicle states",
        "type_name": "Vehicle States",
        "children": [],
    }
    lint_ast(ast)


def test_antlr_portion_usage_snapshot_and_timeslice():
    """`snapshot A;`/`timeslice A;`は旧Lark実装でも構文としては通るが、
    出力が生Tree混じりの断片で実用に耐えず、linter.py側に対応する
    チェック関数も無い（構文的完全性のみ）。"""
    snapshot = parse_sysml_antlr("snapshot A;")
    timeslice = parse_sysml_antlr("timeslice A;")
    base = {"isThen": False, "value": None, "multiplicity": None, "children": []}
    assert snapshot["children"][0] == {"type": "portion_usage", "kind": "snapshot", "name": "A", **base}
    assert timeslice["children"][0] == {"type": "portion_usage", "kind": "timeslice", "name": "A", **base}


def test_antlr_portion_usage_body_multiplicity_then_and_value():
    """2026-08-28、参照実装比較レポートP0-2で発見: 公式コーパス（Time Slice
    and Snapshot Example.sysml）はportion usageに本体・多重度・`then`連鎖
    宣言・値代入を組み合わせて使うため、いずれも受理できる必要がある。"""
    ast = parse_sysml_antlr(
        """
        part def Vehicle {
            then timeslice ownership[0..*] ordered {
                snapshot sale = start;
            }
        }
        """
    )
    vehicle = ast["children"][0]
    outer = vehicle["children"][0]
    assert outer["type"] == "portion_usage"
    assert outer["kind"] == "timeslice"
    assert outer["name"] == "ownership"
    assert outer["isThen"] is True
    assert outer["multiplicity"] is not None

    inner = outer["children"][0]
    assert inner["type"] == "portion_usage"
    assert inner["kind"] == "snapshot"
    assert inner["name"] == "sale"
    assert inner["value"] is not None
    lint_ast(ast)


# --- occurrence def/usage・individual def/usage (8.2.2.9) -----------------------
# フェーズ4完了条件の「未決着3項目」のうち最後の1つ。COVERAGE.md/AST_SCHEMA.md §3.24参照。
# `occurrence def X;`/`individual def X;`は旧Lark実装の文法著者バグ
# （KW_DEFが二重に要求される）により常に構文エラーで比較対象なし。
# `individual X;`も旧実装では常に構文エラー。`occurrence X;`のみ旧実装でも
# 構文が通るが出力が生Tree混じりの断片のため、いずれもクリーンな新規実装にした。


def test_antlr_occurrence_def():
    ast = parse_sysml_antlr("occurrence def A;")
    assert ast["children"][0] == {
        "type": "occurrence_def",
        "name": "A",
        "isIndividual": False,
        "isAbstract": False,
        "inheritance": None,
        "children": [],
    }


def test_antlr_occurrence_usage_is_new_clean_shape():
    ast = parse_sysml_antlr("occurrence A;")
    assert ast["children"][0] == {
        "type": "occurrence_usage",
        "name": "A",
        "isPortion": False,
        "portionKind": None,
        "isAbstract": False,
        "isConstant": False,
        "isRef": False,
        "direction": None,
        "redefines": [],
        "value": None,
        "defaultValue": None,
        "multiplicity": None,
        "children": [],
    }


def test_antlr_occurrence_usage_constant_ref_multiple_redefines():
    """d49_actions_sysml_occurrence_investigation:
    CausationConnections.sysmlの`abstract constant ref occurrence
    causes[1..*] :>> causes :> participant { ... }`のように、constant/ref
    修飾子と複数のpostKind redefine節を伴う形。"""
    src = "part def P { abstract constant ref occurrence causes[1..*] :>> causes :> participant { } }"
    ast = parse_sysml_antlr(src)
    node = ast["children"][0]["children"][-1]
    assert node["type"] == "occurrence_usage"
    assert node["name"] == "causes"
    assert node["isAbstract"] is True
    assert node["isConstant"] is True
    assert node["isRef"] is True
    assert [r["kind"] for r in node["redefines"]] == ["redefines", "subsets"]


def test_antlr_occurrence_usage_direction_name_omitted_and_value():
    """d49_actions_sysml_occurrence_investigation: Actions.sysmlの`ref
    occurrence :>> Action::this, actions::this, subperformances::this =
    thisConnection { }`のように、名前省略・複数ターゲットのredefine節・
    `=`による値代入を伴う形（元の`as`キャスト式部分はd52として別途扱う）。"""
    src = (
        "part def P { ref occurrence :>> Action::this, actions::this, "
        "subperformances::this = thisConnection { } }"
    )
    ast = parse_sysml_antlr(src)
    node = ast["children"][0]["children"][-1]
    assert node["type"] == "occurrence_usage"
    assert node["name"] is None
    assert node["isRef"] is True
    assert node["redefines"][0]["kind"] == "redefines"
    assert node["redefines"][0]["targets"] == ["Action::this", "actions::this", "subperformances::this"]
    assert node["value"] is not None


def test_antlr_individual_def_empty_multiplicity_brackets_optional():
    """IndividualDefinitionはEmptyMultiplicityMember(`[]`)を持つことが多いが、
    必須ではない（2026-08-28、参照実装比較レポートP0-3で発見:
    `individual def IO1;`のように`[]`を省略した公式コーパス実例が存在し、
    以前は必須にしていたため単なる構文エラーになっていた）。`[]`を省略した
    場合は"multiplicity": Noneとなり、`_check_individual_definition`
    （case_and_view_rules.py）が既存の「空の多重度が必要」という
    LintIssueとして報告する（構文エラーではなく意味検証エラーになる）。"""
    ast = parse_sysml_antlr("individual def A[];")
    assert ast["children"][0] == {
        "type": "individual_def",
        "name": "A",
        "multiplicity": {"size": None, "is_ordered": False, "is_unique": True},
        "isAbstract": False,
        "inheritance": None,
        "children": [],
    }
    # `[]`を省略しても構文エラーにはならない。multiplicityがNoneになるだけ。
    bare_ast = parse_sysml_antlr("individual def A;")
    assert bare_ast.get("type") != "error"
    assert bare_ast["children"][0] == {
        "type": "individual_def",
        "name": "A",
        "multiplicity": None,
        "isAbstract": False,
        "inheritance": None,
        "children": [],
    }
    issues = lint_ast(bare_ast)
    assert any("空の多重度" in i.message for i in issues if i.severity == "error")


def test_antlr_individual_usage_bare_and_typed():
    bare = parse_sysml_antlr("individual A;")
    typed = parse_sysml_antlr("individual A : T;")
    assert bare["children"][0] == {
        "type": "individual_usage",
        "name": "A",
        "type_name": None,
        "isAbstract": False,
        "children": [],
    }
    assert typed["children"][0] == {
        "type": "individual_usage",
        "name": "A",
        "type_name": "T",
        "isAbstract": False,
        "children": [],
    }


def test_antlr_occurrence_and_individual_do_not_crash_linter():
    """`_collect_symbols`のシンボル収集whitelistは修正済み（AST_SCHEMA.md §3.29）
    で`occurrence_def`/`occurrence_usage`/`individual_def`は`self.symbols`に
    登録されるようになったが、現在の文法ではこれらのチェック関数
    （`_check_occurrence_definition`等）が警告を出す条件（isIndividual=True
    かつ多重度あり等）を満たす出力を生成できないため、実際には引き続き
    issueは0件になる。"""
    for text in ["occurrence def A;", "occurrence A;", "individual def A[];", "individual A;"]:
        ast = parse_sysml_antlr(text)
        assert lint_ast(ast) == []


# --- qualifiedNameのQUOTED_NAME対応・bare first/then・action本体flow_stmt ------
# real_coffee_v4.sysmlの残ブロッカー解消。COVERAGE.md/AST_SCHEMA.md §3.25参照。


def test_antlr_qualified_name_accepts_quoted_segments():
    """`'Boil Water'.w`のように単一引用符名をqualifiedNameのセグメントとして
    使える（connect/flow/transition/message/dependency等、qualifiedNameを
    使う全ての規則に波及する）。旧Lark実装は参照位置での単一引用符名を
    一切サポートしないため比較対象なし。"""
    ast = parse_sysml_antlr("action def Act { flow 'Boil Water'.w to 'Brew'.hotWater; }")
    flow = ast["children"][0]["children"][0]["children"][0]
    assert flow == {
        "type": "flow_short_stmt",
        "from_port": "Boil Water.w",
        "to_port": "Brew.hotWater",
        "children": [],
    }


def test_antlr_bare_first_and_then_are_new_clean_shapes():
    """`first start;`/`then fork1;`は旧Lark実装でも構文は通るが、`name`
    フィールドが未変換dictをstr()した文字列になる既知バグがあり比較対象
    なし（§3.22の`then_stmt`と同種）。新実装ではtype文字列(first_stmt/
    then_stmt)は旧実装と揃えつつ、nameを正しい文字列にした。"""
    ast = parse_sysml_antlr("action def Act { first start; then fork1; then 'Boil Water'; }")
    children = ast["children"][0]["children"]
    assert children[0] == {"type": "first_stmt", "name": "start"}
    assert children[1] == {"type": "then_stmt", "name": "fork1"}
    assert children[2] == {"type": "then_stmt", "name": "Boil Water"}


def test_antlr_succession_stmt_accepts_quoted_names():
    """`first 'Boil Water' then join1;`（1文の組み合わせ形）で単一引用符名を使える。"""
    ast = parse_sysml_antlr("action def Act { first 'Boil Water' then join1; }")
    succession = ast["children"][0]["children"][0]
    assert succession["firstEnd"]["reference"] == "Boil Water"
    assert succession["thenEnd"]["reference"] == "join1"


def test_antlr_action_flow_stmt_from_and_short_forms():
    """action本体専用のflow_stmt(from有無両形)。working/action_flow.sysmlも参照。"""
    ast = parse_sysml_antlr("action def Act { flow from a to b; flow c to d; }")
    children = ast["children"][0]["children"]
    assert children == [
        {
            "type": "flow_stmt",
            "children": [{"type": "flow_from_stmt", "from_port": "a", "to_port": "b", "children": []}],
        },
        {
            "type": "flow_stmt",
            "children": [{"type": "flow_short_stmt", "from_port": "c", "to_port": "d", "children": []}],
        },
    ]


def test_antlr_real_coffee_v4_now_parses():
    """フェーズ4完了条件の最後の実サンプルブロッカーだったreal_coffee_v4.sysml
    が解消したことを直接固定する。"""
    text = (CORPUS_DIR / "working" / "real_coffee_v4.sysml").read_text(encoding="utf-8")
    ast = parse_sysml_antlr(text)
    assert ast.get("type") != "error"
    lint_ast(ast)  # クラッシュしないことを確認


# --- interaction / sequence diagram notation ------------------------------------
# real_coffee_sequence.sysml の解消。旧Lark実装にはinteraction/participant/
# fragment/operandのいずれも字句・構文規則が一切存在しない（比較対象なし、
# 完全新規実装）。COVERAGE.md/AST_SCHEMA.md §3.26参照。


def test_antlr_interaction_def_separates_params_from_children():
    ast = parse_sysml_antlr(
        "interaction def X { in a : Boolean; participant p : Person; message m from p to p; }"
    )
    interaction = ast["children"][0]
    assert interaction["type"] == "interaction_def"
    assert interaction["params"] == [
        {
            "type": "param",
            "direction": "in",
            "is_item": False,
            "kind": None,
            "name": "a",
            "type_spec": {"name": "Boolean"},
            "type_name": "Boolean",
            "multiplicity": None,
            "redefines": [],
            "value": None,
            "defaultValue": None,
            "children": [],
        }
    ]
    assert interaction["children"] == [
        {"type": "participant", "name": "p", "type_name": "Person", "children": []},
        {"type": "message", "name": "m", "from_end": "p", "to_end": "p"},
    ]


def test_antlr_fragment_with_when_and_else_operands():
    ast = parse_sysml_antlr(
        "interaction def X {"
        "  fragment alt sugarBranch {"
        "    operand when sugarNeeded { message a from x to y; }"
        "    operand else { message b from x to y; }"
        "  }"
        "}"
    )
    fragment = ast["children"][0]["children"][0]
    assert fragment["type"] == "fragment"
    assert fragment["kind"] == "alt"
    assert fragment["name"] == "sugarBranch"
    assert len(fragment["operands"]) == 2

    when_operand, else_operand = fragment["operands"]
    assert when_operand["guard"] == {"type": "name_ref", "reference": "sugarNeeded"}
    assert when_operand["is_else"] is False
    assert [c["type"] for c in when_operand["children"]] == ["message"]

    assert else_operand["guard"] is None
    assert else_operand["is_else"] is True


def test_antlr_fragment_operand_without_guard():
    """`fragment par X { operand { ... } operand { ... } }`のようなguard無しの
    並行分岐（when/elseどちらも無い）もサポートする。"""
    ast = parse_sysml_antlr(
        "interaction def X { fragment par p { operand { message a from x to y; } operand { message b from x to y; } } }"
    )
    fragment = ast["children"][0]["children"][0]
    assert len(fragment["operands"]) == 2
    for operand in fragment["operands"]:
        assert operand["guard"] is None
        assert operand["is_else"] is False


def test_antlr_real_coffee_sequence_now_parses():
    """フェーズ4完了条件の最後の実サンプルブロッカーだったreal_coffee_sequence.sysml
    が解消したことを直接固定する（known_broken/real_*.sysmlの5サンプル全てが
    これで解消した）。"""
    text = (CORPUS_DIR / "working" / "real_coffee_sequence.sysml").read_text(encoding="utf-8")
    ast = parse_sysml_antlr(text)
    assert ast.get("type") != "error"
    lint_ast(ast)  # クラッシュしないことを確認


# --- inheritance: specializes/subsets の複数_def構文への拡張 (8.2.2.6.5) --------
# working/specializes_inheritance.sysmlの回帰をきっかけに、part_def以外の
# _def構文にもinheritanceClauseを追加した。COVERAGE.md/AST_SCHEMA.md §3.28参照。


def test_antlr_inheritance_specializes_single_base():
    ast = parse_sysml_antlr("part def A; part def B specializes A;")
    assert ast["children"][1]["inheritance"] == {"type": "inheritance", "kind": "specializes", "base": "A"}


def test_antlr_inheritance_subsets_multi_base_kept_in_bases_list():
    """複数基底（カンマ区切り）は"base"に先頭の基底のみ、"bases"に全基底を
    持つ。"base"を単純な完全一致検索に使うlinter.pyの大半のチェック関数
    （_check_part_def等）がカンマ区切り文字列を分割しないため、"base"へ
    カンマ結合文字列をそのまま入れると実在する型でも「存在しない型」の
    誤検出になることを実測で確認したため、この形にしている。"""
    ast = parse_sysml_antlr("part def A; part def B; part def C subsets A, B;")
    inheritance = ast["children"][2]["inheritance"]
    assert inheritance == {"type": "inheritance", "kind": "subsets", "base": "A", "bases": ["A", "B"]}
    assert lint_ast(ast) == []  # A, Bともに実在するため誤検出が出ない


@pytest.mark.parametrize(
    "text,index,expected_type",
    [
        ("action def A; action def B specializes A;", 1, "action_def"),
        ("type def A; type def B specializes A;", 1, "type_def"),
        ("item def A; item def B specializes A;", 1, "item_def"),
        ("state def A; state def B specializes A;", 1, "state_def"),
        ("port def A; port def B specializes A;", 1, "port_def"),
        ("interface def A; interface def B specializes A;", 1, "interface_def"),
        ("case def A; case def B specializes A;", 1, "case_def"),
    ],
)
def test_antlr_inheritance_extends_to_other_def_constructs(text, index, expected_type):
    ast = parse_sysml_antlr(text)
    node = ast["children"][index]
    assert node["type"] == expected_type
    assert node["inheritance"] == {"type": "inheritance", "kind": "specializes", "base": "A"}


def test_antlr_arrow_lambda_body_doc_keyword_then_param_and_statement():
    """d48_arrow_lambda_body_doc_then_statement: TradeStudies.sysmlの
    `alternatives->minimize { doc /* ... */ in x; eval(x) };`のように、
    `doc`キーワード付きのdocumentationStmt(bareDocCommentではない)の後に
    lambdaParam・式が続く形。従来のarrowLambdaBodyは`bareDocComment*`
    しか受理せず`doc`キーワードが`extraneous input`になっていた。"""
    src = (
        "part def A { attribute alternatives; "
        "attribute :>> best = alternatives->minimize { "
        "doc /* comment */ in x; eval(x) }; }"
    )
    ast = parse_sysml_antlr(src)
    part_def = ast["children"][0]
    attribute_usage = part_def["children"][-1]
    assert attribute_usage["type"] == "attribute_usage"
    lambda_node = attribute_usage["value"]
    assert lambda_node["type"] == "arrow_lambda"
    assert lambda_node["name"] == "minimize"
    assert lambda_node["param"]["name"] == "x"


def test_antlr_rendering_usage_redefine_with_equals_value():
    """d50_feature_usage_equals_value: Views.sysmlの`rendering :>>
    subrenderings[0..*] = columnView.viewRendering;`のように、redefine
    対象へ`default`ではなく`=`で直接式を代入する形。他のusage規則
    (attribute/item/requirement等)には既に`=`値代入があったが
    renderingUsageのみ横展開が漏れていた。"""
    src = "part def P { rendering :>> subrenderings[0..*] = columnView.viewRendering; }"
    ast = parse_sysml_antlr(src)
    node = ast["children"][0]["children"][-1]
    assert node["type"] == "rendering_usage"
    assert node["name"] is None
    assert node["redefines"] == [{"kind": "redefines", "target": "subrenderings"}]
    assert node["value"] == {"type": "name_ref", "reference": "columnView.viewRendering"}


def test_antlr_item_usage_redefine_with_equals_value():
    """d65_item_usage_equals_value: ShapeItems.sysmlの`item :>> vertices
    [*] = edges.vertices;`のように、itemUsage規則に`=`値代入
    (d50でrenderingUsage、d54でactionUsageStmt、d56でfeatureUsage/
    partUsageに同型のものを追加済み、4件目の同種漏れ)が一切実装
    されていなかった。既存の`default`既定値節とは排他。"""
    src = "part def P { item :>> vertices [*] = edges.vertices; }"
    ast = parse_sysml_antlr(src)
    node = ast["children"][0]["children"][-1]
    assert node["type"] == "item_usage"
    assert node["name"] is None
    assert node["redefines"] == [{"kind": "redefines", "target": "vertices"}]
    assert node["value"] == {"type": "name_ref", "reference": "edges.vertices"}
    assert node["defaultValue"] is None


def test_antlr_flow_def_abstract_with_inheritance_and_body():
    """d51_flow_def_missing: Flows.sysmlの`abstract flow def MessageAction
    :> Action, Link { doc ... }`のように、`flow def`という定義形自体が
    一切未実装だった。partDefと同型で新設した。"""
    src = "part def Action; part def Link; abstract flow def MessageAction :> Action, Link { doc /* c */ }"
    ast = parse_sysml_antlr(src)
    node = ast["children"][2]
    assert node["type"] == "flow_def"
    assert node["name"] == "MessageAction"
    assert node["isAbstract"] is True
    assert node["inheritance"]["bases"] == ["Action", "Link"]
    assert len(node["children"]) == 1


def test_antlr_as_cast_expression_bare():
    """d52_as_cast_expression_missing: Actions.sysmlの`in occurrence
    terminatedOccurrence default that as Occurrence { ... }`のように、
    `expr as Type`という型キャスト式自体が一切未実装だった。"""
    ast = parse_sysml_antlr("part def P { attribute a = that as Occurrence; }")
    value = ast["children"][0]["children"][-1]["value"]
    assert value == {
        "type": "as_cast",
        "base": {"type": "name_ref", "reference": "that"},
        "type_name": "Occurrence",
        "children": [],
    }


def test_antlr_member_access_after_cast():
    """d52_as_cast_expression_missing: Actions.sysmlの`(that as Action).
    this`のように、キャスト後の括弧式に対する後置`.member`アクセスも
    必要だった（従来は任意の式に対する後置`.`メンバアクセス演算子自体が
    一切無かった）。裸の名前参照（`a.b.c`）はqualifiedNameが貪欲に消費
    するためnameRefExprのまま変わらないことも合わせて確認する。"""
    ast = parse_sysml_antlr("part def P { attribute a = (that as Action).this; }")
    value = ast["children"][0]["children"][-1]["value"]
    assert value == {
        "type": "member_access",
        "base": {
            "type": "as_cast",
            "base": {"type": "name_ref", "reference": "that"},
            "type_name": "Action",
            "children": [],
        },
        "member": "this",
        "children": [],
    }

    plain_ast = parse_sysml_antlr("part def P { attribute a = that.that; }")
    plain_value = plain_ast["children"][0]["children"][-1]["value"]
    assert plain_value == {"type": "name_ref", "reference": "that.that"}


def test_antlr_succession_usage_named_with_body_and_symbolic_multiplicity():
    """d53_named_succession_usage_with_body: CausationConnections.sysmlの
    `succession causalOrdering first [nCauses] causes.startShot then
    [nEffects] effects { ... }`のように、`succession`キーワード自体・
    名前・先頭のconnectorEnd側多重度・bodyのいずれも未対応だった。
    `[nCauses]`は数値リテラルではなく同一body内のattributeを指す識別子
    （記号的多重度）であることも合わせて対応した。"""
    src = (
        "connection def M { private succession causalOrdering "
        "first [nCauses] causes.startShot then [nEffects] effects { "
        "attribute nCauses = size(causes); } }"
    )
    ast = parse_sysml_antlr(src)
    node = ast["children"][0]["children"][-1]
    assert node["type"] == "succession_usage"
    assert node["name"] == "causalOrdering"
    assert node["visibility"] == "private"
    assert node["multiplicity"] is None
    assert node["firstMultiplicity"] == {
        "size": {"min": "nCauses", "max": "nCauses"},
        "is_ordered": False,
        "is_unique": True,
    }
    assert node["firstEnd"] == {"type": "connector_end", "declared_name": None, "reference": "causes.startShot"}
    assert node["thenEnd"] == {"type": "connector_end", "declared_name": None, "reference": "effects"}
    assert len(node["children"]) == 1


def test_antlr_succession_usage_leading_multiplicity_no_name():
    """d53_named_succession_usage_with_body: Flows.sysmlの`succession
    [seBeforeNum] first [0..1] sourceEvent then [0..1] self;`のように、
    名前を省略し先頭multiplicity（symbolic）のみを持つ形。"""
    src = "part def P { succession [seBeforeNum] first [0..1] sourceEvent then [0..1] self; }"
    ast = parse_sysml_antlr(src)
    node = ast["children"][0]["children"][-1]
    assert node["type"] == "succession_usage"
    assert node["name"] is None
    assert node["multiplicity"] == {
        "size": {"min": "seBeforeNum", "max": "seBeforeNum"},
        "is_ordered": False,
        "is_unique": True,
    }
    assert node["firstMultiplicity"]["size"] == {"min": 0, "max": 1}
    assert node["thenMultiplicity"]["size"] == {"min": 0, "max": 1}


def test_antlr_succession_flow_composite_form():
    """`succession flow onOffCmdFlow from sendOnOffCmd.onOffCmd to
    produceDirectedLight.onOffCmd;`（FlashlightExample.sysml）のような、
    successionとflowを組み合わせた複合キーワード形（2026-08-28、参照実装
    比較レポートP2-2で発見）。既存の`first`/`then`形（connectorEnd使用）
    とは終端の書き方が異なる（namespacePath、`from`/`to`）ため別形状で
    返す。"""
    ast = parse_sysml_antlr(
        "part def P { succession flow onOffCmdFlow from a.x to b.y; }"
    )
    node = ast["children"][0]["children"][-1]
    assert node == {
        "type": "succession_usage",
        "name": "onOffCmdFlow",
        "visibility": None,
        "isFlow": True,
        "fromEnd": "a::x",
        "toEnd": "b::y",
        "children": [],
    }


def test_antlr_power_expression():
    """d59_ampersand_caret_operators_lexer_missing: SI.sysmlの`s^-1`・
    ShapeItems.sysmlの`Triangle::length^2 + Triangle::width^2`のように、
    `^`べき乗演算子が公式コーパス17ファイルで使われているが一切
    レキサーレベルで未対応だった。"""
    ast = parse_sysml_antlr("part def P { attribute a = s^-1; }")
    value = ast["children"][0]["children"][-1]["value"]
    assert value["type"] == "binary_expr"
    assert value["op"] == "^"
    assert value["left"] == {"type": "name_ref", "reference": "s"}
    assert value["right"] == {"type": "unary_expr", "op": "-", "operand": {"type": "literal", "literal_type": "int", "value": 1}}


def test_antlr_ampersand_and_pipe_as_and_or_alternates():
    """d59_ampersand_caret_operators_lexer_missing: ShapeItems.sysmlの
    `notEmpty(outerSpaceDimension) & outerSpaceDimension <= 2`・
    Items.sysmlの`... == 3 | ... == 3`のように、`&`/`|`が`and`/`or`の
    代替記法として1件ずつのみ使われている。使用範囲が狭いため`and`/`or`
    と同一alt内の代替キーワードとして扱う。"""
    and_ast = parse_sysml_antlr("part def P { attribute a = x & y; }")
    and_value = and_ast["children"][0]["children"][-1]["value"]
    assert and_value == {
        "type": "binary_expr", "op": "&",
        "left": {"type": "name_ref", "reference": "x"},
        "right": {"type": "name_ref", "reference": "y"},
    }

    or_ast = parse_sysml_antlr("part def P { attribute a = x | y; }")
    or_value = or_ast["children"][0]["children"][-1]["value"]
    assert or_value == {
        "type": "binary_expr", "op": "|",
        "left": {"type": "name_ref", "reference": "x"},
        "right": {"type": "name_ref", "reference": "y"},
    }


def test_antlr_meta_expression():
    """d60_meta_expression_missing: CauseAndEffect.sysmlの`ref :>>
    baseType = multicausations meta SysML::Usage;`のように、KerMLの
    `meta`式（`asCastExpr`と同型）が一切未実装だった。"""
    ast = parse_sysml_antlr("part def P { ref :>> baseType = multicausations meta SysML::Usage; }")
    value = ast["children"][0]["children"][-1]["value"]
    assert value == {
        "type": "meta_expr",
        "base": {"type": "name_ref", "reference": "multicausations"},
        "type_name": "SysML::Usage",
        "children": [],
    }


# --- 意味検証ルール: 参照実装比較レポートP0-4の§4.1で発見した偽陰性 -------------
# （2026-08-28、eval/SYSML_LINTER_REFERENCE_COMPARISON_REPORT.md参照）


def test_lint_state_entry_do_exit_action_duplicates_are_rejected():
    """StateSubactions_invalid.sysml参照。entry/do/exitアクションはそれぞれ
    最大1つまで。state_def/state_usageの両方に適用する。"""
    text = (
        "state def S {\n"
        "    entry action a;\n"
        "    do action b;\n"
        "    exit action c;\n"
        "    exit action c1;\n"
        "    entry action a1;\n"
        "    do action b1;\n"
        "}\n"
    )
    ast = parse_sysml_antlr(text)
    issues = lint_ast(ast)
    messages = [i.message for i in issues if i.severity == "error"]
    assert sum("exit" in m and "複数定義" in m for m in messages) == 1
    assert sum("entry" in m and "複数定義" in m for m in messages) == 1
    assert sum("do" in m and "複数定義" in m for m in messages) == 1


def test_lint_state_single_actions_pass():
    """1つずつのentry/do/exitアクションは誤検出されない。"""
    text = "state def S {\n    entry action a;\n    do action b;\n    exit action c;\n}\n"
    ast = parse_sysml_antlr(text)
    issues = lint_ast(ast)
    assert not any("複数定義" in i.message for i in issues if i.severity == "error")


def test_lint_calculation_return_parameter_count():
    """CalculationUsage_Invalid2.sysml参照。return parameterは1つまで。
    calculation_def/calculation_usageの両方に適用する。"""
    invalid_def = parse_sysml_antlr(
        "attribute def T; calc def C1 { return r1 : T; return r2 : T; }"
    )
    issues = lint_ast(invalid_def)
    assert sum("return parameter" in i.message for i in issues if i.severity == "error") == 1

    valid_def = parse_sysml_antlr("attribute def T; calc def C { return T; }")
    issues_valid = lint_ast(valid_def)
    assert not any("return parameter" in i.message for i in issues_valid if i.severity == "error")


def test_lint_requirement_subject_count_and_position():
    """RequirementSubject_Invalid.sysml参照。subjectは1つまで、かつ
    param/subject_usageの中で最初でなければならない。requirement_def/
    requirement_usageの両方に適用する。"""
    two_subjects = parse_sysml_antlr("requirement def R { subject s1; subject s2; }")
    issues = lint_ast(two_subjects)
    assert sum("複数定義" in i.message for i in issues if i.severity == "error" and "8.2.2.21" in i.message) == 1

    subject_not_first = parse_sysml_antlr("requirement def R1 { in x; subject s5; }")
    issues2 = lint_ast(subject_not_first)
    assert sum(
        "最初のパラメータ" in i.message for i in issues2 if i.severity == "error" and "8.2.2.21" in i.message
    ) == 1


def test_lint_requirement_subject_after_doc_and_self_redefine_is_not_flagged():
    """2026-08-28の730件回帰チェックで発見: 公式標準ライブラリの
    RequirementCheck等（`doc`の後に`ref requirement :>> self: ...;`という
    非パラメータ宣言を経てから`subject`が続く）を、`children[0]`基準の
    素朴な「先頭」判定だと誤検出していた。パラメータ相当の要素
    （param/subject_usage）だけで判定するよう修正済み。"""
    text = (
        "requirement def RequirementCheck {\n"
        "    doc /* ... */\n"
        "    ref requirement :>> self: RequirementCheck;\n"
        "    subject subj : Anything[1];\n"
        "}\n"
    )
    ast = parse_sysml_antlr(text)
    issues = lint_ast(ast)
    assert not any("8.2.2.21" in i.message for i in issues if i.severity == "error")
