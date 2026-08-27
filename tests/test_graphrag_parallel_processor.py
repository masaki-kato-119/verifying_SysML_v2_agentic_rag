"""graphrag.parallel_processor の並列探索・バッチ処理・デコレータのテスト。優先度: GraphRAG。

ParallelProcessor は ThreadPoolExecutor でノード探索/ソーステキスト取得/パス探索/
バッチ処理を並列化する。短時間で終わるフェイクのワーカー関数・フェイクの
chunk_storage を注入し、結果の集約（順序に依存しない）・品質フィルタ・
例外時のエラー結果保持・停止イベントによる早期終了を検証する。
"""

import networkx as nx
import pytest
from graphrag.parallel_processor import ParallelProcessor, parallel_execution_decorator


@pytest.fixture
def processor():
    return ParallelProcessor(max_workers=4, timeout=5.0)


# ---- parallel_node_exploration ----


def test_parallel_node_exploration_returns_all_results_unordered(processor):
    graph = nx.DiGraph()

    def explore(node_name):
        return {"node": node_name, "quality_score": 1.0}

    results = processor.parallel_node_exploration(graph, ["a", "b", "c"], explore)

    assert sorted(r["node"] for r in results) == ["a", "b", "c"]


def test_parallel_node_exploration_filters_by_quality_threshold(processor):
    graph = nx.DiGraph()
    scores = {"a": 0.9, "b": 0.1}

    def explore(node_name):
        return {"node": node_name, "quality_score": scores[node_name]}

    results = processor.parallel_node_exploration(
        graph, ["a", "b"], explore, quality_threshold=0.5
    )

    assert [r["node"] for r in results] == ["a"]


def test_parallel_node_exploration_keeps_error_result_on_exception(processor):
    graph = nx.DiGraph()

    def explore(node_name):
        if node_name == "bad":
            raise ValueError("boom")
        return {"node": node_name, "quality_score": 1.0}

    results = processor.parallel_node_exploration(graph, ["ok", "bad"], explore)

    by_node = {r.get("node") or r.get("node_name"): r for r in results}
    assert by_node["ok"]["quality_score"] == 1.0
    assert by_node["bad"]["success"] is False
    assert by_node["bad"]["error"] == "boom"


def test_parallel_node_exploration_resets_stop_event_after_run(processor):
    graph = nx.DiGraph()

    def explore(node_name):
        return {"node": node_name}

    processor.parallel_node_exploration(graph, ["a"], explore, max_results=1)

    # 早期終了で停止イベントが立っても、メソッド終了時にリセットされること
    assert not processor._stop_event.is_set()


def test_parallel_node_exploration_returns_empty_when_already_stopped(processor):
    graph = nx.DiGraph()
    calls = []

    def explore(node_name):
        calls.append(node_name)
        return {"node": node_name}

    processor._stop_event.set()
    results = processor.parallel_node_exploration(graph, ["a", "b"], explore)

    assert results == []
    # リセットされ、以降の呼び出しに影響しないこと
    assert not processor._stop_event.is_set()


# ---- parallel_source_text_retrieval / parallel_edge_source_text_retrieval ----


class _FakeChunkStorage:
    """ChunkStorage の代替。ノード/エッジ -> チャンクIDの対応をメモリ上に保持する。"""

    def __init__(self, node_chunks=None, edge_chunks=None, chunk_texts=None):
        self._node_chunks = node_chunks or {}
        self._edge_chunks = edge_chunks or {}
        self._chunk_texts = chunk_texts or {}

    def get_node_chunks(self, graph_id, node_name):
        return list(self._node_chunks.get(node_name, []))

    def get_edge_chunks(self, graph_id, source, target):
        return list(self._edge_chunks.get((source, target), []))

    def get_chunks(self, graph_id, chunk_ids):
        return {cid: self._chunk_texts[cid] for cid in chunk_ids if cid in self._chunk_texts}


def test_parallel_source_text_retrieval_maps_each_node_to_its_chunks(processor):
    storage = _FakeChunkStorage(
        node_chunks={"n1": ["c1", "c2"], "n2": []},
        chunk_texts={"c1": "text1", "c2": "text2"},
    )

    results = processor.parallel_source_text_retrieval(storage, "g1", ["n1", "n2"])

    assert results["n1"] == ["text1", "text2"]
    assert results["n2"] == []


