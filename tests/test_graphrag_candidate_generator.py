"""GraphRAG candidate_generator（解析器をモック）。優先度: GraphRAG。"""

from graphrag.candidate_generator import CandidateGenerator


def test_candidate_generator_with_mocked_analyzer(monkeypatch):
    gen = CandidateGenerator()

    def fake_analyze(text: str):
        return [
            ("東京", "名詞,固有名詞", "東京"),
            ("大学", "名詞,一般", "大学"),
        ]

    monkeypatch.setattr(gen.analyzer, "analyze", fake_analyze)
    out = gen.generate("東京大学")
    surfaces = [t[0] for t in out]
    assert "東京" in surfaces
    assert "大学" in surfaces
    assert any("東京大学" == t[0] for t in out)


def test_candidate_generator_single_token_verb(monkeypatch):
    gen = CandidateGenerator()

    def fake_analyze(_text: str):
        return [("走る", "動詞,自立", "走る")]

    monkeypatch.setattr(gen.analyzer, "analyze", fake_analyze)
    out = gen.generate("x")
    assert out and "動詞" in out[0][1]
