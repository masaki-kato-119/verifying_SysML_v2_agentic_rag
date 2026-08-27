"""
形態素解析モジュール（仕様書 5.1）
SudachiPyを使用
"""
from typing import List, Tuple

from sudachipy import dictionary, tokenizer

from . import config


class MorphologicalAnalyzer:
    """
    形態素解析器
    
    目的は「候補の漏れ防止」のみ
    出力は正解として扱ってはならない
    """
    
    def __init__(self):
        """Sudachi辞書を初期化"""
        self.tokenizer_obj = dictionary.Dictionary().create()
        self.mode = config.SUDACHI_MODE
    
    def analyze(self, text: str) -> List[Tuple[str, str, str]]:
        """
        テキストを形態素解析
        
        Args:
            text: 入力テキスト（日本語）
        
        Returns:
            List[Tuple[surface, pos, lemma]]: 
                surface: 表層形
                pos: 品詞情報
                lemma: 原形
        """
        mode = getattr(tokenizer.Tokenizer.SplitMode, self.mode)
        tokens = self.tokenizer_obj.tokenize(text, mode)
        
        results = []
        for token in tokens:
            surface = token.surface()
            pos = token.part_of_speech()
            lemma = token.dictionary_form()
            
            # 品詞情報を文字列として取得
            pos_str = ",".join(pos)
            
            results.append((surface, pos_str, lemma))
        
        return results

