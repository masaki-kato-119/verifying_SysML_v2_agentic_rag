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
                "visibility": None,
                "variability": None,
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
                "prefixMetadata": [],
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
                        "isRef": False,
                        "visibility": None,
                        "redefines": [],
                        "prefixMetadata": [],
                        "value": None,
                        "defaultValue": None,
                        "variability": None,
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


def test_antlr_textualrep_stmt_in_partbodyelement():
    """`assert constraint x_constraint { rep inOCL language "ocl" /* ...
    */ }`・`action def setX { ... language "alf" /* ... */ }`
    （TextualRepresentationTest.sysml）のように、textualRepresentationStmt
    （`rep`/`language`）は従来packageBodyElementにしか登録されておらず、
    action定義本体（actionBodyElement経由でpartBodyElementに委譲）や
    assert constraint本体（calcBodyElement経由）にネストすると失敗して
    いた。2026-08-29、730件ベースライン154件エラー要因分析で発見。"""
    assert_ast = parse_sysml_antlr(
        'item def C { attribute x: Real; '
        'assert constraint x_constraint { rep inOCL language "ocl" /* self.x > 0.0 */ } }'
    )
    constraint_node = assert_ast["children"][0]["children"][-1]["children"][0]
    rep_node = constraint_node["children"][0]
    assert rep_node["type"] == "textual_representation"
    assert rep_node["identification"] == {"type": "identification", "name": "inOCL"}
    assert rep_node["language"] == "ocl"

    action_ast = parse_sysml_antlr(
        'action def setX { in c; language "alf" /* c.x = newX; */ }'
    )
    lang_node = action_ast["children"][0]["children"][-1]
    assert lang_node["type"] == "textual_representation"
    assert lang_node["identification"] is None
    assert lang_node["language"] == "alf"


def test_antlr_comment_about_and_locale():
    """`comment about C /* ... */`・`comment cmt_cmt about cmt /* ... */`
    （Comments.sysml/CommentTest.sysml）のように、コメント対象を明示する
    `about`節と、ロケール注釈`locale`節を持つことがある（2026-08-28、
    参照実装比較レポートP1-5で発見）。`about`はpartBodyElement内にも
    書ける。"""
    ast = parse_sysml_antlr("part def C; comment about C /* about a def */")
    node = ast["children"][-1]
    assert node["about"] == ["C"]
    assert node["locale"] is None

    named_ast = parse_sysml_antlr(
        'part def C { comment about C locale "en_US" /* ... */ }'
    )
    named_node = named_ast["children"][0]["children"][0]
    assert named_node["about"] == ["C"]
    assert named_node["locale"] == "en_US"


def test_antlr_commentstmt_multitarget_about():
    """`comment about Person, Container /* These types represent the core
    domain model entities. */`（dfa-coverage-advanced.sysml L220-221）の
    ように、commentStmtの`about`節がカンマ区切りの複数対象を取ることが
    ある（metadataUsageの`about`節と同型のリスト化。従来は単一対象のみ
    だった）。既存の単一対象形・対象無し形が引き続き機能することも
    確認する。2026-08-31、add_commentstmt_multitarget_about対応中に発見。"""
    ast = parse_sysml_antlr(
        "part def Person; part def Container; "
        "comment about Person, Container /* core domain model entities */"
    )
    node = ast["children"][-1]
    assert node["type"] == "comment"
    assert node["about"] == ["Person", "Container"]

    # 既存の単一対象形が引き続き機能することを確認する。
    single_ast = parse_sysml_antlr("part def C; comment about C /* x */")
    single_node = single_ast["children"][-1]
    assert single_node["about"] == ["C"]

    # 既存の対象無し形が引き続き機能することを確認する
    # （"about"キー自体が無いことも確認する）。
    plain_ast = parse_sysml_antlr("comment MyComment /* a note */")
    plain_node = plain_ast["children"][0]
    assert "about" not in plain_node


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
            "redefines": [], "prefixMetadata": [], "reference": None, "children": [],
        },
        {
            "type": "connection_end_member", "name": "b", "endName": "b", "kind": None,
            "isRef": False, "type_name": "PortB", "multiplicity": None, "endMultiplicity": None,
            "redefines": [], "prefixMetadata": [], "reference": None, "children": [],
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
        "prefixMetadata": [],
        "children": [],
    }
    assert lint_ast(ast) == []


def test_antlr_calculation_usage_short_name():
    """`calc <ln> naturalLogarithm { ... }`
    （CoSMAQuantitiesAndUnitsPackage.sysml）のように、calculationUsageにも
    他のusage系規則（partUsage/requirementUsage等）と同じShortName注釈
    （山括弧の短縮名）が付きうる（2026-08-28、730件回帰チェックで発見。
    P1-1でcalculationUsageへの追加を見落としていた）。"""
    ast = parse_sysml_antlr("calc def Calc; calc <ln> naturalLogarithm : Calc;")
    node = ast["children"][-1]
    assert node["type"] == "calculation_usage"
    assert node["shortName"] == "ln"
    assert node["type_name"] == "Calc"
    assert node["name"] == "naturalLogarithm"
    assert lint_ast(ast) == []


def test_antlr_calculationusage_quoted_type_ref():
    """`calc 'Solve for Pressure1' : 'Ideal Gas Law';`（Turbojet Stage
    Analysis.sysml L88）のように、calculationUsageの型節はQUOTED_NAME
    型参照を取ることもある（従来`ID`決め打ちだった）。既存の`ID`型・
    カンマ区切り複数型が引き続き機能することも確認する。2026-08-29、
    add_calculationusage_quoted_type_ref対応中に発見。"""
    ast = parse_sysml_antlr(
        "part def P { calc 'Solve for Pressure1' : 'Ideal Gas Law'; }"
    )
    node = ast["children"][0]["children"][0]
    assert node["type"] == "calculation_usage"
    assert node["name"] == "Solve for Pressure1"
    assert node["type_name"] == "Ideal Gas Law"

    # 既存のID型・カンマ区切り複数型が引き続き機能することを確認する。
    multi_ast = parse_sysml_antlr("part def P { calc f1 : F1, F2; }")
    multi_node = multi_ast["children"][0]["children"][0]
    assert multi_node["type_names"] == ["F1", "F2"]


def test_antlr_statebodyelement_bare_constraint():
    """`constraint { DurationOf(maintenance) <= 48 [h] }`（Time
    Constraints.sysml、state本体内）のように、`assertConstraintUsage`は
    登録済みだが、`assert`を伴わない単純な`constraint { expr }`
    （constraintUsage）はstate def本体で使えなかった。加えて、
    constraintUsageの裸の`{ expr }`代替（resultExpr）は従来
    `_usage_keyword_node`がcalcBodyElementのみをchildrenとして読むため、
    式自体が読み落とされるバグもあった（今回の修正で同時に発見・
    修正）。2026-08-29、730件ベースライン154件エラー要因分析で発見。"""
    ast = parse_sysml_antlr(
        "state healthStates { constraint { DurationOf(maintenance) <= 48 [h] } }"
    )
    constraint_node = ast["children"][0]["children"][0]
    assert constraint_node["type"] == "constraint_usage"
    assert constraint_node["name"] is None
    assert constraint_node["children"] == []
    assert constraint_node["result_expression"] == {
        "type": "binary_expr", "op": "<=",
        "left": {
            "type": "function_call", "name": "DurationOf",
            "arguments": [
                {"type": "positional_argument", "value": {"type": "name_ref", "reference": "maintenance"}, "children": []},
            ],
            "children": [],
        },
        "right": {
            "type": "quantity_literal",
            "value": {"type": "literal", "literal_type": "int", "value": 48},
            "unit": {"type": "name_ref", "reference": "h"},
            "children": [],
        },
    }

    # 既存のnamed/typed body形（calcBodyElement代替）が引き続き機能し、
    # "result_expression"キー自体が無いことを確認する（回帰防止）。
    named_ast = parse_sysml_antlr("constraint massLimitation { mass : Real; mass < 10; }")
    named_node = named_ast["children"][0]
    assert named_node["type"] == "constraint_usage"
    assert "result_expression" not in named_node


def test_antlr_enum_literal_type_clause():
    """`uncl : ClassificationLevel = 0;`（MetadataTest.sysml、
    pilot-implementation生データ）のように、enumLiteral自体が型節
    （`: Type`）を伴うことがある（2026-08-28、730件回帰チェックで発見。
    値代入形・本体形のいずれも型節を持たなかった）。"""
    value_ast = parse_sysml_antlr("enum def E { uncl : E = 0; }")
    value_lit = value_ast["children"][-1]["children"][0]
    assert value_lit["type"] == "enum_literal"
    assert value_lit["name"] == "uncl"
    assert value_lit["type_name"] == "E"
    assert value_lit["value"]["value"] == 0

    body_ast = parse_sysml_antlr("enum def E { open : E { doc /* x */ } }")
    body_lit = body_ast["children"][-1]["children"][0]
    assert body_lit["name"] == "open"
    assert body_lit["type_name"] == "E"

    # 型節無しの既存形も変わらず動作する。
    plain_ast = parse_sysml_antlr("enum def E { low = 1; }")
    plain_lit = plain_ast["children"][-1]["children"][0]
    assert plain_lit["type_name"] is None


def test_antlr_hash_prefix_on_enum_literal_and_feature_usage():
    """`#Security enum secret : ClassificationLevel = 2;`（MetadataTest.sysml
    L9）・`private ref #Classified #Security z1;`（同 L33）のように、
    `#Type`プレフィックス注釈はenumLiteral・featureUsageのいずれにも付きうる
    （2026-08-28、730件回帰チェックで発見。extend_hash_prefix_annotation_
    and_bare_ref_featureで他規則へは拡張済みだったがこの2規則を見落として
    いた）。"""
    enum_ast = parse_sysml_antlr("enum def E { #Security secret : E = 2; }")
    enum_lit = enum_ast["children"][-1]["children"][0]
    assert enum_lit["prefixMetadata"] == ["Security"]
    assert enum_lit["name"] == "secret"
    assert enum_lit["type_name"] == "E"

    feature_ast = parse_sysml_antlr(
        "metadata def Classified; metadata def Security; "
        "private ref #Classified #Security z1;"
    )
    feature_node = feature_ast["children"][-1]
    assert feature_node["type"] == "feature_usage"
    assert feature_node["prefixMetadata"] == ["Classified", "Security"]
    assert feature_node["name"] == "z1"


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
    assert entry == {"type": "entry_action", "kind": "entry", "action_reference": None, "type_name": None, "redefines": [], "assign": None, "children": []}


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


def test_antlr_transition_omitted_source_initial_pseudostate_form():
    """`transition initial then off;`（5-State-based Behavior-1.sysml L77,136,171）は
    初期疑似状態からの遷移を表す省略形で、`first source`節を持たない。
    source=Noneとしてパースされ、_check_transitionはsourceチェックをスキップする。
    """
    ast = parse_sysml_antlr(
        "state def S { state off; transition initial then off; }"
    )
    transition = ast["children"][0]["children"][1]
    assert transition["type"] == "transition"
    assert transition["name"] == "initial"
    assert transition["source"] is None
    assert transition["target"] == "off"
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


def test_antlr_implicit_transition_first_omitted():
    """`accept s : Sig do action D then S2;`・`accept Exit then done;`
    （StateTest.sysml、公式xpectテスト、noErrors指定）のように、`transition
    ... first`を伴わない暗黙遷移形がある。囲むstate自体が暗黙のsourceと
    なるため、initialTransitionMember（`then X;`のみの形）と同じく
    source=Noneになる（2026-08-28、730件回帰チェックで発見）。"""
    ast = parse_sysml_antlr(
        "attribute def Sig; action D; "
        "state def S { state S1; accept s : Sig do action D then S2; state S2; }"
    )
    transition = ast["children"][-1]["children"][1]
    assert transition["type"] == "transition"
    assert transition["source"] is None
    assert transition["target"] == "S2"
    assert transition["trigger"] == {"kind": "trigger", "reference": "s", "type_name": "Sig"}
    assert transition["effect"] == {"kind": "effect", "action_reference": "D"}
    assert lint_ast(ast) is not None

    accept_then_ast = parse_sysml_antlr("state def S { accept Exit then S1; state S1; }")
    accept_then_transition = accept_then_ast["children"][-1]["children"][0]
    assert accept_then_transition["source"] is None
    assert accept_then_transition["target"] == "S1"
    assert accept_then_transition["trigger"] == {"kind": "trigger", "reference": "Exit"}
    assert accept_then_transition["effect"] is None

    if_then_ast = parse_sysml_antlr("state def S { if true then S1; state S1; }")
    if_then_transition = if_then_ast["children"][-1]["children"][0]
    assert if_then_transition["trigger"] is None
    assert if_then_transition["guard"]["kind"] == "guard"

    do_then_ast = parse_sysml_antlr("action D; state def S { do action D then S1; state S1; }")
    do_then_transition = do_then_ast["children"][-1]["children"][0]
    assert do_then_transition["trigger"] is None
    assert do_then_transition["guard"] is None
    assert do_then_transition["effect"] == {"kind": "effect", "action_reference": "D"}

    # 既存の`then X;`のみの暗黙初期遷移（initialTransitionMember）とは
    # 曖昧にならず、両立して使える。
    bare_then_ast = parse_sysml_antlr("state def S { entry; then S1; state S1; }")
    bare_then_transition = bare_then_ast["children"][-1]["children"][1]
    assert bare_then_transition["type"] == "transition"
    assert bare_then_transition["source"] is None
    assert bare_then_transition["target"] == "S1"


def test_antlr_state_parallel_orthogonal_modifier():
    """`state s parallel { state s1; state s2; }`（StateTest.sysml、公式
    xpectテスト、noErrors指定）・`state def S1 parallel { ... }`のように、
    直交(orthogonal)状態を表す`parallel`修飾子がstateUsage/stateDefに
    付きうる（2026-08-28、730件回帰チェックで発見）。`exhibit state
    vehicleStates parallel { ... }`（VehicleModel_2_Simplified.sysml）の
    ように、exhibitStateUsageStmtにも同様に付きうる（以前は`;`終端のみで
    本体を一切持てなかった）。"""
    usage_ast = parse_sysml_antlr("state def S { state s parallel { state s1; state s2; } }")
    usage_node = usage_ast["children"][-1]["children"][0]
    assert usage_node["type"] == "state_usage"
    assert usage_node["isParallel"] is True
    assert len(usage_node["children"]) == 2

    def_ast = parse_sysml_antlr("state def S1 parallel { state s1; }")
    def_node = def_ast["children"][-1]
    assert def_node["type"] == "state_def"
    assert def_node["isParallel"] is True

    plain_ast = parse_sysml_antlr("state def S { state s { state s1; } }")
    plain_node = plain_ast["children"][-1]["children"][0]
    assert plain_node["isParallel"] is False

    exhibit_ast = parse_sysml_antlr(
        "state def VehicleStates; "
        "part def P { exhibit state vehicleStates : VehicleStates parallel { state s1; } }"
    )
    exhibit_node = exhibit_ast["children"][-1]["children"][0]
    assert exhibit_node["type"] == "exhibit_state_usage"
    assert exhibit_node["isParallel"] is True
    assert len(exhibit_node["children"]) == 1


def test_antlr_hash_prefix_on_connection_end_member():
    """`end #cause cause1 : Causer1;`（CauseAndEffectExample.sysml）のように、
    `#Type`プレフィックス注釈はconnectionEndMember（`end`節）にも付きうる
    （2026-08-28、730件回帰チェックで発見。extend_hash_prefix_annotation_
    and_bare_ref_featureで他規則へは拡張済みだったがこの規則を見落として
    いた）。"""
    ast = parse_sysml_antlr(
        "part def Causer1; connection def C { end #cause cause1 : Causer1; }"
    )
    end_member = ast["children"][-1]["children"][0]
    assert end_member["type"] == "connection_end_member"
    assert end_member["prefixMetadata"] == ["cause"]
    assert end_member["endName"] == "cause1"
    assert end_member["type_name"] == "Causer1"


def test_antlr_connection_end_member_direct_reference_form():
    """`end #cause ::> a;`（CauseAndEffectExample.sysml）のように、
    connectionEndMemberには名前・型節を一切伴わず`#Type`プレフィックス
    直後に`::>`（`references`の記号形同義語）+参照先のみで構成される
    代替形もある（2026-08-28、発見）。"""
    ast = parse_sysml_antlr(
        "occurrence a; connection def C { end #cause ::> a; }"
    )
    end_member = ast["children"][-1]["children"][0]
    assert end_member["type"] == "connection_end_member"
    assert end_member["prefixMetadata"] == ["cause"]
    assert end_member["endName"] is None
    assert end_member["reference"] == "a"

    # 既存の名前付き形は変わらず動作する（reference=None）。
    named_ast = parse_sysml_antlr(
        "part def Causer1; connection def C { end #cause cause1 : Causer1; }"
    )
    named_member = named_ast["children"][-1]["children"][0]
    assert named_member["reference"] is None


def test_antlr_feature_usage_double_colon_gt_redefine():
    """`#cause causeA ::> a;`（CauseAndEffectExample.sysml）のように、型
    キーワードを一切伴わない裸のfeatureUsageは`::>`（`references`の記号形
    同義語）をredefine節としても使える（2026-08-28、発見。subsets/
    redefinesとは異なる"references"種別として区別する）。"""
    ast = parse_sysml_antlr("occurrence a; #cause causeA ::> a;")
    node = ast["children"][-1]
    assert node["type"] == "feature_usage"
    assert node["name"] == "causeA"
    assert node["prefixMetadata"] == ["cause"]
    assert node["redefines"] == [{"kind": "references", "target": "a"}]


