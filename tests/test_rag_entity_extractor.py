"""rag.entity_extractor のエンティティ抽出ロジック。優先度: HybridRAG/rag(t5_add_tests_hybridrag_gaps)。

extract_entities_with_parser は正規表現ベースの純粋関数でネットワーク呼び出しが
無いため重点的にテストする。extract_entities_with_llm はOpenAIクライアントを
モックして、レスポンス整形・上限件数・エラー処理を検証する。
"""

import json
from unittest.mock import MagicMock

import pytest
from rag import entity_extractor

# ---- extract_entities_with_parser ----


def test_parser_extracts_constraint_from_must_shall_wording():
    chunks = [{"chunk_id": "doc::chunk-0", "text": "Ports must be defined before use in the model."}]

    result = entity_extractor.extract_entities_with_parser(chunks)

    assert len(result["constraints"]) == 1
    assert result["constraints"][0]["id"] == "C-001"
    assert result["constraints"][0]["related_chunks"] == ["doc::chunk-0"]


def test_parser_filters_out_short_constraint_matches():
    # "required" にマッチしても20文字未満は除外される
    chunks = [{"chunk_id": "doc::chunk-0", "text": "x required."}]

    result = entity_extractor.extract_entities_with_parser(chunks)

    assert result["constraints"] == []


def test_parser_extracts_spec_clause_with_number_and_title():
    chunks = [{"chunk_id": "doc::chunk-1", "text": "7.3.1 Port Definition\nSome body text."}]

    result = entity_extractor.extract_entities_with_parser(chunks)

    clause_ids = [c["id"] for c in result["spec_clauses"]]
    assert "clause-7-3-1" in clause_ids
    match = next(c for c in result["spec_clauses"] if c["id"] == "clause-7-3-1")
    assert match["clause_number"] == "7.3.1"
    assert match["related_chunks"] == ["doc::chunk-1"]


def test_parser_extracts_term_definition_pair():
    chunks = [{"chunk_id": "doc::chunk-2", "text": "port: A connection point that allows interaction."}]

    result = entity_extractor.extract_entities_with_parser(chunks)

    terms = {t["term"]: t for t in result["terms"]}
    assert "port" in terms
    assert terms["port"]["id"] == "term-port"


def test_parser_filters_out_short_term_definitions():
    chunks = [{"chunk_id": "doc::chunk-3", "text": "x: short."}]

    result = entity_extractor.extract_entities_with_parser(chunks)

    assert result["terms"] == []


def test_parser_handles_empty_chunks_list():
    result = entity_extractor.extract_entities_with_parser([])

    assert result == {"constraints": [], "syntax_rules": [], "spec_clauses": [], "terms": []}


def test_parser_aggregates_across_multiple_chunks_with_distinct_ids():
    chunks = [
        {"chunk_id": "doc::chunk-0", "text": "Ports must be defined before use in the model."},
        {"chunk_id": "doc::chunk-1", "text": "State machines must have at least one initial state."},
    ]

    result = entity_extractor.extract_entities_with_parser(chunks)

    ids = [c["id"] for c in result["constraints"]]
    assert ids == ["C-001", "C-002"]


# ---- extract_entities_with_llm ----


def _llm_response(content: str):
    response = MagicMock()
    response.choices = [MagicMock(message=MagicMock(content=content))]
    return response


@pytest.fixture(autouse=True)
def _dummy_api_key(monkeypatch):
    monkeypatch.setattr(entity_extractor, "require_openai_api_key", lambda: "dummy-key")


def test_llm_extraction_parses_json_code_block(monkeypatch):
    payload = {
        "constraints": [{"id": "C-001", "name": "n", "description": "d", "related_chunks": []}],
        "syntax_rules": [],
        "spec_clauses": [],
        "terms": [],
    }
    client = MagicMock()
    client.chat.completions.create.return_value = _llm_response(
        f"```json\n{json.dumps(payload)}\n```"
    )
    monkeypatch.setattr(entity_extractor, "OpenAI", lambda **kwargs: client)

    result = entity_extractor.extract_entities_with_llm([{"chunk_id": "c0", "text": "text"}])

    assert result["constraints"] == payload["constraints"]


def test_llm_extraction_parses_bare_json_without_code_block(monkeypatch):
    payload = {"constraints": [], "syntax_rules": [], "spec_clauses": [], "terms": [{"id": "term-x", "term": "x", "definition": "y", "related_chunks": []}]}
    client = MagicMock()
    client.chat.completions.create.return_value = _llm_response(json.dumps(payload))
    monkeypatch.setattr(entity_extractor, "OpenAI", lambda **kwargs: client)

    result = entity_extractor.extract_entities_with_llm([{"chunk_id": "c0", "text": "text"}])

    assert result["terms"] == payload["terms"]


def test_llm_extraction_respects_max_limits(monkeypatch):
    payload = {
        "constraints": [{"id": f"C-{i}"} for i in range(5)],
        "syntax_rules": [],
        "spec_clauses": [],
        "terms": [],
    }
    client = MagicMock()
    client.chat.completions.create.return_value = _llm_response(json.dumps(payload))
    monkeypatch.setattr(entity_extractor, "OpenAI", lambda **kwargs: client)

    result = entity_extractor.extract_entities_with_llm(
        [{"chunk_id": "c0", "text": "text"}], max_constraints=2
    )

    assert len(result["constraints"]) == 2


def test_llm_extraction_returns_empty_result_on_invalid_json(monkeypatch):
    client = MagicMock()
    client.chat.completions.create.return_value = _llm_response("not valid json at all")
    monkeypatch.setattr(entity_extractor, "OpenAI", lambda **kwargs: client)

    result = entity_extractor.extract_entities_with_llm([{"chunk_id": "c0", "text": "text"}])

    assert result == {"constraints": [], "syntax_rules": [], "spec_clauses": [], "terms": []}


def test_llm_extraction_reraises_unexpected_client_errors(monkeypatch):
    client = MagicMock()
    client.chat.completions.create.side_effect = RuntimeError("api down")
    monkeypatch.setattr(entity_extractor, "OpenAI", lambda **kwargs: client)

    with pytest.raises(RuntimeError, match="api down"):
        entity_extractor.extract_entities_with_llm([{"chunk_id": "c0", "text": "text"}])


def test_llm_extraction_raises_when_openai_sdk_unavailable(monkeypatch):
    monkeypatch.setattr(entity_extractor, "OPENAI_AVAILABLE", False)

    with pytest.raises(RuntimeError, match="OpenAI SDK"):
        entity_extractor.extract_entities_with_llm([{"chunk_id": "c0", "text": "text"}])
