"""GraphRAG graphrag の軽量ユニットテスト。"""

from graphrag.classifier import Classifier
from graphrag.datamodels import POS, ConceptCandidate, ConceptFeatures, ConceptType
from graphrag.feature_estimator import FeatureEstimator
from graphrag.language_detector import Language, LanguageDetector


def test_classifier_entity():
    c = Classifier()
    f = ConceptFeatures(name="x", has_identity=True, persistent=True, referable=True, attribute_count=3)
    assert c.classify(f) == ConceptType.ENTITY


def test_classifier_value():
    c = Classifier()
    f = ConceptFeatures(name="x", has_identity=False, persistent=False, referable=False, attribute_count=0)
    assert c.classify(f) == ConceptType.VALUE


def test_feature_estimator():
    est = FeatureEstimator()
    cand = ConceptCandidate(
        lemma="Foo",
        pos=POS.NOUN,
        is_proper=True,
        has_numeric_id=False,
        is_event_like=False,
        is_abstract=True,
    )
    feat = est.estimate(cand)
    assert feat.name == "Foo"
    assert feat.attribute_count == 3


def test_language_detector():
    d = LanguageDetector()
    assert d.detect("") == Language.UNKNOWN
    assert d.detect("日本語") == Language.JAPANESE
    assert d.detect("hello") == Language.ENGLISH
    assert d.detect("hello 日本") == Language.MIXED


def test_classifier_batch():
    c = Classifier()
    feats = [
        ConceptFeatures(name="a", has_identity=True, persistent=True, referable=True, attribute_count=3),
        ConceptFeatures(name="b", has_identity=False, persistent=False, referable=False, attribute_count=0),
    ]
    out = c.classify_batch(feats)
    assert out[0] == ConceptType.ENTITY
    assert out[1] == ConceptType.VALUE
