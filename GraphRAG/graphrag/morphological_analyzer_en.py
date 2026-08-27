"""
英語形態素解析モジュール
NLTKを使用
"""
import logging
from typing import List, Tuple

logger = logging.getLogger(__name__)

try:
    import nltk
    from nltk.stem import WordNetLemmatizer
    from nltk.tag import pos_tag
    from nltk.tokenize import sent_tokenize, word_tokenize
    NLTK_AVAILABLE = True
except ImportError:
    NLTK_AVAILABLE = False


class MorphologicalAnalyzerEN:
    """
    英語形態素解析器
    
    目的は「候補の漏れ防止」のみ
    出力は正解として扱ってはならない
    """
    
    def __init__(self):
        """NLTKを初期化"""
        if not NLTK_AVAILABLE:
            raise ImportError(
                "NLTK is required for English morphological analysis. "
                "Install with: pip install nltk"
            )
        
        # NLTKデータのダウンロード（初回のみ）
        try:
            nltk.data.find('tokenizers/punkt')
        except LookupError:
            nltk.download('punkt', quiet=True)
        
        # 新しいバージョンのNLTKではpunkt_tabも必要
        try:
            nltk.data.find('tokenizers/punkt_tab')
        except LookupError:
            try:
                nltk.download('punkt_tab', quiet=True)
            except Exception:
                # punkt_tabが利用できない場合は古いpunktを使用（意図的なフォールバック）
                logger.debug("punkt_tab の取得に失敗。punkt へフォールバックします", exc_info=True)
        
        try:
            nltk.data.find('taggers/averaged_perceptron_tagger')
        except LookupError:
            nltk.download('averaged_perceptron_tagger', quiet=True)
        
        # 新しいバージョンのNLTKではaveraged_perceptron_tagger_engも必要
        try:
            nltk.data.find('taggers/averaged_perceptron_tagger_eng')
        except LookupError:
            try:
                nltk.download('averaged_perceptron_tagger_eng', quiet=True)
            except Exception:
                # averaged_perceptron_tagger_engが利用できない場合は古いリソースを使用（意図的なフォールバック）
                logger.debug(
                    "averaged_perceptron_tagger_eng の取得に失敗。"
                    "averaged_perceptron_tagger へフォールバックします",
                    exc_info=True,
                )
        
        try:
            nltk.data.find('corpora/wordnet')
        except LookupError:
            nltk.download('wordnet', quiet=True)
        
        self.lemmatizer = WordNetLemmatizer()
    
    def analyze(self, text: str) -> List[Tuple[str, str, str]]:
        """
        テキストを形態素解析
        
        Args:
            text: 入力テキスト（英語）
        
        Returns:
            List[Tuple[surface, pos, lemma]]: 
                surface: 表層形
                pos: 品詞情報（Penn Treebank形式）
                lemma: 原形
        """
        # 文に分割
        sentences = sent_tokenize(text)
        
        results = []
        for sentence in sentences:
            # 単語に分割
            tokens = word_tokenize(sentence)
            
            # 品詞タグ付け
            tagged = pos_tag(tokens)
            
            for word, pos_tag_str in tagged:
                # 原形を取得
                lemma = self._lemmatize(word, pos_tag_str)
                
                results.append((word, pos_tag_str, lemma))
        
        return results
    
    def _lemmatize(self, word: str, pos_tag_str: str) -> str:
        """
        単語を原形に変換
        
        Args:
            word: 単語
            pos_tag_str: Penn Treebank形式の品詞タグ
        
        Returns:
            str: 原形
        """
        # Penn Treebank形式をWordNet形式に変換
        pos_wn = self._penn_to_wordnet(pos_tag_str)
        
        if pos_wn:
            return self.lemmatizer.lemmatize(word.lower(), pos_wn)
        else:
            return self.lemmatizer.lemmatize(word.lower())
    
    def _penn_to_wordnet(self, penn_tag: str) -> str:
        """
        Penn Treebank形式の品詞タグをWordNet形式に変換
        
        Args:
            penn_tag: Penn Treebank形式の品詞タグ
        
        Returns:
            str: WordNet形式の品詞（'n', 'v', 'a', 'r'）またはNone
        """
        if penn_tag.startswith('N'):
            return 'n'  # noun
        elif penn_tag.startswith('V'):
            return 'v'  # verb
        elif penn_tag.startswith('J'):
            return 'a'  # adjective
        elif penn_tag.startswith('R'):
            return 'r'  # adverb
        else:
            return None

