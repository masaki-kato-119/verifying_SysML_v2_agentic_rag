"""graphrag.evidence_extractor の根拠抜粋ロジック。優先度: GraphRAG(t6_add_tests_graphrag_gaps)。

EvidenceExtractorはこれまでテストが無かった。ChunkStorageをフェイクに置き換えて
チャンク抜粋・ハイライト・エラーハンドリングを検証する。テスト作成中に
extract_evidence_summaryのtarget_term算出が演算子優先順位のせいでnode_name指定時に
常にNoneへ潰れる不具合を発見したため、そのテストも含む。
"""

from graphrag.evidence_extractor import EvidenceExtractor


class _FakeChunkStorage:
    def __init__(self, node_chunks=None, edge_chunks=None, chunks=None):
        self.node_chunks = node_chunks or {}
        self.edge_chunks = edge_chunks or {}
        self.chunks = chunks or {}

    def get_node_chunks(self, graph_id, node_name):
        return self.node_chunks.get(node_name, [])

    def get_edge_chunks(self, graph_id, source, target):
        return self.edge_chunks.get((source, target), [])

    def get_chunks(self, graph_id, chunk_ids=None):
        ids = chunk_ids if chunk_ids is not None else list(self.chunks)
        return {cid: self.chunks[cid] for cid in ids if cid in self.chunks}


class _RaisingChunkStorage:
    def get_node_chunks(self, graph_id, node_name):
        raise RuntimeError("db down")

    def get_edge_chunks(self, graph_id, source, target):
        raise RuntimeError("db down")

    def get_chunks(self, graph_id, chunk_ids=None):
        raise RuntimeError("db down")


# ---- extract_evidence_summary: 正常系 ----


def test_extract_evidence_summary_returns_empty_message_when_no_node_chunks():
    extractor = EvidenceExtractor(_FakeChunkStorage())

    result = extractor.extract_evidence_summary("g1", node_name="requirement")

    assert result["success"] is True
    assert result["evidence_type"] == "node"
    assert result["summaries"] == []
    assert result["total_chunks"] == 0


def test_extract_evidence_summary_returns_node_summaries():
    storage = _FakeChunkStorage(
        node_chunks={"requirement": ["c0"]},
        chunks={"c0": "The requirement must be satisfied by the design."},
    )
    extractor = EvidenceExtractor(storage)

    result = extractor.extract_evidence_summary("g1", node_name="requirement")

    assert result["success"] is True
    assert result["evidence_type"] == "node"
    assert result["shown_chunks"] == 1
    assert result["summaries"][0]["chunk_id"] == "c0"
    assert result["reference_ids"]["node_name"] == "requirement"


def test_extract_evidence_summary_returns_edge_summaries():
    storage = _FakeChunkStorage(
        edge_chunks={("A", "B"): ["c0"]},
        chunks={"c0": "A depends on B for validation."},
    )
    extractor = EvidenceExtractor(storage)

    result = extractor.extract_evidence_summary("g1", edge_key=("A", "B"))

    assert result["success"] is True
    assert result["evidence_type"] == "edge"
    assert result["target"] == ("A", "B")
    assert result["reference_ids"]["edge_key"] == ("A", "B")


def test_extract_evidence_summary_limits_chunks_to_max_chunks():
    storage = _FakeChunkStorage(
        node_chunks={"n": ["c0", "c1", "c2"]},
        chunks={"c0": "text0", "c1": "text1", "c2": "text2"},
    )
    extractor = EvidenceExtractor(storage)

    result = extractor.extract_evidence_summary("g1", node_name="n", max_chunks=2)

    assert result["total_chunks"] == 3
    assert result["shown_chunks"] == 2
    assert result["reference_ids"]["chunk_ids"] == ["c0", "c1"]


def test_extract_evidence_summary_returns_failure_on_exception():
    extractor = EvidenceExtractor(_RaisingChunkStorage())

    result = extractor.extract_evidence_summary("g1", node_name="n")

    assert result["success"] is False
    assert result["error"] == "db down"
    assert result["evidence_type"] == "node"


# ---- バグ回帰テスト: target_term の演算子優先順位 ----
# `target_term=node_name or f"..." if edge_key else None` は
# `(node_name or f"...") if edge_key else None` に解釈されるため、
# edge_keyがNone（node_name指定の通常ケース）だとtarget_termが常にNoneに
# なり、ノード名を中心にした抜粋・ハイライトが機能しなかった。


def test_extract_evidence_summary_centers_extract_on_node_name_when_chunk_is_long():
    filler = "x" * 100
    node_name = "requirement"
    chunk_text = f"{filler} the {node_name} must satisfy the design constraints. {filler}"
    storage = _FakeChunkStorage(
        node_chunks={node_name: ["c0"]},
        chunks={"c0": chunk_text},
    )
    extractor = EvidenceExtractor(storage)

    result = extractor.extract_evidence_summary("g1", node_name=node_name, max_chunk_length=40)

    summary_text = result["summaries"][0]["summary_text"]
    assert node_name in summary_text.lower()
    assert f"**{node_name}**" in summary_text


