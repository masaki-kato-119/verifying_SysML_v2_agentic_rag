"""バックエンド選択の判定ロジックのテスト。優先度: その他。

評価結果の集計が壊れていると、選択率の改善／悪化を誤って読むことになる。
"""

import importlib.util
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="module")
def evalmod():
    """scripts/ はパッケージではないためファイルパスから読み込む。"""
    path = REPO_ROOT / "scripts" / "run_backend_eval.py"
    spec = importlib.util.spec_from_file_location("run_backend_eval", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


HYBRID = "Hybrid RAG MCP Server"
GRAPH = "Graph RAG MCP Server"


def test_no_tool_call_is_flagged(evalmod):
    assert evalmod.classify("hybrid", set()) == "no-tool-call"


def test_expected_backend_matched(evalmod):
    assert evalmod.classify("hybrid", {HYBRID}) == "ok"
    assert evalmod.classify("graph", {GRAPH}) == "ok"


def test_wrong_backend_is_miss(evalmod):
    assert evalmod.classify("graph", {HYBRID}) == "miss"


def test_expected_backend_plus_other_is_still_ok(evalmod):
    assert evalmod.classify("graph", {GRAPH, HYBRID}) == "ok(+other)"


def test_either_accepts_any_single_backend(evalmod):
    assert evalmod.classify("either", {HYBRID}) == "ok"
    assert evalmod.classify("either", {GRAPH}) == "ok"


def test_either_marks_collaboration_when_both_used(evalmod):
    assert evalmod.classify("either", {GRAPH, HYBRID}) == "ok(both)"


def test_eval_query_set_is_consistent_with_classify(evalmod):
    """評価クエリの expected_backend が判定関数の想定と一致していること。"""
    import json

    spec = json.loads(
        (REPO_ROOT / "eval" / "backend_selection_queries.json").read_text(encoding="utf-8")
    )
    allowed = set(evalmod.BACKEND_TO_SERVER) | {"either"}
    for case in spec["cases"]:
        assert case["expected_backend"] in allowed, case["id"]


def test_tool_error_is_detected(evalmod):
    """失敗した呼び出しを成功として数えないこと。"""
    assert evalmod.is_tool_error("ツール実行中にエラーが発生しました: 環境変数が未設定")
    assert evalmod.is_tool_error("ツール 'foo' は登録されていません。")


def test_successful_tool_result_is_not_an_error(evalmod):
    assert not evalmod.is_tool_error('[{"chunk_id": "x", "text": "..."}]')
    assert not evalmod.is_tool_error("")
