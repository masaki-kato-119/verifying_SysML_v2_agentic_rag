"""関係語彙の照合が単語境界を守ることのテスト。優先度: GraphRAG。

部分文字列一致だと "this" の "is" に反応し、無関係な語のペアから
is-a エッジが大量に生まれる（実グラフでは is-a が全エッジの 88%を占め、
"omg -> profit" のような無意味なエッジが混入していた）。
"""

import pytest
from graphrag.graph_builder import GraphBuilder


@pytest.fixture
def builder():
    return GraphBuilder()


@pytest.mark.parametrize(
    "sentence",
    [
        "this element",  # this の is
        "the analysis result",  # analysis の is
        "satisfies the requirement",  # satisfies の is ではないことの確認用
    ],
)
def test_is_does_not_match_inside_other_words(builder, sentence):
    assert builder.find_relation_vocab(sentence, "is") == -1


def test_is_matches_as_a_standalone_word(builder):
    sentence = "a part is a component"

    assert builder.find_relation_vocab(sentence, "is") == sentence.index("is a")


def test_use_does_not_match_inside_uses(builder):
    assert builder.find_relation_vocab("the model uses a port", "use") == -1


def test_uses_matches_itself(builder):
    sentence = "the model uses a port"

    assert builder.find_relation_vocab(sentence, "uses") == sentence.index("uses")


def test_multiword_vocab_is_matched(builder):
    sentence = "the port is part of the block"

    assert builder.find_relation_vocab(sentence, "part of") == sentence.index("part of")


def test_japanese_vocab_still_uses_substring_match(builder):
    """日本語には語境界がないため従来どおり部分文字列で照合する。"""
    sentence = "ポートはブロックの一部である"

    assert builder.find_relation_vocab(sentence, "の一部") == sentence.index("の一部")
    assert builder.find_relation_vocab(sentence, "である") == sentence.index("である")


def test_matching_is_case_insensitive_for_english(builder):
    """文頭の Is / Are を取りこぼさない。"""
    assert builder.find_relation_vocab("Is a port a kind of feature", "is a") == 0
    assert builder.find_relation_vocab("Are these part of the block", "are") == 0


def test_case_insensitive_matching_still_respects_word_boundaries(builder):
    assert builder.find_relation_vocab("Analysis of the model", "is") == -1


def test_reverse_direction_vocab_is_not_registered():
    """向きが逆になる語彙を登録すると誤ったエッジが生まれるため、入れない。"""
    from graphrag import config

    for vocab in ("consists of", "contains", "includes", "is composed of"):
        assert vocab not in config.RELATION_VOCABULARY


def test_all_vocab_map_to_allowed_relations():
    from graphrag import config

    unknown = {
        rel for rel in config.RELATION_VOCABULARY.values() if rel not in config.ALLOWED_RELATIONS
    }
    assert unknown == set()


def test_missing_vocab_returns_minus_one(builder):
    assert builder.find_relation_vocab("no relation words here", "satisfies") == -1


def test_patterns_are_cached_across_calls(builder):
    builder.find_relation_vocab("a is b", "is")
    builder.find_relation_vocab("c is d", "is")

    assert "is" in builder._vocab_patterns


def test_nodes_carry_concept_type(builder):
    """分類結果をノードに残さないと node_type_filter が常に 0 件になる。"""
    from graphrag.datamodels import POS, ConceptCandidate, ConceptFeatures, ConceptType

    candidate = ConceptCandidate(
        lemma="port", pos=POS.PROPN,
        is_proper=True, has_numeric_id=False, is_event_like=False, is_abstract=False,
    )
    features = ConceptFeatures(
        name="port", has_identity=True, persistent=True, referable=True, attribute_count=0
    )
    graph = builder.build([candidate], [features], [ConceptType.ENTITY], text="")

    assert graph.nodes["port"]["concept_type"] == ConceptType.ENTITY.value
    # 下流は 'type' を参照している箇所があるため、後方互換キーも持たせる
    assert graph.nodes["port"]["type"] == ConceptType.ENTITY.value


def _candidate(lemma, proper=True):
    from graphrag.datamodels import POS, ConceptCandidate

    return ConceptCandidate(
        lemma=lemma, pos=POS.PROPN if proper else POS.NOUN,
        is_proper=proper, has_numeric_id=False, is_event_like=False, is_abstract=False,
    )


def _features(name):
    from graphrag.datamodels import ConceptFeatures

    return ConceptFeatures(
        name=name, has_identity=True, persistent=True, referable=True, attribute_count=0
    )


def test_domain_term_set_normalizes_spacing():
    """辞書は "action definition"、lemma は "actiondefinition" に寄るため両方必要。"""
    from graphrag import config

    terms = config.domain_term_set()

    assert "action definition" in terms
    assert "actiondefinition" in terms


