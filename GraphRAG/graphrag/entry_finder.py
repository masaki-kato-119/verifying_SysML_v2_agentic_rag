"""
軽量エントリーファインダー
キーワードベースのエントリーポイント発見機能
"""
import re
from typing import Dict, List, Set

import networkx as nx

from . import config


class LightweightEntryFinder:
    """
    軽量エントリーファインダー
    
    グラフ探索の開始点（エントリーポイント）を発見する機能
    ベクトル検索ではなく、キーワードマッチングと概念階層を活用
    """
    
    def __init__(self, graph: nx.DiGraph):
        """
        エントリーファインダーを初期化
        
        Args:
            graph: 検索対象のグラフ
        """
        self.graph = graph
        self.keyword_index = self._build_keyword_index()
        self.concept_hierarchy = self._build_concept_hierarchy()
    
    def _build_keyword_index(self) -> Dict[str, Set[str]]:
        """
        キーワードインデックスを構築
        
        Returns:
            Dict[str, Set[str]]: キーワード -> ノード名のセット
        """
        index = {}
        node_names = set(self.graph.nodes())
        
        for node_name in node_names:
            # ノード名を小文字化してキーワードとして登録
            node_lower = node_name.lower()
            if node_lower not in index:
                index[node_lower] = set()
            index[node_lower].add(node_name)
            
            # 単語ごとに分割してインデックス
            words = re.findall(r'\w+', node_name.lower())
            for word in words:
                if len(word) >= 3:  # 3文字以上の単語のみ
                    if word not in index:
                        index[word] = set()
                    index[word].add(node_name)
        
        return index
    
    def _build_concept_hierarchy(self) -> Dict[str, List[str]]:
        """
        SysML v2の概念階層を構築
        
        Returns:
            Dict[str, List[str]]: 上位概念 -> 下位概念のリスト
        """
        return {
            # 英語の概念階層
            "definition": ["partdefinition", "actiondefinition", "portdefinition", 
                          "itemdefinition", "interfacedefinition", "attributedefinition",
                          "referencedefinition", "constraintdefinition", "requirementdefinition",
                          "casedefinition", "calculationdefinition", "viewdefinition",
                          "viewpointdefinition", "renderingdefinition", "metadatadefinition",
                          "enumerationdefinition", "analysiscasedefinition", "verificationcasedefinition",
                          "usecasedefinition"],
            "usage": ["partusage", "actionusage", "portusage", "itemusage",
                     "interfaceusage", "attributeusage", "referenceusage",
                     "constraintusage", "requirementusage", "caseusage",
                     "calculationusage", "viewusage", "renderingusage",
                     "metadatausage", "enumerationusage", "analysiscaseusage",
                     "verificationcaseusage", "usecaseusage", "connectionusage",
                     "flowconnectionusage", "successionusage", "allocationusage"],
            "action": ["actiondefinition", "actionusage"],
            "part": ["partdefinition", "partusage"],
            "item": ["itemdefinition", "itemusage"],
            "port": ["portdefinition", "portusage"],
            "interface": ["interfacedefinition", "interfaceusage"],
            "attribute": ["attributedefinition", "attributeusage"],
            "reference": ["referencedefinition", "referenceusage"],
            "constraint": ["constraintdefinition", "constraintusage"],
            "requirement": ["requirementdefinition", "requirementusage"],
            "case": ["casedefinition", "caseusage"],
            "parameter": ["input", "output", "inout"],
            "flow": ["succession", "connection", "flowconnection"],
            
            # 日本語対応
            "定義": ["パート定義", "アクション定義", "ポート定義", "アイテム定義",
                    "インターフェース定義", "属性定義", "参照定義", "制約定義",
                    "要求定義", "ケース定義"],
            "使用": ["パート使用", "アクション使用", "ポート使用", "アイテム使用",
                    "インターフェース使用", "属性使用", "参照使用", "制約使用",
                    "要求使用", "ケース使用"],
            "アクション": ["アクション定義", "アクション使用"],
            "パート": ["パート定義", "パート使用"],
            "アイテム": ["アイテム定義", "アイテム使用"],
            "ポート": ["ポート定義", "ポート使用"],
            "インターフェース": ["インターフェース定義", "インターフェース使用"],
            "属性": ["属性定義", "属性使用"],
            "参照": ["参照定義", "参照使用"],
            "制約": ["制約定義", "制約使用"],
            "要求": ["要求定義", "要求使用"],
            "ケース": ["ケース定義", "ケース使用"],
        }
    
    def find_entry_points(
        self, 
        query: str, 
        max_entries: int = 3
    ) -> List[str]:
        """
        軽量なエントリーポイント発見
        
        Args:
            query: 自然言語クエリ
            max_entries: 最大エントリーポイント数
        
        Returns:
            List[str]: エントリーポイント（ノード名）のリスト
        """
        # 1. キーワード抽出
        keywords = self._extract_keywords(query)
        
        if not keywords:
            # キーワードが見つからない場合は中心性の高いノードを返す
            return self._get_central_nodes(max_entries)
        
        # 2. ノード名との直接マッチング
        direct_matches = self._find_direct_matches(keywords)
        if direct_matches:
            return direct_matches[:max_entries]
        
        # 3. 概念階層での近似マッチング
        concept_matches = self._find_concept_matches(keywords)
        if concept_matches:
            return concept_matches[:max_entries]
        
        # 4. フォールバック: 中心性の高いノード
        return self._get_central_nodes(max_entries)
    
    def _extract_keywords(self, query: str) -> List[str]:
        """
        クエリからキーワードを抽出
        
        Args:
            query: 自然言語クエリ
        
        Returns:
            List[str]: キーワードのリスト
        """
        # SysML特化キーワード辞書を活用
        sysml_terms = self._extract_sysml_terms(query)
        general_terms = self._extract_general_terms(query)
        
        # 重複除去
        all_terms = list(set(sysml_terms + general_terms))
        
        # ストップワードを除外
        filtered_terms = [
            term for term in all_terms 
            if term.lower() not in config.STOPWORDS and len(term) >= 3
        ]
        
        return filtered_terms
    
    def _extract_sysml_terms(self, query: str) -> List[str]:
        """
        SysML v2特化キーワードを抽出
        
        Args:
            query: 自然言語クエリ
        
        Returns:
            List[str]: SysML v2キーワードのリスト
        """
        query_lower = query.lower()
        sysml_terms = []
        
        # SysML v2エイリアス辞書から抽出
        for alias, node_names in config.SYSML_V2_ALIASES.items():
            alias_lower = alias.lower()
            if alias_lower in query_lower:
                sysml_terms.append(alias_lower)
                # 対応するノード名も追加
                for node_name in node_names:
                    node_lower = node_name.lower()
                    if node_lower not in sysml_terms:
                        sysml_terms.append(node_lower)
        
        return sysml_terms
    
    def _extract_general_terms(self, query: str) -> List[str]:
        """
        一般キーワードを抽出
        
        Args:
            query: 自然言語クエリ
        
        Returns:
            List[str]: 一般キーワードのリスト
        """
        # 単語に分割（英数字と日本語を考慮）
        words = re.findall(r'\w+|[一-龠]+', query.lower())
        
        # 3文字以上の単語のみ
        filtered_words = [w for w in words if len(w) >= 3]
        
        return filtered_words
    
    def _find_direct_matches(self, keywords: List[str]) -> List[str]:
        """
        ノード名との直接マッチング
        
        Args:
            keywords: キーワードのリスト
        
        Returns:
            List[str]: マッチしたノード名のリスト
        """
        matches = set()
        
        for keyword in keywords:
            keyword_lower = keyword.lower()
            
            # 完全一致
            if keyword_lower in self.keyword_index:
                matches.update(self.keyword_index[keyword_lower])
            
            # 部分一致（ノード名にキーワードが含まれる）
            for node_name in self.graph.nodes():
                node_lower = node_name.lower()
                if keyword_lower in node_lower:
                    matches.add(node_name)
        
        # スコアリングしてソート
        scored_matches = [
            (node, self._evaluate_entry_quality(node, keywords))
            for node in matches
        ]
        scored_matches.sort(key=lambda x: x[1], reverse=True)
        
        return [node for node, score in scored_matches]
    
    def _find_concept_matches(self, keywords: List[str]) -> List[str]:
        """
        概念階層での近似マッチング
        
        Args:
            keywords: キーワードのリスト
        
        Returns:
            List[str]: マッチしたノード名のリスト
        """
        matches = set()
        
        for keyword in keywords:
            keyword_lower = keyword.lower()
            
            # 概念階層で検索
            for concept, subconcepts in self.concept_hierarchy.items():
                concept_lower = concept.lower()
                
                # 上位概念にマッチ
                if keyword_lower == concept_lower or keyword_lower in concept_lower:
                    # 下位概念のノードを検索
                    for subconcept in subconcepts:
                        subconcept_lower = subconcept.lower()
                        # グラフ内のノードとマッチング
                        for node_name in self.graph.nodes():
                            node_lower = node_name.lower()
                            if subconcept_lower in node_lower or node_lower in subconcept_lower:
                                matches.add(node_name)
                
                # 下位概念に直接マッチ
                for subconcept in subconcepts:
                    subconcept_lower = subconcept.lower()
                    if keyword_lower == subconcept_lower or keyword_lower in subconcept_lower:
                        # グラフ内のノードとマッチング
                        for node_name in self.graph.nodes():
                            node_lower = node_name.lower()
                            if subconcept_lower in node_lower or node_lower in subconcept_lower:
                                matches.add(node_name)
        
        # スコアリングしてソート
        scored_matches = [
            (node, self._evaluate_entry_quality(node, keywords))
            for node in matches
        ]
        scored_matches.sort(key=lambda x: x[1], reverse=True)
        
        return [node for node, score in scored_matches]
    
    def _evaluate_entry_quality(
        self, 
        node: str, 
        keywords: List[str]
    ) -> float:
        """
        エントリーポイントの品質を評価
        
        Args:
            node: ノード名
            keywords: キーワードのリスト
        
        Returns:
            float: 品質スコア（0.0-1.0）
        """
        score = 0.0
        
        # 1. ノード名との類似度
        name_similarity = self._calculate_name_similarity(node, keywords)
        score += name_similarity * 0.4
        
        # 2. ノードの中心性（重要度）
        try:
            centrality = nx.degree_centrality(self.graph)[node]
            score += centrality * 0.3
        except (nx.NetworkXException, KeyError):
            score += 0.0
        
        # 3. ドメイン特化度（SysML用語かどうか）
        domain_score = self._calculate_domain_relevance(node)
        score += domain_score * 0.3
        
        return score
    
    def _calculate_name_similarity(
        self, 
        node: str, 
        keywords: List[str]
    ) -> float:
        """
        ノード名とキーワードの類似度を計算
        
        Args:
            node: ノード名
            keywords: キーワードのリスト
        
        Returns:
            float: 類似度（0.0-1.0）
        """
        node_lower = node.lower()
        max_similarity = 0.0
        
        for keyword in keywords:
            keyword_lower = keyword.lower()
            
            # 完全一致
            if keyword_lower == node_lower:
                return 1.0
            
            # 部分一致
            if keyword_lower in node_lower or node_lower in keyword_lower:
                similarity = len(keyword_lower) / max(len(node_lower), len(keyword_lower))
                max_similarity = max(max_similarity, similarity)
        
        return max_similarity
    
    def _calculate_domain_relevance(self, node: str) -> float:
        """
        ドメイン特化度を計算（SysML用語かどうか）
        
        Args:
            node: ノード名
        
        Returns:
            float: ドメイン特化度（0.0-1.0）
        """
        node_lower = node.lower()
        
        # SysML v2コア用語
        sysml_core_terms = {
            "partdefinition", "partusage", "itemdefinition", "itemusage",
            "actiondefinition", "actionusage", "portdefinition", "portusage",
            "interfacedefinition", "interfaceusage", "constraintdefinition",
            "constraintusage", "requirementdefinition", "requirementusage"
        }
        
        if node_lower in sysml_core_terms:
            return 1.0
        
        # SysML v2関連用語
        sysml_related_terms = {
            "attributedefinition", "attributeusage", "referencedefinition",
            "referenceusage", "connectionusage", "flowconnectionusage",
            "successionusage", "allocationusage", "casedefinition", "caseusage"
        }
        
        if node_lower in sysml_related_terms:
            return 0.8
        
        # SysML v2関係用語
        sysml_relation_terms = {
            "specializes", "subsets", "redefines", "types", "membership",
            "ownership", "feature", "featureusage"
        }
        
        if node_lower in sysml_relation_terms:
            return 0.6
        
        # 一般的なSysML用語を含む
        sysml_keywords = ["definition", "usage", "part", "item", "action",
                         "port", "interface", "attribute", "reference",
                         "constraint", "requirement", "case"]
        
        if any(keyword in node_lower for keyword in sysml_keywords):
            return 0.4
        
        return 0.0
    
    def _get_central_nodes(self, max_nodes: int = 3) -> List[str]:
        """
        中心性の高いノードを取得（フォールバック）
        
        Args:
            max_nodes: 最大ノード数
        
        Returns:
            List[str]: 中心性の高いノードのリスト
        """
        if self.graph.number_of_nodes() == 0:
            return []
        
        try:
            # 次数中心性を計算
            centrality = nx.degree_centrality(self.graph)
            
            # 中心性でソート
            sorted_nodes = sorted(
                centrality.items(),
                key=lambda x: x[1],
                reverse=True
            )
            
            return [node for node, score in sorted_nodes[:max_nodes]]
        except nx.NetworkXException:
            # エラーが発生した場合は、単純にノードを返す
            nodes = list(self.graph.nodes())
            return nodes[:max_nodes]
