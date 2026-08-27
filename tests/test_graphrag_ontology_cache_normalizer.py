"""GraphRAG: オントロジー検証・キャッシュ・正規化のユニットテスト。"""

import networkx as nx
from graphrag.cache_manager import CacheManager
from graphrag.datamodels import POS, ConceptCandidate, ConceptType
from graphrag.normalizer import Normalizer
from graphrag.ontology_validator import OntologyValidator


def test_ontology_validator_part_of_cycle():
    ov = OntologyValidator()
    g = nx.DiGraph()
    g.add_edge("a", "b", relation="part-of")
    g.add_edge("b", "a", relation="part-of")
    ok, errs = ov.check_structure_constraints(g, fast_mode=False)
    assert ok is False
    assert any("part-of" in e for e in errs)


def test_ontology_validator_is_a_cycle():
    ov = OntologyValidator()
    g = nx.DiGraph()
    g.add_edge("x", "y", relation="is-a")
    g.add_edge("y", "x", relation="is-a")
    ok, errs = ov.check_structure_constraints(g, fast_mode=False)
    assert ok is False
    assert any("is-a" in e for e in errs)


def test_ontology_validator_fast_mode_self_loop():
    ov = OntologyValidator()
    g = nx.DiGraph()
    g.add_edge("n", "n", relation="part-of")
    ok, errs = ov.check_structure_constraints(g, fast_mode=True)
    assert ok is False
    assert any("自己ループ" in e for e in errs)


def test_ontology_validate_entities_and_relations():
    ov = OntologyValidator()
    ent = ConceptCandidate(
        lemma="Car",
        pos=POS.NOUN,
        is_proper=False,
        has_numeric_id=False,
        is_event_like=False,
        is_abstract=False,
    )
    rel = ConceptCandidate(
        lemma="is-a",
        pos=POS.NOUN,
        is_proper=False,
        has_numeric_id=False,
        is_event_like=False,
        is_abstract=False,
    )
    ve = ov.validate_entities([ent], [ConceptType.ENTITY])
    assert len(ve) == 1
    vr = ov.validate_relations([rel], [ConceptType.RELATION])
    assert len(vr) == 1 and vr[0][1] == "is-a"


def test_cache_manager_node_edge_and_query():
    cm = CacheManager(
        enable_query_cache=True,
        query_cache_persistent=False,
        cache_dir=None,
    )
    cm.set_node("a", {"k": 1})
    assert cm.get_node("a") == {"k": 1}
    cm.set_edge("a", "b", {"w": 2})
    assert cm.get_edge("a", "b") == {"w": 2}
    cm.set_query_result("q1", {"r": 3})
    assert cm.get_query_result("q1") == {"r": 3}


def test_normalizer_normalize_public():
    """normalize() が品詞文字列から ConceptCandidate.pos を設定する。"""
    n = Normalizer()
    out = n.normalize(
        [
            ("車", "名詞,一般", "車"),
            ("東京", "名詞,固有名詞", "東京"),
            ("走る", "動詞", "走る"),
        ]
    )
    assert out[0].pos == POS.NOUN
    assert out[1].pos == POS.PROPN
    assert out[2].pos == POS.VERB
