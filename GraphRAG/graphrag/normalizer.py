"""
ConceptCandidate正規化モジュール（仕様書 5.3）
日本語依存の処理
"""
import re
from typing import List, Tuple

from . import config
from .datamodels import POS, ConceptCandidate


class Normalizer:
    """
    ConceptCandidate正規化器
    
    日本語依存の処理を行う
    """
    
    def __init__(self):
        self.abstract_nouns = config.ABSTRACT_NOUNS
        self.event_suffixes = config.EVENT_SUFFIXES
        self.suru_patterns = config.SURU_VERB_PATTERNS
    
    def _normalize_pos(self, pos: str) -> POS:
        """
        品詞を正規化（仕様書 5.3）
        - 名詞 → NOUN
        - 動詞 → VERB
        - 固有名詞 → PROPN
        - 形容詞 → ADJ
        """
        if "固有名詞" in pos or "名詞,固有名詞" in pos:
            return POS.PROPN
        elif "名詞" in pos:
            return POS.NOUN
        elif "動詞" in pos:
            return POS.VERB
        elif "形容詞" in pos:
            return POS.ADJ
        else:
            return POS.OTHER
    
    def _is_proper(self, pos: str) -> bool:
        """固有名詞かどうかを判定"""
        return "固有名詞" in pos or "名詞,固有名詞" in pos
    
    def _has_numeric_id(self, lemma: str) -> bool:
        """数値IDを含むかどうかを判定"""
        return bool(re.search(r'\d+', lemma))
    
    def _is_event_like(self, pos: str, lemma: str) -> bool:
        """
        イベント的かどうかを判定（仕様書 5.3）
        - 動詞
        - 「〜した」「〜中」「〜完了」「〜開始」
        - サ変名詞 + する
        """
        # 動詞の場合
        if "動詞" in pos:
            return True
        
        # イベント的接尾辞を含む場合
        for suffix in self.event_suffixes:
            if lemma.endswith(suffix):
                return True
        
        # サ変名詞 + する
        if "名詞,サ変接続" in pos:
            return True
        
        for pattern in self.suru_patterns:
            if lemma.endswith(pattern):
                return True
        
        return False
    
    def _is_abstract(self, lemma: str, pos: str) -> bool:
        """
        抽象的かどうかを判定（仕様書 5.3）
        - 抽象名詞辞書に含まれる
        - 上位語を必要とする名詞（例：「種類」「方式」「概念」）
        """
        if lemma in self.abstract_nouns:
            return True
        
        # 上位語を必要とする名詞パターン
        abstract_patterns = ["種類", "方式", "概念", "方法", "手段", "目的"]
        for pattern in abstract_patterns:
            if pattern in lemma:
                return True
        
        return False
    
    def normalize(self, candidates: List[Tuple[str, str, str]]) -> List[ConceptCandidate]:
        """
        概念候補を正規化してConceptCandidateに変換
        
        Args:
            candidates: List[Tuple[surface, pos, lemma]]
        
        Returns:
            List[ConceptCandidate]: 正規化された候補リスト
        """
        normalized = []
        
        for surface, pos_str, lemma in candidates:
            # lemmaの正規化（原形を使用、活用・助詞を除去）
            normalized_lemma = lemma.strip()
            
            # 品詞の正規化
            pos = self._normalize_pos(pos_str)
            
            # 各種フラグの設定
            is_proper = self._is_proper(pos_str)
            has_numeric_id = self._has_numeric_id(normalized_lemma)
            is_event_like = self._is_event_like(pos_str, normalized_lemma)
            is_abstract = self._is_abstract(normalized_lemma, pos_str)
            
            candidate = ConceptCandidate(
                lemma=normalized_lemma,
                pos=pos,
                is_proper=is_proper,
                has_numeric_id=has_numeric_id,
                is_event_like=is_event_like,
                is_abstract=is_abstract
            )
            
            normalized.append(candidate)
        
        return normalized

