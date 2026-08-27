"""
概念分類モジュール（仕様書 5.5）
"""
from typing import List

from .datamodels import ConceptFeatures, ConceptType


class Classifier:
    """
    概念分類器
    
    仕様書 5.5のルールに基づいて分類
    """
    
    def classify(self, features: ConceptFeatures) -> ConceptType:
        """
        概念を分類（仕様書 5.5）
        
        score = has_identity + persistent + referable + (attribute_count>=3)
        
        if score >= 3:
          ENTITY
        elif persistent and referable:
          RELATION
        elif not persistent and referable:
          EVENT
        else:
          VALUE
        """
        # score計算
        score = (
            (1 if features.has_identity else 0) +
            (1 if features.persistent else 0) +
            (1 if features.referable else 0) +
            (1 if features.attribute_count >= 3 else 0)
        )
        
        # 分類ルール
        if score >= 3:
            return ConceptType.ENTITY
        elif features.persistent and features.referable:
            return ConceptType.RELATION
        elif not features.persistent and features.referable:
            return ConceptType.EVENT
        else:
            return ConceptType.VALUE
    
    def classify_batch(self, features_list: List[ConceptFeatures]) -> List[ConceptType]:
        """
        複数のConceptFeaturesを一括分類
        
        Args:
            features_list: ConceptFeaturesのリスト
        
        Returns:
            List[ConceptType]: 分類結果のリスト
        """
        return [self.classify(features) for features in features_list]

