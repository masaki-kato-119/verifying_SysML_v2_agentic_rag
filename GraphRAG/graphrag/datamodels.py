"""
データモデル定義
仕様書 4章に基づく
"""
from dataclasses import dataclass
from enum import Enum


class POS(Enum):
    """品詞タイプ"""
    NOUN = "NOUN"
    VERB = "VERB"
    PROPN = "PROPN"
    ADJ = "ADJ"  # 形容詞（Phase 1改善: 追加）
    OTHER = "OTHER"


class ConceptType(Enum):
    """概念タイプ（仕様書 4.3）"""
    ENTITY = "ENTITY"
    RELATION = "RELATION"
    EVENT = "EVENT"
    VALUE = "VALUE"


@dataclass
class ConceptCandidate:
    """
    言語依存層の最終出力（仕様書 4.1）
    
    制約：
    - lemma は日本語・英語を含んでもよい
    - この構造以降、言語情報を参照してはならない
    """
    lemma: str  # 正規化概念名
    pos: POS  # 品詞
    is_proper: bool  # 固有名詞かどうか
    has_numeric_id: bool  # 数値IDを含むか
    is_event_like: bool  # イベント的か
    is_abstract: bool  # 抽象的か
    
    def __hash__(self):
        return hash((self.lemma, self.pos))
    
    def __eq__(self, other):
        if not isinstance(other, ConceptCandidate):
            return False
        return self.lemma == other.lemma and self.pos == other.pos


@dataclass
class ConceptFeatures:
    """
    意味判定用 Feature（言語非依存）（仕様書 4.2）
    """
    name: str  # 概念名
    has_identity: bool  # 同一性を持つか
    persistent: bool  # 持続的か
    referable: bool  # 参照可能か
    attribute_count: int  # 属性数