def test_parallel_source_text_retrieval_limits_chunks_per_node(processor):
    storage = _FakeChunkStorage(
        node_chunks={"n1": ["c1", "c2", "c3"]},
        chunk_texts={"c1": "t1", "c2": "t2", "c3": "t3"},
    )

    results = processor.parallel_source_text_retrieval(
        storage, "g1", ["n1"], max_chunks_per_node=2
    )

    assert results["n1"] == ["t1", "t2"]


def test_parallel_source_text_retrieval_returns_empty_on_storage_error(processor):
    class _RaisingStorage:
        def get_node_chunks(self, graph_id, node_name):
            raise RuntimeError("db down")

    results = processor.parallel_source_text_retrieval(_RaisingStorage(), "g1", ["n1"])

    assert results["n1"] == []


def test_parallel_edge_source_text_retrieval_maps_each_edge_to_its_chunks(processor):
    storage = _FakeChunkStorage(
        edge_chunks={("a", "b"): ["c1"], ("c", "d"): []},
        chunk_texts={"c1": "edge-text"},
    )

    results = processor.parallel_edge_source_text_retrieval(
        storage, "g1", [("a", "b"), ("c", "d")]
    )

    assert results[("a", "b")] == ["edge-text"]
    assert results[("c", "d")] == []


# ---- parallel_path_finding ----


def test_parallel_path_finding_generates_all_start_target_combinations(processor):
    graph = nx.DiGraph()
    seen_pairs = []

    def find_path(start, target):
        seen_pairs.append((start, target))
        return {"success": True, "start": start, "target": target, "quality_score": 1.0}

    results = processor.parallel_path_finding(graph, ["s1", "s2"], ["t1"], find_path)

    assert sorted(seen_pairs) == [("s1", "t1"), ("s2", "t1")]
    assert sorted((r["start"], r["target"]) for r in results) == [("s1", "t1"), ("s2", "t1")]


def test_parallel_path_finding_drops_unsuccessful_paths(processor):
    graph = nx.DiGraph()

    def find_path(start, target):
        return {"success": target == "reachable", "start": start, "target": target}

    results = processor.parallel_path_finding(
        graph, ["s1"], ["reachable", "unreachable"], find_path
    )

    assert [r["target"] for r in results] == ["reachable"]


def test_parallel_path_finding_keeps_error_result_on_exception(processor):
    graph = nx.DiGraph()

    def find_path(start, target):
        raise ValueError("path error")

    results = processor.parallel_path_finding(graph, ["s1"], ["t1"], find_path)

    assert len(results) == 1
    assert results[0]["success"] is False
    assert results[0]["error"] == "path error"


# ---- batch_process_with_progress ----


def test_batch_process_with_progress_processes_all_items(processor):
    def double(item):
        return item * 2

    results = processor.batch_process_with_progress([1, 2, 3, 4], double, batch_size=2)

    assert sorted(results) == [2, 4, 6, 8]


def test_batch_process_with_progress_invokes_progress_callback_for_each_item(processor):
    progress_calls = []

    def record_progress(done, total):
        progress_calls.append((done, total))

    processor.batch_process_with_progress(
        [1, 2, 3], lambda x: x, batch_size=10, progress_callback=record_progress
    )

    assert len(progress_calls) == 3
    assert all(total == 3 for _, total in progress_calls)
    assert sorted(done for done, _ in progress_calls) == [1, 2, 3]


# ---- stop_processing / reset ----


def test_stop_processing_sets_event_and_reset_clears_it(processor):
    processor.stop_processing()
    assert processor._stop_event.is_set()

    processor.reset()
    assert not processor._stop_event.is_set()


# ---- parallel_execution_decorator ----


def test_decorator_runs_normally_without_parallel_items():
    @parallel_execution_decorator()
    def add(a, b):
        return a + b

    assert add(1, 2) == 3


def test_decorator_runs_in_parallel_when_parallel_items_given():
    @parallel_execution_decorator(max_workers=2, timeout=5.0)
    def compute(base, offset=0):
        return base + offset

    results = compute(
        10, parallel_items=[{"offset": 1}, {"offset": 2}, {"offset": 3}]
    )

    assert sorted(results) == [11, 12, 13]


def test_decorator_with_empty_parallel_items_falls_back_to_normal_call():
    calls = []

    @parallel_execution_decorator()
    def record(x, parallel_items=None):
        calls.append(x)
        return x

    result = record(5, parallel_items=[])

    assert result == 5
    assert calls == [5]