def test_domain_term_set_excludes_generic_words():
    from graphrag import config

    terms = config.domain_term_set()

    for noise in ("omg", "usa", "profit", "willert"):
        assert noise not in terms


def test_gate_keeps_domain_terms_and_drops_noise(builder, monkeypatch):
    """ノード母集団を SysML 用語へ接地させる（C-lite）。"""
    from graphrag.datamodels import ConceptType

    from graphrag import config

    monkeypatch.setattr(config, "DOMAIN_TERM_GATE", True)
    lemmas = ["port", "omg", "actiondefinition", "usa"]
    graph = builder.build(
        [_candidate(x) for x in lemmas],
        [_features(x) for x in lemmas],
        [ConceptType.ENTITY] * len(lemmas),
        text="",
    )

    assert set(graph.nodes()) == {"port", "actiondefinition"}


def test_gate_can_be_disabled_for_comparison(monkeypatch):
    """従来挙動との比較計測ができるよう、無効化できること。"""
    from graphrag.datamodels import ConceptType
    from graphrag.graph_builder import GraphBuilder

    from graphrag import config

    monkeypatch.setattr(config, "DOMAIN_TERM_GATE", False)
    lemmas = ["port", "omg"]
    graph = GraphBuilder().build(
        [_candidate(x) for x in lemmas],
        [_features(x) for x in lemmas],
        [ConceptType.ENTITY] * len(lemmas),
        text="",
    )

    assert set(graph.nodes()) == {"port", "omg"}


def test_entity_matching_ignores_substrings(builder):
    """"portion"→port, "sometimes"→time のような誤検出が無関係なエッジを生んでいた。"""
    lemmas = {"port", "time", "package", "model"}

    got = builder._extract_entities_from_sentence(
        "exposes a portion of a model, which is sometimes used", lemmas, [], []
    )

    assert [e["lemma"] for e in got] == ["model"]


def test_entity_matching_allows_plurals(builder):
    """ノード名は lemma（単数形）なので、複数形を許容しないと再現率が落ちる。"""
    lemmas = {"port", "package"}

    got = builder._extract_entities_from_sentence("the ports and packages", lemmas, [], [])

    assert {e["lemma"] for e in got} == {"port", "package"}


def test_longer_term_wins_over_contained_term(builder):
    """短い順に先着で採ると "action definition" が "action" に潰される。"""
    lemmas = {"action", "action definition"}

    got = builder._extract_entities_from_sentence("An action definition is used", lemmas, [], [])

    assert [e["lemma"] for e in got] == ["action definition"]


def test_entities_are_returned_in_positional_order(builder):
    """関係語彙の前後判定に使うため、位置順である必要がある。"""
    lemmas = {"port", "action"}

    got = builder._extract_entities_from_sentence("an action uses a port", lemmas, [], [])

    assert [e["lemma"] for e in got] == ["action", "port"]


def test_relation_vocab_cache_is_not_shared_with_entity_cache(builder):
    """関係語彙は複数形を許容しない。キャッシュを共有すると取り違える。"""
    builder._extract_entities_from_sentence("the uses of a port", {"use"}, [], [])

    assert builder.find_relation_vocab("the uses of a port", "use") == -1


def test_bare_copula_is_not_registered():
    """bare "is"/"are" を入れると受動態・前置詞句を is-a と誤認する。

    実コーパスでは名詞述語が一致した文 236 に対し、bare のみ一致が 1,874。
    直後は to / by / as / used / bound / declared が大半で is-a ではない。
    """
    from graphrag import config

    assert "is" not in config.RELATION_VOCABULARY
    assert "are" not in config.RELATION_VOCABULARY
    # 名詞述語の形は残す
    assert config.RELATION_VOCABULARY["is a"] == "is-a"
    assert config.RELATION_VOCABULARY["is an"] == "is-a"


def test_multiword_vocab_matches_across_missing_space(builder):
    """PDF 抽出で単語間の空白が落ちる（"Adependencyis a kind of"）。

    左境界を課すと "is a kind of" の 84%、"is a" の 81% を取りこぼしていた。
    """
    assert builder.find_relation_vocab("Adependencyis a kind of relationship", "is a kind of") == 11
    assert builder.find_relation_vocab("Apackageis a namespace", "is a") == 8


def test_single_word_vocab_keeps_left_boundary(builder):
    """単語 1 つで左を緩めると "because"→use, "redefines"→defines を誤検出する。"""
    assert builder.find_relation_vocab("because of this", "use") == -1
    assert builder.find_relation_vocab("it redefines the feature", "defines") == -1


def test_right_boundary_is_kept_for_multiword(builder):
    """右境界まで緩めると "is a" が "is about" にマッチしてしまう。"""
    assert builder.find_relation_vocab("this is about ports", "is a") == -1
