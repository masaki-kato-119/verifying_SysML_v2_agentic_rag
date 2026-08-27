"""query_expansionのMixin。

graphrag.query_engine.GraphQueryEngine に多重継承で合成される。
単独では使わない(self.graph/self.cache等、本体側__init__の状態に依存する)。
"""

from __future__ import annotations

import logging
import re
from typing import Dict, List

from .. import config

logger = logging.getLogger(__name__)


class QueryExpansionMixin:
    def _expand_query(self, query: str, use_llm: bool = False) -> List[str]:
        """
        クエリを拡張（改善版ハイブリッドアプローチ）
        
        1. SysML v2特化エイリアス辞書: 専門用語の拡張（最優先）
        2. 一般エイリアス辞書: 基本的な拡張（高速、決定論的）
        3. 改善された語形変化処理: 不規則変化対応
        4. 品質管理されたグラフベース: ノイズ除去強化
        5. 制御されたLLM拡張: 品質管理付きLLM拡張（オプション）
        
        Args:
            query: 元のクエリ
            use_llm: LLMを使用してクエリを拡張するか（オプション）
        
        Returns:
            List[str]: 拡張されたクエリのリスト（元のクエリを含む）
        """
        expanded = [query]
        query_lower = query.lower()
        query_words = query_lower.split()
        
        # 1. SysML v2特化エイリアス辞書（最優先）
        sysml_expanded = config.expand_with_sysml_aliases(query)
        expanded.extend(sysml_expanded)
        
        # 2. 一般エイリアス辞書
        general_expanded = config.expand_with_general_aliases(query)
        expanded.extend(general_expanded)
        
        # 3. 改善された語形変化処理（不規則変化対応）
        morphological_expanded = []
        for word in query_words:
            if len(word) >= 3:  # 3文字以上の単語のみ処理
                variations = config.handle_irregular_plurals(word)
                morphological_expanded.extend(variations)
        expanded.extend(morphological_expanded)
        
        # 4. 品質管理されたグラフベース拡張
        if len(expanded) <= 3:  # 十分な拡張が得られない場合
            graph_expanded = self._find_similar_nodes_improved(query)
            expanded.extend(graph_expanded)
        
        # 5. 制御されたLLM拡張（オプション）
        if use_llm and len(expanded) <= 2:
            llm_expanded = self._expand_query_with_llm_controlled(query)
            expanded.extend(llm_expanded)
        
        # 重複を除去してソート（SysML用語を優先）
        unique_expanded = list(set(expanded))
        
        # SysML用語の優先度でソート
        def get_priority(term):
            return config.get_sysml_priority_score(term)
        
        unique_expanded.sort(key=get_priority, reverse=True)
        
        return unique_expanded
    def _expand_query_with_llm_controlled(self, query: str) -> List[str]:
        """
        LLMによるクエリ拡張（品質管理強化版）
        
        Args:
            query: 元のクエリ
        
        Returns:
            List[str]: 検証済みの拡張クエリのリスト
        """
        try:
            # 1. LLM拡張を実行
            llm_suggestions = self._expand_query_with_llm(query)
            
            # 2. 品質フィルタリング
            validated_suggestions = []
            for suggestion in llm_suggestions:
                # グラフ内に存在するかチェック
                if suggestion in self.graph.nodes():
                    # ノード品質チェック
                    if config.is_valid_node_name(suggestion):
                        # 関連度チェック（簡易版）
                        if self._is_semantically_related(query, suggestion):
                            validated_suggestions.append(suggestion)
            
            # 3. 最大数制限
            return validated_suggestions[:3]  # 最大3個まで

        # _expand_query_with_llm呼び出し（LLM API連携）を含む品質フィルタ処理。
        # LLM/ネットワーク層で起こりうる例外の種類を確実に列挙できないため、意図的に広く捕捉して空リストにフォールバックする。
        except Exception:  # noqa: BLE001
            return []  # エラー時は空リスト
    def _is_semantically_related(self, query: str, node_name: str) -> bool:
        """
        クエリとノードの意味的関連性をチェック
        
        Args:
            query: 元のクエリ
            node_name: ノード名
        
        Returns:
            bool: 関連性がある場合True
        """
        query_words = set(query.lower().split())
        node_words = set(node_name.lower().split())
        
        # 共通単語があるかチェック
        common_words = query_words & node_words
        if len(common_words) > 0:
            return True
        
        # SysML用語の関連性チェック
        sysml_relations = {
            "part": ["item", "usage", "definition"],
            "action": ["behavior", "usage", "definition"],
            "port": ["interface", "connection"],
            "constraint": ["requirement", "rule"],
            "case": ["usage", "definition", "analysis", "verification", "use"],
            "view": ["viewpoint", "rendering"],
            "attribute": ["reference", "feature"],
            "connection": ["flow", "succession", "allocation"],
        }
        
        for query_word in query_words:
            if query_word in sysml_relations:
                related_terms = sysml_relations[query_word]
                if any(term in node_words for term in related_terms):
                    return True
        
        return False
    def _expand_query_with_llm(self, query: str) -> List[str]:
        """
        LLMを使用してクエリを拡張（オプション）
        
        グラフ内のノード名をコンテキストとして、LLMにクエリを拡張してもらう
        
        Args:
            query: 元のクエリ
        
        Returns:
            List[str]: 拡張されたクエリのリスト
        """
        try:
            from openai import OpenAI
            client = OpenAI()
            
            # グラフのノード名を取得（コンテキストとして）
            node_names = list(self.graph.nodes())[:50]  # 最大50ノード
            
            if len(node_names) == 0:
                return []
            
            prompt = f"""以下のクエリを、グラフ内のノード名に基づいて拡張してください。

クエリ: {query}

利用可能なノード名（例）:
{', '.join(node_names[:20])}

クエリに関連する可能性のあるノード名を3-5個、カンマ区切りで返してください。
ノード名のみを返し、説明は不要です。"""

            response = client.chat.completions.create(
                model=config.LLM_MODEL,
                messages=[
                    {"role": "system", "content": "あなたはグラフ検索システムのアシスタントです。クエリを拡張して、関連するノード名を提案してください。"},
                    {"role": "user", "content": prompt}
                ],
                # reasoning モデルは temperature 非対応、max_tokens も使えない。
                # クエリ拡張は検索前段なので推論なしで回す。
                reasoning_effort="none",
                max_completion_tokens=200,
            )
            
            # レスポンスをパース
            expanded_text = response.choices[0].message.content.strip()
            expanded = [name.strip() for name in expanded_text.split(',') if name.strip()]
            
            # グラフ内に存在するノード名のみを返す（検証）
            valid_expanded = [name for name in expanded if name in self.graph.nodes()]
            
            return valid_expanded
        except ImportError:
            # OpenAIがインストールされていない場合
            return []
        # OpenAI API呼び出し（ネットワーク/認証/レート制限など多様な例外が発生しうる）を意図的に広く捕捉する。
        except Exception:  # noqa: BLE001
            # エラー時は空のリストを返す（ログは出力しない、仕様書の制約に従う）
            return []
    def _find_similar_nodes_improved(self, query: str, max_results: int = 5) -> List[str]:
        """
        グラフから類似ノードを抽出（品質管理強化版）
        
        Args:
            query: 元のクエリ
            max_results: 最大結果数
        
        Returns:
            List[str]: 類似ノード名のリスト（品質フィルタ済み）
        """

        query_lower = query.lower().strip()
        query_words = [w for w in query_lower.split() if len(w) >= 3]  # 3文字以上の単語のみ

        # 最小文字数制限
        MIN_KEYWORD_LENGTH = 3
        if len(query_lower) < MIN_KEYWORD_LENGTH:
            return []

        # ノード名の長さ制限（長すぎるノード名を除外）
        MAX_NODE_LENGTH = 100

        # 1. ノード品質フィルタを適用
        valid_nodes = [
            node for node in self.graph.nodes()
            if config.is_valid_node_name(node)  # 品質管理強化版フィルタ
        ]
        
        # 2. SysML v2用語の優先度を上げる
        sysml_keywords = {
            "definition", "usage", "part", "item", "action", "port", 
            "interface", "attribute", "reference", "connection", "constraint", 
            "requirement", "feature", "case", "calculation", "analysis", 
            "verification", "use", "view", "viewpoint", "rendering", 
            "metadata", "enumeration", "succession", "allocation",
            "specializes", "subsets", "redefines", "types", "membership", "ownership"
        }
        
        # 3. 完全一致・部分一致の優先順位を明確化
        exact_matches = []
        sysml_partial_matches = []
        general_partial_matches = []
        
        for node in valid_nodes:
            node_lower = str(node).lower()
            
            # ノード名が長すぎる場合はスキップ
            if len(node_lower) > MAX_NODE_LENGTH:
                continue
            
            # ノード名が短すぎる場合はスキップ
            if len(node_lower) < MIN_KEYWORD_LENGTH:
                continue
            
            # 完全一致（最優先）
            if query_lower == node_lower:
                sysml_score = config.get_sysml_priority_score(node)
                exact_matches.append((node, 1.0 + sysml_score * 0.1))
                continue
            
            # SysML用語を含む部分一致（高優先）
            if any(keyword in node_lower for keyword in sysml_keywords):
                if query_lower in node_lower:
                    score = len(query_lower) / len(node_lower)
                    sysml_score = config.get_sysml_priority_score(node)
                    final_score = score * 0.9 + sysml_score * 0.1
                    sysml_partial_matches.append((node, final_score))
                    continue
                
                # 複数キーワードマッチ（SysML用語）
                if len(query_words) > 1:
                    matched_words = sum(
                        1 for word in query_words
                        if re.search(r'\b' + re.escape(word) + r'\b', node_lower)
                    )
                    if matched_words >= 2:  # 2個以上のキーワードがマッチ
                        match_ratio = matched_words / len(query_words)
                        sysml_score = config.get_sysml_priority_score(node)
                        final_score = match_ratio * 0.8 + sysml_score * 0.1
                        sysml_partial_matches.append((node, final_score))
                        continue
            
            # 一般的な部分一致（低優先）
            elif query_lower in node_lower:
                score = len(query_lower) / len(node_lower)
                general_partial_matches.append((node, score * 0.5))
        
        # 結果をマージしてソート
        all_matches = exact_matches + sysml_partial_matches + general_partial_matches
        all_matches.sort(key=lambda x: x[1], reverse=True)
        
        return [node for node, score in all_matches[:max_results]]
    def expand_query_enhanced(
        self,
        query: str,
        max_candidates: int = 10,
        min_score: float = 0.3,
        use_fuzzy_matching: bool = True,
        include_attributes: bool = True
    ) -> Dict:
        """
        自然文クエリを用語候補に拡張
        
        Args:
            query: 自然文クエリ
            max_candidates: 最大候補数
            min_score: 最小マッチスコア（0.0-1.0）
            use_fuzzy_matching: ファジーマッチングを使用するか
            include_attributes: ノード属性も検索対象に含めるか
        
        Returns:
            dict: 拡張結果
        """
        return self.query_expander.expand_query(
            query=query,
            max_candidates=max_candidates,
            min_score=min_score,
            use_fuzzy_matching=use_fuzzy_matching,
            include_attributes=include_attributes
        )
    def get_expansion_suggestions(
        self,
        query: str,
        max_suggestions: int = 5
    ) -> Dict:
        """
        クエリ拡張の提案を取得
        
        Args:
            query: 元のクエリ
            max_suggestions: 最大提案数
        
        Returns:
            dict: 拡張提案
        """
        return self.query_expander.get_expansion_suggestions(
            query=query,
            max_suggestions=max_suggestions
        )
