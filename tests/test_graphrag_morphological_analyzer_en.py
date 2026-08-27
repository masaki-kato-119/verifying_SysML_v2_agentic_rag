"""graphrag.morphological_analyzer_en の英語形態素解析ラッパーのテスト。優先度: GraphRAG。

NLTK依存の初期化ガード（NLTK_AVAILABLE=Falseでのフェイルファスト、リソース
未取得時のダウンロードフォールバック）と、Penn Treebank→WordNetタグ変換・
lemmatize処理という純粋関数部分をあわせて検証する。analyze()自体は必要な
コーパスがローカルに揃っている前提の統合テストとして実行する。
"""

import pytest
from graphrag.morphological_analyzer_en import MorphologicalAnalyzerEN

from graphrag import morphological_analyzer_en as mod


@pytest.fixture(scope="module")
def analyzer():
    return MorphologicalAnalyzerEN()


# ---- __init__: NLTK可用性ガード ----


def test_init_raises_import_error_when_nltk_unavailable(monkeypatch):
    monkeypatch.setattr(mod, "NLTK_AVAILABLE", False)

    with pytest.raises(ImportError, match="NLTK"):
        MorphologicalAnalyzerEN()


def test_init_succeeds_when_nltk_available(analyzer):
    assert analyzer.lemmatizer is not None


def test_init_falls_back_gracefully_when_punkt_tab_download_fails(monkeypatch):
    """punkt_tabの取得に失敗しても例外を伝播させず、初期化を続ける。"""

    def _find(resource):
        if resource == "tokenizers/punkt_tab":
            raise LookupError("missing")
        return None

    def _download(name, quiet=True):
        if name == "punkt_tab":
            raise Exception("network unavailable")
        return True

    monkeypatch.setattr(mod.nltk.data, "find", _find)
    monkeypatch.setattr(mod.nltk, "download", _download)

    MorphologicalAnalyzerEN()  # should not raise


# ---- _penn_to_wordnet ----


@pytest.mark.parametrize(
    "penn_tag,expected",
    [
        ("NN", "n"),
        ("NNS", "n"),
        ("NNP", "n"),
        ("VB", "v"),
        ("VBZ", "v"),
        ("JJ", "a"),
        ("JJR", "a"),
        ("RB", "r"),
        ("RBS", "r"),
        ("DT", None),
        ("IN", None),
        (".", None),
    ],
)
def test_penn_to_wordnet_mapping(analyzer, penn_tag, expected):
    assert analyzer._penn_to_wordnet(penn_tag) == expected


# ---- _lemmatize ----


def test_lemmatize_uses_wordnet_pos_when_mappable(analyzer):
    assert analyzer._lemmatize("running", "VBG") == "run"


def test_lemmatize_falls_back_to_default_pos_when_not_mappable(analyzer):
    # "DT"はWordNet品詞に対応しないため、デフォルト（名詞扱い）でlemmatizeされる
    result = analyzer._lemmatize("This", "DT")
    assert result == "this"


def test_lemmatize_lowercases_input(analyzer):
    assert analyzer._lemmatize("PORTS", "NNS") == "port"


# ---- analyze (統合) ----


def test_analyze_returns_three_tuples(analyzer):
    result = analyzer.analyze("The engineers are running tests.")

    assert all(isinstance(item, tuple) and len(item) == 3 for item in result)


def test_analyze_tags_and_lemmatizes_known_sentence(analyzer):
    result = analyzer.analyze("Ports must be defined.")

    words = {word: (pos, lemma) for word, pos, lemma in result}
    assert words["Ports"][0] == "NNS"
    assert words["Ports"][1] == "port"
    assert words["defined"][0] == "VBN"
    assert words["defined"][1] == "define"


def test_analyze_splits_multiple_sentences(analyzer):
    result = analyzer.analyze("Ports must be defined. Actions use ports.")

    words = [w for w, _, _ in result]
    assert words.count(".") == 2


def test_analyze_empty_string_returns_empty_list(analyzer):
    assert analyzer.analyze("") == []
