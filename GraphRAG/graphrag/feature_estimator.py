"""
Feature推定モジュール（仕様書 5.4）
言語非依存の処理
"""
from typing import List

from .datamodels import POS, ConceptCandidate, ConceptFeatures


class FeatureEstimator:
    """
    Feature推定器
    
    言語非依存の処理を行う
    """
    
    def estimate(self, candidate: ConceptCandidate) -> ConceptFeatures:
        """
        ConceptCandidateからConceptFeaturesを推定
        
        Feature判定基準（仕様書 5.4）:
        - has_identity: 固有名 or 数値IDを含む
        - persistent: 非イベントかつ非動詞
        - referable: NOUN / VERB / PROPN
        - attribute_count: 抽象概念なら ≥3
        """
        # has_identity: 固有名 or 数値IDを含む
        has_identity = candidate.is_proper or candidate.has_numeric_id
        
        # persistent: 非イベントかつ非動詞
        persistent = not candidate.is_event_like and candidate.pos != POS.VERB
        
        # referable: NOUN / VERB / PROPN
        referable = candidate.pos in [POS.NOUN, POS.VERB, POS.PROPN]
        
        # attribute_count: 抽象概念なら ≥3
        attribute_count = 3 if candidate.is_abstract else 0
        
        return ConceptFeatures(
            name=candidate.lemma,
            has_identity=has_identity,
            persistent=persistent,
            referable=referable,
            attribute_count=attribute_count
        )
    
    def estimate_batch(self, candidates: List[ConceptCandidate]) -> List[ConceptFeatures]:
        """
        複数のConceptCandidateからConceptFeaturesを一括推定
        
        Args:
            candidates: ConceptCandidateのリスト
        
        Returns:
            List[ConceptFeatures]: Featureのリスト
        """
        return [self.estimate(candidate) for candidate in candidates]

