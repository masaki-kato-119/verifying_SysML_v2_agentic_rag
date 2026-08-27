"""graphrag.candidate_generator_en の英語概念候補生成のテスト。優先度: GraphRAG。

CandidateGeneratorEN.generate自体は名詞/動詞判定と連続名詞の複合語結合という
純粋なロジックだが、実体はMorphologicalAnalyzerEN（NLTK依存、実データ・環境
依存で不安定）に委ねている。generate()自身のロジックを安定して検証するため、
analyzerをフェイクの(surface, pos, lemma)タプル列に差し替えてテストする。
"""

import pytest
from graphrag.candidate_generator_en import CandidateGeneratorEN


class _FakeAnalyzer:
    def __init__(self, tokens):
        self._tokens = tokens

    def analyze(self, text):
        return self._tokens


def _generator(tokens):
    gen = CandidateGeneratorEN()
    gen.analyzer = _FakeAnalyzer(tokens)
    return gen


# ---- POS判定ヘルパー ----


@pytest.mark.parametrize(
    "pos,expected",
    [("NN", True), ("NNS", True), ("NNP", True), ("NNPS", True), ("VB", False), ("JJ", False)],
)
def test_is_noun(pos, expected):
    gen = CandidateGeneratorEN.__new__(CandidateGeneratorEN)
    assert gen._is_noun(pos) is expected


@pytest.mark.parametrize(
    "pos,expected",
    [("VB", True), ("VBZ", True), ("VBG", True), ("NN", False), ("JJ", False)],
)
def test_is_verb(pos, expected):
    gen = CandidateGeneratorEN.__new__(CandidateGeneratorEN)
    assert gen._is_verb(pos) is expected


@pytest.mark.parametrize(
    "pos,expected",
    [("NNP", True), ("NNPS", True), ("NN", False), ("NNS", False), ("VB", False)],
)
def test_is_proper_noun(pos, expected):
    gen = CandidateGeneratorEN.__new__(CandidateGeneratorEN)
    assert gen._is_proper_noun(pos) is expected


# ---- generate: 単一トークン候補 ----


def test_generate_includes_single_noun_and_verb_tokens():
    gen = _generator([("port", "NN", "port"), ("uses", "VBZ", "use"), ("the", "DT", "the")])

    result = gen.generate("port uses the")

    assert ("port", "NN", "port") in result
    assert ("uses", "VBZ", "use") in result
    assert not any(surface == "the" for surface, _, _ in result)


def test_generate_returns_empty_list_for_no_tokens():
    gen = _generator([])

    assert gen.generate("") == []


def test_generate_excludes_adjectives_and_determiners():
    gen = _generator([("quick", "JJ", "quick"), ("a", "DT", "a")])

    assert gen.generate("quick a") == []


# ---- generate: 複合名詞の検出 ----


def test_generate_merges_consecutive_nouns_into_a_compound_candidate():
    tokens = [("action", "NN", "action"), ("definition", "NN", "definition")]
    gen = _generator(tokens)

    result = gen.generate("action definition")

    # 個々の名詞と、結合された複合名詞の両方が候補に含まれる
    assert ("action", "NN", "action") in result
    assert ("definition", "NN", "definition") in result
    assert ("action definition", "NN", "action definition") in result


def test_generate_does_not_create_compound_for_single_noun():
    tokens = [("port", "NN", "port")]
    gen = _generator(tokens)

    result = gen.generate("port")

    assert result == [("port", "NN", "port")]


def test_generate_compound_uses_pos_of_first_noun_in_the_run():
    tokens = [("Action", "NNP", "Action"), ("usage", "NN", "usage")]
    gen = _generator(tokens)

    result = gen.generate("Action usage")

    compound = next(c for c in result if c[0] == "Action usage")
    assert compound[1] == "NNP"
    assert compound[2] == "Action usage"


def test_generate_merges_three_consecutive_nouns_into_one_compound():
    tokens = [("action", "NN", "action"), ("definition", "NN", "definition"), ("item", "NN", "item")]
    gen = _generator(tokens)

    result = gen.generate("action definition item")

    assert ("action definition item", "NN", "action definition item") in result
    # 部分的な2語結合は作られない
    assert not any(c[0] == "action definition" for c in result)


def test_generate_breaks_compound_run_on_non_noun_token():
    tokens = [
        ("action", "NN", "action"),
        ("uses", "VBZ", "use"),
        ("port", "NN", "port"),
    ]
    gen = _generator(tokens)

    result = gen.generate("action uses port")

    surfaces = [c[0] for c in result]
    assert "action" in surfaces
    assert "port" in surfaces
    assert "uses" in surfaces
    # 名詞が連続していないため複合語は生成されない
    assert "action port" not in surfaces
