"""GraphRAG graphrag.datamodels の単体テスト。"""

from graphrag.datamodels import POS, ConceptCandidate, ConceptFeatures, ConceptType


def test_concept_candidate_eq_hash():
    a = ConceptCandidate(
        lemma="foo",
        pos=POS.NOUN,
        is_proper=False,
        has_numeric_id=False,
        is_event_like=False,
        is_abstract=False,
    )
    b = ConceptCandidate(
        lemma="foo",
        pos=POS.NOUN,
        is_proper=False,
        has_numeric_id=False,
        is_event_like=False,
        is_abstract=False,
    )
    c = ConceptCandidate(
        lemma="bar",
        pos=POS.NOUN,
        is_proper=False,
        has_numeric_id=False,
        is_event_like=False,
        is_abstract=False,
    )
    assert a == b
    assert a != c
    assert hash(a) == hash(b)


def test_concept_features_dataclass():
    f = ConceptFeatures(
        name="n",
        has_identity=True,
        persistent=True,
        referable=True,
        attribute_count=0,
    )
    assert f.name == "n"


def test_enums():
    assert ConceptType.ENTITY.value == "ENTITY"
    assert POS.VERB.value == "VERB"
