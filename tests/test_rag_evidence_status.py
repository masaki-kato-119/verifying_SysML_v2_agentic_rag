"""根拠抽出の結果表明（evidence_status）のテスト。優先度: HybridRAG/rag。

根拠ノードが取得できなかったことを結果側から明示しないと、LLM が
「GraphRAG で Constraint から抽出した」といった実在しない出典を名乗る。
その退行を検知するためのテスト。
"""

from rag.search import EVIDENCE_NOT_AVAILABLE_NOTE, annotate_evidence_status


def test_marks_no_evidence_nodes_when_evidence_text_missing():
    results = [{"chunk_id": "c1", "metadata": {"file_name": "spec.pdf"}}]

    status = annotate_evidence_status(results)

    assert status == "no_evidence_nodes"
    assert results[0]["metadata"]["evidence_status"] == "no_evidence_nodes"
    assert results[0]["metadata"]["evidence_note"] == EVIDENCE_NOT_AVAILABLE_NOTE
    # 既存のメタデータは保持される
    assert results[0]["metadata"]["file_name"] == "spec.pdf"


def test_marks_found_when_any_result_has_evidence_text():
    results = [
        {"chunk_id": "c1", "metadata": {"evidence_text": "Relevant Constraints:\n- C1"}},
        {"chunk_id": "c2", "metadata": {}},
    ]

    status = annotate_evidence_status(results)

    assert status == "found"
    assert all(r["metadata"]["evidence_status"] == "found" for r in results)
    # 取得できている場合は注意書きを付けない
    assert all("evidence_note" not in r["metadata"] for r in results)


def test_does_not_mutate_shared_metadata_dict():
    """metadata は検索キャッシュと共有されうるため、コピーしてから書き換える。"""
    shared = {"file_name": "spec.pdf"}
    results = [{"chunk_id": "c1", "metadata": shared}]

    annotate_evidence_status(results)

    assert "evidence_status" not in shared
    assert results[0]["metadata"] is not shared


def test_handles_missing_metadata_key():
    results = [{"chunk_id": "c1"}]

    status = annotate_evidence_status(results)

    assert status == "no_evidence_nodes"
    assert results[0]["metadata"]["evidence_status"] == "no_evidence_nodes"


def test_empty_results_is_safe():
    results = []

    assert annotate_evidence_status(results) == "no_evidence_nodes"


def test_reranker_is_not_ready_before_preload():
    """MCP のワーカースレッドで初回ロードするとデッドロックするため、
    未ロードかどうかを検索側から判定できる必要がある。"""
    from rag import search

    # モデルを実際にロードすると 25 秒かかるので、状態の判定だけを確認する
    assert search.is_reranker_ready() is (search._GLOBAL_RERANKER is not None)


def test_preload_helpers_are_exported():
    from rag import search

    assert callable(search.preload_reranker)
    assert callable(search.is_reranker_ready)