def test_extract_evidence_summary_highlights_node_name_without_explicit_highlight_terms():
    node_name = "constraint"
    chunk_text = f"a short line mentioning the {node_name} directly."
    storage = _FakeChunkStorage(
        node_chunks={node_name: ["c0"]},
        chunks={"c0": chunk_text},
    )
    extractor = EvidenceExtractor(storage)

    result = extractor.extract_evidence_summary("g1", node_name=node_name)

    assert f"**{node_name}**" in result["summaries"][0]["summary_text"]
    assert node_name in result["summaries"][0]["highlighted_terms"]


# ---- _extract_relevant_text ----


def test_extract_relevant_text_returns_full_text_when_within_max_length():
    extractor = EvidenceExtractor(_FakeChunkStorage())

    result = extractor._extract_relevant_text("short text", {"text"}, max_length=200)

    assert result == "short text"


def test_extract_relevant_text_falls_back_to_prefix_when_no_terms_found():
    extractor = EvidenceExtractor(_FakeChunkStorage())
    text = "a" * 300

    result = extractor._extract_relevant_text(text, {"missing"}, max_length=50)

    assert result == "a" * 50 + "..."


def test_extract_relevant_text_adds_ellipsis_on_both_sides_when_centered():
    extractor = EvidenceExtractor(_FakeChunkStorage())
    text = "a" * 100 + "TARGET" + "b" * 100

    result = extractor._extract_relevant_text(text, {"TARGET"}, max_length=40)

    assert result.startswith("...")
    assert result.endswith("...")
    assert "TARGET" in result


# ---- _apply_highlights ----


def test_apply_highlights_wraps_matching_term_case_insensitively():
    extractor = EvidenceExtractor(_FakeChunkStorage())

    result = extractor._apply_highlights("The Requirement is important", {"requirement"})

    # マッチは大文字小文字を無視するが、置換文字列には登録時のterm表記が使われる
    # （元テキストの表記は保持されない）。
    assert result == "The **requirement** is important"


def test_apply_highlights_ignores_falsy_terms():
    extractor = EvidenceExtractor(_FakeChunkStorage())

    result = extractor._apply_highlights("plain text", {"", None})

    assert result == "plain text"


# ---- get_enhanced_source_text ----


def test_get_enhanced_source_text_returns_empty_list_when_no_chunks():
    extractor = EvidenceExtractor(_FakeChunkStorage())

    assert extractor.get_enhanced_source_text("g1", "missing") == []


def test_get_enhanced_source_text_summary_format():
    storage = _FakeChunkStorage(
        node_chunks={"n": ["c0"]},
        chunks={"c0": "n appears here in this sentence."},
    )
    extractor = EvidenceExtractor(storage)

    result = extractor.get_enhanced_source_text("g1", "n", return_format="summary")

    assert result[0]["is_summary"] is True
    assert result[0]["chunk_id"] == "c0"


def test_get_enhanced_source_text_full_format_highlights_node_name():
    storage = _FakeChunkStorage(
        node_chunks={"n": ["c0"]},
        chunks={"c0": "n appears here."},
    )
    extractor = EvidenceExtractor(storage)

    result = extractor.get_enhanced_source_text("g1", "n", return_format="full")

    assert result[0]["is_summary"] is False
    assert "**n**" in result[0]["text"]


def test_get_enhanced_source_text_returns_empty_list_on_exception():
    extractor = EvidenceExtractor(_RaisingChunkStorage())

    assert extractor.get_enhanced_source_text("g1", "n") == []


# ---- get_enhanced_edge_source_text ----


def test_get_enhanced_edge_source_text_returns_empty_list_when_no_chunks():
    extractor = EvidenceExtractor(_FakeChunkStorage())

    assert extractor.get_enhanced_edge_source_text("g1", "A", "B") == []


def test_get_enhanced_edge_source_text_summary_format_highlights_both_endpoints():
    storage = _FakeChunkStorage(
        edge_chunks={("A", "B"): ["c0"]},
        chunks={"c0": "A relies on B in this system."},
    )
    extractor = EvidenceExtractor(storage)

    result = extractor.get_enhanced_edge_source_text("g1", "A", "B", return_format="summary")

    highlighted = set(result[0]["highlighted_terms"])
    assert {"A", "B"}.issubset(highlighted)


def test_get_enhanced_edge_source_text_full_format():
    storage = _FakeChunkStorage(
        edge_chunks={("A", "B"): ["c0"]},
        chunks={"c0": "A relies on B."},
    )
    extractor = EvidenceExtractor(storage)

    result = extractor.get_enhanced_edge_source_text("g1", "A", "B", return_format="full")

    assert "**A**" in result[0]["text"]
    assert "**B**" in result[0]["text"]


def test_get_enhanced_edge_source_text_returns_empty_list_on_exception():
    extractor = EvidenceExtractor(_RaisingChunkStorage())

    assert extractor.get_enhanced_edge_source_text("g1", "A", "B") == []