def test_antlr_do_action_member_inline_send():
    """`do send new Sig(T.s.x) to p;`（StateTest.sysml）のように、`do`節が
    transitionを伴わず単独のdo-actionメンバーとしてインラインsendアクション
    を持てる（2026-08-28、730件回帰チェックで発見。実コーパスで10件超）。"""
    ast = parse_sysml_antlr(
        "attribute def Sig; part p; state def S { do send new Sig() to p; }"
    )
    do_action = ast["children"][-1]["children"][0]
    assert do_action["type"] == "do_action"
    assert do_action["action_reference"] is None
    assert do_action["send"]["to"] == "p"
    assert do_action["send"]["via"] is None
    assert do_action["send"]["payload"]["type"] == "new_instance"

    # 既存の`do action X;`（既存アクション参照）形は変わらず動作する。
    plain_ast = parse_sysml_antlr("action D; state def S { do action D; }")
    plain_do_action = plain_ast["children"][-1]["children"][0]
    assert plain_do_action["action_reference"] == "D"
    assert plain_do_action["send"] is None


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
                "isParallel": False,
                "children": [
                    {
                        "type": "state_def",
                        "name": "Sub",
                        "inheritance": None,
                        "isAbstract": False,
                        "isParallel": False,
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
    """キーワードは`decision`ではなく`decide`が正しい（公式文法
    sysml2-cli/grammar/sysml.pegの`KW_DECIDE`参照。2026-08-28、
    `then decide`未対応の調査中に発見した既存の誤りを修正）。"""
    ast = parse_sysml_antlr("action def Act { decide; decide D; }")
    children = ast["children"][0]["children"]
    assert children[0] == {"type": "decide_node", "name": None, "children": []}
    assert children[1] == {"type": "decide_node", "name": "D", "children": []}
    lint_ast(ast)  # クラッシュしないことを確認


def test_antlr_fork_join_merge_bare():
    ast = parse_sysml_antlr("action def Act { fork; join; merge; }")
    children = ast["children"][0]["children"]
    assert [c["type"] for c in children] == ["fork_node", "join_node", "merge_node"]
    assert all(c["name"] is None and c["children"] == [] for c in children)


def test_antlr_actionusagestmt_flowcontrolnode_prefix_metadata():
    """`#Security action a { #Security fork; }`（Metadata_valid.sysml(xpect)
    L38-39）のように、actionUsageStmt/flowControlNodeはどちらも`#Type`
    前置メタデータ注釈を持つことがある（従来どちらも未対応だった）。
    既存のメタデータ無し形が引き続き機能することも確認する。2026-08-29、
    add_actionusagestmt_flowcontrolnode_prefix_metadata対応中に発見。"""
    ast = parse_sysml_antlr(
        "part def P { #Security action a { #Security fork; } }"
    )
    action_node = ast["children"][0]["children"][0]
    assert action_node["type"] == "action_usage"
    assert action_node["prefixMetadata"] == ["Security"]
    fork_node = action_node["children"][0]
    assert fork_node["type"] == "fork_node"
    assert fork_node["prefixMetadata"] == ["Security"]

    # 既存のメタデータ無し形が引き続き機能することを確認する
    # （"prefixMetadata"キー自体が無いことも確認する）。
    plain_ast = parse_sysml_antlr("part def P { action a { fork; } }")
    plain_action = plain_ast["children"][0]["children"][0]
    plain_fork = plain_action["children"][0]
    assert "prefixMetadata" not in plain_action
    assert "prefixMetadata" not in plain_fork


def test_antlr_terminate_action_statement():
    """`terminate c1;`（ActionTest.sysml）・`then terminate;`（同、
    flowControlNodeと同じ`isThen`前置修飾子）・`terminate
    processor.workflowProcess;`・`terminate processor;`（Terminate Actions
    Example-2.sysml）・`action stop terminate;`（Terminate Actions
    Example-1.sysml、named action usage自体の本体が波括弧無しの
    `terminate;`単体）のように、TerminateActionUsage文が従来一切
    未実装だった。2026-08-29、730件ベースライン154件エラー要因分析で
    発見。"""
    ast = parse_sysml_antlr(
        "action def c { first start; then action c1 { terminate c1; } then terminate; }"
    )
    c1_node = ast["children"][0]["children"][-2]
    assert c1_node["name"] == "c1"
    assert c1_node["children"] == [{"type": "terminate_stmt", "target": "c1", "children": []}]
    then_terminate = ast["children"][0]["children"][-1]
    assert then_terminate == {"type": "terminate_stmt", "target": None, "children": [], "isThen": True}

    target_ast = parse_sysml_antlr(
        "action terminateProcessing { terminate processor.workflowProcess; terminate processor; }"
    )
    target_nodes = target_ast["children"][0]["children"]
    assert target_nodes[0]["target"] == "processor::workflowProcess"
    assert target_nodes[1]["target"] == "processor"

    bare_body_ast = parse_sysml_antlr("action def MonitoredActivity { action stop terminate; }")
    stop_node = bare_body_ast["children"][0]["children"][0]
    assert stop_node["type"] == "action_usage"
    assert stop_node["name"] == "stop"
    assert stop_node["children"] == [{"type": "terminate_stmt", "target": None, "children": []}]


def test_antlr_decision_with_nested_body():
    """control nodeのbodyはactionBodyElementの反復を許可し、代入・send action
    をネストできる（旧Lark実装のflow_node_bodyより実用上広い。AST_SCHEMA.md参照）。"""
    ast = parse_sysml_antlr("action def Act { decide D { x = 1; send p to q; } }")
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
        {"type": "send_action", "name": "snd", "payload": "x", "receiver": "y", "receiver_type": "to"},
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
    """param型の子はparamsへ、それ以外(decide_node/assignment_stmt等)は
    childrenへ分離される（旧Lark実装 action_def_stmt と同じ振る舞い。
    linter.pyのcontrol node/send actionチェックはchildrenしか見ないため必須）。"""
    ast = parse_sysml_antlr("action def Act { in item x : T; decide D; y = 2; }")
    action = ast["children"][0]
    assert action["params"] == [
        {
            "type": "param",
            "direction": "in",
            "is_item": True,
            "kind": "item",
            "visibility": None,
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
    assert [c["type"] for c in action["children"]] == ["decide_node", "assignment_stmt"]


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
        "after": None,
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
        "after": None,
        "actionName": "外界取得",
    }

    bare_ast = parse_sysml_antlr("action def Act { accept response : ConnectionResponse via client; }")
    assert bare_ast["children"][0]["children"][0] == {
        "type": "accept_action",
        "message": "response",
        "message_type": "ConnectionResponse",
        "port": "client",
        "after": None,
    }


def test_antlr_acceptactionstmt_named_body():
    """`action engineStarted accept engineStart: EngineStart { ... }`
    （3a-Function-based Behavior-1.sysml L102）のように、named形の
    acceptActionStmtは`;`終端の代わりに`do`/`action`キーワード無しの
    裸の`{ actionBodyElement* }`本体を直接持つこともある（従来`do
    action {...}`形しか無かった）。既存の`;`終端形が引き続き機能する
    ことも確認する。2026-08-29、add_acceptactionstmt_named_body対応中に
    発見。"""
    ast = parse_sysml_antlr(
        "action def A { action engineStarted accept engineStart: "
        "EngineStart { doc /* explanation */ } }"
    )
    node = ast["children"][0]["children"][0]
    assert node["type"] == "accept_action"
    assert node["message"] == "engineStart"
    assert node["message_type"] == "EngineStart"
    assert node["actionName"] == "engineStarted"
    assert [c["type"] for c in node["children"]] == ["documentation"]

    # 既存の`;`終端形が引き続き機能することを確認する
    # （"children"キー自体が無いことも確認する）。
    semi_ast = parse_sysml_antlr(
        "action def Act { accept response : ConnectionResponse via client; }"
    )
    semi_node = semi_ast["children"][0]["children"][0]
    assert "children" not in semi_node


def test_antlr_acceptactionstmt_trigger_clause():
    """`then accept at new Time::Iso8601DateTime("...");`・`then accept
    when b.f;`（ActionTest.sysml L19,22）のように、acceptActionStmtは
    `transitionTrigger`と同型の`at`/`when`トリガー節（式ベースの時刻/
    変化トリガー）を持つこともある（従来`message=qualifiedName`単純参照
    形しか無かった）。既存の単純参照形が引き続き機能することも確認する。
    2026-08-29、add_acceptactionstmt_trigger_clause対応中に発見。"""
    ast = parse_sysml_antlr(
        "action a1 { first start; then accept when b.f; "
        'then accept at new Time::Iso8601DateTime("2022-01-30T01:00:00Z"); }'
    )
    when_node, at_node = ast["children"][0]["children"][1], ast["children"][0]["children"][2]
    assert when_node["type"] == "accept_action"
    assert when_node["message"] is None
    assert when_node["trigger"] == {
        "kind": "trigger",
        "trigger_kind": "when",
        "expression": {"type": "name_ref", "reference": "b.f"},
    }

    assert at_node["trigger"]["trigger_kind"] == "at"
    assert at_node["trigger"]["expression"]["type"] == "new_instance"
    assert at_node["trigger"]["expression"]["name"] == "Time::Iso8601DateTime"

    # 既存の単純参照形が引き続き機能することを確認する
    # （"trigger"キー自体が無いことも確認する）。
    plain_ast = parse_sysml_antlr(
        "action def Act { accept response : ConnectionResponse via client; }"
    )
    plain_node = plain_ast["children"][0]["children"][0]
    assert plain_node["message"] == "response"
    assert "trigger" not in plain_node


def test_antlr_perform_action():
    ast = parse_sysml_antlr("action def Act { perform logFailure; }")
    assert ast["children"][0]["children"][0] == {
        "type": "perform_action", "reference": "logFailure", "redefines": [], "params": [], "children": [],
    }


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
    assert if_stmt["else"] == [
        {"type": "perform_action", "reference": "logFailure", "redefines": [], "params": [], "children": []}
    ]


def test_antlr_if_without_else_has_none_else():
    ast = parse_sysml_antlr("action def Act { if x > 0 { y = 1; } }")
    if_stmt = ast["children"][0]["children"][0]
    assert if_stmt["else"] is None


def test_antlr_ifactionstmt_else_if_chain_and_then_prefix():
    """`if i < 0 { ... } else if i == 0 { ... } else { ... }`
    （StructuredControlTest.sysml L9-13）のように、`else`直後に別の`if`を
    続けるelse-if連鎖が未対応だった（従来elseElementは波括弧本体のみ）。
    `then if monitor.charge < 100 { ... }`（Control Structures
    Example.sysml L19）のように、先頭に裸`then`を持つこともある。
    2026-08-29、730件ベースラインの154件エラー要因分析で発見。"""
    ast = parse_sysml_antlr(
        "action { if i < 0 { assign i := 0; } else if i == 0 "
        "{ assign i := 1; } else { assign i := i + 1; } }"
    )
    outer_if = ast["children"][0]["children"][0]
    assert outer_if["type"] == "if_stmt"
    nested_if = outer_if["else"][0]
    assert nested_if["type"] == "if_stmt"
    assert nested_if["condition"]["op"] == "=="
    assert nested_if["else"] == [
        {"type": "assignment_stmt", "name": "i", "operator": ":=", "value": {
            "type": "binary_expr", "op": "+",
            "left": {"type": "name_ref", "reference": "i"},
            "right": {"type": "literal", "literal_type": "int", "value": 1},
        }}
    ]

    then_ast = parse_sysml_antlr("action { assign i := 0; then if i > 0 { assign i := 1; } }")
    then_if = then_ast["children"][0]["children"][-1]
    assert then_if["type"] == "if_stmt"
    assert then_if["isThen"] is True


def test_antlr_actionusagestmt_until_clause_and_loop_prefix():
    """`then action aLoop while i > 0 { assign i := i - 1; } until b;`
    （StructuredControlTest.sysml L19-22）のように、named action usageの
    bodyの直後に継続条件`until <cond>`を持つことがある（従来この節が
    無かった）。`loop action charging { ... } until ...;`（Control
    Structures Example.sysml L14-24）のように、named action usage自体に
    `loop`前置修飾子が付くこともある。2026-08-29、730件ベースラインの
    154件エラー要因分析で発見。"""
    ast = parse_sysml_antlr(
        "action { then action aLoop while i > 0 { assign i := i - 1; } until b; }"
    )
    node = ast["children"][0]["children"][0]
    assert node["type"] == "action_usage"
    assert node["name"] == "aLoop"
    assert node["guard"] == {"type": "binary_expr", "op": ">", "left": {"type": "name_ref", "reference": "i"}, "right": {"type": "literal", "literal_type": "int", "value": 0}}
    assert node["untilGuard"] == {"type": "name_ref", "reference": "b"}
    assert node["isThen"] is True

    loop_ast = parse_sysml_antlr(
        "action { loop action charging { assign i := i - 1; } until b; }"
    )
    loop_node = loop_ast["children"][0]["children"][0]
    assert loop_node["type"] == "action_usage"
    assert loop_node["name"] == "charging"
    assert loop_node["isLoop"] is True
    assert loop_node["untilGuard"] == {"type": "name_ref", "reference": "b"}

    # 既存のwhileガードのみ（untilもloopも無い）形が引き続き機能し、
    # 各キー自体が無いことを確認する（回帰防止）。
    plain_ast = parse_sysml_antlr("action { action aLoop while i > 0 { assign i := i - 1; } }")
    plain_node = plain_ast["children"][0]["children"][0]
    assert "untilGuard" not in plain_node
    assert "isLoop" not in plain_node


def test_antlr_anonymous_while_and_loop_action_stmt():
    """`then while i > 0 { assign i := i - 1; }`・`loop { assign i := i -
    1; } until b;`（StructuredControlTest.sysml L24-30）のように、
    `action`キーワード・名前を一切伴わない匿名のwhile/loopアクションが
    未対応だった。2026-08-29、730件ベースラインの154件エラー要因分析で
    発見。"""
    while_ast = parse_sysml_antlr(
        "action { then while i > 0 { assign i := i - 1; } }"
    )
    while_node = while_ast["children"][0]["children"][0]
    assert while_node["type"] == "loop_stmt"
    assert while_node["kind"] == "while"
    assert while_node["guard"] == {"type": "binary_expr", "op": ">", "left": {"type": "name_ref", "reference": "i"}, "right": {"type": "literal", "literal_type": "int", "value": 0}}
    assert while_node["untilGuard"] is None
    assert while_node["isThen"] is True

    loop_ast = parse_sysml_antlr("action { loop { assign i := i - 1; } until b; }")
    loop_node = loop_ast["children"][0]["children"][0]
    assert loop_node["type"] == "loop_stmt"
    assert loop_node["kind"] == "loop"
    assert loop_node["guard"] is None
    assert loop_node["untilGuard"] == {"type": "name_ref", "reference": "b"}
    assert "isThen" not in loop_node


def test_antlr_forloop_action_stmt_and_bare_range_expression():
    """`for n : ScalarValues::Integer in (1, 2, 3) { assign i := i * n; }`
    （StructuredControlTest.sysml L32-34）のように、for-loopアクションが
    一切未対応だった。`for i in 1..powerProfile->size()-1 { ... }`
    （10d-Dynamics Analysis.sysml L65、型節省略）のように、括弧無しの
    裸の範囲式`a..b`も反復対象として使われる（既存の`(a..b)`という
    括弧付きrangeExprとは別に、加減算より弱く結合する位置に追加した）。
    2026-08-29、730件ベースラインの154件エラー要因分析で発見。"""
    ast = parse_sysml_antlr(
        "action { for n : ScalarValues::Integer in (1, 2, 3) "
        "{ assign i := i * n; } }"
    )
    node = ast["children"][0]["children"][0]
    assert node["type"] == "for_loop_stmt"
    assert node["name"] == "n"
    assert node["type_name"] == "ScalarValues::Integer"
    assert node["iterable"]["type"] == "sequence"
    assert len(node["iterable"]["elements"]) == 3
    assert len(node["children"]) == 1

    # 型節省略形が引き続き機能することを確認する。
    plain_ast = parse_sysml_antlr("action { for vehiclePower in powerProfile { assign i := i - 1; } }")
    plain_node = plain_ast["children"][0]["children"][0]
    assert plain_node["type"] == "for_loop_stmt"
    assert plain_node["name"] == "vehiclePower"
    assert plain_node["type_name"] is None

    # 括弧無しの裸の範囲式が反復対象として使われることを確認する。
    range_ast = parse_sysml_antlr("action { for i in 1..n-1 { assign i := i - 1; } }")
    range_node = range_ast["children"][0]["children"][0]
    assert range_node["iterable"]["type"] == "range_expr"
    assert range_node["iterable"]["lower"] == {"type": "literal", "literal_type": "int", "value": 1}
    assert range_node["iterable"]["upper"] == {
        "type": "binary_expr", "op": "-",
        "left": {"type": "name_ref", "reference": "n"},
        "right": {"type": "literal", "literal_type": "int", "value": 1},
    }

    # 既存の括弧付きrangeExprが引き続き機能することを確認する。
    paren_ast = parse_sysml_antlr("part def P { attribute a = (1..5); }")
    paren_value = paren_ast["children"][0]["children"][-1]["value"]
    assert paren_value == {
        "type": "range_expr",
        "lower": {"type": "literal", "literal_type": "int", "value": 1},
        "upper": {"type": "literal", "literal_type": "int", "value": 5},
        "children": [],
    }


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


def test_antlr_guardedtargetsuccession_action_prefix_target():
    """`decide; if (true) then action pathA; if (false) then action
    pathB; merge;`（dfa-coverage-advanced.sysml L210-213）のように、
    guardedTargetSuccessionStmt（波括弧なしの`if <式> then <参照>;`
    ガード付きsuccession短縮形）の遷移先参照の前に`action`キーワードが
    付くこともある（従来`target`はキーワード無しの裸参照のみ
    受理していた）。既存のキーワード無し形が引き続き機能することも
    確認する。2026-08-31、
    add_guardedtargetsuccession_action_prefix_target対応中に発見。"""
    ast = parse_sysml_antlr(
        "action def M { decide; if (true) then action pathA; merge; }"
    )
    decide, guarded, merge = ast["children"][0]["children"]
    assert guarded["type"] == "guarded_then_stmt"
    assert guarded["name"] == "pathA"

    # 既存のキーワード無し形が引き続き機能することを確認する。
    plain_ast = parse_sysml_antlr(
        "action def A { if x == 0 then A2; }"
    )
    plain_node = plain_ast["children"][0]["children"][0]
    assert plain_node["name"] == "A2"


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


def test_antlr_actionusagestmt_qualified_type():
    """`then action 'destroy connection of trailer to vehicle' :
    OccurrenceFunctions::destroy { ... }`（3c-Function-based
    Behavior-structure mod-1.sysml L41-42）のように、actionUsageStmtの
    型節は`::`修飾名を取ることもある（従来`ID | QUOTED_NAME`単体決め打ち
    だった）。既存のQUOTED_NAME単体型が引き続き機能することも確認する。
    2026-08-29、add_actionusagestmt_qualified_type対応中に発見。"""
    ast = parse_sysml_antlr(
        "action def A { then action 'destroy connection' : "
        "OccurrenceFunctions::destroy { } }"
    )
    node = ast["children"][0]["children"][0]
    assert node["type"] == "action_usage"
    assert node["name"] == "destroy connection"
    assert node["type_name"] == "OccurrenceFunctions::destroy"

    # 既存のQUOTED_NAME単体型が引き続き機能することを確認する。
    quoted_ast = parse_sysml_antlr(
        "action def A { action 'provide power': 'Provide Power' { } }"
    )
    quoted_node = quoted_ast["children"][0]["children"][0]
    assert quoted_node["type_name"] == "Provide Power"


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


def test_antlr_partusage_metadata_prefix_order():
    """`private #Classified #Security part z1;`（Metadata_valid.sysml(xpect)
    L35）のように、visibilityIndicatorがprefixMetadataAnnotation*より前に
    来る語順もある。partUsageは従来`prefixMetadataAnnotation*
    visibilityIndicator?`という逆順で、この入力だとpartDefの`part def`
    代替との曖昧性に負けて`missing 'def'`エラーになっていた。partDefと
    同じ`visibilityIndicator? variability? prefixMetadataAnnotation* ...`
    という順序に統一した。2026-08-29、
    add_partusage_metadata_prefix_order対応中に発見。"""
    ast = parse_sysml_antlr(
        "part def P { private #Classified #Security part z1; }"
    )
    node = ast["children"][0]["children"][0]
    assert node["type"] == "part_instance"
    assert node["name"] == "z1"
    assert node["prefixMetadata"] == ["Classified", "Security"]
    assert node["visibility"] == "private"

    # 既存の`variation part ...`（variabilityあり、metadata無し）が
    # 引き続き機能することを確認する。
    variation_ast = parse_sysml_antlr(
        "part def P { variation part transmission : Transmission[1] { } }"
    )
    variation_node = variation_ast["children"][0]["children"][0]
    assert variation_node["name"] == "transmission"
    assert variation_node["variability"] == "variation"


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


def test_antlr_requirement_def_short_name():
    """`requirement def <'FLR-R001'> PropellantLoadingRequirement { ... }`
    （FunctionalRequirementsPackage.sysml）のように、requirementDefにも
    ShortName注釈（山括弧の短縮名）がある。requirementUsageへは
    P1-1で追加済みだったが、requirementDefへの追加を見落としていた
    （2026-08-28、730件回帰チェックで発見）。"""
    ast = parse_sysml_antlr("requirement def <'FLR-R001'> PropellantLoadingRequirement;")
    node = ast["children"][-1]
    assert node["type"] == "requirement_def"
    assert node["shortName"] == "'FLR-R001'"
    assert node["name"] == "PropellantLoadingRequirement"

    plain_ast = parse_sysml_antlr("requirement def R;")
    plain_node = plain_ast["children"][-1]
    assert plain_node["shortName"] is None


def test_antlr_nested_part_def_in_part_body():
    """`part def Building { part def Floor { ... } }`
    （smart-home-complex.sysml）のように、partDef自体がstateDefと同様に
    partBodyElement内にネストして書ける（2026-08-28、730件回帰
    チェックで発見。partBodyElementのリストにpartDef自体が
    登録されていなかった）。"""
    ast = parse_sysml_antlr("part def Building { part def Floor { part x : X; } }")
    outer = ast["children"][-1]
    assert outer["type"] == "part_def"
    assert outer["name"] == "Building"
    inner = outer["children"][-1]
    assert inner["type"] == "part_def"
    assert inner["name"] == "Floor"
    assert inner["children"][-1]["type"] == "part_instance"


def test_antlr_nested_package_def_in_part_body():
    """`part def B { package P { } }`（PartTest.sysml L23）のように、
    packageDef自体もpartDef/occurrenceDef/requirementDef/interfaceDefと
    同型にpartBodyElement内へネストして書ける（2026-08-29、
    add_direction_prefix_to_featureusage対応中に連鎖的に発見）。"""
    ast = parse_sysml_antlr("part def B { package P { } }")
    outer = ast["children"][-1]
    assert outer["type"] == "part_def"
    assert outer["name"] == "B"
    inner = outer["children"][-1]
    assert inner["type"] == "package"
    assert inner["name"] == "P"
    assert inner["children"] == []


def test_antlr_part_usage_multiplicity_before_type_and_default():
    """`part missions[1..*] : Mission;`（CoSMAPackage.sysml）のように、
    partUsageも名前直後の多重度→型節という順序（portUsageのpreMult/
    postMultと同じ設計）を取りうる。`part subcomponents : MassedComponent
    [*] default null;`のように、値代入とは別のdefault節（既定値）も
    取りうる（2026-08-28、730件回帰チェックで発見）。"""
    pre_ast = parse_sysml_antlr("part def Mission; part def P { part missions[1..*] : Mission; }")
    pre_node = pre_ast["children"][-1]["children"][-1]
    assert pre_node["type_name"] == "Mission"
    assert pre_node["multiplicity"]["size"]["max"] == "*"

    default_ast = parse_sysml_antlr(
        "part def MassedComponent; part def P { part subcomponents : MassedComponent [*] default null; }"
    )
    default_node = default_ast["children"][-1]["children"][-1]
    assert default_node["type_name"] == "MassedComponent"
    assert default_node["multiplicity"]["size"]["max"] == "*"
    assert default_node["defaultValue"] is not None


def test_antlr_action_usage_multiplicity_before_type():
    """`action subfunctions[*] : Function :>> subactions;`
    （CoSMAPackage.sysml）のように、actionUsageStmtも名前直後の多重度→
    型節という順序を取りうる（partUsage/portUsageと同じpreMult/postMult
    設計、2026-08-28、730件回帰チェックで発見）。"""
    ast = parse_sysml_antlr(
        "action def Function; action def A { action subfunctions[*] : Function :>> subactions; }"
    )
    node = ast["children"][-1]["children"][-1]
    assert node["type"] == "action_usage"
    assert node["type_name"] == "Function"
    assert node["multiplicity"]["size"]["max"] == "*"
    assert node["redefines"] == [{"kind": "redefines", "target": "subactions"}]


def test_antlr_bare_nonunique_ordered_modifier():
    """`attribute ratio : RatioValue nonunique :> Quantities::scalarQuantities;`
    （CoSMAQuantitiesAndUnitsPackage.sysml）のように、`nonunique`/`ordered`
    修飾子は明示的な多重度ブラケット`[...]`を伴わない裸の形でも使える
    （2026-08-28、730件回帰チェックで発見。以前はmultiplicitySpecが
    必ず`[...]`ブラケットを要求していた）。"""
    ast = parse_sysml_antlr(
        "attribute def RatioValue; attribute def A { attribute ratio : RatioValue nonunique; }"
    )
    node = ast["children"][-1]["children"][-1]
    assert node["multiplicity"]["size"] is None
    assert node["multiplicity"]["is_unique"] is False
    assert node["multiplicity"]["is_ordered"] is False

    bracket_ast = parse_sysml_antlr(
        "attribute def RatioValue; attribute def A { attribute ratio : RatioValue[1..*] ordered; }"
    )
    bracket_node = bracket_ast["children"][-1]["children"][-1]
    assert bracket_node["multiplicity"]["size"] == {"min": 1, "max": "*"}
    assert bracket_node["multiplicity"]["is_ordered"] is True


def test_antlr_istype_hastype_classification_expression():
    """`sys istype PowerProvider`（CalculationsPackage.sysml）のように、
    KerMLの分類判定式演算子`istype`/`hastype`が式文法に実装されて
    いなかった（2026-08-28、730件回帰チェックで発見）。QUOTED_NAME型名
    （`engine istype '6CylEngine'`）も取りうる。"""
    ast = parse_sysml_antlr(
        "calc def C { in sys; return : Boolean = sys istype PowerProvider; }"
    )
    calc = ast["children"][-1]
    return_param = next(
        c for c in calc["children"] if c.get("type") == "calc_parameter" and c.get("direction") == "return"
    )
    expr = return_param["value"]
    assert expr["type"] == "classification_expr"
    assert expr["op"] == "istype"
    assert expr["type_name"] == "PowerProvider"

    hastype_ast = parse_sysml_antlr(
        "calc def C { in engine; return : Boolean = engine hastype 'Quoted Type'; }"
    )
    hastype_return = hastype_ast["children"][-1]["children"][-1]
    hastype_expr = hastype_return["value"]
    assert hastype_expr["type"] == "classification_expr"
    assert hastype_expr["op"] == "hastype"
    assert hastype_expr["type_name"] == "Quoted Type"


def test_antlr_hash_prefix_metadata_annotation_extended():
    """`#Type`プレフィックス注釈（PrefixMetadataMember）はdependencyStmt
    にしか実装されておらず、part/attribute/connect/connection/port/
    requirement/enum/metadataにも付きうる（2026-08-28、730件回帰チェックで
    発見。P0-4の継続）。"""
    part_ast = parse_sysml_antlr(
        "part def Batmobile; part def P { #system part bm1 : Batmobile; }"
    )
    part_node = part_ast["children"][-1]["children"][-1]
    assert part_node["prefixMetadata"] == ["system"]

    attr_ast = parse_sysml_antlr("part def P { #mop attribute totalPower = 1; }")
    attr_node = attr_ast["children"][-1]["children"][-1]
    assert attr_node["prefixMetadata"] == ["mop"]

    connect_ast = parse_sysml_antlr("part def P { #multicausation connect a to b; }")
    connect_node = connect_ast["children"][-1]["children"][-1]
    assert connect_node["prefixMetadata"] == ["multicausation"]

    connection_bare_ast = parse_sysml_antlr("part def P { #derivation connection { } }")
    connection_bare_node = connection_bare_ast["children"][-1]["children"][-1]
    assert connection_bare_node["prefixMetadata"] == ["derivation"]

    connection_def_ast = parse_sysml_antlr("#multicausation connection def MultiCauseEffect;")
    connection_def_node = connection_def_ast["children"][-1]
    assert connection_def_node["prefixMetadata"] == ["multicausation"]

    port_def_ast = parse_sysml_antlr("#service port def ServiceDiscovery;")
    port_def_node = port_def_ast["children"][-1]
    assert port_def_node["prefixMetadata"] == ["service"]

    requirement_usage_ast = parse_sysml_antlr("#goal requirement deliverPayload;")
    requirement_usage_node = requirement_usage_ast["children"][-1]
    assert requirement_usage_node["prefixMetadata"] == ["goal"]

    enum_def_ast = parse_sysml_antlr("#Security enum def ClassificationLevel;")
    enum_def_node = enum_def_ast["children"][-1]
    assert enum_def_node["prefixMetadata"] == ["Security"]

    metadata_def_ast = parse_sysml_antlr(
        "metadata def Classified; metadata def Security; "
        "part def P { ref z { #Security #Classified metadata Classified; } }"
    )
    metadata_usage_node = metadata_def_ast["children"][-1]["children"][-1]["children"][-1]
    assert metadata_usage_node["prefixMetadata"] == ["Security", "Classified"]


def test_antlr_bare_feature_usage_at_package_and_state_level():
    """`ref annotatedRef { metadata Important { ... } }`
    （comprehensive_data_loss.sysml）のように、型キーワード（part/item等）を
    伴わない裸のfeatureUsageはpackage直下にも書ける。`ref vehicle :
    Vehicle;`（VehicleModel.sysml）のように、state def本体内にも書ける
    （2026-08-28、730件回帰チェックで発見。以前はpartBodyElement内にしか
    登録されておらず、どちらの位置でも構文エラーになっていた）。"""
    package_ast = parse_sysml_antlr(
        "metadata def Important; ref annotatedRef { metadata Important; }"
    )
    package_node = package_ast["children"][-1]
    assert package_node["type"] == "feature_usage" or package_node.get("name") == "annotatedRef"

    state_ast = parse_sysml_antlr("part def Vehicle; state def S { ref vehicle : Vehicle; }")
    state_node = state_ast["children"][-1]["children"][-1]
    assert state_node["name"] == "vehicle"
    assert state_node["type_name"] == "Vehicle"


def test_antlr_attribute_usage_ref_modifier():
    """`derived constant ref attribute y :> x;`（PartTest.sysml）のように、
    attributeUsageにも他のusage系規則と同じ`ref`修飾子が付きうる
    （2026-08-28、730件回帰チェックで発見。それまでisRefが未実装だった）。"""
    ast = parse_sysml_antlr(
        "part def P { attribute x; derived constant ref attribute y :> x; }"
    )
    node = ast["children"][-1]["children"][-1]
    assert node["isRef"] is True
    assert node["isDerived"] is True
    assert node["isConstant"] is True


def test_antlr_attributeusage_triple_colon_gt_redefine():
    """`attribute ::> m = ms.totalMass;`（CalculationTest.sysml L14）の
    ように、attributeUsageのredefineトークン一覧に`::>`（featureUsage/
    connectionEndMember等には既にある`references`の記号形同義語）が
    欠けていた。既存の`:>>`形が引き続き機能することも確認する。
    2026-08-29、add_attributeusage_triple_colon_gt_redefine対応中に発見。"""
    ast = parse_sysml_antlr(
        "calc def C { attribute ::> m = ms.totalMass; }"
    )
    node = ast["children"][0]["children"][0]
    assert node["type"] == "attribute_usage"
    assert node["redefines"] == [{"kind": "references", "target": "m"}]
    assert node["value"] == {"type": "name_ref", "reference": "ms.totalMass"}

    # 既存の`:>>`形が引き続き機能することを確認する。
    plain_ast = parse_sysml_antlr(
        "part def P { attribute unit :>> UnitPowerFactor::unit = 1; }"
    )
    plain_node = plain_ast["children"][0]["children"][0]
    assert plain_node["redefines"] == [{"kind": "redefines", "target": "UnitPowerFactor::unit"}]


def test_antlr_item_usage_ref_before_individual_order():
    """`ref individual item :>> operator : Alice;`（Boeing.sysml、Individuals
    and Time Slices.sysml）のように、`ref`が`individual`より前に来る語順も
    実在する（既存の`individual ... ref`という語順とは逆、2026-08-28、
    730件回帰チェックで発見）。"""
    ast = parse_sysml_antlr(
        "part def Alice; part def P { ref individual item :>> operator : Alice; }"
    )
    node = ast["children"][-1]["children"][-1]
    assert node["type"] == "item_usage"
    assert node["isRef"] is True
    assert node["isIndividual"] is True

    reversed_ast = parse_sysml_antlr(
        "part def Alice; part def P { individual ref item :>> operator : Alice; }"
    )
    reversed_node = reversed_ast["children"][-1]["children"][-1]
    assert reversed_node["isRef"] is True
    assert reversed_node["isIndividual"] is True


def test_antlr_itemusage_prefix_metadata():
    """`#fmea item 'Glucose Meter in Use' : 'Glucose FMEA Item' { ... }`
    （14c-Language Extensions.sysml L190）のように、itemUsageは`#Type`
    前置メタデータ注釈を持つことがある（itemDef/occurrenceUsageは既に
    対応済みだが、itemUsage自体には無かった）。visibilityIndicatorの
    直後という、itemDefと同じ順序に置く必要がある（順序がずれると
    itemDefの`item def`代替とのあいまい性に負ける、partUsageの
    モディファイア順序修正と同型の注意点）。既存のメタデータ無し形が
    引き続き機能することも確認する。2026-08-31、
    add_itemusage_prefix_metadata対応中に発見。"""
    ast = parse_sysml_antlr(
        "package P { #fmea item 'Glucose Meter in Use' : "
        "'Glucose FMEA Item' { } }"
    )
    node = ast["children"][0]
    assert node["type"] == "item_usage"
    assert node["name"] == "Glucose Meter in Use"
    assert node["type_name"] == "Glucose FMEA Item"
    assert node["prefixMetadata"] == ["fmea"]

    # 既存のメタデータ無し形が引き続き機能することを確認する。
    plain_ast = parse_sysml_antlr("package P { item x : A; }")
    plain_node = plain_ast["children"][0]
    assert plain_node["prefixMetadata"] == []


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


def test_antlr_assume_keyword_and_redefine_on_assert_constraint_usage():
    """`assume constraint fuelConstraint { ... }`（8-Requirements.sysml）・
    `require constraint c1 :>> c;`（RequirementTest.sysml）のように、
    assertConstraintUsageは`assert`/`require`に加えて`assume`キーワードも
    使え、redefine節（複数可）も持ちうる（2026-08-28、730件回帰チェックで
    発見。以前は`assume`キーワード自体・redefine節のいずれも未対応
    だった）。`#goal requirement { assume #goal constraint ...; }`
    （RequirementMetadataExample.sysml）のような`#Type`プレフィックス注釈
    （`assume`/`require`キーワードの直後、`constraint`キーワードの前に
    付く）も持つ。"""
    assume_ast = parse_sysml_antlr(
        "requirement def R { attribute def C; assume constraint c1 : C; }"
    )
    assume_node = assume_ast["children"][-1]["children"][-1]["children"][0]
    assert assume_node["type"] == "assert_constraint_usage"
    assert assume_node["kind"] == "assume"
    assert assume_node["name"] == "c1"
    assert assume_node["type_name"] == "C"

    redefine_ast = parse_sysml_antlr(
        "requirement def R2 { constraint c; } "
        "requirement def R :> R2 { require constraint c1 :>> c; }"
    )
    redefine_node = redefine_ast["children"][-1]["children"][-1]["children"][0]
    assert redefine_node["kind"] == "require"
    assert redefine_node["redefines"] == [{"kind": "redefines", "target": "c"}]

    prefix_ast = parse_sysml_antlr(
        "metadata def goal; requirement def R { assume #goal constraint payloadMassLimit; }"
    )
    prefix_node = prefix_ast["children"][-1]["children"][-1]["children"][0]
    assert prefix_node["kind"] == "assume"
    assert prefix_node["prefixMetadata"] == ["goal"]
    assert prefix_node["name"] == "payloadMassLimit"


def test_antlr_assert_bare_name_constraint_omission():
    """`assert mc { in totalMass = m; in partMasses = (eng.m, trans.m); }`
    （MassConstraintExample.sysml）・`assert not massLimitation { :>>
    mass = vehicle3.mass; ... }`（ConstraintTest.sysml）のように、継承した
    制約フィーチャーを暗黙に再定義する場合、`assert`は`constraint`
    キーワード自体を省略した`assert <name> { パラメータ束縛 }`形も広く
    使われる（従来`assertConstraintUsage`は`constraint`キーワードを
    必須としていた）。`require`/`assume`は同型の省略形が別途`requireUsage`
    として既に存在するため、この省略形は`assert`のみに限定する。
    2026-08-29、730件ベースライン154件エラー要因分析で発見。"""
    ast = parse_sysml_antlr(
        "part def V4 { assert mc { in totalMass = m; in partMasses = (eng.m, trans.m); } }"
    )
    node = ast["children"][0]["children"][0]["children"][0]
    assert node["type"] == "assert_constraint_usage"
    assert node["kind"] == "assert"
    assert node["is_negated"] is False
    assert node["name"] == "mc"
    assert node["type_name"] == ""
    assert len(node["children"]) == 2

    negated_ast = parse_sysml_antlr(
        "part def V4b { assert not massLimitation { :>> mass = vehicle3.mass; :>> massLimit = vehicle4.mass; } }"
    )
    negated_node = negated_ast["children"][0]["children"][0]["children"][0]
    assert negated_node["is_negated"] is True
    assert negated_node["name"] == "massLimitation"

    # 既存の`assert constraint`明示形・`require`/`assume`のconstraint省略形
    # （requireUsage）が回帰しないことを確認する。
    explicit_ast = parse_sysml_antlr("part def V { assert constraint { mass == 1; } }")
    explicit_node = explicit_ast["children"][0]["children"][0]["children"][0]
    assert explicit_node["type"] == "assert_constraint_usage"
    assert explicit_node["name"] is None

    require_ast = parse_sysml_antlr("part def V { require viewpointSatisfactions { ref x; } }")
    require_node = require_ast["children"][0]["children"][0]
    assert require_node["type"] == "require_usage"
    assert require_node["name"] == "viewpointSatisfactions"


def test_antlr_require_usage_assume_keyword_multiplicity_and_prefix():
    """`assume c1 [0..*];`（RequirementTest.sysml）のように、requireUsage
    （`constraint`キーワードを伴わない裸参照形）は`require`だけでなく
    `assume`キーワードも使え、多重度（`[...]`）も持ちうる（2026-08-28、
    730件回帰チェックで発見）。`require #goal vehicleMassRequirement;`
    （RequirementMetadataExample.sysml）のような`#Type`プレフィックス注釈
    も持つ。"""
    ast = parse_sysml_antlr(
        "requirement def R { requirement c1; assume c1 [0..*]; }"
    )
    node = ast["children"][-1]["children"][-1]
    assert node["type"] == "require_usage"
    assert node["kind"] == "assume"
    assert node["name"] == "c1"
    assert node["multiplicity"]["size"] == {"min": 0, "max": "*"}

    prefix_ast = parse_sysml_antlr(
        "metadata def goal; requirement vehicleMassRequirement; "
        "requirement def R { require #goal vehicleMassRequirement; }"
    )
    prefix_node = prefix_ast["children"][-1]["children"][-1]
    assert prefix_node["kind"] == "require"
    assert prefix_node["prefixMetadata"] == ["goal"]


def test_antlr_requireusage_feature_chain_target():
    """`require vehicleSpecification.vehicleFuelEconomyRequirements;`
    （VehicleModel_2_Simplified.sysml L314）・`require vehicleSpecification
    ::vehicleFuelEconomyRequirements;`（VehicleModel.sysml）のように、
    requireUsageの対象名は単一識別子ではなく`.`/`::`区切りのfeature
    chainを取ることもある（従来`simpleName`決め打ちだった）。既存の
    単一識別子形が引き続き機能することも確認する。2026-08-29、
    add_requireusage_feature_chain_target対応中に発見。"""
    ast = parse_sysml_antlr(
        "requirement def R { require vehicleSpecification."
        "vehicleFuelEconomyRequirements; }"
    )
    node = ast["children"][0]["children"][0]
    assert node["type"] == "require_usage"
    assert node["name"] == "vehicleSpecification::vehicleFuelEconomyRequirements"

    qualified_ast = parse_sysml_antlr(
        "requirement def R { require vehicleSpecification::"
        "vehicleFuelEconomyRequirements; }"
    )
    qualified_node = qualified_ast["children"][0]["children"][0]
    assert qualified_node["name"] == "vehicleSpecification::vehicleFuelEconomyRequirements"

    # 既存の単一識別子形が引き続き機能することを確認する。
    single_ast = parse_sysml_antlr("requirement def R { require c1; }")
    single_node = single_ast["children"][0]["children"][0]
    assert single_node["name"] == "c1"


def test_antlr_performactionstmt_bare_form_redefine_equals_value():
    """`perform action2:>> action2 = ActionTree::action0.action2;`
    （VehicleModel_2_Simplified.sysml）のように、performActionStmtの
    裸参照形（`action`キーワード無し）にも、`action`キーワード付き形と
    同様にredefine節の後に`= value`値代入が続くことがある（従来この
    代替にだけ移植されていなかった）。既存のredefineのみ形（値代入
    無し）が引き続き機能することも確認する。2026-08-29、
    add_requireusage_feature_chain_target対応中に連鎖的に発見。"""
    ast = parse_sysml_antlr(
        "action def A { perform action2:>> action2 = "
        "ActionTree::action0.action2; }"
    )
    node = ast["children"][0]["children"][0]
    assert node["type"] == "perform_action"
    assert node["reference"] == "action2"
    assert node["redefines"] == [{"kind": "redefines", "target": "action2"}]
    assert node["value"] == {
        "type": "name_ref",
        "reference": "ActionTree::action0::action2",
        "segments": [("ActionTree", None), ("action0", "::"), ("action2", ".")],
    }

    # 既存のredefineのみ形（値代入無し）が引き続き機能することを確認する
    # （"value"キー自体が無いことも確認する）。
    plain_ast = parse_sysml_antlr(
        "action def A { perform GroundSupportSystem::performCrewIngress "
        ":>> performCrewIngress; }"
    )
    plain_node = plain_ast["children"][0]["children"][0]
    assert "value" not in plain_node


def test_antlr_nary_connect_and_double_colon_gt_references():
    """`#multicausation connect ( cause1 ::> causer1, cause2 ::> causer2,
    effect1 ::> effected1, effect2 ::> effected2 );`
    （CauseAndEffectExample.sysml）のように、connectUsage/connectionUsageは
    2項の`A to B`形に加えて、括弧で囲んだ3項以上のend列（n元connect）も
    持ちうる（2026-08-28、730件回帰チェックで発見）。`::>`は`references`
    キーワードの記号形の同義語（connectorEndPathで対応）。"""
    nary_ast = parse_sysml_antlr(
        "part def P { connect ( cause1 ::> causer1, cause2 ::> causer2, "
        "effect1 ::> effected1 ); }"
    )
    nary_node = nary_ast["children"][-1]["children"][0]
    assert nary_node["type"] == "connect_usage"
    assert nary_node["from_end"] is None
    assert nary_node["to_end"] is None
    assert nary_node["ends"] == [
        {"type": "connector_end", "declared_name": "cause1", "reference": "causer1", "segments": [("causer1", None)]},
        {"type": "connector_end", "declared_name": "cause2", "reference": "causer2", "segments": [("causer2", None)]},
        {"type": "connector_end", "declared_name": "effect1", "reference": "effected1", "segments": [("effected1", None)]},
    ]

    plain_refs_ast = parse_sysml_antlr(
        "part def P { connect ( causeA, causeB, effectC ); }"
    )
    plain_refs_node = plain_refs_ast["children"][-1]["children"][0]
    assert plain_refs_node["ends"] == [
        {"type": "connector_end", "declared_name": None, "reference": "causeA", "segments": [("causeA", None)]},
        {"type": "connector_end", "declared_name": None, "reference": "causeB", "segments": [("causeB", None)]},
        {"type": "connector_end", "declared_name": None, "reference": "effectC", "segments": [("effectC", None)]},
    ]

    # 既存の2項`A to B`形も変わらず動作する。
    binary_ast = parse_sysml_antlr("part def P { connect a to b; }")
    binary_node = binary_ast["children"][-1]["children"][0]
    assert binary_node["ends"] is None
    assert binary_node["from_end"]["reference"] == "a"
    assert binary_node["to_end"]["reference"] == "b"

    typed_nary_ast = parse_sysml_antlr(
        "connection def MultiCauseEffect; "
        "part def P { connection : MultiCauseEffect connect ( cause1 ::> causer1, cause2 ::> causer2 ); }"
    )
    typed_nary_node = typed_nary_ast["children"][-1]["children"][0]
    assert typed_nary_node["type"] == "connection_usage"
    assert typed_nary_node["ends"] == [
        {"type": "connector_end", "declared_name": "cause1", "reference": "causer1", "segments": [("causer1", None)]},
        {"type": "connector_end", "declared_name": "cause2", "reference": "causer2", "segments": [("causer2", None)]},
    ]


def test_antlr_connect_usage_with_body():
    """`#causation connect b to d { @CausationMetadata { isNecessary =
    true; probability = 0.1; } }`（CauseAndEffectExample.sysml）のように、
    connectUsageは`;`終端だけでなくbody（`{ ... }`）も持ちうる
    （2026-08-28、発見。以前は`;`終端のみだった）。"""
    ast = parse_sysml_antlr(
        "metadata def CausationMetadata; "
        "part def P { part a; part d; "
        "connect a to d { @CausationMetadata { isNecessary = true; } } }"
    )
    node = ast["children"][-1]["children"][-1]
    assert node["type"] == "connect_usage"
    assert node["from_end"]["reference"] == "a"
    assert node["to_end"]["reference"] == "d"
    assert len(node["children"]) == 1
    assert node["children"][0]["type"] == "metadata_usage"

    # 既存の`;`終端形も変わらず動作する。
    plain_ast = parse_sysml_antlr("part def P { part a; part b; connect a to b; }")
    plain_node = plain_ast["children"][-1]["children"][-1]
    assert plain_node["children"] == []


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
    assert children[0] == {"type": "entry_action", "kind": "entry", "action_reference": None, "type_name": None, "redefines": [], "assign": None, "children": []}
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
        "isParallel": False,
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
        "type_name": None, "redefines": [{"kind": "redefines", "target": "entry"}],
        "assign": None, "children": [],
    }
    assert do == {
        "type": "do_action", "kind": "do", "action_reference": "doAction",
        "type_name": "Action", "redefines": [{"kind": "redefines", "target": "do"}],
        "send": None, "assign": None, "children": [],
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
        "type": "flow_usage", "name": None, "item_type": "X", "from_end": "a", "to_end": "b", "children": [],
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
        "name": None,
        "item_type": None,
        "from_end": "外界の映像を撮る::映像",
        "to_end": "前方障害物との距離を推定する::カメラ映像",
        "children": [],
    }

    from_ast = parse_sysml_antlr("part def P { flow from a to b; }")
    from_node = from_ast["children"][0]["children"][-1]
    assert from_node == {
        "type": "flow_usage", "name": None, "item_type": None, "from_end": "a", "to_end": "b", "children": [],
    }

    bare_ast = parse_sysml_antlr("part def P { flow; }")
    bare_node = bare_ast["children"][0]["children"][-1]
    assert bare_node == {
        "type": "flow_usage", "name": None, "item_type": None, "from_end": None, "to_end": None, "children": [],
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
        "name": None,
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
        "from_end": {"type": "connector_end", "declared_name": None, "reference": "A::B::C", "segments": [("A", None), ("B", "::"), ("C", ".")]},
        "to_end": {"type": "connector_end", "declared_name": None, "reference": "D::E", "segments": [("D", None), ("E", ".")]},
        "ends": None,
        "prefixMetadata": [],
        "children": [],
    }

    plain_connect_ast = parse_sysml_antlr("part def P { connect end1 references a.b to c.d; }")
    plain_connect_node = plain_connect_ast["children"][0]["children"][-1]
    assert plain_connect_node == {
        "type": "connect_usage",
        "from_end": {"type": "connector_end", "declared_name": "end1", "reference": "a::b", "segments": [("a", None), ("b", ".")]},
        "to_end": {"type": "connector_end", "declared_name": None, "reference": "c::d", "segments": [("c", None), ("d", ".")]},
        "ends": None,
        "prefixMetadata": [],
        "children": [],
    }


def test_antlr_connectusage_endpoint_multiplicity():
    """`connect [0..1] lugBoltJoints to [1] wheel.w.mountingHoles;`
    （Connections Example.sysml L38-39）のように、connectUsage（キー
    ワード無し`connect`文）の各エンドポイントの前に多重度`[mult]`が
    付くこともある（従来2項形にはエンドポイント側の多重度ラベルが
    無かった）。2026-08-29、
    add_connectionendmember_leading_multiplicity対応中に連鎖的に発見。"""
    ast = parse_sysml_antlr(
        "part def P { connect [0..1] lugBoltJoints to [1] wheel.w.mountingHoles; }"
    )
    node = ast["children"][0]["children"][0]
    assert node["type"] == "connect_usage"
    assert node["from_multiplicity"]["size"] == {"min": 0, "max": 1}
    assert node["to_multiplicity"]["size"] == {"min": 1, "max": 1}
    assert node["from_end"]["reference"] == "lugBoltJoints"
    assert node["to_end"]["reference"] == "wheel::w::mountingHoles"

    # 既存の多重度無し形が引き続き機能し、"from_multiplicity"/
    # "to_multiplicity"キー自体が無いことを確認する（回帰防止）。
    plain_ast = parse_sysml_antlr("part def P { connect a to b; }")
    plain_node = plain_ast["children"][0]["children"][0]
    assert "from_multiplicity" not in plain_node
    assert "to_multiplicity" not in plain_node


def test_antlr_flowusage_prekind_redefine_before_type_or_from_to():
    """`flow :>> publish_message: Transfers::MessageTransfer { ... }`・
    `flow :>> publish_message from producer... to server... { ... }`
    （ServerSequenceOutsideRealization-2/3.sysml、
    ServerSequenceRealization-2/3.sysml）のように、flowUsageの名前省略
    代替（型付き代替・from/to代替の両方）は`postKind`（型節後の
    redefine）しか持たず、名前の代わりに型節前にredefineターゲットを
    置く`preKind`（attributeUsage等と同型）が無かった。型付き代替の
    型節が`::`修飾名を取れなかった（同じ行の反例、`ID`単体のみだった）
    ことも併せて対応する。2026-08-29、
    add_flow_end_member_triple_colon_gt_operator対応中に連鎖的に発見。"""
    typed_ast = parse_sysml_antlr(
        "flow :>> publish_message: Transfers::MessageTransfer { }"
    )
    typed_node = typed_ast["children"][0]
    assert typed_node["type"] == "flow_usage"
    assert typed_node["name"] is None
    assert typed_node["type_name"] == "Transfers::MessageTransfer"
    assert typed_node["redefines"] == [
        {"kind": "redefines", "target": "publish_message"}
    ]

    from_to_ast = parse_sysml_antlr(
        "flow :>> publish_message from producer.a to server.b { }"
    )
    from_to_node = from_to_ast["children"][0]
    assert from_to_node["type"] == "flow_usage"
    assert from_to_node["from_end"] == "producer::a"
    assert from_to_node["to_end"] == "server::b"
    assert from_to_node["redefines"] == [
        {"kind": "redefines", "target": "publish_message"}
    ]

    # 既存のpreKindを伴わない裸のfrom/to形（"redefines"キー自体が無い）が
    # 引き続き機能することを確認する。
    plain_ast = parse_sysml_antlr("part def P { flow from a to b; }")
    plain_node = plain_ast["children"][0]["children"][-1]
    assert "redefines" not in plain_node


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
        "type": "perform_action", "name": None, "type_name": None, "multiplicity": None,
        "redefines": [], "params": [], "children": [],
    }

    bare_ast = parse_sysml_antlr("part def P { perform y; }")
    bare_node = bare_ast["children"][0]["children"][-1]
    assert bare_node == {
        "type": "perform_action", "reference": "y", "redefines": [], "params": [], "children": [],
    }


def test_antlr_portusage_performaction_redefine_assign():
    """`port fuelCmdPort:>>fuelCmdPort=vehicle_1.fuelCmdPort;`
    （VehicleModel_2_Simplified.sysml）・`port leftWheelToRoadPort :>
    wheelToRoadPort = wheelToRoadPort#(1);`（2a-Parts Interconnection.sysml）・
    `perform action :>> doXorY = doX;`（7a1-Variant Configuration...-a.sysml）
    のように、attributeUsageには既にあるredefine節後の`= value`値代入が
    portUsage・performActionStmt(action形)には移植されていなかった。
    2026-08-29、730件ベースライン154件エラー要因分析で発見。"""
    port_ast = parse_sysml_antlr(
        "part def P { port fuelCmdPort:>>fuelCmdPort=vehicle_1.fuelCmdPort; }"
    )
    port_node = port_ast["children"][0]["children"][-1]
    assert port_node["type"] == "port_usage"
    assert port_node["redefines"] == [{"kind": "redefines", "target": "fuelCmdPort"}]
    assert port_node["value"] == {"type": "name_ref", "reference": "vehicle_1.fuelCmdPort"}

    plain_port_ast = parse_sysml_antlr("part def P { port p : T; } ")
    plain_port_node = plain_port_ast["children"][0]["children"][-1]
    assert "value" not in plain_port_node

    perform_ast = parse_sysml_antlr(
        "action def A { variant perform action :>> doXorY = doX; } "
    )
    perform_node = perform_ast["children"][0]["children"][-1]
    assert perform_node["type"] == "perform_action"
    assert perform_node["redefines"] == [{"kind": "redefines", "target": "doXorY"}]
    assert perform_node["value"] == {"type": "name_ref", "reference": "doX"}

    plain_perform_ast = parse_sysml_antlr("part def P { perform action { } }")
    plain_perform_node = plain_perform_ast["children"][0]["children"][-1]
    assert "value" not in plain_perform_node


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
    assert perform_node == {
        "type": "perform_action", "reference": "FCW::外界の映像を撮る", "redefines": [], "params": [], "children": [],
    }

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
        "type": "perform_action", "reference": "logFailure", "redefines": [], "params": [], "children": [],
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
    `in calc calculation { in x; }`のように、calc種別のパラメータ自身の
    body内にさらにパラメータをネストする形が受理できなかった（従来の
    bodyはdocumentationStmt/bareDocCommentのみ）。calc def本体内なので
    calcParameterのkind節（2026-08-29、add_part_kind_to_calc_action_
    parameterで追加）を経由するのが正しい経路になり、以前の
    actionParameter経由（kind節が無かったため`in calc ...`がcalcParameter
    にマッチせずpartBodyElement経由でactionParameterへフォールバック
    していた）から変わった。"""
    ast = parse_sysml_antlr("calc def Sample { in calc calculation { in x; } }")
    outer = ast["children"][0]["children"][0]
    assert outer["type"] == "calc_parameter"
    assert outer["kind"] == "calc"
    assert outer["name"] == "calculation"
    inner = outer["children"][0]
    assert inner == {
        "type": "calc_parameter", "direction": "in", "kind": None,
        "name": "x", "type_name": None, "multiplicity": None,
        "value": None, "children": [],
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


def test_antlr_default_clause_equals_form():
    """`attribute m default = 10;`・`attribute :>> m default = n;`
    （DefaultValueTest.sysml）・`attribute mass redefines Vehicle::mass
    default = 1750 [kg] { ... }`（1c-Parts Tree Redefinition.sysml）の
    ように、`default`節は直後に式を直接置く形しか無く、実コーパスで
    広く使われる`default = <expr>`という`=`付き形を受理できなかった
    （2026-08-29、730件ベースライン154件エラー要因分析で発見）。"""
    ast = parse_sysml_antlr(
        "part def V { attribute m default = 10; attribute n = 20; }"
    )
    m_node, n_node = ast["children"][0]["children"]
    assert m_node["defaultValue"] == {"type": "literal", "literal_type": "int", "value": 10}
    assert n_node["value"] == {"type": "literal", "literal_type": "int", "value": 20}

    redefine_ast = parse_sysml_antlr("part def W { attribute :>> m default = n; }")
    redefine_node = redefine_ast["children"][0]["children"][0]
    assert redefine_node["redefines"] == [{"kind": "redefines", "target": "m"}]
    assert redefine_node["defaultValue"] == {"type": "name_ref", "reference": "n"}

    # 既存の`=`無し裸形が引き続き機能することを確認する（回帰防止）。
    plain_ast = parse_sysml_antlr("part def V2 { attribute m default 10; }")
    plain_node = plain_ast["children"][0]["children"][0]
    assert plain_node["defaultValue"] == {"type": "literal", "literal_type": "int", "value": 10}


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
    assert inner[1] == {
        "type": "perform_action", "reference": "body", "redefines": [], "params": [], "children": [],
        "isThen": True,
    }
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
    assert bare_children[1] == {
        "type": "perform_action", "reference": "y", "redefines": [], "params": [], "children": [],
    }


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


def test_antlr_interface_and_allocation_connect_colon_colon_and_body():
    """`interface engineToTransmissionInterface: EngineToTransmissionInterface
    connect engine::drivePwrPort to transmission::clutchPort { ... }`
    （VehicleModel.sysml）のように、interfaceUsageのインライン`connect`節は
    `::`修飾参照とbody（`{ ... }`）のいずれも取りうる（以前は`.`区切りの
    qualifiedNameのみ・`;`終端のみだった）。`allocate DSLA::DroneSystem::
    navigationModule to Drone::controlUnit;`（The-SysMLv2-Book-
    DroneSystemModel-Example.sysml）のように、allocationUsageの`allocate`
    節も同様に`::`を取りうる（2026-08-28、investigate_connectorend_
    coloncolonで発見。共有connectorEnd自体は変更せず、connectUsage/
    bindingConnectorと同じくこの2規則をconnectorEndPathへ切り替えた）。"""
    ast = parse_sysml_antlr(
        "interface def IF { interface x : IFace connect a::b to c::d { doc /* note */ } }"
    )
    node = ast["children"][0]["children"][0]
    assert node["type"] == "interface_usage"
    assert node["interface_part"]["from_end"]["reference_subsetting"]["referenced_feature"] == "a::b"
    assert node["interface_part"]["to_end"]["reference_subsetting"]["referenced_feature"] == "c::d"
    assert len(node["children"]) == 1

    allocation_ast = parse_sysml_antlr("part def P { allocate x::y to z::w; }")
    allocation_node = allocation_ast["children"][-1]["children"][0]
    assert allocation_node["type"] == "allocation_usage"
    assert allocation_node["connector_part"]["from_end"]["reference_subsetting"]["referenced_feature"] == "x::y"
    assert allocation_node["connector_part"]["to_end"]["reference_subsetting"]["referenced_feature"] == "z::w"


def test_antlr_allocationusage_nary_allocate_form():
    """`allocation allocation2 : Logical_to_Physical allocate ( logical
    ::> l, physical ::> p );`（AllocationTest.sysml L30-33）のように、
    allocationUsageの`allocate`節は2項の`A to B`形だけでなく、括弧で
    囲んだ3項以上のend列（connectUsage/connectionUsage/interfaceUsageで
    既に対応済みのn項形）も取りうる。`getTypedRuleContext`がラベルを
    区別せず型だけで子ノードを検索するため、無ラベルの
    `ctx.connectorEndPath()`がn項形のnaryEndsノードも拾ってしまい
    `len(ends) == 2`が誤って真になる回帰を防ぐため、naryEndsの有無を
    先に判定する必要があった（flowUsageのofMult/typeMultで発見した
    衝突と同型）。2026-08-29、
    add_interfaceusage_nary_connect_form対応中に連鎖的に発見。"""
    ast = parse_sysml_antlr(
        "allocation def Logical_to_Physical; "
        "allocation allocation2 : Logical_to_Physical allocate "
        "( logical ::> l, physical ::> p );"
    )
    node = ast["children"][-1]
    assert node["type"] == "allocation_usage"
    assert node["connector_part"] is None
    assert [e["declared_name"] for e in node["ends"]] == ["logical", "physical"]
    assert [e["reference"] for e in node["ends"]] == ["l", "p"]

    # 既存の2項`A to B`形が引き続き機能し、"ends"キーが付かないことを
    # 確認する（回帰防止）。
    binary_ast = parse_sysml_antlr(
        "allocation allocation1 : Logical_to_Physical allocate l to p;"
    )
    binary_node = binary_ast["children"][0]
    assert binary_node["connector_part"] is not None
    assert "ends" not in binary_node


def test_antlr_allocationusage_bare_body():
    """`allocate torqueGenerator to powerTrain { allocate
    torqueGenerator.generateTorque to powerTrain.engine.generateTorque; }`
    （Allocation Usage Example.sysml、12b-Allocation.sysml）のように、
    allocationUsageの裸形（名前・型節省略の第2alt）にもbody（ネストした
    裸allocate文を含む）を持ちうる（従来この代替は`;`終端のみだった）。
    2026-08-29、730件ベースライン154件エラー要因分析で発見。"""
    ast = parse_sysml_antlr(
        "part def P { allocate torqueGenerator to powerTrain { "
        "allocate torqueGenerator.generateTorque to powerTrain.engine.generateTorque; "
        "} }"
    )
    outer = ast["children"][0]["children"][0]
    assert outer["type"] == "allocation_usage"
    assert outer["name"] is None
    assert outer["connector_part"]["from_end"]["reference_subsetting"]["referenced_feature"] == "torqueGenerator"
    assert len(outer["children"]) == 1
    inner = outer["children"][0]
    assert inner["type"] == "allocation_usage"
    assert inner["connector_part"]["from_end"]["reference_subsetting"]["referenced_feature"] == "torqueGenerator::generateTorque"

    # 既存の`;`終端形（body無し）が引き続き機能することを確認する
    # （回帰防止）。
    plain_ast = parse_sysml_antlr("part def P { allocate a to b; }")
    plain_node = plain_ast["children"][0]["children"][0]
    assert plain_node["children"] == []


def test_antlr_named_multiplicity_binding_connector():
    """d74_named_multiplicity_binding_connector_missing: ShapeItems.sysmlの
    `binding [1] bind [0..*] base.edges = [0..*] be;`（公式コーパス
    全体で51件）のように、`'binding'`キーワード（自体の多重度`[1]`を
    伴う。名前は無し）+各end側の多重度を伴うbindingConnector形が一切
    未対応だった。既存の裸形（`bind a = b;`・body付き`bind a = b {
    ... }`）との共存も確認する。d99でleftEnd/rightEndの型を
    `connectorEnd`から`connectorEndPath`へ差し替えたため、出力は
    区切り文字を常に`::`へ正規化する（d81の既存方針）。
    2026-08-29、add_connectionendmember_leading_multiplicity対応中に
    連鎖的に発見した`binding NAME bind ...;`（名前が'binding'とは別に
    存在する形）への対応時に、従来`simpleName`が「常に'binding'という
    文字列そのもの」という誤った前提だったことが判明し、`'binding'`を
    独立した予約語として切り出した。それに伴い、この51件の形は名前が
    無い（`name is None`）ものとして正しく解釈されるようになった
    （従来は`name == "binding"`という誤った値を返していた）。"""
    named_ast = parse_sysml_antlr(
        "part def P { binding [1] bind [0..*] base.edges = [0..*] be; }"
    )
    named_node = named_ast["children"][0]["children"][0]
    assert named_node["type"] == "binding_connector"
    assert named_node["name"] is None
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


def test_antlr_bindingconnector_named_binding_keyword_form():
    """`binding ab bind a = b;`・`binding ab1 : AB bind a = b;`
    （ConnectionTest.sysml L23-24）のように、bindingConnectorには
    `'binding'`キーワード付きの名前付き（+任意で型節）形がある（従来
    `simpleName?`は「常に'binding'という文字列そのものが名前」という
    前提で設計されており、実際の別名が続く形を受理できなかった）。
    2026-08-29、add_connectionendmember_leading_multiplicity対応中に
    連鎖的に発見。"""
    named_ast = parse_sysml_antlr(
        "part def P { part a; part b; binding ab bind a = b; }"
    )
    named_node = named_ast["children"][0]["children"][-1]
    assert named_node["type"] == "binding_connector"
    assert named_node["name"] == "ab"
    assert named_node["type_name"] is None
    assert named_node["leftEnd"]["reference"] == "a"
    assert named_node["rightEnd"]["reference"] == "b"

    typed_ast = parse_sysml_antlr(
        "part def P { part a; part b; binding ab1 : AB bind a = b; }"
    )
    typed_node = typed_ast["children"][0]["children"][-1]
    assert typed_node["name"] == "ab1"
    assert typed_node["type_name"] == "AB"


def test_antlr_binding_connector_ref_modifier():
    """`ref bind chargePort = battery.chargeInPort;`
    （The-SysMLv2-Book-DroneSystemModel-Example.sysml）のように、
    bindingConnectorにも他のusage系規則と同じ`ref`修飾子が付きうる
    （2026-08-28、コーパス全体1件のみだが公式の書籍例で確認）。"""
    ref_ast = parse_sysml_antlr("part def P { ref bind chargePort = battery.chargeInPort; }")
    ref_node = ref_ast["children"][-1]["children"][0]
    assert ref_node["type"] == "binding_connector"
    assert ref_node["isRef"] is True
    assert ref_node["leftEnd"]["reference"] == "chargePort"
    assert ref_node["rightEnd"]["reference"] == "battery::chargeInPort"

    plain_ast = parse_sysml_antlr("part def P { bind a = b; }")
    plain_node = plain_ast["children"][-1]["children"][0]
    assert plain_node["isRef"] is False


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
    assert node["leftEnd"] == {"type": "connector_end", "declared_name": None, "reference": "LDW::A::B", "segments": [("LDW", None), ("A", "::"), ("B", ".")]}
    assert node["rightEnd"] == {"type": "connector_end", "declared_name": None, "reference": "C", "segments": [("C", None)]}


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
        {"type": "named_argument", "name": "probability", "value": {"type": "name_ref", "reference": "LevelEnum::low", "segments": [("LevelEnum", None), ("low", "::")]}, "children": []},
    ]


def test_antlr_newexpr_namespacepath_type():
    """`new Time::Clock()`（Local Clock Example.sysml L8）のように、new式の
    型参照は`::`修飾名を取ることもある（従来`qualifiedName`は`.`区切りの
    みだったため`namespacePath`へ差し替えた）。既存の単一セグメント・
    `.`区切り型が引き続き機能することも確認する。2026-08-29、
    add_newexpr_namespacepath_type対応中に発見。"""
    ast = parse_sysml_antlr(
        "part def Server { part :>> localClock = new Time::Clock(); }"
    )
    value = ast["children"][0]["children"][0]["expression"]
    assert value["type"] == "new_instance"
    assert value["name"] == "Time::Clock"
    assert value["arguments"] == []

    # 既存の単一セグメント型が引き続き機能することを確認する。
    single_ast = parse_sysml_antlr(
        "part def P { attribute a = new SamplePair(x, calculation(x)); }"
    )
    single_value = single_ast["children"][0]["children"][0]["value"]
    assert single_value["name"] == "SamplePair"


def test_antlr_expression_all_selection():
    """`subject : Engine[1..*] = all engineChoice;`（10b-Trade-off Among
    Alternative Configurations.sysml L76）のように、KerMLの`all <ref>`
    コレクション選択式（指定した分類子の全インスタンスを選択）が式文法に
    無かった。`::`区切りの型参照も受理できることを確認する。2026-08-29、
    add_expression_all_selection対応中に発見。"""
    ast = parse_sysml_antlr(
        "analysis def A { subject : Engine[1..*] = all engineChoice; }"
    )
    node = ast["children"][0]["children"][0]
    assert node["value"] == {"type": "all_selection", "type_name": "engineChoice"}

    qualified_ast = parse_sysml_antlr(
        "analysis def A { subject : Engine[1..*] = all Choices::engineChoice; }"
    )
    qualified_node = qualified_ast["children"][0]["children"][0]
    assert qualified_node["value"] == {"type": "all_selection", "type_name": "Choices::engineChoice"}


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


def test_antlr_lambda_body_multiple_local_declarations():
    """`(1..numberOfBolts)->forAll { in i : Natural; private attribute
    lbcf = lugBolts#(i).coordinateFrame; private attribute trs : Type
    { ... } lbcf.transformation == trs }`
    （VehicleGeometryAndCoordinateFrames.sysml）・`->forAll {in i:
    Integer; private thisSample : Type = sc.samples#(i); private
    nextSample : Type = sc.samples#(i+1); StraightLineDynamicsEquations
    (...)}`（Vehicle Analysis Demo.sysml、`attribute`キーワード省略の
    featureUsage形）のように、arrowLambdaBodyは単一パラメータ+最終式
    のみで、最終結果式の前に複数のローカル宣言を並べる実例に対応
    できなかった。2026-08-29、730件ベースライン154件エラー要因分析で
    発見。"""
    attr_ast = parse_sysml_antlr(
        "part def P { attribute numberOfBolts : Natural = 5; "
        "assert constraint { (1..numberOfBolts)->forAll { "
        "in i : Natural; "
        "private attribute lbcf = lugBolts; "
        "private attribute trs : TranslationRotationSequence { :>> source = wcf; } "
        "lbcf.transformation == trs } } }"
    )
    lambda_node = attr_ast["children"][0]["children"][-1]["children"][0]["result_expression"]
    assert lambda_node["type"] == "arrow_lambda"
    assert lambda_node["name"] == "forAll"
    assert lambda_node["param"] == {"name": "i", "isRef": False, "typeName": "Natural"}
    assert len(lambda_node["children"]) == 2
    lbcf_node, trs_node = lambda_node["children"]
    assert lbcf_node["type"] == "attribute_usage"
    assert lbcf_node["name"] == "lbcf"
    assert lbcf_node["visibility"] == "private"
    assert trs_node["type"] == "attribute_usage"
    assert trs_node["name"] == "trs"
    assert trs_node["type_name"] == "TranslationRotationSequence"
    assert lambda_node["body"] == {
        "type": "binary_expr", "op": "==",
        "left": {"type": "name_ref", "reference": "lbcf.transformation"},
        "right": {"type": "name_ref", "reference": "trs"},
    }

    # `attribute`キーワード省略のfeatureUsage形ローカル宣言（Vehicle
    # Analysis Demo.sysml）も受理することを確認する。
    feature_ast = parse_sysml_antlr(
        "part def P { attribute a = (1..5)->forAll {in i: Integer; "
        "private thisSample : T = samples; "
        "private nextSample : T = samples; "
        "f(p = power, m = mass) }; }"
    )
    feature_lambda = feature_ast["children"][0]["children"][0]["value"]
    assert len(feature_lambda["children"]) == 2
    assert feature_lambda["children"][0]["type"] == "feature_usage"
    assert feature_lambda["children"][0]["name"] == "thisSample"

    # 既存のローカル宣言無し形（最終式のみ）が引き続き機能することを
    # 確認する（回帰防止）。
    plain_ast = parse_sysml_antlr("part def P { attribute a = x->forAll {in i: T; y}; }")
    plain_lambda = plain_ast["children"][0]["children"][0]["value"]
    assert plain_lambda["children"] == []


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


def test_antlr_metadatausage_type_and_about_clause():
    """`metadata InterfaceCompatibilityIssue : Issue about
    engineToTransmissionInterface { ... }`（IssueMetadataExample.sysml）・
    `metadata SafetyFeature about a, b, c;`（Metadata Example-1.sysml）の
    ように、`metadata <name> [: Type] about <ref1>[, <ref2>...]`という
    頻出パターンに未対応だった（従来`inheritanceClause`(`:>`等)しか
    持たず、plainな`: Type`型節・`about`節のいずれも受理できなかった）。
    2026-08-29、730件ベースライン154件エラー要因分析で発見。"""
    typed_ast = parse_sysml_antlr(
        "metadata def Issue; "
        "metadata InterfaceCompatibilityIssue : Issue about engineToTransmissionInterface { }"
    )
    typed_node = typed_ast["children"][-1]
    assert typed_node["type"] == "metadata_usage"
    assert typed_node["name"] == "InterfaceCompatibilityIssue"
    assert typed_node["type_name"] == "Issue"
    assert typed_node["about"] == ["engineToTransmissionInterface"]

    multi_ast = parse_sysml_antlr(
        "metadata def SafetyFeature; metadata SafetyFeature about a, b, c;"
    )
    multi_node = multi_ast["children"][-1]
    assert multi_node["about"] == ["a", "b", "c"]
    assert "type_name" not in multi_node

    # 既存の`about`/型節無し形が引き続き機能し、両キー自体が無いことを
    # 確認する（回帰防止）。
    plain_ast = parse_sysml_antlr("metadata def M; metadata m;")
    plain_node = plain_ast["children"][-1]
    assert "about" not in plain_node
    assert "type_name" not in plain_node


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
        "value": None,
        "redefines": [],
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
        "redefines": [],
        "isParallel": False,
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
        "redefines": [],
        "isParallel": False,
        "children": [],
    }
    lint_ast(ast)


def test_antlr_portion_usage_snapshot_and_timeslice():
    """`snapshot A;`/`timeslice A;`は旧Lark実装でも構文としては通るが、
    出力が生Tree混じりの断片で実用に耐えず、linter.py側に対応する
    チェック関数も無い（構文的完全性のみ）。"""
    snapshot = parse_sysml_antlr("snapshot A;")
    timeslice = parse_sysml_antlr("timeslice A;")
    base = {
        "isThen": False,
        "isIndividual": False,
        "value": None,
        "multiplicity": None,
        "redefines": [],
        "type_name": None,
        "children": [],
        "subKind": None,
    }
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


def test_antlr_portion_usage_redefine_clause_and_type():
    """`snapshot groundSystemAtIngress :> context : Apollo11MissionContext
    { ... }`（Apollo11MissionExecutionPackage.sysml）のように、portion usage
    はredefine節（`:>`/`:>>`/subsets/redefines）と型節を持ちうる
    （2026-08-28、730件回帰チェックで発見。P0-2対応時の見落とし）。"""
    ast = parse_sysml_antlr(
        "part def P { snapshot groundSystemAtIngress :> context : "
        "Apollo11MissionContext { } }"
    )
    node = ast["children"][0]["children"][-1]
    assert node["type"] == "portion_usage"
    assert node["name"] == "groundSystemAtIngress"
    assert node["redefines"] == [{"kind": "subsets", "target": "context"}]
    assert node["type_name"] == "Apollo11MissionContext"


def test_antlr_perform_action_bare_with_redefine():
    """`perform GroundSupportSystem::performCrewIngress :>> performCrewIngress;`
    （Apollo11MissionExecutionPackage.sysml）のように、`action`キーワードを
    伴わない裸のperform文もredefine節を持ちうる（2026-08-28、730件回帰
    チェックで発見）。"""
    ast = parse_sysml_antlr(
        "part def P { perform GroundSupportSystem::performCrewIngress "
        ":>> performCrewIngress; } "
    )
    node = ast["children"][0]["children"][-1]
    assert node == {
        "type": "perform_action",
        "reference": "GroundSupportSystem::performCrewIngress",
        "redefines": [{"kind": "redefines", "target": "performCrewIngress"}],
        "params": [],
        "children": [],
    }


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
        "isIndividual": False,
        "isAbstract": False,
        "isConstant": False,
        "isRef": False,
        "direction": None,
        "redefines": [],
        "value": None,
        "defaultValue": None,
        "multiplicity": None,
        "type_name": None,
        "children": [],
    }


def test_antlr_occurrenceusage_itemdef_prefix_metadata():
    """`#fmea item def 'Glucose FMEA Item' { #cause occurrence 'battery
    depleted' { ... } }`（14c-Language Extensions.sysml L161-165）の
    ように、itemDef/occurrenceUsageはどちらも`#Type`前置メタデータ注釈を
    持つことがある（従来どちらも未対応だった）。既存のメタデータ無し形が
    引き続き機能することも確認する。2026-08-29、
    add_occurrenceusage_itemdef_prefix_metadata対応中に発見。"""
    ast = parse_sysml_antlr(
        "package P { #fmea item def 'Glucose FMEA Item' { "
        "#cause occurrence 'battery depleted' { } } }"
    )
    item_node = ast["children"][0]
    assert item_node["type"] == "item_def"
    assert item_node["prefixMetadata"] == ["fmea"]
    occ_node = item_node["children"][0]
    assert occ_node["type"] == "occurrence_usage"
    assert occ_node["prefixMetadata"] == ["cause"]

    # 既存のメタデータ無し形が引き続き機能することを確認する
    # （"prefixMetadata"キー自体が無いことも確認する）。
    plain_item_ast = parse_sysml_antlr("package P { item def A { } }")
    plain_item = plain_item_ast["children"][0]
    assert "prefixMetadata" not in plain_item

    plain_occ_ast = parse_sysml_antlr("occurrence A;")
    plain_occ = plain_occ_ast["children"][0]
    assert "prefixMetadata" not in plain_occ


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
        "isRef": False,
        "redefines": [],
        "children": [],
    }
    assert typed["children"][0] == {
        "type": "individual_usage",
        "name": "A",
        "type_name": "T",
        "isAbstract": False,
        "isRef": False,
        "redefines": [],
        "children": [],
    }


def test_antlr_individualusage_ref_redefine():
    """`individual testSystem : TestSystem :> massVerificationSystem
    { ... }`（9-Verification-simplified.sysml）・`ref individual :>>
    vehicleUnderTest : TestVehicle1 :> vehicle1_c2 { ... }`（同、名前
    省略形）・`individual leftFrontWheel_t0 : Wheel_1 :>> leftFrontWheel;`
    （IndividualUsage.sysml）のように、individualUsageは他の多くのusage
    規則（port/occurrence等）にある`ref`修飾子・名前省略・redefine節
    （pre/post、`:>`/`:>>`/subsets/redefines）一式を欠いていた。
    2026-08-29、730件ベースライン154件エラー要因分析で発見。"""
    postkind_ast = parse_sysml_antlr(
        "part def P { individual testSystem : TestSystem :> massVerificationSystem { } }"
    )
    postkind_node = postkind_ast["children"][0]["children"][0]
    assert postkind_node["name"] == "testSystem"
    assert postkind_node["type_name"] == "TestSystem"
    assert postkind_node["redefines"] == [{"kind": "subsets", "target": "massVerificationSystem"}]

    ref_prekind_ast = parse_sysml_antlr(
        "part def P { ref individual :>> vehicleUnderTest : TestVehicle1 :> vehicle1_c2 { } }"
    )
    ref_node = ref_prekind_ast["children"][0]["children"][0]
    assert ref_node["name"] is None
    assert ref_node["isRef"] is True
    assert ref_node["type_name"] == "TestVehicle1"
    assert ref_node["redefines"] == [
        {"kind": "redefines", "target": "vehicleUnderTest"},
        {"kind": "subsets", "target": "vehicle1_c2"},
    ]

    bare_redefine_ast = parse_sysml_antlr(
        "part def P { individual leftFrontWheel_t0 : Wheel_1 :>> leftFrontWheel; }"
    )
    bare_redefine_node = bare_redefine_ast["children"][0]["children"][0]
    assert bare_redefine_node["name"] == "leftFrontWheel_t0"
    assert bare_redefine_node["redefines"] == [{"kind": "redefines", "target": "leftFrontWheel"}]


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


def test_antlr_successionstmt_doc_body():
    """`first start then continue { doc /* ... */ }`（3a-Function-based
    Behavior-1.sysml L85）のように、successionStmt（無名の`first X then
    Y;`）は`;`終端の代わりに`{ doc ... }`という本体を持つこともある
    （transitionStmtと同型）。既存の`;`終端形が引き続き機能することも
    確認する。2026-08-29、add_successionstmt_body対応中に発見。"""
    ast = parse_sysml_antlr(
        "action def A { first start then continue { doc /* explanation */ } }"
    )
    succession = ast["children"][0]["children"][0]
    assert succession["type"] == "succession"
    assert succession["firstEnd"]["reference"] == "start"
    assert succession["thenEnd"]["reference"] == "continue"
    assert [c["type"] for c in succession["children"]] == ["documentation"]

    # 既存の`;`終端形が引き続き機能することを確認する。
    semi_ast = parse_sysml_antlr("action def A { first start then continue; }")
    semi_succession = semi_ast["children"][0]["children"][0]
    assert semi_succession["children"] == []


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
            "visibility": None,
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


def test_antlr_expression_select_filter_dotquestion():
    """`subcomponents.totalMass.?{in p:>ISQ::mass; p >= minMass}`
    （MassRollup2.sysml）・`subcomponents.totalMass.?{in p :> ISQ::mass;
    p > minMass}`（MassRollup.sysml）のように、`.?{ ... }`というOCL的
    selectフィルタ式が未対応だった（`.`直後の`?`が既存の`memberAccessExpr`
    の`member=simpleName`として解釈できず失敗していた）。パラメータの
    型節は`:`だけでなく`:>`でも書かれる。2026-08-29、730件ベースライン
    154件エラー要因分析で発見。"""
    ast = parse_sysml_antlr(
        "part def P { attribute a = "
        "subcomponents.totalMass.?{in p:>ISQ::mass; p >= minMass}; }"
    )
    node = ast["children"][0]["children"][0]
    value = node["value"]
    assert value["type"] == "select_filter"
    assert value["receiver"] == {"type": "name_ref", "reference": "subcomponents.totalMass"}
    assert value["param"] == {"name": "p", "isRef": False, "typeName": "ISQ::mass"}
    assert value["body"] == {
        "type": "binary_expr", "op": ">=",
        "left": {"type": "name_ref", "reference": "p"},
        "right": {"type": "name_ref", "reference": "minMass"},
    }

    # `:>`ではなく素の`:`型節、複数のsubcomponentsチェーンとの併存も確認する。
    plain_colon_ast = parse_sysml_antlr(
        "part def P { attribute a = "
        "subcomponents.totalMass.?{in p : ISQ::mass; p > minMass}; }"
    )
    plain_colon_node = plain_colon_ast["children"][0]["children"][0]["value"]
    assert plain_colon_node["type"] == "select_filter"
    assert plain_colon_node["param"]["typeName"] == "ISQ::mass"


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


def test_antlr_render_stmt_variants():
    """`render rendering r1: R[0..1]; render r;`（ViewTest.sysml）・
    `render asElementTable { view :>> columnView[1] { render
    asTextualNotation; } }`（11a-View-Viewpoint.sysml）のように、`render`
    は`rendering`宣言のインライン形・既存/ライブラリ組み込みrenderingへの
    単純参照形のいずれも受理する専用文（従来一切未実装だった）。
    2026-08-29、730件ベースライン154件エラー要因分析で発見。"""
    ast = parse_sysml_antlr(
        "view def V { render rendering r1: R[0..1]; render r; }"
    )
    view_node = ast["children"][0]
    assert view_node["type"] == "view_def"
    decl_node = view_node["children"][0]
    assert decl_node == {
        "type": "render_stmt",
        "name": "r1",
        "isRendering": True,
        "type_name": "R",
        "multiplicity": {"size": {"min": 0, "max": 1}, "is_ordered": False, "is_unique": True},
        "children": [],
    }
    ref_node = view_node["children"][1]
    assert ref_node == {
        "type": "render_stmt",
        "name": "r",
        "isRendering": False,
        "type_name": None,
        "multiplicity": None,
        "children": [],
    }

    # 多重度付きの単純参照形（`renderingUsage`は無し）。
    mult_ast = parse_sysml_antlr("view v : V { render r [0..*]; }")
    mult_node = mult_ast["children"][0]["children"][0]
    assert mult_node["type"] == "render_stmt"
    assert mult_node["multiplicity"] == {"size": {"min": 0, "max": "*"}, "is_ordered": False, "is_unique": True}

    # 本体付きの単純参照形（ネストしたview usage内でさらにrenderを使う）。
    body_ast = parse_sysml_antlr(
        "view def V { render asElementTable { view :>> columnView[1] { render asTextualNotation; } } }"
    )
    outer_render = body_ast["children"][0]["children"][0]
    assert outer_render["type"] == "render_stmt"
    assert outer_render["name"] == "asElementTable"
    assert len(outer_render["children"]) == 1
    inner_view = outer_render["children"][0]
    assert inner_view["type"] == "view_usage"
    inner_render = inner_view["children"][0]
    assert inner_render["type"] == "render_stmt"
    assert inner_render["name"] == "asTextualNotation"

    # `::`区切りの修飾参照形（DontPanic-SysMLv2-Batmobile.sysml）。
    qualified_ast = parse_sysml_antlr("view def V { render Views::asElementTable; }")
    qualified_node = qualified_ast["children"][0]["children"][0]
    assert qualified_node["name"] == "Views::asElementTable"


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


def test_antlr_implicit_subject_ascast_expression():
    """`filter @Safety and (as Safety).isMandatory;`（Filtering
    Example-1.sysml L32）のように、`asCastExpr`(`expr as Type`)の左辺
    （暗黙の対象）を省略した短縮形`(as Type)`が未対応だった（従来`as`は
    常にleft-recursiveな中置演算子としてのみ現れる前提だった）。既存の
    明示的な左辺を持つ`(that as Occurrence)`形が引き続き機能することも
    確認する。2026-08-29、730件ベースラインの154件エラー要因分析で発見。"""
    ast = parse_sysml_antlr(
        "part def P { attribute a = (as Safety).isMandatory; }"
    )
    value = ast["children"][0]["children"][-1]["value"]
    assert value == {
        "type": "member_access",
        "base": {
            "type": "as_cast",
            "base": None,
            "type_name": "Safety",
            "children": [],
        },
        "member": "isMandatory",
        "children": [],
    }

    # 既存の明示的な左辺を持つas_cast形が引き続き機能することを確認する。
    explicit_ast = parse_sysml_antlr("part def P { attribute a = that as Occurrence; }")
    explicit_value = explicit_ast["children"][0]["children"][-1]["value"]
    assert explicit_value["base"] == {"type": "name_ref", "reference": "that"}


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


def test_antlr_successionusage_typed_first_then_form():
    """`succession s1 : AB first a then b;`（ConnectionTest.sysml L28）の
    ように、successionUsageの`first...then`代替は名前の後に型節
    （`: AB`）を置くこともある（従来この代替は型節を一切持たなかった）。
    2026-08-29、add_connectionendmember_leading_multiplicity対応中に
    連鎖的に発見。"""
    ast = parse_sysml_antlr(
        "part def P { part a; part b; succession s1 : AB first a then b; }"
    )
    node = ast["children"][0]["children"][-1]
    assert node["type"] == "succession_usage"
    assert node["name"] == "s1"
    assert node["type_name"] == "AB"
    assert node["firstEnd"]["reference"] == "a"
    assert node["thenEnd"]["reference"] == "b"

    # 既存の型節無し形が引き続き機能することを確認する。
    plain_ast = parse_sysml_antlr(
        "part def P { part a; part b; succession first a then b; }"
    )
    plain_node = plain_ast["children"][0]["children"][-1]
    assert plain_node["type_name"] is None


def test_antlr_succession_first_if_then_shorthand():
    """`public succession S first A1 if x == 0 then A2;`（DecisionTest.sysml）
    のように、named successionUsage(first...then代替)はfirst側とthen側の
    間にガード付き継続条件`if <cond>`を挟むこともある。`first focus if
    focus.image.isWellFocused then shoot;`（Conditional Succession
    Example-1.sysml）のように、bareFirstStmt（`first <name>;`単体形）も
    区切りの`;`無しでガード付き継続節`if <cond> then <target>`を直接
    続けることがある。`private first A3;`（DecisionTest.sysml、同ファイル
    内で連鎖的に発見）のように、bareFirstStmtはvisibilityIndicatorも
    伴いうる。2026-08-29、730件ベースライン154件エラー要因分析で発見。"""
    ast = parse_sysml_antlr(
        "action def D { action A1; action A2; "
        "public succession S first A1 if x == 0 then A2; }"
    )
    node = ast["children"][0]["children"][-1]
    assert node["type"] == "succession_usage"
    assert node["guard"] == {
        "type": "binary_expr", "op": "==",
        "left": {"type": "name_ref", "reference": "x"},
        "right": {"type": "literal", "literal_type": "int", "value": 0},
    }

    plain_ast = parse_sysml_antlr(
        "part def P { part a; part b; succession first a then b; }"
    )
    plain_node = plain_ast["children"][0]["children"][-1]
    assert "guard" not in plain_node

    bare_ast = parse_sysml_antlr(
        "action def D { action focus; action shoot; "
        "first focus if focus.image.isWellFocused then shoot; }"
    )
    bare_node = bare_ast["children"][0]["children"][-1]
    assert bare_node == {
        "type": "first_stmt",
        "name": "focus",
        "guard": {"type": "name_ref", "reference": "focus.image.isWellFocused"},
        "thenTarget": "shoot",
    }

    visibility_ast = parse_sysml_antlr("action def D { action A3; private first A3; }")
    visibility_node = visibility_ast["children"][0]["children"][-1]
    assert visibility_node == {"type": "first_stmt", "name": "A3", "visibility": "private"}

    plain_bare_ast = parse_sysml_antlr("action def D { action A3; first A3; }")
    plain_bare_node = plain_bare_ast["children"][0]["children"][-1]
    assert plain_bare_node == {"type": "first_stmt", "name": "A3"}


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


def test_antlr_successionusageflow_bare_from_omitted():
    """`succession flow x.p to a1.aa.receiver;`（PartTest.sysml L25）の
    ように、successionUsageの`succession flow`複合キーワード形は`from`
    キーワードが省略され、sourceのnamespacePathが直接書かれる短縮形も
    取りうる（flowUsageの`from`省略bare形と同型のギャップ。従来は
    `from`が必須だった）。2026-08-29、add_nested_packagedef_in_partbody
    対応中に連鎖的に発見。"""
    ast = parse_sysml_antlr(
        "part def B { succession flow x.p to a1.aa.receiver; }"
    )
    node = ast["children"][0]["children"][-1]
    assert node == {
        "type": "succession_usage",
        "name": None,
        "visibility": None,
        "isFlow": True,
        "fromEnd": "x::p",
        "toEnd": "a1::aa::receiver",
        "children": [],
    }

    # 既存の`from`明示形が引き続き機能することを確認する。
    explicit_ast = parse_sysml_antlr(
        "part def P { succession flow onOffCmdFlow from a.x to b.y; }"
    )
    explicit_node = explicit_ast["children"][0]["children"][-1]
    assert explicit_node["fromEnd"] == "a::x"


def test_antlr_successionusageflow_of_type_clause():
    """`succession flow of Command from receive to validate;`
    （dfa-coverage-advanced.sysml L134-135）のように、successionUsageの
    `succession flow`複合キーワード形はflowUsageと同様のペイロード型節
    `of Type`を持つこともある（従来この代替は型節を一切持たなかった）。
    既存の型節無し形が引き続き機能することも確認する。2026-08-31、
    add_successionusageflow_of_type_clause対応中に発見。"""
    ast = parse_sysml_antlr(
        "action def A { action receive; action validate; "
        "succession flow of Command from receive to validate; }"
    )
    node = ast["children"][0]["children"][-1]
    assert node["type"] == "succession_usage"
    assert node["item_type"] == "Command"
    assert node["fromEnd"] == "receive"
    assert node["toEnd"] == "validate"

    # 既存の型節無し形が引き続き機能することを確認する
    # （"item_type"キー自体が無いことも確認する）。
    plain_ast = parse_sysml_antlr(
        "part def B { succession flow x.p to a1.aa.receiver; }"
    )
    plain_node = plain_ast["children"][0]["children"][-1]
    assert "item_type" not in plain_node


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


def test_antlr_double_star_power_operator():
    """`(p_2 / p_1)**((gamma - 1) / gamma)`（Turbojet Stage Analysis.sysml）・
    `tpd_avg **(-3)`（VehicleModel_2_Simplified.sysml）・`231.0 * 'in' **
    3`（Vehicle Analysis Demo.sysml）のように、物理量計算式では`^`と同じ
    べき乗演算子として`**`も多用されるが、従来`powerExpr`は`^`のみを
    受理していた。2026-08-29、730件ベースライン154件エラー要因分析で
    発見。"""
    ast = parse_sysml_antlr("part def P { attribute a = x ** 3; }")
    value = ast["children"][0]["children"][-1]["value"]
    assert value == {
        "type": "binary_expr", "op": "**",
        "left": {"type": "name_ref", "reference": "x"},
        "right": {"type": "literal", "literal_type": "int", "value": 3},
    }

    # 既存の`^`（回帰防止）と、括弧付きオペランドの組み合わせ。
    nested_ast = parse_sysml_antlr("part def P { attribute a = (p2 / p1) ** ((g - 1) / g); }")
    nested_value = nested_ast["children"][0]["children"][-1]["value"]
    assert nested_value["type"] == "binary_expr"
    assert nested_value["op"] == "**"

    caret_ast = parse_sysml_antlr("part def P { attribute a = s^-1; }")
    caret_value = caret_ast["children"][0]["children"][-1]["value"]
    assert caret_value["op"] == "^"


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


def test_lint_subsetting_uniqueness_conformance():
    """Subsetting_UniquenessConformance_Invalid.sysml参照。subsets/redefines
    対象がシブリングスコープ（同じ親のchildren内）でunique(既定)な場合、
    subsetting/redefining側はnonuniqueにできない（2026-08-28、参照実装
    比較で発見した偽陰性）。"""
    text = (
        "part rearAxleAssembly {\n"
        "    part rearWheel: Wheel[2];\n"
        "    part rearWheel_1: Wheel[2] nonunique subsets rearWheel;\n"
        "    part rearWheel_2[0..1] nonunique subsets rearWheel;\n"
        "}\n"
        "part def Wheel;\n"
    )
    ast = parse_sysml_antlr(text)
    issues = lint_ast(ast)
    uniqueness_errors = [
        i for i in issues
        if i.severity == "error" and "nonunique if subsetted" in i.message
    ]
    assert len(uniqueness_errors) == 2

    # unique制約の対象がnonunique自体なら誤検出しない。
    ok_text = (
        "part rearAxleAssembly {\n"
        "    part rearWheel: Wheel[2] nonunique;\n"
        "    part rearWheel_1: Wheel[2] nonunique subsets rearWheel;\n"
        "}\n"
        "part def Wheel;\n"
    )
    ok_ast = parse_sysml_antlr(ok_text)
    ok_issues = lint_ast(ok_ast)
    assert not any("nonunique if subsetted" in i.message for i in ok_issues)

    # subsets対象がシブリングに存在しない場合は判定しない（型解決なしの
    # 安全側の設計）。
    unresolved_text = (
        "part rearAxleAssembly {\n"
        "    part rearWheel_1: Wheel[2] nonunique subsets elsewhereWheel;\n"
        "}\n"
        "part def Wheel;\n"
    )
    unresolved_ast = parse_sysml_antlr(unresolved_text)
    unresolved_issues = lint_ast(unresolved_ast)
    assert not any("nonunique if subsetted" in i.message for i in unresolved_issues)


def test_lint_accessible_feature_path():
    """FeaturePath_Invalid.sysml参照。`::`で辿った先がtype（def）ではなく
    feature（usage）である場合は不正（8.2.2.7、参照実装比較で発見した偽陰性）。
    ルートがfeatureか型かは問わない。"""
    text = (
        "package Q {\n"
        "  part def F {\n"
        "    part a : A;\n"
        "  }\n"
        "  part f : F;\n"
        "  part def A {\n"
        "    part g = f::a;\n"
        "  }\n"
        "}\n"
    )
    ast = parse_sysml_antlr(text)
    issues = lint_ast(ast)
    accessible_errors = [
        i for i in issues
        if i.severity == "error" and "accessible feature" in i.message
    ]
    assert len(accessible_errors) == 1

    # dot記法で書き直せばエラーなし。
    ok_text = text.replace("f::a", "f.a")
    ok_ast = parse_sysml_antlr(ok_text)
    ok_issues = lint_ast(ok_ast)
    assert not any("accessible feature" in i.message for i in ok_issues)

    # 自スコープの名前への`::`自己参照は許容する
    # （`action dyn2 { calc acc { in dt = dyn2::dt; } }`型のパターン）。
    self_ref_text = (
        "action def D {\n"
        "    in attribute dt;\n"
        "}\n"
        "action dyn2 : D {\n"
        "    calc acc {\n"
        "        in x = dyn2::dt;\n"
        "    }\n"
        "}\n"
    )
    self_ref_ast = parse_sysml_antlr(self_ref_text)
    self_ref_issues = lint_ast(self_ref_ast)
    assert not any("accessible feature" in i.message for i in self_ref_issues)

    # 基底型名を通じた自己参照（継承済みfeatureは実質アクセス可能）も許容する
    # （`item def RightTriangle :> Triangle { ... Triangle::width ... }`型）。
    inherited_base_text = (
        "item def Triangle {\n"
        "    attribute width;\n"
        "}\n"
        "item def RightTriangle :> Triangle {\n"
        "    attribute w2 = Triangle::width;\n"
        "}\n"
    )
    inherited_base_ast = parse_sysml_antlr(inherited_base_text)
    inherited_base_issues = lint_ast(inherited_base_ast)
    assert not any("accessible feature" in i.message for i in inherited_base_issues)

    # 標準ライブラリ等、単体ファイルでは検証不能な参照は判定対象外にする
    # （`ISQ::torque`型、既存の_is_unverifiable_referenceと同じ設計方針）。
    unverifiable_text = (
        "part def P {\n"
        "    attribute t = ISQ::torque;\n"
        "}\n"
    )
    unverifiable_ast = parse_sysml_antlr(unverifiable_text)
    unverifiable_issues = lint_ast(unverifiable_ast)
    assert not any("accessible feature" in i.message for i in unverifiable_issues)


def test_lint_binding_feature_override():
    """Vehicle.sysml/toaster-system.sysml参照。既に値束縛(`= expr`)を持つ
    フィーチャをredefineしつつ、redefine側も新たに値束縛を与えるのは不正
    （2026-08-28、参照実装比較で発見した偽陰性）。"""
    # `:>> name = value;`という、ターゲット省略の値束縛ショートハンド形。
    shorthand_text = (
        "part def Toaster {\n"
        "    attribute maxTemp : Real;\n"
        "    attribute slots : Integer = 2;\n"
        "}\n"
        "part myToaster : Toaster {\n"
        "    :>> maxTemp = 230.0;\n"
        "    :>> slots = 2;\n"
        "}\n"
    )
    shorthand_ast = parse_sysml_antlr(shorthand_text)
    shorthand_issues = lint_ast(shorthand_ast)
    override_errors = [
        i for i in shorthand_issues
        if i.severity == "error" and "override a binding feature" in i.message
    ]
    # maxTempは基底に値束縛が無いので許容、slotsのみ不正。
    assert len(override_errors) == 1

    # 明示的な`attribute :>> Target = value;`形、かつ多段階の継承チェーン
    # （vehicle_1a :> vehicle_1が、vehicle_1自身のredefine済みフィーチャを
    # 更にredefineする）でも検出できる。
    explicit_text = (
        "package Vehicle {\n"
        "    part def Vehicle {\n"
        "        attribute cylinders: Integer = 3;\n"
        "    }\n"
        "    part vehicle_1 : Vehicle {\n"
        "        attribute cylinders :>> Vehicle::cylinders = 4;\n"
        "    }\n"
        "    part vehicle_1a :> vehicle_1 {\n"
        "        attribute cylinders :>> vehicle_1::cylinders = 6;\n"
        "    }\n"
        "}\n"
    )
    explicit_ast = parse_sysml_antlr(explicit_text)
    explicit_issues = lint_ast(explicit_ast)
    explicit_errors = [
        i for i in explicit_issues
        if i.severity == "error" and "override a binding feature" in i.message
    ]
    assert len(explicit_errors) == 2

    # 型付きusage本体内で継承フィーチャと同名のフィーチャを宣言する暗黙の
    # redefine（明示的な`:>>`が無くとも、KerMLの仕様上は自動的に継承
    # フィーチャをredefineしたものとみなされる）でも検出できる。
    implicit_text = (
        "package CalculationExample {\n"
        "    calc def MassSum {\n"
        "        in partMasses;\n"
        "        return totalMass = 1;\n"
        "    }\n"
        "    calc ms : MassSum {\n"
        "        in partMasses = 2;\n"
        "        return totalMass = 3;\n"
        "    }\n"
        "}\n"
    )
    implicit_ast = parse_sysml_antlr(implicit_text)
    implicit_issues = lint_ast(implicit_ast)
    implicit_errors = [
        i for i in implicit_issues
        if i.severity == "error" and "override a binding feature" in i.message
    ]
    assert len(implicit_errors) == 1

    # 基底フィーチャに値束縛が無ければ誤検出しない。
    ok_text = (
        "part def P {\n"
        "    attribute x : Integer;\n"
        "}\n"
        "part p1 : P {\n"
        "    attribute x :>> P::x = 5;\n"
        "}\n"
    )
    ok_ast = parse_sysml_antlr(ok_text)
    ok_issues = lint_ast(ok_ast)
    assert not any("override a binding feature" in i.message for i in ok_issues)


def test_antlr_recursive_wildcard_import():
    """`import Pkg::**;`（再帰ワイルドカードimport。パッケージ自身に加え
    その配下の入れ子パッケージのメンバまでインポートする形）が未対応
    だった（2026-08-28、730件パース失敗の要因分析で発見。コーパス全体で
    13件のパース失敗の直接原因）。再現: apollo-11-sysml-v2/Technical/
    SystemSpecificationPackage.sysml `private import
    TechnicalRequirementsPackage::**;`。`**`はレキサー上`*`トークン2つの
    並びとして扱われる。"""
    ast = parse_sysml_antlr(
        "package P { private import TechnicalRequirementsPackage::**; }"
    )
    import_node = ast["children"][0]
    assert import_node["type"] == "import"
    assert import_node["name"] == "TechnicalRequirementsPackage"
    assert import_node["wildcard"] is True
    assert import_node["visibility"] == "private"

    # 既存の単一`*`ワイルドカード形・非ワイルカード形・expose文への同種の
    # 拡張が壊れていないことも確認する。
    single_wildcard_ast = parse_sysml_antlr(
        "package P { import TechnicalRequirementsPackage::*; }"
    )
    assert single_wildcard_ast["children"][0]["wildcard"] is True

    member_ast = parse_sysml_antlr(
        "package P { import TechnicalRequirementsPackage::Foo; }"
    )
    assert member_ast["children"][0]["wildcard"] is False

    expose_ast = parse_sysml_antlr(
        "package P { expose TechnicalRequirementsPackage::**; }"
    )
    expose_node = expose_ast["children"][0]
    assert expose_node["type"] == "special_stmt"
    assert expose_node["children"][0]["type"] == "expose"


def test_antlr_import_expose_multilevel_wildcard_and_bracket_filter():
    """`private import Pkg211::*::**;`（ImportTest.sysml）のように、
    ワイルドカード段が複数連なる多段形が未対応だった（従来は`::`+`*`
    +任意で追加の`*`という1段のみ）。`public import
    vehicle::**[@Safety and ...];`（Filtering Example-2.sysml、
    13b-Safety and Security Features Element Group-2.sysml、
    ElementFilter.sysml(xpect)）・`expose vehicle::*::**;`、
    `expose SystemModel::vehicle::**[@SysML::PartUsage];`
    （11a/11b-...View...sysml）のように、ワイルドカード直後に
    ブラケット付きインラインフィルタ式が続く形も未対応だった。
    2026-08-29、730件ベースラインの154件エラー要因分析で発見。"""
    multilevel_ast = parse_sysml_antlr("private import Pkg211::*::**;")
    multilevel_node = multilevel_ast["children"][0]
    assert multilevel_node["type"] == "import"
    assert multilevel_node["name"] == "Pkg211"
    assert multilevel_node["wildcard"] is True

    bracket_ast = parse_sysml_antlr(
        "package P { part vehicle; public import vehicle::**[@Safety]; }"
    )
    bracket_node = bracket_ast["children"][-1]
    assert bracket_node["type"] == "import"
    assert bracket_node["wildcard"] is True
    assert bracket_node["filter"] == {"type": "metadata_ref", "reference": "Safety"}

    expose_multilevel_ast = parse_sysml_antlr("expose vehicle::*::**;")
    assert expose_multilevel_ast["children"][0]["children"][0]["type"] == "expose"

    expose_bracket_ast = parse_sysml_antlr(
        "expose SystemModel::vehicle::**[@SysML::PartUsage];"
    )
    expose_bracket_node = expose_bracket_ast["children"][0]["children"][0]
    assert expose_bracket_node["qualified_name"] == "SystemModel::vehicle"
    assert expose_bracket_node["filter"] == {"type": "metadata_ref", "reference": "SysML::PartUsage"}

    # 既存の単一ワイルドカード・ブラケット無し形が引き続き機能し、
    # "filter"キー自体が無いことを確認する（回帰防止）。
    plain_ast = parse_sysml_antlr("import TechnicalRequirementsPackage::*;")
    plain_node = plain_ast["children"][0]
    assert "filter" not in plain_node


def test_antlr_import_all_modifier():
    """`public import all P2::*;`（PrivateImportTest.sysml）のように、
    `import`直後に`all`修飾子（`private import`による可視性制限を
    上書きする）が付くことがある（従来importStmtには`import`直後の
    `all`オプションが無かった）。2026-08-29、730件ベースライン154件
    エラー要因分析で発見。"""
    ast = parse_sysml_antlr("package P { public import all P2::*; }")
    node = ast["children"][0]
    assert node["type"] == "import"
    assert node["name"] == "P2"
    assert node["wildcard"] is True
    assert node["visibility"] == "public"
    assert node["isAll"] is True

    # 既存の`all`無し形が引き続き機能し、"isAll"キー自体が無いことを
    # 確認する（回帰防止）。
    plain_ast = parse_sysml_antlr("private import P3::*;")
    plain_node = plain_ast["children"][0]
    assert "isAll" not in plain_node


def test_antlr_importstmt_body_form():
    """`private import ScalarValues::Integer { doc /* ... */ }`
    （15_10-Primitive Data Types.sysml）・`private import Definitions::*
    { /* ... */ }`（1a-Parts Tree.sysml、`doc`キーワード無しの裸コメント）
    のように、importStmtは`;`終端のみで、docコメントのみのbody形が
    無かった。2026-08-29、730件ベースライン154件エラー要因分析で発見。"""
    doc_ast = parse_sysml_antlr(
        "private import ScalarValues::Integer { doc /* text */ }"
    )
    doc_node = doc_ast["children"][0]
    assert doc_node["type"] == "import"
    assert doc_node["name"] == "ScalarValues::Integer"
    assert doc_node["children"] == [
        {"type": "documentation", "identification": None, "locale": None, "body": "text", "children": []},
    ]

    bare_comment_ast = parse_sysml_antlr(
        "private import Definitions::* { /* bare comment */ }"
    )
    bare_comment_node = bare_comment_ast["children"][0]
    assert bare_comment_node["wildcard"] is True
    assert bare_comment_node["children"] == [
        {"type": "documentation", "identification": None, "locale": None, "body": "bare comment", "children": []},
    ]

    # 既存の`;`終端形が引き続き機能し、childrenが空リストであることを
    # 確認する（回帰防止）。
    plain_ast = parse_sysml_antlr("private import ScalarValues::Natural;")
    plain_node = plain_ast["children"][0]
    assert plain_node["children"] == []


def test_antlr_interface_usage_unnamed_typed_inline_connect():
    """`interface : StagingInterface connect a.p to b.q;`のように、名前を
    省略した型付きinterface usageへのインライン`connect...to...`が
    未対応だった（2026-08-28、730件パース失敗の要因分析で発見。コーパス
    全体で11件のパース失敗の直接原因）。再現: apollo-11-sysml-v2/
    Technical/TechnicalComponentsPackage.sysml。第1代替（名前付き形）は
    `simpleName`が必須のため名前省略形にマッチできず、`connect`節を
    持たない第2代替（裸形）にフォールバックしていたが、そちらには
    `connect`節が無かった。名前付き形（第1代替）が既存どおり動くことも
    合わせて確認する。"""
    unnamed_ast = parse_sysml_antlr(
        "part a { part p; }\n"
        "part b { part q; }\n"
        "interface : StagingInterface connect a.p to b.q;\n"
    )
    interface_node = unnamed_ast["children"][-1]
    assert interface_node["type"] == "interface_usage"
    assert interface_node["name"] is None
    assert interface_node["type_name"] == "StagingInterface"
    assert interface_node["interface_part"] == {
        "type": "binary_interface_part",
        "from_end": {"reference_subsetting": {"referenced_feature": "a::p"}},
        "to_end": {"reference_subsetting": {"referenced_feature": "b::q"}},
    }

    named_ast = parse_sysml_antlr(
        "part a { part p; }\n"
        "part b { part q; }\n"
        "interface cmLMDocking : DockingInterface connect a.p to b.q;\n"
    )
    named_node = named_ast["children"][-1]
    assert named_node["type"] == "interface_usage"
    assert named_node["name"] == "cmLMDocking"
    assert named_node["type_name"] == "DockingInterface"
    assert named_node["interface_part"] == {
        "type": "binary_interface_part",
        "from_end": {"reference_subsetting": {"referenced_feature": "a::p"}},
        "to_end": {"reference_subsetting": {"referenced_feature": "b::q"}},
    }


def test_antlr_use_case_actor_usage():
    """`actor driver : RoadUser;`（use case def本体内でのactor宣言）が
    未実装だった（2026-08-28、730件パース失敗の要因分析で発見。コーパス
    全体で11件のパース失敗の直接原因）。再現: elan8-sysml-examples/
    intersection/TrafficLightIntersectionRequirements.sysml、
    sysml-v2-pilot-implementation/sysml/src/training/35. Use Cases/
    Use Case Definition Example.sysml。subjectUsageと同型の設計。"""
    ast = parse_sysml_antlr(
        "use case def UC {\n"
        "    actor driver : Person;\n"
        "    actor passengers : Person[0..4];\n"
        "}\n"
    )
    driver, passengers = ast["children"][0]["children"]

    assert driver["type"] == "actor_usage"
    assert driver["name"] == "driver"
    assert driver["type_name"] == "Person"
    assert driver["multiplicity"] is None

    assert passengers["type"] == "actor_usage"
    assert passengers["name"] == "passengers"
    assert passengers["type_name"] == "Person"
    assert passengers["multiplicity"] == {
        "size": {"min": 0, "max": 4}, "is_ordered": False, "is_unique": True
    }


def test_antlr_then_control_node_keywords():
    """`then fork F { ... }`/`then merge m;`/`then decide D;`（succession先
    として制御フローノードをインライン宣言する形）と`then event occurrence
    ...;`が未対応だった（2026-08-28、730件パース失敗の要因分析で発見。
    コーパス全体で11件のパース失敗の直接原因）。再現: ControlNodeTest.sysml
    `then fork F { ... }`、ActionTest.sysml `then merge m;`、
    DecisionTest.sysml.xt `then decide D;`、Event Occurrence
    Example.sysml `then event occurrence sensedSpeedReceived;`。
    調査中に、既存のflowControlNodeのキーワードが公式文法(`decide`)ではなく
    誤って`decision`になっていたことも発覚したため、あわせて修正した
    （実コーパスに`decision`をキーワードとして使う例は無い）。"""
    ast = parse_sysml_antlr(
        "action def A {\n"
        "    action A1;\n"
        "    then fork F { in a; }\n"
        "    then merge m;\n"
        "    then decide D;\n"
        "}\n"
    )
    _a1, fork, merge, decide = ast["children"][0]["children"]
    assert fork["type"] == "fork_node" and fork["name"] == "F" and fork["isThen"] is True
    assert merge["type"] == "merge_node" and merge["name"] == "m" and merge["isThen"] is True
    assert decide["type"] == "decide_node" and decide["name"] == "D" and decide["isThen"] is True

    # `then`無しの既存形（bareのcontrol node宣言）も壊れていないことを確認する。
    bare_ast = parse_sysml_antlr("action def A { fork F; merge m; decide D; }")
    bare_fork, bare_merge, bare_decide = bare_ast["children"][0]["children"]
    assert "isThen" not in bare_fork
    assert "isThen" not in bare_merge
    assert "isThen" not in bare_decide

    event_ast = parse_sysml_antlr(
        "part cruiseController {\n"
        "    event occurrence setSpeedReceived;\n"
        "    then event occurrence sensedSpeedReceived;\n"
        "}\n"
    )
    plain_event, then_event = event_ast["children"][0]["children"]
    assert "isThen" not in plain_event
    assert then_event["type"] == "event_occurrence_usage"
    assert then_event["name"] == "sensedSpeedReceived"
    assert then_event["isThen"] is True


def test_antlr_item_and_subject_usage_qualified_type_clause():
    """itemUsage/subjectUsageの型節が`::`修飾型名（namespacePath形）を
    受理せず単一`ID`のままだった（2026-08-28、730件パース失敗の要因分析で
    発見。コーパス全体で10件のパース失敗の直接原因）。再現:
    DontPanic-SysMLv2-Batmobile.sysml `item boundingBox : ShapeItems::Box
    [1] :> boundingShapes { ... }`、MiningCorporationRequirementsDecl.sysml
    `subject miningcorporation : Domain::MiningCorporation;`。"""
    item_ast = parse_sysml_antlr(
        "part def Wheel {\n"
        "    part boundingShapes;\n"
        "    item boundingBox : ShapeItems::Box [1] :> boundingShapes;\n"
        "}\n"
    )
    item_node = item_ast["children"][0]["children"][1]
    assert item_node["type"] == "item_usage"
    assert item_node["name"] == "boundingBox"
    assert item_node["type_name"] == "ShapeItems::Box"

    subject_ast = parse_sysml_antlr(
        "requirement def R {\n"
        "    subject miningcorporation : Domain::MiningCorporation;\n"
        "}\n"
    )
    subject_node = subject_ast["children"][0]["children"][0]
    assert subject_node["type"] == "subject_usage"
    assert subject_node["name"] == "miningcorporation"
    assert subject_node["type_name"] == "Domain::MiningCorporation"

    # 既存の単一ID型名の形も壊れていないことを確認する。
    plain_item_ast = parse_sysml_antlr("part def Wheel { item boundingBox : Box [1]; }")
    assert plain_item_ast["children"][0]["children"][0]["type_name"] == "Box"

    plain_subject_ast = parse_sysml_antlr("requirement def R { subject s : Vehicle; }")
    assert plain_subject_ast["children"][0]["children"][0]["type_name"] == "Vehicle"


def test_antlr_action_def_nested_in_state_body():
    """state本体（stateBodyElement）への`action def`のネストが未対応
    だった（2026-08-28、730件パース失敗の要因分析で発見。コーパス全体で
    9件のパース失敗の直接原因）。以前対応したfix_nested_partdef_in_partbody
    （part def本体へのpart defネスト）と全く同型のギャップ。再現:
    StopWatchStates.sysml `state s { ... action def VehicleStartSignal; ... }`。"""
    ast = parse_sysml_antlr(
        "state def S {\n"
        "    state s {\n"
        "        action def VehicleStartSignal;\n"
        "        action def VehicleOnSignal;\n"
        "    }\n"
        "}\n"
    )
    inner_state = ast["children"][0]["children"][0]
    assert inner_state["type"] == "state_usage"
    nested_action_defs = inner_state["children"]
    assert [c["type"] for c in nested_action_defs] == ["action_def", "action_def"]
    assert [c["name"] for c in nested_action_defs] == ["VehicleStartSignal", "VehicleOnSignal"]


def test_antlr_variability_variation_and_variant_keywords():
    """Variability（可変性）ライブラリ機能の`variation`/`variant`先頭修飾子
    （`variation part def V { variant part x : Q { ... } }`等）が全く
    未実装だった（2026-08-28、730件パース失敗の要因分析で発見。コーパス
    全体で9件のパース失敗の直接原因）。VariabilityTest.sysml参照。
    part/attribute/action def・part/attribute/action usage・bareな
    featureUsage・use case/requirement usageの広い範囲に付きうる。"""
    ast = parse_sysml_antlr(
        "package VariabilityTest {\n"
        "    part def P { attribute a; }\n"
        "    part def Q :> P;\n"
        "    attribute def B;\n"
        "    variation part def V :> P {\n"
        "        variant part x : Q {\n"
        "            attribute b : B :>> a;\n"
        "        }\n"
        "    }\n"
        "    part q : Q;\n"
        "    variation part v : P {\n"
        "        variant q;\n"
        "    }\n"
        "    variation action def A {\n"
        "        variant action a1;\n"
        "        variant action a2;\n"
        "    }\n"
        "    variation use case uc1 {\n"
        "        variant use case uc11;\n"
        "    }\n"
        "    variation requirement r {\n"
        "        variant requirement r1;\n"
        "    }\n"
        "}\n"
    )
    pkg_children = ast["children"]
    by_name = {c.get("name"): c for c in pkg_children}

    variation_part_def = by_name["V"]
    assert variation_part_def["type"] == "part_def"
    assert variation_part_def["variability"] == "variation"
    variant_part = variation_part_def["children"][0]
    assert variant_part["type"] == "part_instance"
    assert variant_part["variability"] == "variant"

    variation_part_usage = by_name["v"]
    assert variation_part_usage["type"] == "part_instance"
    assert variation_part_usage["variability"] == "variation"
    # `variant q;`という型キーワードを伴わない裸のvariant参照。
    bare_variant = variation_part_usage["children"][0]
    assert bare_variant["type"] == "feature_usage"
    assert bare_variant["name"] == "q"
    assert bare_variant["variability"] == "variant"

    variation_action_def = by_name["A"]
    assert variation_action_def["type"] == "action_def"
    assert variation_action_def["variability"] == "variation"
    assert [c["variability"] for c in variation_action_def["children"]] == ["variant", "variant"]

    variation_use_case = by_name["uc1"]
    assert variation_use_case["type"] == "use_case_usage"
    assert variation_use_case["variability"] == "variation"
    assert variation_use_case["children"][0]["variability"] == "variant"

    variation_requirement = by_name["r"]
    assert variation_requirement["type"] == "requirement_usage"
    assert variation_requirement["variability"] == "variation"
    assert variation_requirement["children"][0]["variability"] == "variant"

    # variability修飾子を持たない既存の宣言はNoneのままであることも確認する。
    assert by_name["P"]["variability"] is None
    assert by_name["q"]["variability"] is None


def test_antlr_accessible_feature_path_exempts_variant_selection():
    """`transmission::manualTransmission`（Variation Usages.sysml、`::`で
    variant選択肢を参照する形）や`cylinder::diameter::diameterSmall`
    （VehicleVariabilityModel.sysml、途中のfeatureがローカルにvariation型へ
    redefineされている多段チェーン）が、`Must be an accessible feature`
    ルールの偽陽性にならないことを確認する（2026-08-28、Variability機能
    追加に伴う730件回帰チェックで発見）。"""
    # variabilityスコープの外からvariantを`::`参照する形
    # （_is_feature_only_nameのvariant/variation除外）。
    outer_ref_text = (
        "part def Transmission;\n"
        "part def ManualTransmission :> Transmission;\n"
        "part def AutomaticTransmission :> Transmission;\n"
        "part manualTransmission : ManualTransmission;\n"
        "part automaticTransmission : AutomaticTransmission;\n"
        "part vehicleFamily {\n"
        "    variation part transmission : Transmission[1] {\n"
        "        variant manualTransmission;\n"
        "        variant automaticTransmission;\n"
        "    }\n"
        "    assert constraint {\n"
        "        transmission == transmission::manualTransmission\n"
        "    }\n"
        "}\n"
    )
    outer_ast = parse_sysml_antlr(outer_ref_text)
    outer_issues = lint_ast(outer_ast)
    assert not any("accessible feature" in i.message for i in outer_issues)

    # variabilityスコープ内から、ローカルにredefineされた型経由でvariant
    # 選択肢を`::`で多段参照する形（_iter_reference_bearing_dictsの
    # variabilityスコープ祖先除外）。
    nested_ref_text = (
        "attribute def Diameter;\n"
        "variation attribute def DiameterChoices :> Diameter {\n"
        "    variant attribute diameterSmall;\n"
        "    variant attribute diameterLarge;\n"
        "}\n"
        "part def Cylinder {\n"
        "    attribute diameter : Diameter[1];\n"
        "}\n"
        "part def Engine {\n"
        "    part cylinder : Cylinder[2..*];\n"
        "}\n"
        "variation part def EngineChoices :> Engine {\n"
        "    variant '6cylEngine' {\n"
        "        part :>> cylinder {\n"
        "            attribute :>> diameter : DiameterChoices;\n"
        "        }\n"
        "        assert constraint {\n"
        "            cylinder.diameter == cylinder::diameter::diameterSmall\n"
        "        }\n"
        "    }\n"
        "}\n"
    )
    nested_ast = parse_sysml_antlr(nested_ref_text)
    nested_issues = lint_ast(nested_ast)
    assert not any("accessible feature" in i.message for i in nested_issues)


def test_antlr_satisfy_requirement_omitted_keyword_and_qualified_name():
    """`satisfy 'flr-R001' by performLunarMission...;`のように、既存の
    requirement usageを名前だけで参照する場合に`requirement`キーワードを
    省略できる形（FunctionSpecificationPackage.sysml）と、`satisfy
    Drone_StakeholderRequirements::longDistance by drone;`のように対象
    参照名が`::`修飾を取る形（Drone_BaseArchitecture.sysml）の両方が
    未対応だった（2026-08-28、730件パース失敗の要因分析で発見。コーパス
    全体で7件のパース失敗の直接原因）。"""
    omitted_ast = parse_sysml_antlr(
        "part def System {\n"
        "    requirement 'flr-R001' : Something;\n"
        "    action performLunarMission;\n"
        "    satisfy 'flr-R001' by performLunarMission;\n"
        "}\n"
        "requirement def Something;\n"
    )
    satisfy_node = omitted_ast["children"][0]["children"][-1]
    assert satisfy_node["type"] == "satisfy_requirement_usage"
    assert satisfy_node["name"] == "flr-R001"
    assert satisfy_node["by"] == "performLunarMission"

    qualified_ast = parse_sysml_antlr(
        "package Q {\n"
        "    requirement def Drone_StakeholderRequirements {\n"
        "        requirement longDistance;\n"
        "    }\n"
        "    part drone;\n"
        "    satisfy Drone_StakeholderRequirements::longDistance by drone;\n"
        "}\n"
    )
    qualified_satisfy_node = qualified_ast["children"][-1]
    assert qualified_satisfy_node["type"] == "satisfy_requirement_usage"
    assert qualified_satisfy_node["name"] == "Drone_StakeholderRequirements::longDistance"
    assert qualified_satisfy_node["by"] == "drone"

    # 既存の`requirement`キーワード付き形も壊れていないことを確認する。
    with_keyword_ast = parse_sysml_antlr(
        "part def System {\n"
        "    requirement 'flr-R001' : Something;\n"
        "    action performLunarMission;\n"
        "    satisfy requirement 'flr-R001' by performLunarMission;\n"
        "}\n"
        "requirement def Something;\n"
    )
    with_keyword_node = with_keyword_ast["children"][0]["children"][-1]
    assert with_keyword_node["type"] == "satisfy_requirement_usage"
    assert with_keyword_node["name"] == "flr-R001"


def test_antlr_assert_satisfy_by_combined_form():
    """`satisfy r by p;`・`assert satisfy r by q;`・`not satisfy r1 by p;`・
    `assert not satisfy r1 by q;`（RequirementTest.sysml）のように、
    `satisfy...by`形自体にも`assert`/`not`前置修飾子が（互いに独立して）
    付きうる（従来この代替は前置修飾子を一切持たず、`assert`/`not`は
    別キーワード形`assert (not)? satisfiedBy ...;`にしか無かった）。
    2026-08-29、730件ベースライン154件エラー要因分析で発見。"""
    bare_ast = parse_sysml_antlr(
        "part def P { requirement r : R; satisfy r by p; }\n"
        "requirement def R;\n"
    )
    bare_node = bare_ast["children"][0]["children"][-1]
    assert bare_node["type"] == "satisfy_requirement_usage"
    assert bare_node["is_negated"] is False
    assert bare_node["by"] == "p"

    assert_ast = parse_sysml_antlr(
        "part def P { requirement r : R; assert satisfy r by q; }\n"
        "requirement def R;\n"
    )
    assert_node = assert_ast["children"][0]["children"][-1]
    assert assert_node["is_negated"] is False
    assert assert_node["name"] == "r"
    assert assert_node["by"] == "q"

    not_ast = parse_sysml_antlr(
        "part def P { requirement r1 : R1; not satisfy r1 by p; }\n"
        "requirement def R1;\n"
    )
    not_node = not_ast["children"][0]["children"][-1]
    assert not_node["is_negated"] is True
    assert not_node["by"] == "p"

    assert_not_ast = parse_sysml_antlr(
        "part def P { requirement r1 : R1; assert not satisfy r1 by q; }\n"
        "requirement def R1;\n"
    )
    assert_not_node = assert_not_ast["children"][0]["children"][-1]
    assert assert_not_node["is_negated"] is True
    assert assert_not_node["name"] == "r1"
    assert assert_not_node["by"] == "q"


def test_antlr_satisfyrequirementusage_type_and_by_omission():
    """`satisfy requirement req1 : Req1 by system;`
    （RequirementDerivationExample.sysml）のように、nameRefと`by`の間に
    型節`: Type`を挟むことがある。`satisfy 'system structure
    perspective';`（11a-View-Viewpoint.sysml）のように、`by`節自体を
    省略した裸参照形（既存のrequirement usageを名前のみで参照する形）も
    ある。従来は`ctx.by`の有無で`satisfiedBy`キーワード形との代替判別を
    行っていたが、`by`省略対応でこの判別方法自体を`ctx.nameRef`に
    切り替える必要があった。2026-08-29、730件ベースライン154件エラー
    要因分析で発見。"""
    typed_ast = parse_sysml_antlr(
        "part def P { requirement req1 : Req1; part system; "
        "satisfy requirement req1 : Req1 by system; }\n"
        "requirement def Req1;\n"
    )
    typed_node = typed_ast["children"][0]["children"][-1]
    assert typed_node["type"] == "satisfy_requirement_usage"
    assert typed_node["name"] == "req1"
    assert typed_node["type_name"] == "Req1"
    assert typed_node["by"] == "system"

    by_omitted_ast = parse_sysml_antlr(
        "part def P { requirement 'system structure perspective'; "
        "satisfy 'system structure perspective'; }\n"
    )
    by_omitted_node = by_omitted_ast["children"][0]["children"][-1]
    assert by_omitted_node["type"] == "satisfy_requirement_usage"
    assert by_omitted_node["name"] == "system structure perspective"
    assert by_omitted_node["type_name"] is None
    assert by_omitted_node["by"] is None

    # 既存の`satisfiedBy`キーワード形・型節無しの`by`付き形が引き続き
    # 機能することを確認する（回帰防止）。
    satisfiedby_ast = parse_sysml_antlr(
        "part def P { assert satisfiedBy requirement x : R; }"
    )
    satisfiedby_node = satisfiedby_ast["children"][0]["children"][-1]
    assert satisfiedby_node["type"] == "satisfy_requirement_usage"
    assert satisfiedby_node["name"] == "x"
    assert satisfiedby_node["type_name"] == "R"

    plain_by_ast = parse_sysml_antlr(
        "part def P { requirement r : R; satisfy r by q; }\n"
        "requirement def R;\n"
    )
    plain_by_node = plain_by_ast["children"][0]["children"][-1]
    assert plain_by_node["type_name"] is None
    assert plain_by_node["by"] == "q"


def test_antlr_import_statement_inside_typedef_body():
    """`part def Camera { private import PictureTaking::*; ... }`
    （camera.sysml）のように、import文が型定義スコープに閉じた形で使われる
    構文が未対応だった（従来はpackage直下限定。2026-08-28、730件パース
    失敗の要因分析で発見。コーパス全体で7件のパース失敗の直接原因）。"""
    ast = parse_sysml_antlr(
        "package PictureTaking { part def X; }\n"
        "part def Camera {\n"
        "    private import PictureTaking::*;\n"
        "    perform action takePicture;\n"
        "}\n"
    )
    camera_def = ast["children"][-1]
    assert camera_def["type"] == "part_def"
    assert camera_def["name"] == "Camera"
    import_node = camera_def["children"][0]
    assert import_node["type"] == "import"
    assert import_node["name"] == "PictureTaking"
    assert import_node["wildcard"] is True
    assert import_node["visibility"] == "private"


def test_antlr_dependency_from_to_without_name():
    """`dependency from 'System Assembly'::'Computer Subsystem' to
    'Software Design';`（Dependency Example.sysml）のように、名前を省略した
    dependency文にも`from`節が付く形が未対応だった（従来は名前と`from`が
    常にペアという前提だった。2026-08-28、730件パース失敗の要因分析で
    発見）。名前付き形・`#Type`プレフィックス付き無名形も壊れていないことを
    合わせて確認する。"""
    unnamed_ast = parse_sysml_antlr(
        "part def A;\npart def B;\ndependency from A to B;\n"
    )
    dependency_node = unnamed_ast["children"][-1]["children"][0]
    assert dependency_node["type"] == "dependency"
    assert dependency_node["clients"] == ["A"]
    assert dependency_node["suppliers"] == ["B"]

    named_ast = parse_sysml_antlr(
        "part def A;\npart def B;\ndependency D from A to B;\n"
    )
    named_dependency_node = named_ast["children"][-1]["children"][0]
    assert named_dependency_node["clients"] == ["A"]
    assert named_dependency_node["suppliers"] == ["B"]

    prefixed_ast = parse_sysml_antlr(
        "requirement def A;\nrequirement def B;\n#refinement dependency from A to B;\n"
    )
    prefixed_dependency_node = prefixed_ast["children"][-1]["children"][0]
    assert prefixed_dependency_node["prefixMetadata"] == ["refinement"]
    assert prefixed_dependency_node["clients"] == ["A"]
    assert prefixed_dependency_node["suppliers"] == ["B"]


def test_antlr_occurrence_usage_type_clause():
    """occurrenceUsageに型節`: Type`が全く無かった（`ref occurrence occ1 :
    Occ;`/`occurrence situations : Situation[*] nonunique;`が未対応。
    2026-08-28、730件パース失敗の要因分析で発見。コーパス全体で6件の
    パース失敗の直接原因）。itemUsageと同じtypeRef=namespacePathパターンを
    追加した。"""
    ast = parse_sysml_antlr(
        "occurrence def Occ;\n"
        "occurrence def Situation;\n"
        "part def P {\n"
        "    ref occurrence occ1 : Occ;\n"
        "    abstract occurrence situations : Situation[*] nonunique;\n"
        "}\n"
    )
    occ1, situations = ast["children"][-1]["children"]
    assert occ1["type"] == "occurrence_usage"
    assert occ1["type_name"] == "Occ"
    assert occ1["isRef"] is True
    assert situations["type_name"] == "Situation"
    assert situations["multiplicity"] == {
        "size": {"min": "*", "max": "*"}, "is_ordered": False, "is_unique": False
    }


def test_antlr_individual_prefix_propagation():
    """`individual occurrence ind : Ind, Occ { ... }`・`individual timeslice
    t3 :> ind;`・`individual snapshot s4 : Ind;`（OccurrenceTest.sysml）・
    `individual analysis def FuelEconomyAnalysis_1 :> FuelEconomyAnalysis;`・
    `individual analysis fuelEconomyAnalysis_1 : FuelEconomyAnalysis_1
    { ... }`（AnalysisIndividualExample.sysml）のように、occurrenceDef/
    partDef/actionDef等には既にある`individual`先頭修飾子が、
    occurrenceUsage・portionUsageStmt（snapshot/timeslice）・
    analysisCaseDef・analysisCaseUsageには無かった。2026-08-29、730件
    ベースライン154件エラー要因分析で発見。"""
    ast = parse_sysml_antlr(
        "occurrence def Ind; occurrence def Occ; part def P {\n"
        "    individual occurrence ind : Ind, Occ {\n"
        "        snapshot s3;\n"
        "        individual timeslice t3 :> ind;\n"
        "        individual snapshot s4 : Ind;\n"
        "    }\n"
        "}\n"
    )
    ind_node = ast["children"][-1]["children"][0]
    assert ind_node["type"] == "occurrence_usage"
    assert ind_node["isIndividual"] is True
    s3_node, t3_node, s4_node = ind_node["children"]
    assert s3_node["isIndividual"] is False
    assert t3_node["isIndividual"] is True
    assert t3_node["redefines"] == [{"kind": "subsets", "target": "ind"}]
    assert s4_node["isIndividual"] is True
    assert s4_node["type_name"] == "Ind"

    def_ast = parse_sysml_antlr(
        "analysis def FuelEconomyAnalysis; "
        "individual analysis def FuelEconomyAnalysis_1 :> FuelEconomyAnalysis;"
    )
    plain_def, individual_def = def_ast["children"]
    assert plain_def["type"] == "analysis_case_def"
    assert "isIndividual" not in plain_def
    assert individual_def["isIndividual"] is True
    assert individual_def["inheritance"] == {"type": "inheritance", "kind": "subsets", "base": "FuelEconomyAnalysis"}

    usage_ast = parse_sysml_antlr(
        "analysis def FuelEconomyAnalysis_1; part def P {\n"
        "    individual analysis fuelEconomyAnalysis_1 : FuelEconomyAnalysis_1 { }\n"
        "}\n"
    )
    usage_node = usage_ast["children"][-1]["children"][0]
    assert usage_node["type"] == "analysis_case_usage"
    assert usage_node["isIndividual"] is True
    assert usage_node["type_name"] == "FuelEconomyAnalysis_1"


def test_antlr_analysiscase_verificationcase_bare_result_expr():
    """`analysis def MassAnalysisCase { subject vehicle : Vehicle; ...
    vehicle.mass }`（10a-Analysis.sysml、AnalysisTest.sysml）・
    `verification def VerificationCase { ... VerificationCases::PassIf
    (v.m == 0) }`（VerificationTest.sysml）のように、calculationDef/
    constraintDefと同じ、本体末尾に`;`無しの裸の戻り値式
    （resultExpressionMember）を、analysisCaseDef/analysisCaseUsage/
    verificationCaseDef/verificationCaseUsageの本体も受理できる必要が
    あった（従来body要素種別がpartBodyElementのみで、これを含まな
    かった）。2026-08-29、730件ベースライン154件エラー要因分析で発見。"""
    def_ast = parse_sysml_antlr(
        "part def V { }\n"
        "analysis def AnalysisCase {\n"
        "    subject v : V;\n"
        "    v.m\n"
        "}\n"
    )
    def_node = def_ast["children"][-1]
    assert def_node["type"] == "analysis_case_def"
    result_node = def_node["children"][-1]
    assert result_node == {
        "type": "result_expression_member",
        "expression": {"type": "name_ref", "reference": "v.m"},
    }

    usage_ast = parse_sysml_antlr(
        "analysis def AnalysisCase; part def P {\n"
        "    analysis analysisCase : AnalysisCase { vehicle.mass }\n"
        "}\n"
    )
    usage_node = usage_ast["children"][-1]["children"][0]
    assert usage_node["type"] == "analysis_case_usage"
    usage_result = usage_node["children"][-1]
    assert usage_result == {
        "type": "result_expression_member",
        "expression": {"type": "name_ref", "reference": "vehicle.mass"},
    }

    verif_def_ast = parse_sysml_antlr(
        "part def V { }\n"
        "verification def VerificationCase {\n"
        "    subject v : V;\n"
        "    PassIf(v.m == 0)\n"
        "}\n"
    )
    verif_def_node = verif_def_ast["children"][-1]
    assert verif_def_node["type"] == "verification_case_def"
    verif_result = verif_def_node["children"][-1]
    assert verif_result["type"] == "result_expression_member"
    assert verif_result["expression"]["type"] == "function_call"
    assert verif_result["expression"]["name"] == "PassIf"

    verif_usage_ast = parse_sysml_antlr(
        "verification def VerificationCase; part def P {\n"
        "    verification verificationCase : VerificationCase { PassIf(v.m == 0) }\n"
        "}\n"
    )
    verif_usage_node = verif_usage_ast["children"][-1]["children"][0]
    assert verif_usage_node["type"] == "verification_case_usage"
    assert verif_usage_node["children"][-1]["type"] == "result_expression_member"


def test_antlr_mult_before_type_extended_to_more_usage_kinds():
    """`fix_partusage_actionusage_mult_before_type_order_and_default`
    （過去完了）で対応した「名前の直後に多重度、その後に型節」という順序を、
    requirement/item/attribute/connection usageにも拡張した（2026-08-28、
    730件パース失敗の要因分析で発見。コーパス全体で6件のパース失敗の
    直接原因）。既存の「型節→多重度」の通常順が壊れていないことも
    合わせて確認する。"""
    ast = parse_sysml_antlr(
        "requirement def Goal;\n"
        "connection def D;\n"
        "part def P {\n"
        "    requirement goals[1..*] : Goal;\n"
        "    item concerns[*] : D;\n"
        "    attribute occurs[0..1] : Real;\n"
        "    abstract connection capabilityToGoals[*] : D;\n"
        "}\n"
    )
    goals, concerns, occurs, capabilityToGoals = ast["children"][-1]["children"]

    assert goals["type"] == "requirement_usage"
    assert goals["type_name"] == "Goal"
    assert goals["multiplicity"] == {
        "size": {"min": 1, "max": "*"}, "is_ordered": False, "is_unique": True
    }

    assert concerns["type"] == "item_usage"
    assert concerns["type_name"] == "D"
    assert concerns["multiplicity"] == {
        "size": {"min": "*", "max": "*"}, "is_ordered": False, "is_unique": True
    }

    assert occurs["type"] == "attribute_usage"
    assert occurs["type_name"] == "Real"
    assert occurs["multiplicity"] == {
        "size": {"min": 0, "max": 1}, "is_ordered": False, "is_unique": True
    }

    assert capabilityToGoals["type"] == "connection_usage"
    assert capabilityToGoals["type_name"] == "D"
    assert capabilityToGoals["multiplicity"] == {
        "size": {"min": "*", "max": "*"}, "is_ordered": False, "is_unique": True
    }

    # 既存の「型節→多重度」の通常順（partUsageで既に対応済みのものに加え、
    # 今回拡張した規則）も壊れていないことを確認する。
    ok_ast = parse_sysml_antlr(
        "requirement def Goal;\n"
        "connection def D;\n"
        "part def P {\n"
        "    requirement g : Goal[1..*];\n"
        "    item c : D[*];\n"
        "    attribute o : Real[0..1];\n"
        "    abstract connection cc : D[*];\n"
        "}\n"
    )
    ok_goals, ok_concerns, ok_occurs, ok_capability = ok_ast["children"][-1]["children"]
    assert ok_goals["multiplicity"]["size"] == {"min": 1, "max": "*"}
    assert ok_concerns["multiplicity"]["size"] == {"min": "*", "max": "*"}
    assert ok_occurs["multiplicity"]["size"] == {"min": 0, "max": 1}
    assert ok_capability["multiplicity"]["size"] == {"min": "*", "max": "*"}


def test_antlr_requirementusage_multisegment_qualified_type():
    """`requirement uavSystemRequirements : DSRE::TextualRequirements::
    UAVSystemRequirements { ... }`（The-SysMLv2-Book-DroneSystemModel-
    Example.sysml L41）のように、requirementUsageの型節は3階層以上の
    `::`修飾名を取りうる（従来は単一`ID`のみで、2階層以上の`::`修飾名を
    受理できなかった。2026-08-29、add_actorusage_namespacepath_type対応
    中に連鎖的に発見）。カンマ区切り複数型の各要素も`::`修飾名を取れる
    ことも併せて確認する。"""
    ast = parse_sysml_antlr(
        "requirement uavSystemRequirements : "
        "DSRE::TextualRequirements::UAVSystemRequirements { }"
    )
    node = ast["children"][0]
    assert node["type"] == "requirement_usage"
    assert node["type_name"] == "DSRE::TextualRequirements::UAVSystemRequirements"

    multi_ast = parse_sysml_antlr(
        "requirement r : A::B::C, D::E;"
    )
    multi_node = multi_ast["children"][0]
    assert multi_node["type_names"] == ["A::B::C", "D::E"]

    # 既存の単一セグメント型（`::`無し）が引き続き機能することを確認する。
    plain_ast = parse_sysml_antlr("requirement req : Goal;")
    plain_node = plain_ast["children"][0]
    assert plain_node["type_name"] == "Goal"


def test_antlr_requirementusage_references_form():
    """`requirement references vehicleMass1 { ... }`（8-Requirements.sysml
    L162）のように、名前無しの`requirement`直後に`references`キーワード
    （connectionEndMemberのdirectKindと同じ記号的な同義語）+参照先が
    続くことがある。既存の通常の名前付き形が引き続き機能することも
    確認する。2026-08-29、add_requirementusage_references_form対応中に
    発見。"""
    ast = parse_sysml_antlr(
        "requirement def R { "
        "requirement references vehicleMass1 { doc /* x */ } "
        "}"
    )
    node = ast["children"][0]["children"][0]
    assert node["type"] == "requirement_usage"
    assert node["name"] is None
    assert node["reference"] == "vehicleMass1"
    assert len(node["children"]) == 1

    # 既存の通常の名前付き形が引き続き機能することを確認する
    # （"reference"キー自体が無いことも確認する）。
    named_ast = parse_sysml_antlr("requirement req : Goal;")
    named_node = named_ast["children"][0]
    assert named_node["name"] == "req"
    assert "reference" not in named_node


def test_antlr_comma_separated_multi_type_declaration():
    """usage型節がカンマ区切りの複数型を取れなかった（部分的なdef/usage系
    規則にしか対応していなかった。2026-08-28、730件パース失敗の要因分析で
    発見。コーパス全体で8件のパース失敗の直接原因。calc/case/constraint/
    individual/occurrence/port/requirement/part usageに拡張した）。
    再現: MissionPackage.sysml `part crew[1..*] : Astronaut,
    LogicalComponentsPackage::Crew :>> crew;`、公式xpectテストの各
    *Usage_Invalid.sysml（参照実装は構文上は受理しつつ「1つの型のみ許可」
    という別の意味検証エラーを出す）。"""
    part_ast = parse_sysml_antlr(
        "part def Astronaut;\n"
        "package LogicalComponentsPackage { part def Crew; }\n"
        "part def P {\n"
        "    part crew;\n"
        "    part crew2[1..*] : Astronaut, LogicalComponentsPackage::Crew :>> crew;\n"
        "}\n"
    )
    crew2 = part_ast["children"][-1]["children"][-1]
    assert crew2["type_name"] == "Astronaut"
    assert crew2["type_names"] == ["Astronaut", "LogicalComponentsPackage::Crew"]

    calc_ast = parse_sysml_antlr("calc def F1;\ncalc def F2;\ncalc f1 : F1, F2;\n")
    calc_node = calc_ast["children"][-1]
    assert calc_node["type_name"] == "F1"
    assert calc_node["type_names"] == ["F1", "F2"]

    case_ast = parse_sysml_antlr("case def C1;\ncase def C2;\ncase c1: C1, C2;\n")
    case_node = case_ast["children"][-1]
    assert case_node["type_name"] == "C1"
    assert case_node["type_names"] == ["C1", "C2"]

    # `analysis ac2: AC1, AC2;`（CaseUsage_Invalid.sysml L26）・
    # `use case uc2: UC1, UC2;`（同ファイルL38、同一投稿の並列テストケースで
    # 連鎖的に発見）のように、analysisCaseUsage/useCaseUsageもcaseUsageと
    # 同型のカンマ区切り複数型を取れる（2026-08-29、
    # add_bare_include_shorthand対応中に連鎖的に発見）。
    analysis_ast = parse_sysml_antlr(
        "analysis def AC1;\nanalysis def AC2;\nanalysis ac2: AC1, AC2;\n"
    )
    analysis_node = analysis_ast["children"][-1]
    assert analysis_node["type_name"] == "AC1"
    assert analysis_node["type_names"] == ["AC1", "AC2"]

    use_case_ast = parse_sysml_antlr(
        "use case def UC1;\nuse case def UC2;\nuse case uc2: UC1, UC2;\n"
    )
    use_case_node = use_case_ast["children"][-1]
    assert use_case_node["type_name"] == "UC1"
    assert use_case_node["type_names"] == ["UC1", "UC2"]

    constraint_ast = parse_sysml_antlr(
        "constraint def AConstraint;\nconstraint def ABlock;\n"
        "assert constraint two_types : AConstraint, ABlock;\n"
    )
    constraint_node = constraint_ast["children"][-1]["children"][0]
    assert constraint_node["type_name"] == "AConstraint"
    assert constraint_node["type_names"] == ["AConstraint", "ABlock"]

    individual_ast = parse_sysml_antlr(
        "part def A_1;\npart def B_1;\nindividual two_types : A_1, B_1;\n"
    )
    individual_node = individual_ast["children"][-1]
    assert individual_node["type_name"] == "A_1"
    assert individual_node["type_names"] == ["A_1", "B_1"]

    occurrence_ast = parse_sysml_antlr(
        "part def PartDef;\noccurrence twoTypes: PartDef, Real;\n"
    )
    occurrence_node = occurrence_ast["children"][-1]
    assert occurrence_node["type_name"] == "PartDef"
    assert occurrence_node["type_names"] == ["PartDef", "Real"]

    port_ast = parse_sysml_antlr(
        "port def pd1;\nport def pd2;\npart def P { port two_port_def_types: pd1, pd2; }\n"
    )
    port_node = port_ast["children"][-1]["children"][-1]
    assert port_node["type_name"] == "pd1"
    assert port_node["type_names"] == ["pd1", "pd2"]

    requirement_ast = parse_sysml_antlr(
        "requirement def R1def;\nrequirement def R2def;\n"
        "requirement r12 : R1def, R2def;\n"
    )
    requirement_node = requirement_ast["children"][-1]
    assert requirement_node["type_name"] == "R1def"
    assert requirement_node["type_names"] == ["R1def", "R2def"]

    # 単一型の既存の形も壊れていないことを確認する（type_namesキーは
    # 2件以上のときのみ現れる）。
    single_ast = parse_sysml_antlr("part def A;\npart p : A;\n")
    single_node = single_ast["children"][-1]
    assert single_node["type_name"] == "A"
    assert "type_names" not in single_node


def test_antlr_perform_action_with_type_clause():
    """`perform action performLunarMission : PerformLunarMission;`
    （MissionPackage.sysml）のように、`action`キーワード付きperform action
    文にも型節が付くことがある（従来は型節を全く持たなかった。2026-08-28、
    730件パース失敗の要因分析で発見）。型節追加により裸参照形
    （`perform X;`）との判別が壊れていないことも確認する（`typeRef`と
    無ラベルの裸参照が同じnamespacePathルールを共有するため、
    `hasActionKeyword`という専用ラベルで判別している）。"""
    typed_ast = parse_sysml_antlr(
        "action def PerformLunarMission;\n"
        "part def P { perform action performLunarMission : PerformLunarMission; }\n"
    )
    typed_node = typed_ast["children"][-1]["children"][-1]
    assert typed_node["type"] == "perform_action"
    assert typed_node["name"] == "performLunarMission"
    assert typed_node["type_name"] == "PerformLunarMission"

    bare_ref_ast = parse_sysml_antlr(
        "action def SomeAction;\n"
        "part def P { perform SomeAction; }\n"
    )
    bare_ref_node = bare_ref_ast["children"][-1]["children"][-1]
    assert bare_ref_node["type"] == "perform_action"
    assert bare_ref_node["reference"] == "SomeAction"
    assert "name" not in bare_ref_node

    unnamed_untyped_ast = parse_sysml_antlr("part def P { perform action { } }")
    unnamed_untyped_node = unnamed_untyped_ast["children"][-1]["children"][-1]
    assert unnamed_untyped_node["name"] is None
    assert unnamed_untyped_node["type_name"] is None


def test_antlr_bodyless_package_forward_declaration():
    """`package 'Application Layer';`（DependencyTest.sysml）のように、
    本体`{}`を持たないpackage宣言が未対応だった（従来はpackageに常に
    `{ ... }`本体を要求していた。2026-08-28、730件パース失敗の要因分析で
    発見。コーパス全体で6件のパース失敗の直接原因）。"""
    ast = parse_sysml_antlr(
        "package DependencyTest {\n"
        "    package 'Application Layer';\n"
        "    package 'Service Layer';\n"
        "}\n"
    )
    app_layer, service_layer = ast["children"]
    assert app_layer == {"type": "package", "name": "Application Layer", "shortName": None, "children": []}
    assert service_layer["name"] == "Service Layer"
    assert service_layer["children"] == []

    # 本体ありの既存形も壊れていないことを確認する。
    with_body_ast = parse_sysml_antlr("package Outer { package Inner { part def X; } }")
    inner = with_body_ast["children"][0]
    assert inner["name"] == "Inner"
    assert len(inner["children"]) == 1


def test_antlr_concern_stakeholder_usage():
    """`stakeholder s : S;`（concern def本体内のstakeholder宣言）が
    未実装だった（2026-08-28、730件パース失敗の要因分析で発見。コーパス
    全体で6件のパース失敗の直接原因）。再現: ViewTest.sysml
    `concern def C { subject; stakeholder s : S; }`。subjectUsageと
    同型の設計。"""
    ast = parse_sysml_antlr(
        "part def S;\n"
        "concern def C {\n"
        "    subject;\n"
        "    stakeholder s : S;\n"
        "}\n"
    )
    stakeholder_node = ast["children"][-1]["children"][-1]
    assert stakeholder_node["type"] == "stakeholder_usage"
    assert stakeholder_node["name"] == "s"
    assert stakeholder_node["type_name"] == "S"

    bare_ast = parse_sysml_antlr("concern def C { stakeholder s1; }")
    bare_node = bare_ast["children"][-1]["children"][-1]
    assert bare_node["type"] == "stakeholder_usage"
    assert bare_node["name"] == "s1"
    assert bare_node["type_name"] is None


def test_antlr_send_action_new_expression_payload():
    """`action publish send new Publish(someTopic, somePublication) via
    publicationPort;`（ServerSequenceOutsideRealization-2.sysml）のように、
    sendActionStmtのpayloadが`new Type(args)`オブジェクト生成式を取る形が
    未対応だった。named形には`via`節も先頭の裸`then`（直前ノードとの暗黙の
    連鎖）も無かった（`then action sendFuelCommand send new FuelCommand()
    to engine_a;`、Interaction Realization-1.sysml参照）。2026-08-28、
    730件パース失敗の要因分析で発見。既存の文字列ベースpayload（namespacePath
    参照）との互換性も確認する。"""
    named_new_via_ast = parse_sysml_antlr(
        "action def A {\n"
        "    action publish send new Publish(someTopic, somePublication) via publicationPort;\n"
        "}\n"
    )
    named_new_via_node = named_new_via_ast["children"][0]["children"][0]
    assert named_new_via_node["type"] == "send_action"
    assert named_new_via_node["name"] == "publish"
    assert named_new_via_node["payload"] == {
        "type": "new_instance",
        "name": "Publish",
        "arguments": [
            {"type": "positional_argument", "value": {"type": "name_ref", "reference": "someTopic"}, "children": []},
            {"type": "positional_argument", "value": {"type": "name_ref", "reference": "somePublication"}, "children": []},
        ],
        "children": [],
    }
    assert named_new_via_node["receiver"] == "publicationPort"
    assert named_new_via_node["receiver_type"] == "via"

    then_named_new_to_ast = parse_sysml_antlr(
        "action def A {\n"
        "    action a1 { }\n"
        "    then action sendFuelCommand send new FuelCommand() to engine_a;\n"
        "}\n"
    )
    then_node = then_named_new_to_ast["children"][0]["children"][1]
    assert then_node["name"] == "sendFuelCommand"
    assert then_node["payload"]["type"] == "new_instance"
    assert then_node["payload"]["name"] == "FuelCommand"
    assert then_node["receiver"] == "engine_a"
    assert then_node["receiver_type"] == "to"
    assert then_node["isThen"] is True

    anonymous_new_ast = parse_sysml_antlr("action def A { send new SetSpeed() to vehicle_a; }")
    anonymous_node = anonymous_new_ast["children"][0]["children"][0]
    assert anonymous_node["payload"]["type"] == "new_instance"
    assert anonymous_node["payload"]["name"] == "SetSpeed"
    assert anonymous_node["target"] == "vehicle_a"
    assert anonymous_node["target_type"] == "to"

    # 既存の文字列ベースpayload（namespacePath参照）との互換性を確認する。
    plain_named_ast = parse_sysml_antlr("action def A { action snd send x to y; }")
    plain_named_node = plain_named_ast["children"][0]["children"][0]
    assert plain_named_node["payload"] == "x"
    assert plain_named_node["receiver"] == "y"
    assert plain_named_node["receiver_type"] == "to"


def test_antlr_sendaction_anonymous_then_prefix():
    """`then send new Show(shoot.picture) to screen;`（Messaging
    Example.sysml）・`then send new Show(shoot.picture) via displayPort;`
    （Messaging with Ports.sysml）・`then send new S() to b;`（ActionTest.sysml）
    のように、sendActionStmtの匿名形（`action`キーワード・名前を伴わない
    `send ...;`）にも、named形と同じ先頭の裸`then`（直前ノードとの暗黙の
    連鎖）を持ちうる（従来named形にしか無かった）。2026-08-29、730件
    ベースライン154件エラー要因分析で発見。"""
    to_ast = parse_sysml_antlr("action def A { then send new Show(x) to screen; }")
    to_node = to_ast["children"][0]["children"][0]
    assert to_node["type"] == "send_action"
    assert to_node["name"] is None
    assert to_node["target"] == "screen"
    assert to_node["target_type"] == "to"
    assert to_node["isThen"] is True

    via_ast = parse_sysml_antlr("action def A { then send new Show(x) via displayPort; }")
    via_node = via_ast["children"][0]["children"][0]
    assert via_node["target_type"] == "via"
    assert via_node["isThen"] is True

    # 既存の`then`無し匿名形が引き続き機能し、"isThen"キー自体が無いことを
    # 確認する（回帰防止）。
    plain_ast = parse_sysml_antlr("action def A { send new S() to b; }")
    plain_node = plain_ast["children"][0]["children"][0]
    assert "isThen" not in plain_node


def test_antlr_sendactionstmt_named_body():
    """`action snd send { in :>> payload = s; }`（ActionTest.sysml）の
    ように、sendActionStmtのnamed形はpayload/target（to/via）をインライン
    ではなく、actionParameter形の宣言（`in :>> payload = s;`）を並べた
    bodyで表すこともある（従来named形はインラインpayload+to/via必須
    だった）。2026-08-29、730件ベースライン154件エラー要因分析で発見。"""
    ast = parse_sysml_antlr(
        "action a2 { in s : S; action snd send { in :>> payload = s; } }"
    )
    node = ast["children"][0]["children"][-1]
    assert node["type"] == "send_action"
    assert node["name"] == "snd"
    assert node["payload"] is None
    assert node["receiver"] is None
    assert len(node["params"]) == 1
    param = node["params"][0]
    assert param["type"] == "param"
    assert param["redefines"] == [{"kind": "redefines", "target": "payload"}]
    assert param["value"] == {"type": "name_ref", "reference": "s"}

    # 既存のインライン形が引き続き機能することを確認する（回帰防止）。
    inline_ast = parse_sysml_antlr("action def A { action snd send x to y; }")
    inline_node = inline_ast["children"][0]["children"][0]
    assert inline_node["payload"] == "x"
    assert inline_node["receiver"] == "y"


def test_antlr_sendactionstmt_via_to_combined():
    """`action snd2 send via this to aa.target;`（ActionTest.sysml）の
    ように、sendActionStmtのnamed形はpayloadを省略し、`via <port>`と
    `to <target>`を併記することもある（従来`to`/`via`は排他選択かつ
    payload必須だった）。2026-08-29、730件ベースライン154件エラー要因
    分析で発見。"""
    ast = parse_sysml_antlr(
        "action a2 { action aa { out part target; } "
        "action snd2 send via this to aa.target; }"
    )
    node = ast["children"][0]["children"][-1]
    assert node["type"] == "send_action"
    assert node["name"] == "snd2"
    assert node["payload"] is None
    assert node["receiver"] == "aa.target"
    assert node["receiver_type"] == "to"
    assert node["via"] == "this"

    # 既存の`to`/`via`単独選択形が引き続き機能し、"via"キー自体が無いことを
    # 確認する（回帰防止）。
    plain_ast = parse_sysml_antlr("action def A { action snd send x to y; }")
    plain_node = plain_ast["children"][0]["children"][0]
    assert "via" not in plain_node


def test_antlr_quoted_name_type_reference():
    """`use case 'provide transportation' : 'Provide Transportation' { }`
    （Use Case Usage Example.sysml）・`action 'provide power' :
    'Provide Power' { }`（3a-Function-based Behavior-1.sysml）・
    `individual reference : 'Temporal-Spatial Reference_ID1' { }`
    （6-Individual and Snapshots.sysml）・`state 'perform self test' :
    'Perform Self Test' { }`（5-State-based Behavior-1.sysml）のように、
    useCaseUsage/actionUsageStmt/individualUsage/stateUsageの型節が
    プレーンIDしか受け付けず、QUOTED_NAME（スペース入り型名）で
    'mismatched input ... expecting ID'となっていた。type_nameは
    self.types/self.symbolsのキー（引用符無し）と一致させるため、
    QUOTED_NAMEの引用符を剥がした値になる必要がある。2026-08-28、
    730件パース失敗の要因分析で発見。individualUsageは同時に
    `{ ... }`body（それまで無かった）にも対応させた。"""
    use_case_ast = parse_sysml_antlr(
        "use case def 'Provide Transportation';\n"
        "use case 'provide transportation' : 'Provide Transportation' { }\n"
    )
    use_case_node = use_case_ast["children"][-1]
    assert use_case_node["type"] == "use_case_usage"
    assert use_case_node["name"] == "provide transportation"
    assert use_case_node["type_name"] == "Provide Transportation"

    action_ast = parse_sysml_antlr(
        "action def 'Provide Power';\n"
        "part def P { action 'provide power' : 'Provide Power' { } }\n"
    )
    action_node = action_ast["children"][-1]["children"][0]
    assert action_node["type"] == "action_usage"
    assert action_node["name"] == "provide power"
    assert action_node["type_name"] == "Provide Power"

    # プレーンIDの型参照（既存挙動）が引き続き機能することも確認する。
    action_plain_ast = parse_sysml_antlr("action def X; part def P { action a : X; } ")
    action_plain_node = action_plain_ast["children"][-1]["children"][0]
    assert action_plain_node["type_name"] == "X"

    individual_ast = parse_sysml_antlr(
        "part def 'Temporal-Spatial Reference_ID1';\n"
        "part def P { individual reference : 'Temporal-Spatial Reference_ID1' { attribute x; } }\n"
    )
    individual_node = individual_ast["children"][-1]["children"][0]
    assert individual_node["type"] == "individual_usage"
    assert individual_node["name"] == "reference"
    assert individual_node["type_name"] == "Temporal-Spatial Reference_ID1"
    assert len(individual_node["children"]) == 1

    # 複数型参照（extraTypeRefs）とbody無し（`;`終端）の既存挙動も確認する。
    individual_plain_ast = parse_sysml_antlr(
        "part def A_1; part def B_1; individual two_types : A_1, B_1;"
    )
    individual_plain_node = individual_plain_ast["children"][-1]
    assert individual_plain_node["type_name"] == "A_1"
    assert individual_plain_node["type_names"] == ["A_1", "B_1"]

    state_ast = parse_sysml_antlr(
        "state def 'Perform Self Test';\n"
        "part def P { state 'perform self test' : 'Perform Self Test' { } }\n"
    )
    state_node = state_ast["children"][-1]["children"][0]
    assert state_node["type"] == "state_usage"
    assert state_node["name"] == "perform self test"
    assert state_node["type_name"] == "Perform Self Test"


def test_antlr_perform_bare_reference_with_body():
    """`perform illuminateRegion.sendOnOffCmd { out onOffCmd =
    onOffCmdPort.onOffCmd; }`（Flashlight Example.sysml）のように、
    `action`キーワードを伴わない裸参照形のperformにも、`action`キーワード
    付き形と同型の`{ ... }`bodyが続くことがある。従来は`;`終端か
    redefines節にしか対応していなかった。2026-08-28、730件パース失敗の
    要因分析で発見。既存の裸参照形（body無し）との共存も確認する。"""
    ast = parse_sysml_antlr(
        "action def A {\n"
        "    action illuminateRegion {\n"
        "        action sendOnOffCmd { out onOffCmd: OnOffCmd; }\n"
        "    }\n"
        "    part user {\n"
        "        port onOffCmdPort: OnOffCmdPort;\n"
        "        perform illuminateRegion.sendOnOffCmd {\n"
        "            out onOffCmd = onOffCmdPort.onOffCmd;\n"
        "        }\n"
        "    }\n"
        "}\n"
    )
    part_user = ast["children"][0]["children"][1]
    node = part_user["children"][-1]
    assert node["type"] == "perform_action"
    assert node["reference"] == "illuminateRegion::sendOnOffCmd"
    assert node["redefines"] == []
    assert node["params"] == [
        {
            "type": "param",
            "direction": "out",
            "is_item": False,
            "kind": None,
            "visibility": None,
            "name": "onOffCmd",
            "type_spec": None,
            "type_name": None,
            "multiplicity": None,
            "redefines": [],
            "value": {"type": "name_ref", "reference": "onOffCmdPort.onOffCmd"},
            "defaultValue": None,
            "children": [],
        },
    ]
    assert node["children"] == []

    # 既存の裸参照形（body無し、`;`終端）との共存を確認する。
    bare_ast = parse_sysml_antlr("part def P { perform y; }")
    bare_node = bare_ast["children"][0]["children"][-1]
    assert bare_node == {
        "type": "perform_action", "reference": "y", "redefines": [], "params": [], "children": [],
    }


def test_antlr_action_parameter_inline_metadata_annotation():
    """`in dt : TimeValue { @ToolVariable { name = "deltaT"; } }`
    （AnalysisAnnotation.sysml、AnnotationTest.sysml）のように、action
    usageのin/out/inoutパラメータ宣言の型節直後のbodyに、`@Type { ... }`
    ショートハンド形のインラインメタデータ注釈が続くことがある。従来は
    actionParameterのbody（`documentationStmt | bareDocComment |
    actionParameter`）にmetadataUsageが含まれておらず未対応だった。
    2026-08-28、730件パース失敗の要因分析で発見。既存のdoc本体・
    ネストしたactionParameter（`in calc calculation { in x; }`）との
    共存も確認する。"""
    ast = parse_sysml_antlr(
        'action def A { in dt : TimeValue { @ToolVariable { name = "deltaT"; } } }'
    )
    param = ast["children"][0]["params"][0]
    assert param["name"] == "dt"
    assert param["type_name"] == "TimeValue"
    assert param["children"] == [
        {
            "type": "metadata_usage",
            "name": "ToolVariable",
            "shortName": None,
            "inheritance": None,
            "isAbstract": False,
            "children": [
                {
                    "type": "feature_usage",
                    "name": "name",
                    "type_name": None,
                    "multiplicity": None,
                    "inheritance": None,
                    "isAbstract": False,
                    "isConstant": False,
                    "isRef": False,
                    "visibility": None,
                    "redefines": [],
                    "prefixMetadata": [],
                    "value": {"type": "literal", "literal_type": "string", "value": "deltaT"},
                    "defaultValue": None,
                    "variability": None,
                    "children": [],
                },
            ],
        },
    ]

    # doc本体・ネストしたactionParameterとの共存確認。
    doc_and_nested_ast = parse_sysml_antlr(
        "action def A { in calc calculation { doc /* x */ in x; } }"
    )
    doc_and_nested_param = doc_and_nested_ast["children"][0]["params"][0]
    assert doc_and_nested_param["name"] == "calculation"
    assert len(doc_and_nested_param["children"]) == 2
    assert doc_and_nested_param["children"][1]["type"] == "param"
    assert doc_and_nested_param["children"][1]["name"] == "x"


def test_antlr_assignment_operator_colon_equals():
    """`attribute i : ScalarValues::Integer := 0;`（StructuredControlTest.sysml、
    AssignmentTest.sysml）・`out attribute positions :> ISQ::length[*] :=
    ( );`（Assignment Example.sysml）のように、attributeUsage・
    actionParameterの初期値代入節が`=`しか受理せず、別形式の`:=`代入演算子
    （KerMLのFeatureValue、下流で再定義可能な初期値）を受理できなかった。
    2026-08-28、730件パース失敗の要因分析で発見。`:=`は`=`と全く同じAST
    形状（valueフィールドのみ）を生成する（assignmentStmtとは異なり演算子
    自体は区別しない）。既存の`=`との共存も確認する。"""
    attr_ast = parse_sysml_antlr(
        "attribute def Integer; part def P { attribute count : Integer := 0; }"
    )
    attr_node = attr_ast["children"][-1]["children"][0]
    assert attr_node["type"] == "attribute_usage"
    assert attr_node["name"] == "count"
    assert attr_node["value"] == {"type": "literal", "literal_type": "int", "value": 0}

    attr_eq_ast = parse_sysml_antlr(
        "attribute def Integer; part def P { attribute count : Integer = 0; }"
    )
    attr_eq_node = attr_eq_ast["children"][-1]["children"][0]
    assert attr_eq_node["value"] == {"type": "literal", "literal_type": "int", "value": 0}

    # 型節無しの裸形（`private attribute position := initialPosition;`）。
    attr_no_type_ast = parse_sysml_antlr("part def P { private attribute position := x; }")
    attr_no_type_node = attr_no_type_ast["children"][-1]["children"][0]
    assert attr_no_type_node["name"] == "position"
    assert attr_no_type_node["value"] == {"type": "name_ref", "reference": "x"}

    param_ast = parse_sysml_antlr(
        "action def A { out attribute positions :> ISQ::length[*] := (); } "
    )
    param_node = param_ast["children"][0]["params"][0]
    assert param_node["type"] == "param"
    assert param_node["name"] == "positions"
    assert param_node["value"] == {"type": "sequence", "elements": [], "children": []}


def test_antlr_verify_requirement_usage():
    """`verify requirement : R;`（無名の型付きインライン宣言）・`verify
    requirement massRequirement : MassRequirement;`（有名、
    9-Verification-simplified.sysml）・`verify r;`（既存requirement
    usageへの裸参照）・`verify vehicleSpec by VehicleTest;`（`by`節付き、
    diagnostics.test.ts）・`verify vehicleMassRequirement :>>
    massRequirement;`（redefine節付き、同ファイル）のように、`verify`
    requirement usage形が全く未実装だった。`requirement`キーワードの
    有無で「型付きインライン宣言」と「既存usageへの裸参照（by/redefine/
    body任意）」の2代替を判別する。2026-08-28、730件パース失敗の要因分析
    で発見。"""
    typed_named_ast = parse_sysml_antlr(
        "requirement def R; verification def V { objective { "
        "verify requirement massRequirement : R; } }"
    )
    typed_named_node = typed_named_ast["children"][-1]["children"][0]["children"][0]
    assert typed_named_node == {
        "type": "verify_requirement_usage",
        "name": "massRequirement",
        "type_name": "R",
        "by": None,
        "redefines": [],
        "children": [],
    }

    typed_anon_ast = parse_sysml_antlr(
        "requirement def R; verification def V { objective { verify requirement : R; } }"
    )
    typed_anon_node = typed_anon_ast["children"][-1]["children"][0]["children"][0]
    assert typed_anon_node["name"] is None
    assert typed_anon_node["type_name"] == "R"

    bare_ast = parse_sysml_antlr(
        "requirement r; verification def V { objective { verify r; } }"
    )
    bare_node = bare_ast["children"][-1]["children"][0]["children"][0]
    assert bare_node == {
        "type": "verify_requirement_usage",
        "name": "r",
        "type_name": None,
        "by": None,
        "redefines": [],
        "children": [],
    }

    by_ast = parse_sysml_antlr(
        "requirement vehicleSpec; case def VehicleTest; verification def V { "
        "objective { verify vehicleSpec by VehicleTest; } } "
    )
    by_node = by_ast["children"][-1]["children"][0]["children"][0]
    assert by_node == {
        "type": "verify_requirement_usage",
        "name": "vehicleSpec",
        "type_name": None,
        "by": "VehicleTest",
        "redefines": [],
        "children": [],
    }

    redefine_ast = parse_sysml_antlr(
        "requirement r1; requirement r2; verification def V { objective { "
        "verify r1 :>> r2; } } "
    )
    redefine_node = redefine_ast["children"][-1]["children"][0]["children"][0]
    assert redefine_node["name"] == "r1"
    assert redefine_node["redefines"] == [{"kind": "redefines", "target": "r2"}]


def test_antlr_view_expose_and_filter():
    """`expose TrafficLightIntersection::intersectionInstance;`・`filter
    @SysML::PartUsage or @SysML::PartDefinition or @SysML::PortUsage or
    @SysML::PortDefinition;`（Views.sysml、elan8-sysml-examples）のように、
    view/viewpoint本体でexposeStmt/filterStmtが使われる。従来
    exposeStmtはpackageBodyElementにしか登録されておらず（viewUsageの
    body＝partBodyElement内では未対応）、filterStmt自体・式コンテキストの
    `@Type`メタデータ参照式（metadataRefExpr）はいずれも完全に未実装
    だった。2026-08-28、730件パース失敗の要因分析で発見。"""
    ast = parse_sysml_antlr(
        "view structure : GeneralView {\n"
        "    expose Pkg::instance;\n"
        "    filter @SysML::PartUsage or @SysML::PartDefinition;\n"
        "}\n"
    )
    view_node = ast["children"][0]
    assert view_node["type"] == "view_usage"
    expose_node = view_node["children"][0]
    assert expose_node == {
        "type": "special_stmt",
        "children": [
            {
                "type": "expose",
                "qualified_name": "Pkg::instance",
                "wildcard": False,
                "children": [],
            },
        ],
    }
    filter_node = view_node["children"][1]
    assert filter_node == {
        "type": "special_stmt",
        "children": [
            {
                "type": "filter",
                "expression": {
                    "type": "binary_expr",
                    "op": "or",
                    "left": {"type": "metadata_ref", "reference": "SysML::PartUsage"},
                    "right": {"type": "metadata_ref", "reference": "SysML::PartDefinition"},
                },
                "children": [],
            },
        ],
    }


def test_antlr_viewusage_quoted_type_ref():
    """`view batmobileParts : 'Part list' { ... }`（DontPanic-SysMLv2-
    Batmobile.sysml L252）・`view 'vehicle structure view' : 'Part
    Structure View' { ... }`（Views Example.sysml L11）のように、
    viewUsageの型節が記号を含む名前をQUOTED_NAME形式で書いた型参照を
    取ることがある（従来`ID`単体決め打ちだった）。既存のID型が引き続き
    機能することも確認する。2026-08-31、add_viewusage_quoted_type_ref
    対応中に発見。"""
    ast = parse_sysml_antlr(
        "part def P { view batmobileParts : 'Part list' { } }"
    )
    node = ast["children"][0]["children"][0]
    assert node["type"] == "view_usage"
    assert node["name"] == "batmobileParts"
    assert node["type_name"] == "Part list"

    # 既存のID型が引き続き機能することを確認する。
    plain_ast = parse_sysml_antlr("part def P { view v : Ordinary { } }")
    plain_node = plain_ast["children"][0]["children"][0]
    assert plain_node["type_name"] == "Ordinary"


def test_antlr_packagebodyelement_bare_filter_stmt():
    """`package 'Safety Features' { public import vehicle::**; filter
    @Safety; }`（Filtering Example-1.sysml）のように、`filterStmt`は
    view/viewpoint本体（partBodyElement経由）だけでなく、パッケージ本体
    直下にも単独で書ける（従来packageBodyElementに未登録だった）。
    2026-08-29、730件ベースライン154件エラー要因分析で発見。"""
    ast = parse_sysml_antlr(
        "package Outer {\n"
        "    package 'Safety Features' {\n"
        "        public import vehicle::**;\n"
        "        filter @Safety;\n"
        "    }\n"
        "}\n"
    )
    inner_pkg = ast["children"][0]
    assert inner_pkg["type"] == "package"
    assert inner_pkg["name"] == "Safety Features"
    filter_node = inner_pkg["children"][1]
    assert filter_node == {
        "type": "special_stmt",
        "children": [
            {
                "type": "filter",
                "expression": {"type": "metadata_ref", "reference": "Safety"},
                "children": [],
            },
        ],
    }


def test_antlr_bracket_multiplicity_after_type_clause():
    """`timeslice asPresident : Person [0..*] { ... }`（型節の後に多重度）・
    `timeslice item UnitedStatesWhenJohnIsPresident[*] : UnitedStates
    { ... }`（`timeslice`直後にusage種別キーワード`item`）・`ref
    presidentOfCountry[0..1] : Person :> presidentOfCountry.asPresident;`
    （featureUsageの型節の前に多重度）（いずれもJohnIndividualExample.sysml）
    のように、`[`による多重度指定がportionUsageStmt/featureUsageの一部の
    位置で受理されなかった。2026-08-28、730件パース失敗の要因分析で発見。
    portionUsageStmt/actionUsageStmt等と同型のpreMult/postMult順序を適用
    する。"""
    postmult_ast = parse_sysml_antlr(
        "item def Person; part def P { timeslice asPresident : Person [0..*] { } }"
    )
    postmult_node = postmult_ast["children"][-1]["children"][0]
    assert postmult_node["type"] == "portion_usage"
    assert postmult_node["kind"] == "timeslice"
    assert postmult_node["subKind"] is None
    assert postmult_node["type_name"] == "Person"
    assert postmult_node["multiplicity"] == {
        "size": {"min": 0, "max": "*"},
        "is_ordered": False,
        "is_unique": True,
    }

    subkind_ast = parse_sysml_antlr(
        "item def UnitedStates; individual UnitedStatesWithJohnAsPresident : UnitedStates "
        "{ timeslice item UnitedStatesWhenJohnIsPresident[*] : UnitedStates { } }"
    )
    subkind_node = subkind_ast["children"][-1]["children"][0]
    assert subkind_node["subKind"] == "item"
    assert subkind_node["name"] == "UnitedStatesWhenJohnIsPresident"
    assert subkind_node["type_name"] == "UnitedStates"

    feature_ast = parse_sysml_antlr(
        "item def Person; item def Country { ref presidentOfCountry[0..1] : Person "
        ":> presidentOfCountry.asPresident; }"
    )
    feature_node = feature_ast["children"][-1]["children"][0]
    assert feature_node["type"] == "feature_usage"
    assert feature_node["name"] == "presidentOfCountry"
    assert feature_node["type_name"] == "Person"
    assert feature_node["multiplicity"] == {
        "size": {"min": 0, "max": 1},
        "is_ordered": False,
        "is_unique": True,
    }
    assert feature_node["redefines"] == [
        {"kind": "subsets", "target": "presidentOfCountry::asPresident"}
    ]

    # 既存の型節後の多重度形（featureUsage）が引き続き機能することも確認する。
    feature_postmult_ast = parse_sysml_antlr(
        "item def Person; item def Country { ref presidents : Person [0..1]; }"
    )
    feature_postmult_node = feature_postmult_ast["children"][-1]["children"][0]
    assert feature_postmult_node["multiplicity"] == {
        "size": {"min": 0, "max": 1},
        "is_ordered": False,
        "is_unique": True,
    }


def test_antlr_enum_literal_bare_redefine_shorthand():
    """`enum red { :>> val = 0; }`（EnumerationTest.sysml）のように、
    enumLiteralの本体内で継承した属性を再定義する裸の`:>> name = expr;`
    値束縛リデファイン文（valueBindingStmt）が使われる。partBodyElement等
    では既にvalueBindingStmtを含んでいたが、enumBodyElementには未登録
    だった。2026-08-28、730件パース失敗の要因分析で発見。"""
    ast = parse_sysml_antlr(
        "attribute def Color { attribute val : ScalarValues::Natural; }\n"
        "enum def ColorKind :> Color {\n"
        "    enum red { :>> val = 0; }\n"
        "    enum blue { :>> val = 1; }\n"
        "}\n"
    )
    enum_def = ast["children"][1]
    assert enum_def["type"] == "enum_def"
    red_literal = enum_def["children"][0]
    assert red_literal["type"] == "enum_literal"
    assert red_literal["name"] == "red"
    assert red_literal["children"] == [
        {
            "type": "value_binding",
            "kind": "redefines",
            "target": "val",
            "value": {"type": "literal", "literal_type": "int", "value": 0},
            "children": [],
        },
    ]


def test_antlr_valuebindingstmt_walrus_assign_operator():
    """`:>> problemStatement := "As a Hero, Batman needs a cool vehicle.";`
    （DontPanic-SysMLv2-Batmobile.sysml L79-80）のように、valueBindingStmt
    （`:>> target = expr;`という値束縛リデファイン文）は`=`だけでなく
    `:=`代入演算子も使える（他の多くのfeatureUsage系規則では既に両方
    許可しているのと同型）。既存の`=`形が引き続き機能することも確認
    する。2026-08-31、add_valuebindingstmt_walrus_assign_operator対応中に
    発見。"""
    ast = parse_sysml_antlr(
        'part def P { :>> problemStatement := "As a Hero"; }'
    )
    node = ast["children"][0]["children"][0]
    assert node["type"] == "value_binding"
    assert node["kind"] == "redefines"
    assert node["target"] == "problemStatement"
    assert node["value"] == {"type": "literal", "literal_type": "string", "value": "As a Hero"}

    # 既存の`=`形が引き続き機能することを確認する。
    equals_ast = parse_sysml_antlr('part def P { :>> problemStatement = "As a Hero"; }')
    equals_node = equals_ast["children"][0]["children"][0]
    assert equals_node["value"] == {"type": "literal", "literal_type": "string", "value": "As a Hero"}


def test_antlr_enumusage_and_anonymous_literal():
    """`enum color : ColorKind;`・`enum color1 = ColorKind::blue;`・
    `enum size: SizeChoice = 60.0;`（EnumerationTest.sysml）のように、
    package/part本体直下では`enum def`ではなく`enum`単体キーワードで
    既存のenum定義から値を導入するEnumerationUsageが使われる（従来
    `enumDef`しか存在しなかった）。`= 60.0;`（同、`enum def SizeChoice
    { = 60.0; = 70.0; = 80.0; }`の各行）のように、enumLiteralの値代入形
    は名前自体を省略した無名リテラルも取りうる（従来simpleNameが必須
    だった）。2026-08-29、730件ベースライン154件エラー要因分析で発見。"""
    typed_ast = parse_sysml_antlr("enum def ColorKind; enum color : ColorKind;")
    typed_node = typed_ast["children"][-1]
    assert typed_node["type"] == "enum_usage"
    assert typed_node["name"] == "color"
    assert typed_node["type_name"] == "ColorKind"
    assert typed_node["value"] is None

    value_ast = parse_sysml_antlr(
        "enum def ColorKind { enum blue; } enum color1 = ColorKind::blue;"
    )
    value_node = value_ast["children"][-1]
    assert value_node["type"] == "enum_usage"
    assert value_node["name"] == "color1"
    assert value_node["type_name"] is None
    assert value_node["value"]["type"] == "name_ref"
    assert value_node["value"]["reference"] == "ColorKind::blue"

    typed_value_ast = parse_sysml_antlr(
        "enum def SizeChoice; enum size: SizeChoice = 60.0;"
    )
    typed_value_node = typed_value_ast["children"][-1]
    assert typed_value_node["type_name"] == "SizeChoice"
    assert typed_value_node["value"] == {"type": "literal", "literal_type": "real", "value": 60.0}

    anon_ast = parse_sysml_antlr(
        "enum def SizeChoice { = 60.0; = 70.0; = 80.0; }"
    )
    anon_children = anon_ast["children"][0]["children"]
    assert len(anon_children) == 3
    for child, expected in zip(anon_children, [60.0, 70.0, 80.0]):
        assert child["type"] == "enum_literal"
        assert child["name"] is None
        assert child["value"] == {"type": "literal", "literal_type": "real", "value": expected}

    # 既存の名前付きリテラルが引き続き機能することを確認する（回帰防止）。
    named_ast = parse_sysml_antlr("enum def E { low = 0.25; }")
    named_node = named_ast["children"][0]["children"][0]
    assert named_node["name"] == "low"


def test_antlr_xpect_multiline_block_comment():
    """`//* XPECT errors --- "..." at "..." --- */`（公式xpectテスト
    フィクスチャの複数行アノテーション規約、Connector_Invalid.sysml等）の
    ように、`//`直後に`*`が続く場合、従来はLINE_COMMENT（`~[\\r\\n]*`で
    その行末までしか消費できない）としてしか扱われず、続く行のアノテー
    ション本文（引用文字列等）がトークンとして漏れ出し、`--- */`直後の
    実コードへのパースエラーを引き起こしていた。2026-08-28、730件パース
    失敗の要因分析で発見（以前から既知の問題）。対応する`*/`までを1つの
    複数行コメントとして読み飛ばす専用字句規則で解消する。"""
    ast = parse_sysml_antlr(
        "package P {\n"
        "    part def A { part x; }\n"
        "    part def B {\n"
        "        part y { part z; }\n"
        "        //* XPECT errors ---\n"
        "            \"Must be an accessible feature\" at \"A::x\"\n"
        "        --- */\n"
        "        part w;\n"
        "    }\n"
        "}\n"
    )
    part_def_b = ast["children"][1]
    assert part_def_b["type"] == "part_def"
    assert part_def_b["name"] == "B"
    child_names = [c["name"] for c in part_def_b["children"]]
    assert child_names == ["y", "w"]

    # 単一行の`// XPECT errors --> "..." at "..."`（既存挙動）が引き続き
    # 機能することも確認する。
    single_line_ast = parse_sysml_antlr(
        "part def A {\n"
        "    // XPECT errors --> \"some message\" at \"x\"\n"
        "    part x;\n"
        "}\n"
    )
    assert single_line_ast["children"][0]["children"][0]["name"] == "x"


def test_antlr_nested_occurrence_def_in_partbody():
    """`part AHFN_LocalCloudDD_Seqs = ... { occurrence def
    APIS_transfer_lifetime { ... } }`（AHFSequences.sysml）のように、
    `occurrence def`自体もpartDef/stateDef/actionDefと同型にpartBodyElement
    内へネストして書ける。従来occurrenceDefはpartBodyElementの代替に
    登録されておらず未対応だった。2026-08-29、235件パース失敗の要因分析
    で発見。"""
    ast = parse_sysml_antlr(
        "part def P { occurrence def Nested { attribute x; } }"
    )
    nested = ast["children"][0]["children"][0]
    assert nested["type"] == "occurrence_def"
    assert nested["name"] == "Nested"
    assert nested["children"] == [
        {
            "type": "attribute_usage",
            "name": "x",
            "shortName": None,
            "type_name": None,
            "multiplicity": None,
            "inheritance": None,
            "isAbstract": False,
            "isConstant": False,
            "isDerived": False,
            "isRef": False,
            "visibility": None,
            "redefines": [],
            "prefixMetadata": [],
            "value": None,
            "defaultValue": None,
            "variability": None,
            "children": [],
        },
    ]


def test_antlr_nested_requirement_def_in_requirement_body():
    """`requirement def R { ... requirement def <'1'> A { ... } }`
    （RequirementTest.sysml）のように、requirementDef自体もrequirementBody
    Element（=partBodyElementに委譲）内へネストして書ける。従来
    requirementDefはpartBodyElementの代替に登録されておらず未対応
    だった（occurrenceDefと同型のギャップ）。2026-08-29、235件パース
    失敗の要因分析で発見。"""
    ast = parse_sysml_antlr(
        "requirement def R { requirement def <'1'> A { doc /* x */ } }"
    )
    nested = ast["children"][0]["children"][0]
    assert nested["type"] == "requirement_def"
    assert nested["name"] == "A"
    assert len(nested["children"]) == 1
    assert nested["children"][0]["type"] == "documentation"


def test_antlr_connectionusage_named_typed_inline_connect():
    """`connection link : DataLink connect tx.txPort to rx.rxPort;`
    （dfa-coverage-advanced.sysml）のように、名前と型節の両方を持つ
    connectionUsageにインライン（本体`{}`なし）の`connect...to...`が
    続く形が未対応だった（interfaceUsageの同型ギャップは対応済みで
    非対称だった）。2026-08-29、235件パース失敗の要因分析で発見。既存の
    `connect`無し形・型無しキーワード形が引き続き機能することも確認する。"""
    ast = parse_sysml_antlr(
        "part def CommSystem { part tx; part rx; "
        "connection link : DataLink connect tx.txPort to rx.rxPort; }"
    )
    node = ast["children"][0]["children"][2]
    assert node["type"] == "connection_usage"
    assert node["name"] == "link"
    assert node["type_name"] == "DataLink"
    assert node["firstEnd"] == {
        "type": "connector_end",
        "declared_name": None,
        "reference": "tx.txPort",
    }
    assert node["thenEnd"] == {
        "type": "connector_end",
        "declared_name": None,
        "reference": "rx.rxPort",
    }
    assert node["ends"] is None

    # 既存の`connect`無し裸形（名前・型のみ）が引き続き機能することを確認する。
    bare_ast = parse_sysml_antlr(
        "abstract connection connections: Connection[0..*];"
    )
    bare_node = bare_ast["children"][0]
    assert bare_node["type"] == "connection_usage"
    assert bare_node["name"] == "connections"
    assert bare_node["type_name"] == "Connection"
    assert bare_node["firstEnd"] is None
    assert bare_node["thenEnd"] is None


def test_antlr_connectionusage_variant_prefix():
    """`variant connection adoption_certificate_TypeB1 : Adoption_Certificate
    connect (parent1 ::> woman, adoptiveParent_1 ::> adult, certifiedChild
    ::> child);`（family.sysml L217-218、variation part本体内）のように、
    connectionUsage（名前+型節形）はVariability機能の先頭修飾子
    （`variation`/`variant`）を持つことがある（partDef/attributeUsageと
    同型）。2026-08-29、add_connectionusage_variant_prefix対応中に発見。"""
    ast = parse_sysml_antlr(
        "part def P { "
        "variant connection adoption_certificate_TypeB1 : Adoption_Certificate "
        "connect (parent1 ::> woman, adoptiveParent_1 ::> adult, "
        "certifiedChild ::> child); "
        "}"
    )
    node = ast["children"][0]["children"][0]
    assert node["type"] == "connection_usage"
    assert node["name"] == "adoption_certificate_TypeB1"
    assert node["type_name"] == "Adoption_Certificate"
    assert node["variability"] == "variant"
    assert len(node["ends"]) == 3

    # 既存の`variability`無し形が引き続き機能することを確認する。
    plain_ast = parse_sysml_antlr(
        "part def CommSystem { connection link : DataLink connect tx.txPort to rx.rxPort; }"
    )
    plain_node = plain_ast["children"][0]["children"][0]
    assert plain_node["variability"] is None


def test_antlr_messageusage_of_type_with_from_to():
    """`message submitCheckout of CheckoutRequest from storefront.submitSent
    to apiGateway.submitReceived;`（WebShopArchitecture.sysml）のように、
    `messageUsage`が`of Type`ペイロード型節と`from...to`端点節を同時に
    持つことがある。従来`from...to`は`messageStmt`（`from`/`to`必須の
    別構文）側にのみあり、`messageUsage`側は非対応だった。2026-08-29、
    235件パース失敗の要因分析で発見。既存の`of Type`のみの形・裸形が
    引き続き機能することも確認する。"""
    ast = parse_sysml_antlr(
        "part def X { message submitCheckout of CheckoutRequest "
        "from storefront.submitSent to apiGateway.submitReceived; }"
    )
    node = ast["children"][0]["children"][0]
    assert node["type"] == "message_usage"
    assert node["name"] == "submitCheckout"
    assert node["type_name"] == "CheckoutRequest"
    assert node["from_end"] == "storefront::submitSent"
    assert node["to_end"] == "apiGateway::submitReceived"

    # 既存の`of Type`のみ（`from...to`なし）の形が引き続き機能することを確認する。
    of_only_ast = parse_sysml_antlr(
        "part def X { message publish_message of Publish[1]; }"
    )
    of_only_node = of_only_ast["children"][0]["children"][0]
    assert of_only_node["type"] == "message_usage"
    assert of_only_node["type_name"] == "Publish"
    assert of_only_node["from_end"] is None
    assert of_only_node["to_end"] is None

    # 既存の裸形（`of`/`from...to`なし）が引き続き機能することを確認する。
    bare_ast = parse_sysml_antlr(
        "part def X { abstract message messages: Message[0..*] nonunique :> transfers, actions; }"
    )
    bare_node = bare_ast["children"][0]["children"][0]
    assert bare_node["type"] == "message_usage"
    assert bare_node["from_end"] is None
    assert bare_node["to_end"] is None


def test_antlr_messageusage_named_payload_of_clause_and_then_prefix():
    """`message Statement1 of applicableLaw : ApplicableLaw from
    judge.statementOfLaw to adoptiveParent_1.informationOfLaw;`
    （family.sysml L171）のように、`of`節が「型のみ」ではなく
    「名前:型」のnamed payload形を取ることがある。また後続行
    `then message agreementParent1 of agreement : Agreement from ...;`
    （family.sysml L172）のように、直前のmessageに続くsuccession-then
    接頭辞を伴うこともある（従来`messageUsage`には`isThen`が無かった）。
    `messageName`という専用ラベルでこの規則自身の名前を読む必要がある
    （`payloadName`と同じ規則へのラベル無し位置参照は、名前省略時に
    `payloadName`側を誤って拾ってしまう）。2026-08-29、
    add_messageflow_named_payload_of_clause対応中に発見。"""
    ast = parse_sysml_antlr(
        "occurrence def O { "
        "message Statement1 of applicableLaw : ApplicableLaw from a.x to b.y; "
        "then message agreementParent1 of agreement : Agreement from c.x to d.y; "
        "}"
    )
    first, second = ast["children"][0]["children"]
    assert first["type"] == "message_usage"
    assert first["name"] == "Statement1"
    assert first["type_name"] == "ApplicableLaw"
    assert first["payload_name"] == "applicableLaw"
    assert "isThen" not in first

    assert second["type"] == "message_usage"
    assert second["name"] == "agreementParent1"
    assert second["type_name"] == "Agreement"
    assert second["payload_name"] == "agreement"
    assert second["isThen"] is True

    # 規則自身の名前が省略された場合、`payloadName`側を誤って拾わず
    # `name`は`None`になることを確認する（`ctx.messageName`/
    # `ctx.payloadName`が独立して読めることの検証）。
    unnamed_ast = parse_sysml_antlr(
        "message of applicableLaw : ApplicableLaw from a.x to b.y;"
    )
    unnamed_node = unnamed_ast["children"][0]
    assert unnamed_node["name"] is None
    assert unnamed_node["payload_name"] == "applicableLaw"


def test_antlr_messageusage_redefine_equals_value():
    """`message :>> setSpeedMessage = driver_a.driverBehavior.sendSetSpeed.
    sentMessage;`（Interaction Realization-1.sysml L51-53）のように、
    messageUsageはredefine節(:>>)の後に`= value`値代入を持つことがある
    （`of`/`from`/`to`節はすでに対応済みだが、この単純な`=`代入形は
    未対応だった。attributeUsage/portUsage/connectionEndMemberと同型）。
    2026-08-29、add_messageusage_redefine_equals_value対応中に発見。"""
    ast = parse_sysml_antlr(
        "message :>> setSpeedMessage = "
        "driver_a.driverBehavior.sendSetSpeed.sentMessage;"
    )
    node = ast["children"][0]
    assert node["type"] == "message_usage"
    assert node["name"] is None
    assert node["redefines"] == [{"kind": "redefines", "target": "setSpeedMessage"}]
    assert node["value"]["type"] == "name_ref"
    assert node["value"]["reference"] == "driver_a.driverBehavior.sendSetSpeed.sentMessage"

    # `:=`初期値代入も同様に機能することを確認する。
    walrus_ast = parse_sysml_antlr(
        "message :>> fuelCommandMessage := vehicle_a.controllerBehavior.sentMessage;"
    )
    walrus_node = walrus_ast["children"][0]
    assert walrus_node["value"]["type"] == "name_ref"

    # 既存の`of`/`from...to`形が引き続き機能することを確認する
    # （"value"キー自体が無いことも確認する）。
    of_ast = parse_sysml_antlr(
        "message Statement1 of applicableLaw : ApplicableLaw from a.x to b.y;"
    )
    of_node = of_ast["children"][0]
    assert "value" not in of_node


def test_antlr_messageusage_redefine_qualified_type_clause():
    """`message :>> publish_message: Transfers::MessageTransfer { end :>>
    source = producer.publicationPort; end :>> target = server.
    publicationPort; }`（ServerSequenceRealization-2.sysml、
    ServerSequenceOutsideRealization-2.sysml）のように、redefine節(:>>)の
    postTargetの直後に修飾名（`::`区切り）の型節が続くことがある
    （flowUsageの第2代替と同型）。従来の`( ':' ID | 'of' ...)`型節スロット
    はredefineより前の位置にしかなく、この位置には対応していなかった。
    2026-08-31、add_messageusage_redefine_qualified_type_clause対応中に
    発見。"""
    ast = parse_sysml_antlr(
        "message :>> publish_message: Transfers::MessageTransfer { "
        "end :>> source = producer.publicationPort; "
        "end :>> target = server.publicationPort; "
        "}"
    )
    node = ast["children"][0]
    assert node["type"] == "message_usage"
    assert node["name"] is None
    assert node["type_name"] == "Transfers::MessageTransfer"
    assert node["redefines"] == [{"kind": "redefines", "target": "publish_message"}]
    assert len(node["children"]) == 2

    # 既存の`= value`redefine形が引き続き機能することを確認する
    # （"type_name"がNoneのままであることも確認する）。
    value_ast = parse_sysml_antlr(
        "message :>> setSpeedMessage = driver_a.sentMessage;"
    )
    value_node = value_ast["children"][0]
    assert value_node["type_name"] is None
    assert value_node["value"]["type"] == "name_ref"


def test_antlr_flowusage_named_payload_of_clause_omitted_name():
    """`flow of fuel : Fuel from pump.fuelOutPort.fuel to
    vehicle.fuelInPort.fuel;`（3d-Function-based Behavior-item.sysml
    L59-60）のように、`of`節が「名前:型」のnamed payload形を取り、かつ
    flow自身の名前は省略されうる。`ofName`という専用ラベル追加により
    無ラベルの`ctx.simpleName()`がリストを返すようになったため、
    flow自身の名前にも`flowName`という専用ラベルを与える必要がある
    （さもないと、名前省略時に位置0が`ofName`側にずれてしまう）。
    2026-08-29、730件ベースライン154件エラー要因分析で発見。"""
    ast = parse_sysml_antlr(
        "part def P { flow of fuel : Fuel from pump.fuelOutPort.fuel "
        "to vehicle.fuelInPort.fuel; }"
    )
    node = ast["children"][0]["children"][0]
    assert node["type"] == "flow_usage"
    assert node["name"] is None
    assert node["item_type"] == "Fuel"
    assert node["item_name"] == "fuel"
    assert node["from_end"] == "pump::fuelOutPort::fuel"
    assert node["to_end"] == "vehicle::fuelInPort::fuel"

    # flow自身の名前とofNameが両方存在する場合も正しく区別できることを確認する。
    named_ast = parse_sysml_antlr(
        "part def P { flow f of fuel : Fuel from pump.fuelOutPort.fuel "
        "to vehicle.fuelInPort.fuel; }"
    )
    named_node = named_ast["children"][0]["children"][0]
    assert named_node["name"] == "f"
    assert named_node["item_name"] == "fuel"


def test_antlr_part_kind_calc_and_action_parameter():
    """`in part : Engine;`・`return part : Engine;`（TradeStudyTest.sysml）、
    `in part testVehicle : Vehicle = ...;`（Verification Case Definition
    Example.sysml）のように、calc/actionのパラメータ宣言のkind節に`part`が
    含まれていなかった（従来calcParameterにはkind節自体が無く、
    actionParameterはitem/attribute/ref/calc/actionのみ）。2026-08-29、
    235件パース失敗の要因分析で発見。"""
    calc_ast = parse_sysml_antlr(
        "calc def E { in part : Engine; return part : Engine; }"
    )
    calc_children = calc_ast["children"][0]["children"]
    in_param = calc_children[0]
    assert in_param["type"] == "calc_parameter"
    assert in_param["direction"] == "in"
    assert in_param["kind"] == "part"
    assert in_param["type_name"] == "Engine"
    return_param = calc_children[1]
    assert return_param["type"] == "calc_parameter"
    assert return_param["direction"] == "return"
    assert return_param["kind"] == "part"
    assert return_param["type_name"] == "Engine"

    action_ast = parse_sysml_antlr(
        "action collectData { in part testVehicle : Vehicle = "
        "VehicleMassTest::testVehicle; }"
    )
    action_param = action_ast["children"][0]["params"][0]
    assert action_param["type"] == "param"
    assert action_param["direction"] == "in"
    assert action_param["kind"] == "part"
    assert action_param["name"] == "testVehicle"
    assert action_param["type_name"] == "Vehicle"

    # 既存のkind無し形（`in x = value;`）が引き続き機能することを確認する。
    plain_ast = parse_sysml_antlr("calc def C { in x = 1; }")
    plain_param = plain_ast["children"][0]["children"][0]
    assert plain_param["type"] == "calc_parameter"
    assert plain_param["kind"] is None


def test_antlr_calcparameter_requirement_kind():
    """`in requirement fuelEconomyRequirement : FuelEconomyRequirement;`
    （Vehicle Analysis Demo.sysml、10c-Fuel Economy Analysis.sysml）の
    ように、calcParameterのkind節（item/attribute/ref/part/calc/action）
    に`requirement`が抜けていた。2026-08-29、730件ベースライン154件
    エラー要因分析で発見。"""
    ast = parse_sysml_antlr(
        "analysis def A { in requirement fuelEconomyRequirement : FuelEconomyRequirement; }"
    )
    node = ast["children"][0]["children"][0]
    assert node["type"] == "calc_parameter"
    assert node["direction"] == "in"
    assert node["kind"] == "requirement"
    assert node["name"] == "fuelEconomyRequirement"
    assert node["type_name"] == "FuelEconomyRequirement"


def test_antlr_transitionstmt_target_with_doc_body():
    """`transition first preparation accept PreparationPhaseCompletedNotification
    then launch { doc /* ... */ }`（MissionPackage.sysml）のように、
    transitionStmtの遷移先（target）に`;`終端の代わりにdocのみのbody
    （lambdaParamと同型）が付くことがある（従来`;`終端のみ）。2026-08-29、
    235件パース失敗の要因分析で発見。"""
    ast = parse_sysml_antlr(
        "state def S { transition first preparation accept X then launch "
        "{ doc /* hello */ } }"
    )
    node = ast["children"][0]["children"][0]
    assert node["type"] == "transition"
    assert node["source"] == "preparation"
    assert node["target"] == "launch"
    assert len(node["children"]) == 1
    assert node["children"][0]["type"] == "documentation"

    # 既存の`;`終端形が引き続き機能することを確認する。
    semi_ast = parse_sysml_antlr(
        "state def S { transition first a then b; }"
    )
    semi_node = semi_ast["children"][0]["children"][0]
    assert semi_node["type"] == "transition"
    assert semi_node["target"] == "b"
    assert semi_node["children"] == []


def test_antlr_performactionstmt_action_form_multiplicity():
    """`perform action takePicture[*] :> PictureTaking::takePicture;`
    （camera.sysml）のように、performActionStmtの`action`キーワード付き
    形にも名前直後の多重度`[...]`が付くことがある（従来は型節
    （`: Type`）かredefine節に直接続くのみだった）。2026-08-29、235件
    パース失敗の要因分析で発見。"""
    ast = parse_sysml_antlr(
        "part def P { perform action takePicture[*] :> "
        "PictureTaking::takePicture; }"
    )
    node = ast["children"][0]["children"][-1]
    assert node["type"] == "perform_action"
    assert node["name"] == "takePicture"
    assert node["multiplicity"] == {
        "size": {"min": "*", "max": "*"},
        "is_ordered": False,
        "is_unique": True,
    }
    assert node["redefines"] == [
        {"kind": "subsets", "target": "PictureTaking::takePicture"}
    ]

    # 既存の多重度無し形が引き続き機能することを確認する。
    plain_ast = parse_sysml_antlr(
        "part def P { perform action performLunarMission : PerformLunarMission; }"
    )
    plain_node = plain_ast["children"][0]["children"][-1]
    assert plain_node["type"] == "perform_action"
    assert plain_node["name"] == "performLunarMission"
    assert plain_node["type_name"] == "PerformLunarMission"
    assert plain_node["multiplicity"] is None


def test_antlr_accept_after_duration_trigger():
    """`then accept sig after 10[SI::s];`（ActionTest.sysml）、
    `accept after 48[h] then normal;`（Change and Time Triggers.sysml）の
    ように、`after`継続時間（タイムアウト）トリガー節がaccept文
    （acceptActionStmt/transitionStmtのaccept節どちらも）で未対応
    だった。acceptActionStmtは従来`via`節が必須で、`then accept S;`という
    `via`/`after`いずれも無い裸形も同じファイルで使われているため、この
    節全体を任意化して対応した。2026-08-29、235件パース失敗の要因分析
    で発見。"""
    ast = parse_sysml_antlr(
        "action a1 { first start; then accept S; "
        "then accept sig after 10[SI::s]; }"
    )
    children = ast["children"][0]["children"]
    bare_accept = children[1]
    assert bare_accept["type"] == "accept_action"
    assert bare_accept["message"] == "S"
    assert bare_accept["port"] is None
    assert bare_accept["after"] is None

    after_accept = children[2]
    assert after_accept["type"] == "accept_action"
    assert after_accept["message"] == "sig"
    assert after_accept["port"] is None
    assert after_accept["after"]["type"] == "quantity_literal"

    # 既存の`via`節形が引き続き機能することを確認する。
    via_ast = parse_sysml_antlr(
        "action def Act { accept response : ConnectionResponse via client; }"
    )
    via_node = via_ast["children"][0]["children"][0]
    assert via_node["port"] == "client"
    assert via_node["after"] is None

    # 暗黙遷移（implicitTransitionStmt）側のafterトリガーも確認する。
    implicit_ast = parse_sysml_antlr(
        "state def X { state normal; accept after 48 [h] then normal; }"
    )
    transition_node = implicit_ast["children"][0]["children"][-1]
    assert transition_node["type"] == "transition"
    assert transition_node["trigger"]["trigger_kind"] == "after"


def test_antlr_accept_action_do_action_body_in_state():
    """`accept cl:CallGiveItems via tellu.APIS_HTTP do action { first
    start; ... }`（AHFNorwayTopics.sysml L94-99）のように、acceptActionStmt
    は`;`終端の代わりに`do action { actionBodyElement* }`という明示的な
    振る舞い節を持つこともある。また従来`stateBodyElement`には
    `implicitTransitionStmt`（`accept ... then target;`必須）しか登録
    されておらず、`then target;`を伴わない単独のacceptActionStmtは
    state本体直下で使えなかった（非対称）。2026-08-29、
    add_ahfnorwaytopics_composite_gaps対応中に発見。"""
    ast = parse_sysml_antlr(
        "state def X { "
        "state WaitOnData; "
        "accept cl:CallGiveItems via tellu.APIS_HTTP "
        "do action { first start; then send new Result(x) via tellu.APIS_HTTP; } "
        "then WaitOnData; "
        "}"
    )
    children = ast["children"][0]["children"]
    accept_node = next(c for c in children if c["type"] == "accept_action")
    assert accept_node["message"] == "cl"
    assert accept_node["message_type"] == "CallGiveItems"
    assert accept_node["port"] == "tellu.APIS_HTTP"
    assert [c["type"] for c in accept_node["children"]] == ["first_stmt", "send_action"]

    # 既存の`;`終端形（"children"キー自体が無いこと）が引き続き機能することを確認する。
    semi_ast = parse_sysml_antlr(
        "action def Act { accept response : ConnectionResponse via client; }"
    )
    semi_node = semi_ast["children"][0]["children"][0]
    assert "children" not in semi_node

    # 既存のimplicitTransitionStmt（`accept ... then target;`必須形）が
    # 引き続き機能することを確認する。
    implicit_ast = parse_sysml_antlr(
        "state def X { accept s : Sig do action D then S2; }"
    )
    transition_node = implicit_ast["children"][0]["children"][-1]
    assert transition_node["type"] == "transition"


def test_antlr_featureusage_conjugated_type():
    """`#servicedd serviceDiscovery:~ServiceDiscoveryDD ;`
    （AHFNorwayTopics.sysml）のように、キーワード無しの汎用usage形
    （featureUsage）でも共役（`~`）修飾型節を取ることがある（portUsageと
    同型）。2026-08-29、add_ahfnorwaytopics_composite_gaps対応中に発見。"""
    ast = parse_sysml_antlr(
        "package P { #servicedd serviceDiscovery:~ServiceDiscoveryDD ; }"
    )
    node = ast["children"][0]
    assert node["type"] == "feature_usage"
    assert node["name"] == "serviceDiscovery"
    assert node["type_name"] == "~ServiceDiscoveryDD"
    assert node["prefixMetadata"] == ["servicedd"]

    # 既存の共役無し形が引き続き機能することを確認する。
    plain_ast = parse_sysml_antlr("package P { apisp: APIS_DD ; }")
    plain_node = plain_ast["children"][0]
    assert plain_node["type_name"] == "APIS_DD"


def test_antlr_featuredef_metadata_prefix_bare_def():
    """`#service def APISService { attribute :>> serviceDefinition =
    "APISPullService"; }`（AHFNorwayTopics.sysml）のように、メタデータ
    注釈（`#service`）付きで種別キーワード（part/port/attribute等）を
    一切伴わない汎用def宣言もある（featureUsageのdef版として`featureDef`
    規則を新設）。2026-08-29、add_ahfnorwaytopics_composite_gaps対応中に
    発見。"""
    ast = parse_sysml_antlr(
        'package P { #service def APISService { '
        'attribute :>> serviceDefinition = "APISPullService"; '
        '} }'
    )
    node = ast["children"][0]
    assert node["type"] == "feature_def"
    assert node["name"] == "APISService"
    assert node["prefixMetadata"] == ["service"]
    assert len(node["children"]) == 1


def test_antlr_entryactionmember_send_form():
    """`entry send new CallGiveItems("All the items") via apisp.APIS_HTTP;`
    （AHFNorwayTopics.sysml）のように、doActionMemberの`do send ...`と
    同型のインラインsendアクションを、単独のentry-actionメンバーとしても
    書ける（従来entryActionMemberには`entry assign ...`しか無く非対称
    だった）。2026-08-29、add_ahfnorwaytopics_composite_gaps対応中に発見。"""
    ast = parse_sysml_antlr(
        "state def X { "
        'entry send new Publish("Return_AllItems") via apisc.APIS_MQTT; '
        "}"
    )
    node = ast["children"][0]["children"][0]
    assert node["type"] == "entry_action"
    assert node["kind"] == "entry"
    assert node["send"]["payload"]["type"] == "new_instance"
    assert node["send"]["via"] == "apisc::APIS_MQTT"
    assert node["send"]["to"] is None

    # 既存の`entry assign ...`形が引き続き機能することを確認する
    # （"send"キー自体が無いことも確認する）。
    assign_ast = parse_sysml_antlr("state def X { entry assign counter.count := 0; }")
    assign_node = assign_ast["children"][0]["children"][0]
    assert "send" not in assign_node


def test_antlr_frame_statement():
    """`frame concern ProfitabilityConcern;`（BusinessCaseOpsCon.sysml）・
    `frame 'Reduce the number of special parts';`
    （DontPanic-SysMLv2-Batmobile.sysml）のように、requirement/concern/
    viewpoint定義本体内でframed concern参照を宣言する`frame`文が完全に
    未実装だった。`concern`キーワード付き/省略形、多重度付き
    （`frame c3[0..*];`）、型節付き（`frame concern hs : HomeSafety;`）
    のいずれも受理できることを確認する。2026-08-29、235件パース失敗の
    要因分析で発見。"""
    ast = parse_sysml_antlr(
        "requirement def R2 { frame concern ProfitabilityConcern; "
        "frame c3[0..*]; frame 'Reduce the number of special parts'; "
        "frame concern hs : HomeSafety; }"
    )
    nodes = ast["children"][0]["children"]
    assert nodes[0] == {
        "type": "frame_statement", "isConcern": True,
        "name": "ProfitabilityConcern", "multiplicity": None, "type_name": None,
    }
    assert nodes[1]["type"] == "frame_statement"
    assert nodes[1]["isConcern"] is False
    assert nodes[1]["name"] == "c3"
    assert nodes[1]["multiplicity"] == {
        "size": {"min": 0, "max": "*"}, "is_ordered": False, "is_unique": True,
    }
    assert nodes[2] == {
        "type": "frame_statement", "isConcern": False,
        "name": "Reduce the number of special parts",
        "multiplicity": None, "type_name": None,
    }
    assert nodes[3] == {
        "type": "frame_statement", "isConcern": True,
        "name": "hs", "multiplicity": None, "type_name": "HomeSafety",
    }

    # viewpoint def/usage本体でも同様に機能することを確認する。
    viewpoint_ast = parse_sysml_antlr(
        "viewpoint def VP { frame c; } viewpoint vp: VP { frame concern c1; }"
    )
    vp_def_frame = viewpoint_ast["children"][0]["children"][0]
    assert vp_def_frame["type"] == "frame_statement"
    assert vp_def_frame["name"] == "c"
    vp_usage_frame = viewpoint_ast["children"][1]["children"][0]
    assert vp_usage_frame["type"] == "frame_statement"
    assert vp_usage_frame["isConcern"] is True
    assert vp_usage_frame["name"] == "c1"


def test_antlr_portusage_conjugated_type_namespacepath():
    """`port controlPort : ~Domain::PodPort;`（MiningFrigate.sysml）の
    ように、portUsageの共役（`~`）修飾型節が`::`修飾名（namespacePath）を
    受理できなかった（従来は単一segmentのIDのみで、fix_p0_1の
    namespacePath全面置換漏れだった）。既存のカンマ区切り複数型形
    （`port p: pd1, pd2;`）が引き続き機能することも確認する。2026-08-29、
    235件パース失敗の要因分析で発見。"""
    ast = parse_sysml_antlr(
        "part def X { port controlPort : ~Domain::PodPort; }"
    )
    node = ast["children"][0]["children"][0]
    assert node["type"] == "port_usage"
    assert node["type_name"] == "~Domain::PodPort"

    multi_ast = parse_sysml_antlr(
        "part def X { port two_port_def_types: pd1, pd2; }"
    )
    multi_node = multi_ast["children"][0]["children"][0]
    assert multi_node["type_name"] == "pd1"
    assert multi_node["type_names"] == ["pd1", "pd2"]

    # 既存の共役無し単純型が引き続き機能することを確認する。
    plain_ast = parse_sysml_antlr("part def X { port p2 : SimpleType; }")
    plain_node = plain_ast["children"][0]["children"][0]
    assert plain_node["type_name"] == "SimpleType"


def test_antlr_event_usage_occurrence_keyword_omission():
    """`event publish_source_event = publish_message.start;`
    （ServerSequenceModelOutside.sysml）のように、`occurrence`キーワードを
    省略した`event`usage形が未対応だった（従来`occurrence`は必須）。
    同ファイルの`event occurrence :>> subscribe_target_event =
    subscribe_message.done;`という、名前を持たず`:>>`redefine節と`=`値
    代入を同時に持つ形（従来いずれも規則自体に存在しなかった）も併せて
    確認する。2026-08-29、235件パース失敗の要因分析で発見。"""
    ast = parse_sysml_antlr(
        "part def X { event publish_source_event = publish_message.start; }"
    )
    node = ast["children"][0]["children"][0]
    assert node["type"] == "event_occurrence_usage"
    assert node["name"] == "publish_source_event"
    assert node["value"]["reference"] == "publish_message.start"
    assert node["redefines"] == []

    redefine_ast = parse_sysml_antlr(
        "part def X { event occurrence :>> subscribe_target_event = "
        "subscribe_message.done; }"
    )
    redefine_node = redefine_ast["children"][0]["children"][0]
    assert redefine_node["type"] == "event_occurrence_usage"
    assert redefine_node["name"] is None
    assert redefine_node["value"]["reference"] == "subscribe_message.done"
    assert redefine_node["redefines"] == [
        {"kind": "redefines", "target": "subscribe_target_event"}
    ]

    # 既存の`occurrence`キーワード付き裸形が引き続き機能することを確認する。
    bare_ast = parse_sysml_antlr("event occurrence A;")
    bare_node = bare_ast["children"][0]
    assert bare_node["type"] == "event_occurrence_usage"
    assert bare_node["name"] == "A"
    assert bare_node["value"] is None
    assert bare_node["redefines"] == []


def test_antlr_event_occurrence_usage_dotted_name_and_multiplicity_before_redefine():
    """`event producerBehavior.publish[1] :>> publish_source_event;`
    （ServerSequenceOutsideRealization-3.sysml L127）のように、名前スロッ
    トがドット区切りのフィーチャーチェーンパス（`producerBehavior.publish`）
    を取る形が未対応だった（従来は単一`simpleName`のみ）。同じ行で多重度
    `[1]`がredefine節`:>>`より先に置かれる語順（従来の規則はredefine節を
    多重度より先に置く順序のみ対応）も併せて確認する。2026-08-29、
    add_flowusage_named_bare_from_to_form対応中に連鎖的に発見。"""
    ast = parse_sysml_antlr(
        "action def A { event producerBehavior.publish[1] :>> publish_source_event; }"
    )
    node = ast["children"][0]["children"][0]
    assert node["type"] == "event_occurrence_usage"
    assert node["name"] == "producerBehavior.publish"
    assert node["redefines"] == [
        {"kind": "redefines", "target": "publish_source_event"}
    ]

    # 既存の単純名（ドット無し）が引き続き機能することを確認する。
    plain_ast = parse_sysml_antlr("event occurrence A;")
    plain_node = plain_ast["children"][0]
    assert plain_node["name"] == "A"


def test_antlr_exhibitstateusagestmt_state_keyword_omission():
    """`exhibit vehicleStates { ... }`（State Exhibition Example.sysml）の
    ように、exhibitStateUsageStmtの`state`キーワードが省略できなかった
    （従来は`exhibit state NAME`のように必須）。同種のコーパス実例には
    `::`修飾参照（`exhibit MiningFrigate::miningFrigatesStates;`）、`.`
    参照（`exhibit vehicleStates.on;`）、redefine節付き
    （`exhibit 'vehicle states' :>> VehicleA::'vehicle states' { ... }`）
    もあるため、これらも併せて確認する。2026-08-29、235件パース失敗の
    要因分析で発見。"""
    ast = parse_sysml_antlr(
        "part def X { exhibit vehicleStates { state s1; } }"
    )
    node = ast["children"][0]["children"][0]
    assert node["type"] == "exhibit_state_usage"
    assert node["name"] == "vehicleStates"
    assert node["redefines"] == []
    assert len(node["children"]) == 1

    qualified_ast = parse_sysml_antlr(
        "part def X { exhibit MiningFrigate::miningFrigatesStates; }"
    )
    qualified_node = qualified_ast["children"][0]["children"][0]
    assert qualified_node["name"] == "MiningFrigate::miningFrigatesStates"

    dotted_ast = parse_sysml_antlr("part def X { exhibit vehicleStates.on; }")
    dotted_node = dotted_ast["children"][0]["children"][0]
    assert dotted_node["name"] == "vehicleStates::on"

    redefine_ast = parse_sysml_antlr(
        "part def X { exhibit 'vehicle states' :>> VehicleA::'vehicle states' "
        "{ state s1; } }"
    )
    redefine_node = redefine_ast["children"][0]["children"][0]
    assert redefine_node["name"] == "vehicle states"
    assert redefine_node["redefines"] == [
        {"kind": "redefines", "target": "VehicleA::vehicle states"}
    ]

    # 既存の`state`キーワード付き形が引き続き機能することを確認する。
    keyworded_ast = parse_sysml_antlr(
        "part def X { exhibit state 'vehicle states': 'Vehicle States'; }"
    )
    keyworded_node = keyworded_ast["children"][0]["children"][0]
    assert keyworded_node["name"] == "vehicle states"
    assert keyworded_node["type_name"] == "Vehicle States"
    assert keyworded_node["redefines"] == []


def test_antlr_then_prefix_include_use_case():
    """`then include use case detectThreat : DetectThreat { ... }`
    （UseCasesHull.sysml）のように、includeUseCaseUsageに`then`前置が
    無かった（他の多くの規則（performActionStmt等）では既に対応済み）。
    従来の規則自体も`'include' 'use' 'case' simpleName ';'`のみで型節・
    多重度・redefine節・bodyすべて未対応かつpartBodyElementに未登録
    だったため、useCaseUsageと同型のredefinition機能一式も併せて追加
    する。既存の`include use case enterHome_a :> enterHome [1..5];`
    （redefine節+多重度）が引き続き機能することも確認する。2026-08-29、
    235件パース失敗の要因分析で発見。"""
    ast = parse_sysml_antlr(
        "use case def X { then include use case detectThreat : "
        "DetectThreat { subject s; } }"
    )
    node = ast["children"][0]["children"][0]
    assert node["type"] == "include_use_case_usage"
    assert node["isThen"] is True
    assert node["name"] == "detectThreat"
    assert node["type_name"] == "DetectThreat"
    assert len(node["children"]) == 1

    redefine_ast = parse_sysml_antlr(
        "use case def X { include use case enterHome_a :> enterHome [1..5]; }"
    )
    redefine_node = redefine_ast["children"][0]["children"][0]
    assert redefine_node["type"] == "include_use_case_usage"
    assert redefine_node.get("isThen") is None
    assert redefine_node["redefines"] == [
        {"kind": "subsets", "target": "enterHome"}
    ]
    assert redefine_node["multiplicity"] == {
        "size": {"min": 1, "max": 5}, "is_ordered": False, "is_unique": True,
    }

    # 既存の裸形が引き続き機能することを確認する。
    bare_ast = parse_sysml_antlr(
        "use case def X { include use case startEngine; }"
    )
    bare_node = bare_ast["children"][0]["children"][0]
    assert bare_node["type"] == "include_use_case_usage"
    assert bare_node["name"] == "startEngine"
    assert bare_node["type_name"] is None


def test_antlr_minimal_bare_interfaceusage_connect_form():
    """`interface producer_2.publicationPort to server_2.publicationPort;`
    （ServerSequenceOutsideRealization-2.sysml）のように、名前・型節・
    `connect`キーワードすべてを省略した最小形interfaceUsage（ドット区切り
    パス同士を直接`to`で接続）が未対応だった。`connect`キーワードを任意化
    することで対応する。既存の`connect`キーワード付き形（名前付き・名前
    省略の両方）が引き続き機能することも確認する。2026-08-29、235件
    パース失敗の要因分析で発見。"""
    ast = parse_sysml_antlr(
        "part def X { interface producer_2.publicationPort to "
        "server_2.publicationPort; }"
    )
    node = ast["children"][0]["children"][0]
    assert node["type"] == "interface_usage"
    assert node["name"] is None
    assert node["type_name"] is None
    assert node["interface_part"]["from_end"]["reference_subsetting"]["referenced_feature"] == "producer_2::publicationPort"
    assert node["interface_part"]["to_end"]["reference_subsetting"]["referenced_feature"] == "server_2::publicationPort"

    # 既存の`connect`キーワード付き形（名前省略の型付き）が引き続き機能
    # することを確認する。
    typed_ast = parse_sysml_antlr(
        "part def X { interface : StagingInterface connect a.p to b.q; }"
    )
    typed_node = typed_ast["children"][0]["children"][0]
    assert typed_node["type_name"] == "StagingInterface"
    assert typed_node["interface_part"] is not None

    # 既存の`connect`無し裸形（redefine節のみ）が引き続き機能することを
    # 確認する。
    plain_ast = parse_sysml_antlr(
        "part def X { abstract interface interfaces: Interface[0..*] "
        "nonunique :> connections; }"
    )
    plain_node = plain_ast["children"][0]["children"][0]
    assert plain_node["type_name"] == "Interface"
    assert plain_node["interface_part"] is None


def test_antlr_partusage_and_inline_assign_in_statebodyelement():
    """`state def Counting { part counter : Counter; entry assign
    counter.count := 0; ... state increment { do assign counter.count :=
    counter.count + 1; } }`（AssignmentTest.sysml）のように、partUsageが
    stateBodyElementに登録されておらず（attributeUsage/featureUsage/
    actionUsageStmtは登録済みで非対称）、かつentry/doに続くインライン
    代入アクション（`entry assign ...;`・`do assign ...;`、doActionMember
    の既存の`do send ...`と同型）も未対応だった。2026-08-29、235件パース
    失敗の要因分析で発見。"""
    ast = parse_sysml_antlr(
        "state def Counting { part counter : Counter; "
        "entry assign counter.count := 0; "
        "state increment { do assign counter.count := counter.count + 1; } }"
    )
    children = ast["children"][0]["children"]
    part_node = children[0]
    assert part_node["type"] == "part_instance"
    assert part_node["name"] == "counter"
    assert part_node["type_name"] == "Counter"

    entry_node = children[1]
    assert entry_node["type"] == "entry_action"
    assert entry_node["assign"]["type"] == "assignment_stmt"
    assert entry_node["assign"]["operator"] == ":="

    nested_do = children[2]["children"][0]
    assert nested_do["type"] == "do_action"
    assert nested_do["assign"]["type"] == "assignment_stmt"

    # 既存の参照形（アクション参照のみ）が引き続き機能することを確認する。
    plain_ast = parse_sysml_antlr("state def S { entry; do x; }")
    plain_children = plain_ast["children"][0]["children"]
    assert plain_children[0]["assign"] is None
    assert plain_children[1]["assign"] is None
    assert plain_children[1]["send"] is None


def test_antlr_actionparameter_style_direction_in_statebodyelement():
    """`state def VehicleStates { in operatingVehicle : Vehicle; }`
    （State Actions.sysml）のように、`in`/`out`方向付きパラメータ宣言
    （actionParameter）がstateBodyElementに登録されていなかった
    （part/objective本体はpartBodyElement経由で既に対応済みで非対称
    だった。add_partusage_in_statebodyelementと同根の不足）。2026-08-29、
    235件パース失敗の要因分析で発見。"""
    ast = parse_sysml_antlr(
        "state def VehicleStates { in operatingVehicle : Vehicle; }"
    )
    node = ast["children"][0]["children"][0]
    assert node["type"] == "param"
    assert node["direction"] == "in"
    assert node["name"] == "operatingVehicle"
    assert node["type_name"] == "Vehicle"

    # 既存の`out`方向・part/attribute等が同居する形が引き続き機能する
    # ことを確認する。
    mixed_ast = parse_sysml_antlr(
        "state def S { in x : X; out y : Y; part p : P; }"
    )
    mixed_children = mixed_ast["children"][0]["children"]
    assert [c["type"] for c in mixed_children] == ["param", "param", "part_instance"]
    assert mixed_children[1]["direction"] == "out"


def test_antlr_visibility_modifier_on_toplevel_def_rules():
    """`public item def A { ... }`（ItemTest.sysml）・`private part def
    Automobile;`（Package Example.sysml）・`public abstract part def
    Vehicle { ... }`（comprehensive_data_loss.sysml）・`private port def
    C { ... }`（PartTest.sysml）のように、partDef/itemDef/portDefに
    visibilityIndicator（public/private/protected）が付いていなかった
    （calculationDef/constraintDefは既に対応済みで非対称だった）。
    コーパス調査の結果、これら3規則以外に実例が無いことを確認済み。
    2026-08-29、235件パース失敗の要因分析で発見。"""
    item_ast = parse_sysml_antlr("public item def A;")
    item_node = item_ast["children"][0]
    assert item_node["type"] == "item_def"
    assert item_node["visibility"] == "public"

    part_ast = parse_sysml_antlr("private part def Automobile;")
    part_node = part_ast["children"][0]
    assert part_node["type"] == "part_def"
    assert part_node["visibility"] == "private"

    abstract_part_ast = parse_sysml_antlr("public abstract part def Vehicle;")
    abstract_part_node = abstract_part_ast["children"][0]
    assert abstract_part_node["visibility"] == "public"
    assert abstract_part_node["isAbstract"] is True

    port_ast = parse_sysml_antlr("private port def C;")
    port_node = port_ast["children"][0]
    assert port_node["type"] == "port_def"
    assert port_node["visibility"] == "private"

    # 既存のvisibility無し形が引き続き機能することを確認する。
    plain_ast = parse_sysml_antlr("part def P;")
    assert plain_ast["children"][0]["visibility"] is None


def test_antlr_actorusage_namespacepath_type():
    """`actor hostileShip : Domain::HostileShip;`（UseCasesHull.sysml）の
    ように、actorUsageの型節が`::`修飾名（namespacePath）を受理できな
    かった（従来は単一segmentのIDのみで、同型の姉妹規則stakeholderUsage
    とも非対称だった）。2026-08-29、235件パース失敗の要因分析で発見。"""
    ast = parse_sysml_antlr(
        "use case def X { actor hostileShip : Domain::HostileShip; }"
    )
    node = ast["children"][0]["children"][0]
    assert node["type"] == "actor_usage"
    assert node["name"] == "hostileShip"
    assert node["type_name"] == "Domain::HostileShip"

    # 既存の単一segment型が引き続き機能することを確認する。
    plain_ast = parse_sysml_antlr("use case def X { actor driver : RoadUser; }")
    plain_node = plain_ast["children"][0]["children"][0]
    assert plain_node["type_name"] == "RoadUser"


def test_antlr_actorusage_at_package_level():
    """`actor Doctor;`（EIT_System_Use_Cases.sysml L4）のように、
    actorUsageはpackage直下（packageBodyElement）にも直接書けることが
    ある（従来はpartBodyElementにのみ登録済みで、package直下は構文
    エラーになっていた。2026-08-29、add_bare_include_shorthand対応中に
    連鎖的に発見）。"""
    ast = parse_sysml_antlr("package P { actor Doctor; }")
    node = ast["children"][0]
    assert node["type"] == "actor_usage"
    assert node["name"] == "Doctor"


def test_antlr_actorusage_prefix_metadata_after_keyword():
    """`actor #B a;`（SemanticMetadata_valid.sysml(xpect) L38）のように、
    `#Type`前置メタデータ注釈が`actor`キーワードの直後（名前の前）に
    来ることがある（他の多くの規則とは異なり、キーワードより前ではない
    位置）。既存のメタデータ無し形が引き続き機能することも確認する。
    2026-08-29、add_generic_tag_def_usage_shorthand対応中に発見。"""
    ast = parse_sysml_antlr("requirement def R { actor #B a; }")
    node = ast["children"][0]["children"][0]
    assert node["type"] == "actor_usage"
    assert node["name"] == "a"
    assert node["prefixMetadata"] == ["B"]

    # 既存のメタデータ無し形が引き続き機能することを確認する。
    plain_ast = parse_sysml_antlr("use case def U { actor driver : RoadUser; }")
    plain_node = plain_ast["children"][0]["children"][0]
    assert plain_node["name"] == "driver"
    assert plain_node["prefixMetadata"] == []


def test_antlr_then_prefix_usecaseusage():
    """`then use case 'drive vehicle' { ... }`（Use Case Usage Example.sysml）
    のように、useCaseUsage自体に`then`前置が無かった（includeUseCaseUsage
    等の多くの規則では既に`isThen`対応済みで非対称だった）。2026-08-29、
    235件パース失敗の要因分析で発見。"""
    ast = parse_sysml_antlr(
        "use case def X { first start; then use case 'drive vehicle' "
        "{ subject vehicle; } }"
    )
    node = ast["children"][0]["children"][1]
    assert node["type"] == "use_case_usage"
    assert node["isThen"] is True
    assert node["name"] == "drive vehicle"
    assert len(node["children"]) == 1

    # 既存の`then`無し形が引き続き機能することを確認する。
    plain_ast = parse_sysml_antlr("use case def X { use case uc1 : UC1; }")
    plain_node = plain_ast["children"][0]["children"][0]
    assert plain_node["type"] == "use_case_usage"
    assert "isThen" not in plain_node


def test_antlr_bare_include_shorthand():
    """`include uc2;`・`include system.uc1;`（UseCaseTest.sysml）・
    `include 'add fuel'[0..*] { ... }`（Use Case Usage Example.sysml）・
    `then include 'enter vehicle' { ... }`（18-Use Case.sysml）のように、
    `use case`キーワードを完全に省略した裸のinclude短縮形が全く未実装
    だった（`then`前置もincludeUseCaseUsageと同様に持ちうる）。
    2026-08-29、235件パース失敗の要因分析で発見。"""
    ast = parse_sysml_antlr(
        "use case def X { include uc2; include system.uc1; }"
    )
    children = ast["children"][0]["children"]
    assert children[0] == {
        "type": "include_use_case_usage", "name": "uc2", "type_name": None,
        "multiplicity": None, "redefines": [], "inheritance": None, "children": [],
    }
    assert children[1]["name"] == "system::uc1"

    mult_ast = parse_sysml_antlr(
        "use case def X { include 'add fuel'[0..*] { subject vehicle; } }"
    )
    mult_node = mult_ast["children"][0]["children"][0]
    assert mult_node["name"] == "add fuel"
    assert mult_node["multiplicity"]["size"] == {"min": 0, "max": "*"}
    assert len(mult_node["children"]) == 1

    then_ast = parse_sysml_antlr(
        "use case def X { then include 'enter vehicle' { subject vehicle; } }"
    )
    then_node = then_ast["children"][0]["children"][0]
    assert then_node["name"] == "enter vehicle"
    assert then_node["isThen"] is True


def test_antlr_nested_interfacedef_in_partbody():
    """`part def Module { interface def SensorLink { end source :
    DataPort; end target : DataPort; } }`（synthetic-100.sysml）のように、
    interfaceDef自体もpartDef等と同型にpartBodyElement内へネストして
    書ける（従来packageBodyElementにしか登録されておらず未対応
    だった）。同ファイルの`end`メンバー宣言自体は既存の
    connectionEndMember経由で既に対応済みであることも確認する。
    2026-08-29、235件パース失敗の要因分析で発見。"""
    ast = parse_sysml_antlr(
        "part def Module { interface def SensorLink { "
        "end source : DataPort; end target : DataPort; } }"
    )
    nested = ast["children"][0]["children"][0]
    assert nested["type"] == "interface_def"
    assert nested["name"] == "SensorLink"
    assert len(nested["children"]) == 2
    assert nested["children"][0]["type"] == "connection_end_member"
    assert nested["children"][0]["name"] == "source"
    assert nested["children"][0]["type_name"] == "DataPort"


def test_antlr_interfaceusage_named_type_namespacepath():
    """`interface APIS_transfer_interface : Interfaces::APIS_transfer_interface_def
    connect ...;`（AHFSequences.sysml）のように、interfaceUsageの名前付き
    代替（第1代替）の型節が`::`修飾名（namespacePath）を受理できなかった
    （従来は単一segmentのIDのみ）。fix_portusage_conjugated_type_
    namespacepath/add_actorusage_namespacepath_typeと同型のギャップ。
    2026-08-29、235件パース失敗の要因分析で発見。"""
    ast = parse_sysml_antlr(
        "part def X { interface APIS_transfer_interface : "
        "Interfaces::APIS_transfer_interface_def connect a.p to b.q; }"
    )
    node = ast["children"][0]["children"][0]
    assert node["type"] == "interface_usage"
    assert node["name"] == "APIS_transfer_interface"
    assert node["type_name"] == "Interfaces::APIS_transfer_interface_def"
    assert node["interface_part"] is not None

    # 既存の単一segment型が引き続き機能することを確認する。
    plain_ast = parse_sysml_antlr(
        "part def X { interface named : Type connect a.p to b.q; }"
    )
    plain_node = plain_ast["children"][0]["children"][0]
    assert plain_node["type_name"] == "Type"

    # 既存の名前省略の裸形（第2代替）が引き続き機能することを確認する。
    bare_ast = parse_sysml_antlr(
        "part def X { interface : StagingInterface connect a.p to b.q; }"
    )
    bare_node = bare_ast["children"][0]["children"][0]
    assert bare_node["name"] is None
    assert bare_node["type_name"] == "StagingInterface"


def test_antlr_interfaceusage_nary_connect_form():
    """`interface APIS_transfer_interface : Interfaces::Interface connect
    (tlu ::> ..., apsph ::> ..., apspm ::> ...);`（AHFSequences.sysml
    L77-81）のように、interfaceUsageの`connect`節は2項の`A to B`形だけ
    でなく、括弧で囲んだ3項以上のend列（connectUsage/connectionUsageで
    既に対応済みのn項形）も取りうる（従来は2項形のみだった）。名前省略の
    裸形（第2代替）でも同じn項形を受理できることも併せて確認する。
    2026-08-29、add_interfaceusage_named_type_namespacepath対応中に
    連鎖的に発見。"""
    ast = parse_sysml_antlr(
        "part def X { interface APIS_transfer_interface : Interfaces::Interface "
        "connect (tlu ::> a, apsph ::> b, apspm ::> c); }"
    )
    node = ast["children"][0]["children"][0]
    assert node["type"] == "interface_usage"
    assert node["interface_part"] is None
    assert [e["declared_name"] for e in node["ends"]] == ["tlu", "apsph", "apspm"]
    assert [e["reference"] for e in node["ends"]] == ["a", "b", "c"]

    # 既存の2項`A to B`形が引き続き機能することを確認する。
    binary_ast = parse_sysml_antlr(
        "part def X { interface named : Type connect a.p to b.q; }"
    )
    binary_node = binary_ast["children"][0]["children"][0]
    assert binary_node["interface_part"] is not None
    assert "ends" not in binary_node

    # 名前省略の裸形（第2代替）でも同じn項形を受理できることを確認する。
    bare_ast = parse_sysml_antlr(
        "part def X { interface : StagingInterface connect (a.p, b.q, c.r); }"
    )
    bare_node = bare_ast["children"][0]["children"][0]
    assert [e["declared_name"] for e in bare_node["ends"]] == [None, None, None]
    assert [e["reference"] for e in bare_node["ends"]] == ["a::p", "b::q", "c::r"]


def test_antlr_interfaceusage_value_assignment():
    """`abstract interface i = i1;`（InterfaceTest.sysml）のように、
    `connect`節を伴わず既存のinterface usageへ`= value`で直接値代入
    することがある（従来interfaceUsageには`= value`代入が無かった）。
    2026-08-29、730件ベースライン154件エラー要因分析で発見。"""
    ast = parse_sysml_antlr(
        "part def A { interface i1 : I1; abstract interface i = i1; }"
    )
    node = ast["children"][0]["children"][-1]
    assert node["type"] == "interface_usage"
    assert node["name"] == "i"
    assert node["isAbstract"] is True
    assert node["value"] == {"type": "name_ref", "reference": "i1"}
    assert node["interface_part"] is None

    # 既存の`connect`節付き形が引き続き機能し、"value"キー自体が無いことを
    # 確認する（回帰防止）。
    connect_ast = parse_sysml_antlr(
        "part def X { interface named : Type connect a.p to b.q; }"
    )
    connect_node = connect_ast["children"][0]["children"][0]
    assert "value" not in connect_node


def test_antlr_connectionendmember_redefine_and_direct_reference_combined():
    """`end :>> source ::> producer.publicationPort;`
    （ServerSequenceOutsideRealization-2.sysml）のように、
    connectionEndMemberが名前を伴わない`:>>`redefine節（postKind）と
    直後の`::>`直接参照（directKind）を同時に持つことがある（従来この
    2つは互いに排他的な代替として扱われており未対応だった）。既存の
    `directKind`単独形（`end #cause ::> a;`）・通常の名前付き形
    （`end p1: P;`）が引き続き機能することも確認する。2026-08-29、
    235件パース失敗の要因分析で発見。"""
    ast = parse_sysml_antlr(
        "connection a: A { end :>> source ::> producer.publicationPort; }"
    )
    node = ast["children"][0]["children"][0]
    assert node["type"] == "connection_end_member"
    assert node["redefines"] == [{"kind": "redefines", "target": "source"}]
    assert node["reference"] == "producer::publicationPort"

    # 既存のdirectKind単独形が引き続き機能することを確認する。
    direct_only_ast = parse_sysml_antlr("connection a: A { end #cause ::> a; }")
    direct_only_node = direct_only_ast["children"][0]["children"][0]
    assert direct_only_node["reference"] == "a"
    assert direct_only_node["redefines"] == []

    # 既存の通常の名前付き形が引き続き機能することを確認する。
    named_ast = parse_sysml_antlr("connection a: A { end p1: P; }")
    named_node = named_ast["children"][0]["children"][0]
    assert named_node["name"] == "p1"
    assert named_node["type_name"] == "P"
    assert named_node["reference"] is None


def test_antlr_connectionendmember_redefine_and_value_assign():
    """`end :>> source = producer.publicationPort;`
    （ServerSequenceRealization-2.sysml、sysml2-cli）のように、
    connectionEndMemberが名前を伴わない`:>>`redefine節（postKind）の
    ターゲットの直後に`::>`直接参照ではなく`= value`値代入を持つことも
    ある（attributeUsage/portUsageと同型のvalueOp/value節を追加）。
    既存の`::>`直接参照形が引き続き機能することも確認する。2026-08-29、
    add_portusage_performaction_redefine_assign対応中に連鎖的に発見。"""
    ast = parse_sysml_antlr(
        "connection a: A { end :>> source = producer.publicationPort; }"
    )
    node = ast["children"][0]["children"][0]
    assert node["type"] == "connection_end_member"
    assert node["redefines"] == [{"kind": "redefines", "target": "source"}]
    assert node["value"]["type"] == "name_ref"
    assert node["reference"] is None

    # `:=`初期値代入も同様に機能することを確認する。
    walrus_ast = parse_sysml_antlr(
        "connection a: A { end :>> source := producer.publicationPort; }"
    )
    walrus_node = walrus_ast["children"][0]["children"][0]
    assert walrus_node["value"]["type"] == "name_ref"

    # 既存の`::>`直接参照形が引き続き機能することを確認する
    # （"value"キー自体が無いことも確認する）。
    direct_ast = parse_sysml_antlr(
        "connection a: A { end :>> source ::> producer.publicationPort; }"
    )
    direct_node = direct_ast["children"][0]["children"][0]
    assert direct_node["reference"] == "producer::publicationPort"
    assert "value" not in direct_node


def test_antlr_connectionendmember_directtarget_multiplicity():
    """`end mother ::> woman[1];`（family.sysml L204）のように、
    connectionEndMemberの`::>`直接参照の直後に多重度`[1]`が付くことが
    ある（従来directTarget直後の多重度は未対応だった）。`directMult`と
    いう新規ラベルが既存の`type_name`側の内側多重度探索（`endMult`除外
    ループ）を汚染しないことも確認する。2026-08-29、
    add_connectionendmember_directtarget_multiplicity対応中に発見。"""
    ast = parse_sysml_antlr(
        "connection child : Child { end mother ::> woman[1]; "
        "end father ::> man[1]; }"
    )
    mother, father = ast["children"][0]["children"]
    assert mother["type"] == "connection_end_member"
    assert mother["endName"] == "mother"
    assert mother["reference"] == "woman"
    assert mother["referenceMultiplicity"] == {
        "size": {"min": 1, "max": 1}, "is_ordered": False, "is_unique": True
    }
    assert mother["multiplicity"] is None

    assert father["reference"] == "man"

    # 既存の多重度無し`::>`直接参照形が引き続き機能することを確認する
    # （"referenceMultiplicity"キー自体が無いことも確認する）。
    no_mult_ast = parse_sysml_antlr("connection a: A { end #cause ::> a; }")
    no_mult_node = no_mult_ast["children"][0]["children"][0]
    assert no_mult_node["reference"] == "a"
    assert "referenceMultiplicity" not in no_mult_node

    # 既存の内側型多重度（`type_name`側）が引き続き正しく読めることを
    # 確認する（directMultとの混同が無いこと）。
    inner_mult_ast = parse_sysml_antlr(
        "connection a: A { end item cart: ShoppingCart[1] "
        "crosses selectedProduct.inCart; }"
    )
    inner_mult_node = inner_mult_ast["children"][0]["children"][0]
    assert inner_mult_node["multiplicity"] == {
        "size": {"min": 1, "max": 1}, "is_ordered": False, "is_unique": True
    }
    assert "referenceMultiplicity" not in inner_mult_node


def test_antlr_connectionendmember_leading_multiplicity_and_trailing_postkind():
    """`end [1] item a : A { ... }`・`end ref end1 ::> d1 :> q;`
    （ConnectionTest.sysml L68, L53）のように、connectionEndMemberでは
    (1) `endName`を伴わずに多重度`[1]`だけが`'end'`直後・kindキーワード
    （`item`）の前に現れることがある（従来`endMult`は`endName`との
    ペアでしか現れられなかった）。(2) `::>`直接参照の後にさらに`:>`
    subsets節が続くこともある（従来postKind*はdirectKind節より前にしか
    置けなかった）。2026-08-29、
    add_flow_end_member_triple_colon_gt_operator対応中に連鎖的に発見。"""
    leading_mult_ast = parse_sysml_antlr(
        "connection def C { end [1] item a : A { } }"
    )
    leading_mult_node = leading_mult_ast["children"][0]["children"][0]
    assert leading_mult_node["type"] == "connection_end_member"
    assert leading_mult_node["endName"] is None
    assert leading_mult_node["endMultiplicity"] == {
        "size": {"min": 1, "max": 1}, "is_ordered": False, "is_unique": True
    }
    assert leading_mult_node["kind"] == "item"
    assert leading_mult_node["name"] == "a"
    assert leading_mult_node["type_name"] == "A"

    # `end [1] part producer : PowerProducer;`（The-SysMLv2-Book-
    # DroneSystemModel-Example.sysml、Connections Example.sysml）のように、
    # kindキーワードは`occurrence`/`port`/`item`だけでなく`part`も取りうる
    # （leading multiplicity対応と同時に発見した同一行パターン）。
    part_kind_ast = parse_sysml_antlr(
        "connection def C { end [1] part producer : PowerProducer; }"
    )
    part_kind_node = part_kind_ast["children"][0]["children"][0]
    assert part_kind_node["kind"] == "part"
    assert part_kind_node["name"] == "producer"
    assert part_kind_node["type_name"] == "PowerProducer"

    trailing_postkind_ast = parse_sysml_antlr(
        "connection { part q; end ref end1 ::> d1 :> q; }"
    )
    trailing_postkind_node = trailing_postkind_ast["children"][0]["children"][-1]
    assert trailing_postkind_node["type"] == "connection_end_member"
    assert trailing_postkind_node["reference"] == "d1"
    assert trailing_postkind_node["redefines"] == [
        {"kind": "subsets", "target": "q"}
    ]

    # 既存のendName+endMultペア形が引き続き機能することを確認する。
    paired_ast = parse_sysml_antlr(
        "connection def C { end theCauses [*] occurrence theCause; }"
    )
    paired_node = paired_ast["children"][0]["children"][0]
    assert paired_node["endName"] == "theCauses"
    assert paired_node["endMultiplicity"] == {
        "size": {"min": "*", "max": "*"}, "is_ordered": False, "is_unique": True
    }


def test_antlr_connectionendmember_crosses_clause():
    """`end item cart: ShoppingCart[1] crosses selectedProduct.inCart;`
    （ProductSelection_UnownedEnds.sysml L14-15）のように、
    connectionEndMemberには型節・多重度の後に`crosses`節（KerMLの
    CrossSubsetting、対となる相方end側のフィーチャーチェーンパスを
    参照）を置くこともある（従来完全に未実装だった）。2026-08-29、
    add_connectionendmember_leading_multiplicity対応中に連鎖的に発見。"""
    ast = parse_sysml_antlr(
        "connection def ProductSelection {\n"
        "    end item cart: ShoppingCart[1] crosses selectedProduct.inCart;\n"
        "    end item selectedProduct: Product[1] crosses cart.selectedProducts;\n"
        "}"
    )
    cart, selected_product = ast["children"][0]["children"]
    assert cart["type"] == "connection_end_member"
    assert cart["name"] == "cart"
    assert cart["crosses"] == "selectedProduct.inCart"
    assert selected_product["name"] == "selectedProduct"
    assert selected_product["crosses"] == "cart.selectedProducts"

    # 既存のcrosses節無し形が引き続き機能し、"crosses"キー自体が無いことを
    # 確認する（回帰防止、既存のexact-equality辞書テストとの共存）。
    plain_ast = parse_sysml_antlr("connection def C { end a : PortA; }")
    plain_node = plain_ast["children"][0]["children"][0]
    assert "crosses" not in plain_node


def test_antlr_flowusage_named_bare_from_to_form():
    """`flow publish_request from producerBehavior.publish.request to
    publicationPort.publish { attribute :>> isInstant = true; }`
    （ServerSequenceOutsideRealization-3.sysml）のように、flowUsageの裸
    短縮形（`from...to`）に名前を伴い、かつ`;`終端の代わりに本体を持つ
    ことがある（従来この代替に名前スロット自体が無かった）。`ofType`/
    `typeRef`ラベルで代替を判別するため、既存の`flow of X from a to b;`
    （型付き裸形）・`abstract flow flows: Flow[0..*] ... { }`（型定義形）
    が引き続き機能することも確認する。2026-08-29、235件パース失敗の
    要因分析で発見。"""
    ast = parse_sysml_antlr(
        "part def X { flow publish_request from a.b to c.d "
        "{ attribute :>> isInstant = true; } }"
    )
    node = ast["children"][0]["children"][0]
    assert node["type"] == "flow_usage"
    assert node["name"] == "publish_request"
    assert node["from_end"] == "a::b"
    assert node["to_end"] == "c::d"
    assert len(node["children"]) == 1

    # 既存の`;`終端・名前無し形が引き続き機能することを確認する。
    semi_ast = parse_sysml_antlr("part def X { flow publish_request2 from a.b to c.d; }")
    semi_node = semi_ast["children"][0]["children"][0]
    assert semi_node["name"] == "publish_request2"
    assert semi_node["children"] == []

    typed_ast = parse_sysml_antlr("part def X { flow of X from a to b; }")
    typed_node = typed_ast["children"][0]["children"][0]
    assert typed_node["name"] is None
    assert typed_node["item_type"] == "X"

    # 既存の型定義形（第2代替）が引き続き機能することを確認する。
    def_ast = parse_sysml_antlr(
        "part def P { abstract flow flows: Flow[0..*] "
        "nonunique :> messages, flowTransfers { } }"
    )
    def_node = def_ast["children"][0]["children"][0]
    assert def_node["name"] == "flows"
    assert def_node["type_name"] == "Flow"
    assert def_node["isAbstract"] is True


def test_antlr_flowusage_of_type_multiplicity():
    """`flow call_getItems of CallGiveItems[1] from tlu.cll to
    apsph.cll;`（AHFSequences.sysml L89）のように、flowUsageの第1代替の
    `of`型の直後に多重度`[1]`が付くことがある（従来`ofType=ID`のみで
    multiplicitySpecが無かった）。`ofMult`という専用ラベルを使う必要が
    あった（無ラベルのままだと`getTypedRuleContext`が代替を区別せず
    型だけで検索するため、第2代替（型定義形）の判別ロジックが誤って
    このofMultノードを拾ってしまい、第2代替として誤分類される回帰が
    あった。その回帰を防ぐため第2代替の多重度にも`typeMult`という専用
    ラベルを付けた）。2026-08-29、
    add_interfaceusage_nary_connect_form対応中に連鎖的に発見。"""
    ast = parse_sysml_antlr(
        "flow call_getItems of CallGiveItems[1] from tlu.cll to apsph.cll;"
    )
    node = ast["children"][0]
    assert node["type"] == "flow_usage"
    assert node["name"] == "call_getItems"
    assert node["item_type"] == "CallGiveItems"
    assert node["from_end"] == "tlu::cll"
    assert node["to_end"] == "apsph::cll"
    assert node["item_multiplicity"] == {
        "size": {"min": 1, "max": 1}, "is_ordered": False, "is_unique": True
    }

    # 既存の多重度無し`of`型が引き続き機能することを確認する
    # （"item_multiplicity"キー自体が無いことも確認する）。
    plain_ast = parse_sysml_antlr("part def X { flow of X from a to b; }")
    plain_node = plain_ast["children"][0]["children"][0]
    assert plain_node["item_type"] == "X"
    assert "item_multiplicity" not in plain_node

    # 既存の型定義形（第2代替）が誤分類されないことを確認する
    # （typeMultラベル分離の回帰防止）。
    def_ast = parse_sysml_antlr(
        "part def P { abstract flow flows: Flow[0..*] "
        "nonunique :> messages, flowTransfers { } }"
    )
    def_node = def_ast["children"][0]["children"][0]
    assert def_node["type_name"] == "Flow"
    assert def_node["multiplicity"] == {
        "size": {"min": 0, "max": "*"}, "is_ordered": False, "is_unique": False
    }
    assert "item_type" not in def_node


def test_antlr_then_prefix_stateusage():
    """`then state wait;`（AssignmentTest.sysml）のように、stateUsage自体
    に`then`前置が無かった（他の多くの規則（performActionStmt等）では
    既に`isThen`対応済みで非対称だった）。2026-08-29、235件パース失敗の
    要因分析で発見。"""
    ast = parse_sysml_antlr(
        "state def Counting { entry; then state wait; state wait; }"
    )
    children = ast["children"][0]["children"]
    then_node = children[1]
    assert then_node["type"] == "state_usage"
    assert then_node["name"] == "wait"
    assert then_node["isThen"] is True

    # 既存の`then`無し形が引き続き機能することを確認する。
    plain_node = children[2]
    assert plain_node["type"] == "state_usage"
    assert "isThen" not in plain_node


def test_antlr_entry_do_exit_actionmember_body():
    """`entry performSelfTest{ in vehicle = operatingVehicle; }` /
    `do action providePower { ... }` / `exit action applyParkingBrake
    { ... }`（State Actions.sysml）のように、entryActionMember/
    doActionMember/exitActionMemberのいずれも参照直後に`;`終端の代わりに
    `{ actionBodyElement* }`本体を持てなかった（従来`;`終端のみ）。
    既存の`;`終端形が引き続き機能することも確認する。2026-08-29、235件
    パース失敗の要因分析で発見。"""
    ast = parse_sysml_antlr(
        "state on { entry performSelfTest{ in vehicle = operatingVehicle; } "
        "do action providePower { } exit action applyParkingBrake { } }"
    )
    entry, do, exit_ = ast["children"][0]["children"]
    assert entry["type"] == "entry_action"
    assert entry["action_reference"] == "performSelfTest"
    assert len(entry["children"]) == 1
    assert do["type"] == "do_action"
    assert do["action_reference"] == "providePower"
    assert do["children"] == []
    assert exit_["type"] == "exit_action"
    assert exit_["action_reference"] == "applyParkingBrake"
    assert exit_["children"] == []

    # 既存の`;`終端形が引き続き機能することを確認する。
    semi_ast = parse_sysml_antlr(
        "state on { entry action entryAction :>> 'entry'; "
        "do action doAction: Action :>> 'do'; "
        "exit action exitAction: Action :>> 'exit'; }"
    )
    semi_entry, semi_do, semi_exit = semi_ast["children"][0]["children"]
    assert semi_entry["children"] == []
    assert semi_do["children"] == []
    assert semi_exit["children"] == []


def test_antlr_visibility_prefix_on_actionparameter():
    """`private in ref y: A, B;`（ItemTest.sysml）のように、
    visibilityIndicatorが方向修飾子の前に付くことがある（従来
    actionParameterには一切登録されていなかった）。型節がカンマ区切り
    の複数型（`A, B`）を取ることも併せて確認する。当初featureUsage側に
    directionを追加する案を試したが、featureUsageはpartBodyElement/
    stateBodyElement等でactionParameterより先に登録されており、
    `in x : Type;`のような裸形の判別が曖昧になって既存の多数のテストを
    壊したため、actionParameter自体にvisibilityIndicator?を足す設計に
    変更した。2026-08-29、235件パース失敗の要因分析で発見。"""
    ast = parse_sysml_antlr("action def A { private in ref y: A, B; }")
    param = ast["children"][0]["params"][0]
    assert param["type"] == "param"
    assert param["visibility"] == "private"
    assert param["direction"] == "in"
    assert param["kind"] == "ref"
    assert param["name"] == "y"
    assert param["type_names"] == ["A", "B"]

    # 既存のvisibility無し形が引き続き機能することを確認する。
    plain_ast = parse_sysml_antlr("action def A { in x : T; }")
    plain_param = plain_ast["children"][0]["params"][0]
    assert plain_param["visibility"] is None
    assert plain_param["type_name"] == "T"
    assert "type_names" not in plain_param


def test_antlr_actionparameter_compound_kind():
    """`private in ref item y: A, B;`（ItemTest.sysml(xpect) L16）のように、
    actionParameterの`kind`は単一トークンだけでなく`ref item`のような
    複合形も取りうる（従来`ref`単独か`item`等単独のいずれかしか受理
    できなかった）。`ref`単独形（`kind`が`"ref"`になる後方互換）が
    引き続き機能することも確認する。2026-08-29、
    add_actionparameter_compound_kind対応中に発見。"""
    ast = parse_sysml_antlr(
        "part def C { private in ref item y: A, B; }"
    )
    param = ast["children"][0]["children"][0]
    assert param["type"] == "param"
    assert param["kind"] == "item"
    assert param["isRef"] is True
    assert param["is_item"] is True
    assert param["type_names"] == ["A", "B"]

    # 既存の`ref`単独形が引き続き機能することを確認する
    # （"isRef"キー自体が無いことも確認する）。
    bare_ref_ast = parse_sysml_antlr("action def A { private in ref y: A, B; }")
    bare_ref_param = bare_ref_ast["children"][0]["params"][0]
    assert bare_ref_param["kind"] == "ref"
    assert "isRef" not in bare_ref_param

    # 既存の`item`単独形が引き続き機能することを確認する。
    bare_item_ast = parse_sysml_antlr("action def A { in item x : T; }")
    bare_item_param = bare_item_ast["children"][0]["params"][0]
    assert bare_item_param["kind"] == "item"
    assert "isRef" not in bare_item_param


def test_antlr_actionparameter_general_body_content():
    """`private in ref y: A, B { part B_b redefines B::b; port B_x
    redefines B::x; }`（PartTest.sysml L38、private port def C本体内）の
    ように、actionParameterのbodyには一般のpartBodyElement内容
    （part/port等のredefine宣言）も持ちうる（従来はdocumentationStmt/
    bareDocComment/actionParameter/metadataUsageの4種のみに限定されて
    おり、`part`キーワードで構文エラーになっていた）。誤診断の経緯:
    当初はfeatureUsageにdirectionプレフィックスを追加する必要があると
    考えたが、実際にはactionParameter自体へのディスパッチは既に正しく
    行われており（`kind`は既に`'ref'`を含む）、body内容の許可範囲が
    狭すぎただけだった。partBodyElement自体がこの4種を全て含むため、
    他の多くの規則と同じ`partBodyElement*`に一般化することで解決した
    （actionParameterへのディスパッチ自体は変更していないため、
    feedback_grammar_alt_order_ambiguityで警告された代替順アンビギュ
    イティのリスクは無い）。既存の入れ子actionParameter形・`@Type { ... }`
    インラインメタデータ注釈形が引き続き機能することも確認する。
    2026-08-29、add_nested_packagedef_in_partbody対応中に連鎖的に発見。"""
    ast = parse_sysml_antlr(
        "part def X { private in ref y: A, B { "
        "part B_b redefines B::b; port B_x redefines B::x; } }"
    )
    param = ast["children"][0]["children"][0]
    assert param["type"] == "param"
    assert param["direction"] == "in"
    assert param["kind"] == "ref"
    assert [c["type"] for c in param["children"]] == ["part_instance", "port_usage"]
    assert param["children"][0]["redefines"] == [
        {"kind": "redefines", "target": "B::b"}
    ]
    assert param["children"][1]["redefines"] == [
        {"kind": "redefines", "target": "B::x"}
    ]

    # 既存の入れ子actionParameter形が引き続き機能することを確認する。
    nested_ast = parse_sysml_antlr("action def A { in calc calculation { in x; } }")
    nested_param = nested_ast["children"][0]["params"][0]
    assert nested_param["children"][0]["type"] == "param"
    assert nested_param["children"][0]["name"] == "x"

    # 既存の`@Type { ... }`インラインメタデータ注釈形が引き続き機能する
    # ことを確認する。
    meta_ast = parse_sysml_antlr(
        'action def A { in dt : TimeValue { @ToolVariable { name = "deltaT"; } } }'
    )
    meta_param = meta_ast["children"][0]["params"][0]
    assert meta_param["children"][0]["type"] == "metadata_usage"
    assert meta_param["children"][0]["name"] == "ToolVariable"


def test_antlr_visibility_modifier_on_aliasstmt():
    """`public alias X for Y;`（Package Example.sysml）のように、
    aliasStmtにvisibilityIndicator（public/private/protected）が付いて
    いなかった。既存のvisibility無し形が引き続き機能することも確認する。
    2026-08-29、235件パース失敗の要因分析で発見。"""
    ast = parse_sysml_antlr("public alias X for Y;")
    node = ast["children"][0]
    assert node["type"] == "alias"
    assert node["visibility"] == "public"
    assert node["name"] == "X"
    assert node["target"] == "Y"

    plain_ast = parse_sysml_antlr("alias X for Y;")
    plain_node = plain_ast["children"][0]
    assert plain_node["visibility"] is None
