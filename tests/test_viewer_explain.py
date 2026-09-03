"""viewer.backend.explain の単体テスト（Group4 b17, R2）。

実際のOpenAI API呼び出しは行わず、環境変数の有無で分岐する部分と、
「根拠(basis)を入力そのまま返す」という決定的な部分を検証する
（LLM応答の自由記述内容自体はテスト対象外）。
"""

from __future__ import annotations

import os

import pytest

from viewer.backend.explain import explain_element


async def test_explain_element_unavailable_without_api_key(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    result = await explain_element({"id": "$root::A", "type": "part_def", "label": "A"}, [], [])

    assert result["available"] is False
    assert "OPENAI_API_KEY" in result["error"]


async def test_explain_element_reports_unavailable_on_llm_call_failure(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "dummy-key-for-test")

    class _FailingClient:
        def __init__(self, api_key):
            pass

        class chat:
            class completions:
                @staticmethod
                def create(**kwargs):
                    raise RuntimeError("simulated API failure")

    monkeypatch.setattr("openai.OpenAI", _FailingClient)

    result = await explain_element({"id": "$root::A", "type": "part_def", "label": "A"}, [], [])

    assert result["available"] is False
    assert "simulated API failure" in result["error"]


async def test_explain_element_echoes_input_as_basis_on_success(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "dummy-key-for-test")

    class _FakeMessage:
        content = "これは推論です。Aはpart_def型の要素です。"

    class _FakeChoice:
        message = _FakeMessage()

    class _FakeResponse:
        choices = [_FakeChoice()]

    class _FakeClient:
        def __init__(self, api_key):
            pass

        class chat:
            class completions:
                @staticmethod
                def create(**kwargs):
                    return _FakeResponse()

    monkeypatch.setattr("openai.OpenAI", _FakeClient)

    related_edges = [{"kind": "feature_typing", "direction": "outgoing", "other_label": "Engine", "other_type": "part_def"}]
    findings = [{"severity": "warning", "rule": "_check_x", "message": "型が不明です"}]

    result = await explain_element({"id": "$root::A", "type": "part_def", "label": "A"}, related_edges, findings)

    assert result["available"] is True
    assert result["explanation"] == "これは推論です。Aはpart_def型の要素です。"
    # 根拠(basis)はLLMの自由記述ではなく、入力に使った値をそのまま返す(決定的)。
    assert result["basis"] == {"related_edges": related_edges, "findings": findings}
