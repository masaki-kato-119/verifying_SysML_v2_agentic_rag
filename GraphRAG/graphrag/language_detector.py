"""
言語検出モジュール
日本語と英語を検出
"""
import re
from enum import Enum


class Language(Enum):
    """言語タイプ"""
    JAPANESE = "ja"
    ENGLISH = "en"
    MIXED = "mixed"
    UNKNOWN = "unknown"


class LanguageDetector:
    """言語検出器"""
    
    # 日本語の文字範囲
    JAPANESE_PATTERN = re.compile(r'[\u3040-\u309F\u30A0-\u30FF\u4E00-\u9FAF]')
    
    # 英語の文字範囲（基本的なラテン文字）
    ENGLISH_PATTERN = re.compile(r'[a-zA-Z]')
    
    def detect(self, text: str) -> Language:
        """
        テキストの言語を検出
        
        Args:
            text: 検出するテキスト
        
        Returns:
            Language: 検出された言語
        """
        if not text or not text.strip():
            return Language.UNKNOWN
        
        has_japanese = bool(self.JAPANESE_PATTERN.search(text))
        has_english = bool(self.ENGLISH_PATTERN.search(text))
        
        if has_japanese and has_english:
            return Language.MIXED
        elif has_japanese:
            return Language.JAPANESE
        elif has_english:
            return Language.ENGLISH
        else:
            return Language.UNKNOWN
    
    def is_japanese(self, text: str) -> bool:
        """日本語かどうかを判定"""
        return self.detect(text) in [Language.JAPANESE, Language.MIXED]
    
    def is_english(self, text: str) -> bool:
        """英語かどうかを判定"""
        return self.detect(text) in [Language.ENGLISH, Language.MIXED]

