"""graphrag.morphological_analyzer の日本語形態素解析ラッパーのテスト。優先度: GraphRAG。

SudachiPyの実辞書を使った統合的な動作確認がこれまで一度も無かった。
analyze()が(surface, pos, lemma)のタプル列を返すこと、posが読点区切りの
文字列に整形されること、config.SUDACHI_MODEに応じて分割モードが切り替わる
ことを検証する。
"""

import pytest
from graphrag.morphological_analyzer import MorphologicalAnalyzer

from graphrag import config


@pytest.fixture(scope="module")
def analyzer():
    return MorphologicalAnalyzer()


def test_analyze_returns_list_of_three_tuples(analyzer):
    result = analyzer.analyze("犬が走る。")

    assert all(isinstance(item, tuple) and len(item) == 3 for item in result)


def test_analyze_extracts_expected_surfaces_in_order(analyzer):
    result = analyzer.analyze("犬が走る。")

    surfaces = [surface for surface, _, _ in result]
    assert surfaces == ["犬", "が", "走る", "。"]


def test_analyze_pos_string_is_comma_joined_and_contains_noun_or_verb_tag(analyzer):
    result = analyzer.analyze("犬が走る。")

    noun_entry = next(item for item in result if item[0] == "犬")
    verb_entry = next(item for item in result if item[0] == "走る")

    assert "," in noun_entry[1]
    assert noun_entry[1].startswith("名詞")
    assert verb_entry[1].startswith("動詞")


def test_analyze_lemma_is_dictionary_form(analyzer):
    result = analyzer.analyze("犬が走る。")

    verb_entry = next(item for item in result if item[0] == "走る")
    assert verb_entry[2] == "走る"


def test_analyze_empty_string_returns_empty_list(analyzer):
    assert analyzer.analyze("") == []


def test_analyzer_uses_split_mode_from_config(analyzer):
    assert analyzer.mode == config.SUDACHI_MODE


def test_analyze_handles_conjugated_verb_form_via_dictionary_form():
    """辞書形と表層形が異なる活用形でも、lemmaは基本形に正規化される。"""
    analyzer = MorphologicalAnalyzer()

    result = analyzer.analyze("走った")

    verb_entry = next(item for item in result if "走" in item[0])
    assert verb_entry[2] == "走る"
