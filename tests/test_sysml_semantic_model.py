"""Semantic Model基盤（SysMLv2_SemanticModel_拡張仕様書.md）の新規ユニットテスト。

parse_sysml_with_semantic_model() は parse_sysml_antlr() に対する追加のみの
拡張であり、既存の ast 形状・既存テストには一切影響しない
（拡張仕様書3,4章の後方互換制約）。そのためこのファイルは新規に追加し、
既存の test_sysml_antlr_pipeline.py 等のexact-equalityテストには一切手を
入れない。
"""

from __future__ import annotations

from sysml_v2_checker_advanced.antlr_transformer import (
    _extract_source_range,
    parse_sysml_antlr,
    parse_sysml_with_semantic_model,
)

_SAMPLE = """
package Vehicle {
    part def Engine {
        attribute power : Real;
    }
    part myEngine : Engine;
}
"""


def test_ast_is_unaffected_by_semantic_model_collection():
    """astの内容はparse_sysml_antlr()と完全一致し、新規キーも混入しない。"""
    ast_plain = parse_sysml_antlr(_SAMPLE.strip())
    ast_with_model, _ = parse_sysml_with_semantic_model(_SAMPLE.strip())

    assert ast_with_model == ast_plain
    # part_def(Engine)ノードにid/source_range等が混入していないこと
    engine_node = ast_with_model["children"][0]
    assert engine_node["type"] == "part_def"
    assert set(engine_node.keys()) == {
        "type", "name", "shortName", "visibility", "isAbstract",
        "isIndividual", "variability", "inheritance", "children",
    }


def test_semantic_model_node_is_same_object_as_ast_node():
    """model.nodes[id]["node"] は ast 内の実物と同一オブジェクト（コピーでない）。"""
    ast, model = parse_sysml_with_semantic_model(_SAMPLE.strip())
    engine_via_tree = ast["children"][0]
    engine_via_model = model["nodes"]["$root::Engine"]["node"]
    assert engine_via_model is engine_via_tree


def test_root_gets_fixed_id():
    ast, model = parse_sysml_with_semantic_model(_SAMPLE.strip())
    assert model["root_id"] == "$root"
    assert model["nodes"]["$root"]["type"] == "package"
    assert model["nodes"]["$root"]["parent_id"] is None


def test_named_nodes_get_qualified_name_style_id():
    _, model = parse_sysml_with_semantic_model(_SAMPLE.strip())
    assert model["nodes"]["$root::Engine"]["parent_id"] == "$root"
    assert model["nodes"]["$root::Engine::power"]["parent_id"] == "$root::Engine"
    assert model["nodes"]["$root::myEngine"]["type"] == "part_instance"


def test_anonymous_sibling_nodes_get_positional_index():
    text = """
    action def A {
        assert constraint : C1;
        assert constraint : C2;
    }
    """
    _, model = parse_sysml_with_semantic_model(text.strip())
    positional_ids = sorted(
        sid for sid, entry in model["nodes"].items()
        if entry["type"] == "assert_constraint_usage"
    )
    assert positional_ids == [
        "$root::A/constraint_stmt#0/assert_constraint_usage#0",
        "$root::A/constraint_stmt#1/assert_constraint_usage#0",
    ]


def test_duplicate_named_siblings_get_numbered_suffix():
    """同一親内に同名ノードが複数ある場合、発見順に#2,#3...を付与する
    （2026-09-03、P2-0でユーザー確認の上確定。拡張仕様書6.2章）。
    """
    text = """
    package P {
        part def A {
            attribute mass : Real;
            attribute mass : Real;
            attribute mass : Real;
        }
    }
    """
    _, model = parse_sysml_with_semantic_model(text.strip())
    assert "$root::A::mass" in model["nodes"]
    assert "$root::A::mass#2" in model["nodes"]
    assert "$root::A::mass#3" in model["nodes"]
    assert model["nodes"]["$root::A::mass#2"]["node"] is not model["nodes"]["$root::A::mass"]["node"]


def test_source_range_is_populated_for_every_node():
    _, model = parse_sysml_with_semantic_model(_SAMPLE.strip())
    power = model["nodes"]["$root::Engine::power"]["source_range"]
    assert power is not None
    assert power["start_line"] == 3
    assert power["end_line"] == 3
    assert power["start_offset"] < power["end_offset"]


def test_parse_error_returns_empty_semantic_model():
    ast, model = parse_sysml_with_semantic_model("this is not valid sysml {{{")
    assert ast.get("type") == "error"
    assert model == {"nodes": {}, "root_id": None}


def test_extract_source_range_falls_back_when_stop_is_none():
    """ctx.stopがNoneの構文エラー回復パスでもクラッシュせずstartで代用する
    （拡張仕様書7章）。実パースでの再現は難しいため、最小スタブで直接検証する。
    """

    class _FakeToken:
        def __init__(self, line, column, start):
            self.line = line
            self.column = column
            self.start = start
            self.stop = start

    class _FakeCtx:
        start = _FakeToken(line=1, column=0, start=0)
        stop = None

    source_range = _extract_source_range(_FakeCtx())
    assert source_range == {
        "start_line": 1,
        "start_column": 0,
        "end_line": 1,
        "end_column": 0,
        "start_offset": 0,
        "end_offset": 0,
    }


# --- 5.2章のカバレッジギャップ回帰テスト -------------------------------
# _binary_part()経由・"*_stmt"ラッパー内のinnerノードは、visit()の
# オーバーライドだけでは捕捉できなかった（source_rangeがNoneのままになる）
# 既知のギャップだった。個別にself._register()を追加して解消したことを
# 確認する。


def test_flow_from_stmt_inner_node_has_source_range():
    text = """
    action def A {
        flow from a to b;
    }
    """
    _, model = parse_sysml_with_semantic_model(text.strip())
    inner = next(e for e in model["nodes"].values() if e["type"] == "flow_from_stmt")
    assert inner["source_range"] is not None


def test_expose_inner_node_has_source_range():
    text = """
    package P {
        view def V {
            expose Q::*;
        }
    }
    """
    _, model = parse_sysml_with_semantic_model(text.strip())
    inner = next(e for e in model["nodes"].values() if e["type"] == "expose")
    assert inner["source_range"] is not None


def test_dependency_inner_node_has_source_range():
    text = """
    package P {
        part def A;
        part def B;
        dependency from A to B;
    }
    """
    _, model = parse_sysml_with_semantic_model(text.strip())
    inner = next(e for e in model["nodes"].values() if e["type"] == "dependency")
    assert inner["source_range"] is not None


def test_interface_part_has_source_range():
    text = """
    package P {
        part a;
        part b;
        interface iface: IfaceType connect a to b;
    }
    """
    _, model = parse_sysml_with_semantic_model(text.strip())
    inner = next(e for e in model["nodes"].values() if e["type"] == "binary_interface_part")
    assert inner["source_range"] is not None
