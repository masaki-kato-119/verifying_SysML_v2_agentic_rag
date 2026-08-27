"""
概念候補生成モジュール（仕様書 5.2）
"""
from typing import List, Tuple

from .morphological_analyzer import MorphologicalAnalyzer


class CandidateGenerator:
    """
    概念候補生成器
    
    以下の候補を生成：
    - 名詞
    - 動詞
    - サ変名詞
    - 複合名詞（連続名詞）
    """
    
    def __init__(self):
        self.analyzer = MorphologicalAnalyzer()
    
    def _is_noun(self, pos: str) -> bool:
        """名詞かどうかを判定"""
        return "名詞" in pos
    
    def _is_verb(self, pos: str) -> bool:
        """動詞かどうかを判定"""
        return "動詞" in pos
    
    def _is_proper_noun(self, pos: str) -> bool:
        """固有名詞かどうかを判定"""
        return "固有名詞" in pos or "名詞,固有名詞" in pos
    
    def _is_suru_verb(self, pos: str, lemma: str) -> bool:
        """サ変名詞かどうかを判定"""
        return "名詞,サ変接続" in pos or (self._is_noun(pos) and lemma.endswith("する"))
    
    def generate(self, text: str) -> List[Tuple[str, str, str]]:
        """
        概念候補を生成
        
        Args:
            text: 入力テキスト
        
        Returns:
            List[Tuple[surface, pos, lemma]]: 候補リスト
        """
        analyzed = self.analyzer.analyze(text)
        candidates = []
        
        # 単一トークンの候補
        for surface, pos, lemma in analyzed:
            if self._is_noun(pos) or self._is_verb(pos):
                candidates.append((surface, pos, lemma))
        
        # 複合名詞（連続名詞）の検出
        i = 0
        while i < len(analyzed):
            if self._is_noun(analyzed[i][1]):
                # 連続する名詞を結合
                compound = [analyzed[i][0]]
                j = i + 1
                while j < len(analyzed) and self._is_noun(analyzed[j][1]):
                    compound.append(analyzed[j][0])
                    j += 1
                
                if len(compound) > 1:
                    # 複合名詞として追加
                    compound_surface = "".join(compound)
                    compound_lemma = "".join([analyzed[k][2] for k in range(i, j)])
                    compound_pos = analyzed[i][1]  # 最初の名詞の品詞を使用
                    candidates.append((compound_surface, compound_pos, compound_lemma))
                
                i = j
            else:
                i += 1
        
        return candidates

