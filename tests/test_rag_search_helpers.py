"""rag.search の純粋関数・結合ロジック（API 非依存）。優先度: HybridRAG/rag。"""

from rag.metadata_store import ChunkMetadata
from rag.search import (
    HybridSearchResult,
    _apply_diversity_limit,
    _dedupe_meta_results,
    _dedupe_vector_results,
    _extract_chunk_index,
    _extract_file_key,
    _min_max_normalize,
    _rank_based_scores,
    _rrf_scores,
    choose_weights_for_query,
    combine_for_hybrid,
    combine_for_hybrid_rrf,
    combine_for_hybrid_with_scores,
    detect_query_type,
)
from rag.vector_store import VectorRecord


def _chunk_meta(chunk_id: str, *, bm25: float | None = 1.0) -> ChunkMetadata:
    return ChunkMetadata(
        id=1,
        chunk_id=chunk_id,
        file_name="f.txt",
        file_path="/x/f.txt",
        file_type="txt",
        chunk_text="body",
        chunk_index=0,
        page_number=None,
        created_at="2020-01-01T00:00:00",
        updated_at="2020-01-01T00:00:00",
        bm25_score=bm25,
    )


def test_rank_based_and_rrf():
    assert _rank_based_scores([]) == {}
    r = _rank_based_scores(["a", "b"])
    assert r["a"] > r["b"]
    s = _rrf_scores(["a", "b"], k=60)
    assert s["a"] > s["b"]


def test_dedupe_vector_and_meta():
    v = [
        VectorRecord(id="1", text="a", metadata={}),
        VectorRecord(id="1", text="b", metadata={}),
    ]
    assert len(_dedupe_vector_results(v)) == 1
    m = [_chunk_meta("c1"), _chunk_meta("c1")]
    assert len(_dedupe_meta_results(m)) == 1


def test_min_max_normalize():
    assert _min_max_normalize([], smaller_is_better=False) == []
    assert _min_max_normalize([5.0, 5.0], smaller_is_better=False) == [1.0, 1.0]
    assert _min_max_normalize([1.0, 3.0], smaller_is_better=True)[0] > _min_max_normalize([1.0, 3.0], smaller_is_better=True)[1]


def test_combine_for_hybrid_rank():
    vec = [VectorRecord(id="a", text="ta", metadata={"k": 1})]
    meta = [_chunk_meta("a"), _chunk_meta("b")]
    out = combine_for_hybrid(vec, meta, weight_vector=0.5, weight_meta=0.5)
    assert len(out) == 2
    assert all(isinstance(r, HybridSearchResult) for r in out)


def test_combine_for_hybrid_rrf():
    vec = [VectorRecord(id="x", text="t", metadata={})]
    meta = [_chunk_meta("x")]
    out = combine_for_hybrid_rrf(vec, meta, rrf_k=10)
    assert len(out) >= 1


def test_combine_for_hybrid_with_scores():
    vec = [VectorRecord(id="u1", text="t", metadata={}, distance=0.1)]
    meta = [_chunk_meta("u1", bm25=0.2)]
    out = combine_for_hybrid_with_scores(vec, meta)
    assert out and out[0].score_hybrid > 0


def test_detect_query_and_weights():
    assert detect_query_type("") == "semantic"
    assert detect_query_type("short") == "keyword"
    assert choose_weights_for_query("a" * 5)[0] < 0.5


def test_extract_file_key_and_chunk_index():
    r = HybridSearchResult(
        chunk_id="doc1::chunk-3",
        text="",
        metadata={"file_path": "/p/f.txt"},
    )
    assert _extract_file_key(r) == "/p/f.txt"
    r2 = HybridSearchResult(chunk_id="d::chunk-2", text="", metadata={})
    assert _extract_file_key(r2) == "d"
    assert _extract_chunk_index(r2) == 2


def test_apply_diversity_limit():
    same_file = "/x/a.txt"
    results = [
        HybridSearchResult(
            chunk_id=f"id{i}::chunk-{i}",
            text="t",
            metadata={"file_path": same_file},
            score_hybrid=1.0 - i * 0.1,
        )
        for i in range(4)
    ]
    limited = _apply_diversity_limit(results, max_chunks_per_file=2)
    assert len(limited) == 2
    assert _apply_diversity_limit(results, max_chunks_per_file=None) == results
    assert _apply_diversity_limit(results, max_chunks_per_file=0) == []
