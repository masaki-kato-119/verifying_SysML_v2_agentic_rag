"""
Query Expander（クエリ拡張器）
自然文クエリを用語候補に変換し、グラフ検索を支援する機能
"""
import re
from typing import Dict, List

import networkx as nx

from . import config


class QueryExpander:
    """
    クエリ拡張器
    
    自然文クエリから用語候補を抽出し、グラフ内ノードとマッチングする機能を提供
    """
    
    def __init__(self, graph: nx.DiGraph):
        """
        クエリ拡張器を初期化
        
        Args:
            graph: 検索対象のグラフ
        """
        self.graph = graph
        self._build_node_index()
    
    def _build_node_index(self):
        """
        ノードインデックスを構築（高速検索用）
        """
        self.node_names = set(self.graph.nodes())
        self.node_names_lower = {name.lower(): name for name in self.node_names}
        
        # ノード属性からも検索可能にする
        self.node_attributes = {}
        for node_name in self.node_names:
            node_data = self.graph.nodes[node_name]
            attributes = []
            
            # 一般的な属性を収集
            for attr in ['type', 'category', 'description', 'label']:
                if attr in node_data and node_data[attr]:
                    attributes.append(str(node_data[attr]).lower())
            
            self.node_attributes[node_name] = attributes
    
    def expand_query(
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
        try:
            # 1. キーフレーズ抽出
            keyphrases = self._extract_keyphrases(query)
            
            # 2. 用語候補の抽出
            candidates = []
            
            # 2.1 直接マッチング
            direct_matches = self._find_direct_matches(keyphrases)
            candidates.extend(direct_matches)
            
            # 2.2 エイリアス辞書マッチング
            alias_matches = self._find_alias_matches(keyphrases)
            candidates.extend(alias_matches)
            
            # 2.3 ファジーマッチング（オプション）
            if use_fuzzy_matching:
                fuzzy_matches = self._find_fuzzy_matches(keyphrases, min_score)
                candidates.extend(fuzzy_matches)
            
            # 2.4 属性マッチング（オプション）
            if include_attributes:
                attribute_matches = self._find_attribute_matches(keyphrases)
                candidates.extend(attribute_matches)
            
            # 3. スコアリングと重複除去
            scored_candidates = self._score_and_deduplicate(candidates, query)
            
            # 4. 上位候補を選択
            top_candidates = sorted(
                scored_candidates, 
                key=lambda x: x['score'], 
                reverse=True
            )[:max_candidates]
            
            # 5. 最小スコアでフィルタ
            filtered_candidates = [
                c for c in top_candidates if c['score'] >= min_score
            ]
            
            return {
                "success": True,
                "original_query": query,
                "keyphrases": keyphrases,
                "candidates": filtered_candidates,
                "total_candidates": len(scored_candidates),
                "filtered_candidates": len(filtered_candidates)
            }
        
        # キーフレーズ抽出〜スコアリングの複数処理をまとめてAPI応答（success/error）に変換するため意図的に広く捕捉
        except Exception as e:  # noqa: BLE001
            return {
                "success": False,
                "error": str(e),
                "original_query": query
            }

    def _extract_keyphrases(self, query: str) -> List[str]:
        """
        クエリからキーフレーズを抽出（Phase 3: 専門用語抽出機能の強化）
        
        Args:
            query: 自然文クエリ
        
        Returns:
            List[str]: キーフレーズのリスト
        """
        # 基本的なキーフレーズ抽出
        keyphrases = []
        
        # 1. 全体をキーフレーズとして追加
        keyphrases.append(query.strip())
        
        # 2. 専門用語抽出（SysML v2特化）
        sysml_terms = self._extract_sysml_terms(query)
        keyphrases.extend(sysml_terms)
        
        # 3. 単語に分割
        words = re.findall(r'\b\w+\b', query.lower())
        keyphrases.extend(words)
        
        # 4. 語形変化の正規化処理
        normalized_words = []
        for word in words:
            if len(word) >= 3:  # 3文字以上の単語のみ
                try:
                    variations = config.handle_irregular_plurals(word)
                    if variations is not None:
                        normalized_words.extend(variations)
                except (AttributeError, TypeError):
                    # handle_irregular_pluralsが存在しない、またはNoneを返す場合
                    pass
        keyphrases.extend(normalized_words)
        
        # 5. 2-gram, 3-gramを生成
        for i in range(len(words) - 1):
            keyphrases.append(' '.join(words[i:i+2]))
        
        for i in range(len(words) - 2):
            keyphrases.append(' '.join(words[i:i+3]))
        
        # 6. 重要そうな単語を優先（大文字で始まる、長い単語など）
        important_words = []
        for word in re.findall(r'\b[A-Z]\w+\b', query):  # 大文字で始まる単語
            important_words.append(word)
        
        for word in words:
            if len(word) >= 4:  # 4文字以上の単語
                important_words.append(word)
        
        keyphrases.extend(important_words)
        
        # 7. 重複除去と空文字除去、ストップワード除去
        unique_keyphrases = []
        seen = set()
        for phrase in keyphrases:
            phrase = phrase.strip().lower()
            if phrase and phrase not in seen:
                # ストップワードを除外
                if phrase not in config.STOPWORDS and len(phrase) >= 3:
                    unique_keyphrases.append(phrase)
                    seen.add(phrase)
        
        return unique_keyphrases
    
    def _extract_sysml_terms(self, query: str) -> List[str]:
        """
        専門用語抽出（SysML v2特化）
        
        Args:
            query: 自然文クエリ
        
        Returns:
            List[str]: 専門用語のリスト
        """
        sysml_terms = []
        query_lower = query.lower()
        
        # SysML v2エイリアス辞書から抽出
        if hasattr(config, 'SYSML_V2_ALIASES') and config.SYSML_V2_ALIASES:
            for alias, node_names in config.SYSML_V2_ALIASES.items():
                if node_names is None:
                    continue
                alias_lower = alias.lower()
                # 単語境界を考慮したマッチング
                pattern = r'\b' + re.escape(alias_lower) + r'\b'
                if re.search(pattern, query_lower):
                    sysml_terms.append(alias_lower)
                    # 対応するノード名も追加
                    if isinstance(node_names, (list, tuple)):
                        for node_name in node_names:
                            node_lower = node_name.lower()
                            if node_lower not in sysml_terms:
                                sysml_terms.append(node_lower)
        
        return sysml_terms
    
    def _find_direct_matches(self, keyphrases: List[str]) -> List[Dict]:
        """
        直接マッチングで候補を検索
        
        Args:
            keyphrases: キーフレーズのリスト
        
        Returns:
            List[Dict]: マッチした候補のリスト
        """
        matches = []
        
        for phrase in keyphrases:
            phrase_lower = phrase.lower()
            
            # 完全一致
            if phrase_lower in self.node_names_lower:
                node_name = self.node_names_lower[phrase_lower]
                matches.append({
                    "node_name": node_name,
                    "match_type": "exact",
                    "matched_phrase": phrase,
                    "base_score": 1.0
                })
            
            # 部分一致（Phase 3: 部分一致問題の解決）
            if self.node_names:
                for node_name in self.node_names:
                    node_lower = node_name.lower()
                    
                    # 単語境界を考慮した部分一致（誤検出を防ぐ）
                    # 例: "parts"が"aparts"にマッチしないようにする
                    if self._is_valid_partial_match(phrase_lower, node_lower):
                        # 一致度を計算
                        phrase_words = set(phrase_lower.split()) if phrase_lower else set()
                        node_words = set(node_lower.split()) if node_lower else set()
                        overlap = len(phrase_words & node_words)
                        total_words = len(phrase_words | node_words)
                        score = overlap / total_words if total_words > 0 else 0
                        
                        if score > 0.3:  # 30%以上の一致
                            matches.append({
                                "node_name": node_name,
                                "match_type": "partial",
                                "matched_phrase": phrase,
                                "base_score": score
                            })

        return matches

    def _is_valid_partial_match(self, phrase: str, node_name: str) -> bool:
        """
        有効な部分一致かどうかを判定（Phase 3: 部分一致問題の解決）
        
        Args:
            phrase: フレーズ
            node_name: ノード名
        
        Returns:
            bool: 有効な部分一致の場合True
        """
        # 完全一致は有効
        if phrase == node_name:
            return True
        
        # 単語境界を考慮した部分一致
        # 例: "part"は"partdefinition"にマッチするが、"aparts"にはマッチしない
        import re
        
        # 単語境界で囲まれた部分一致
        pattern = r'\b' + re.escape(phrase) + r'\b'
        if re.search(pattern, node_name):
            return True
        
        # ノード名がフレーズで始まる、または終わる
        if node_name.startswith(phrase) or node_name.endswith(phrase):
            return True
        
        # フレーズがノード名で始まる、または終わる
        if phrase.startswith(node_name) or phrase.endswith(node_name):
            return True
        
        # 無効なパターン: 部分一致ノード（"aparts", "partsthat"など）
        invalid_patterns = [
            r'^.*parts$',  # "aparts"など
            r'^.*part[a-z]+$',  # "partsthat"など（ただし有効例外は除外）
            r'^.*item[a-z]+$',  # "itemsthat"など
            r'^.*usages$',  # "portusages"など（ただし有効例外は除外）
        ]
        
        # 有効な例外（SysML v2用語）
        valid_exceptions = {
            'partusage', 'itemusage', 'partdefinition', 'itemdefinition',
            'actionusage', 'actiondefinition', 'portusage', 'portdefinition',
            'interfaceusage', 'interfacedefinition', 'attributedefinition',
            'attributeusage', 'referencedefinition', 'referenceusage',
            'constraintusage', 'constraintdefinition', 'requirementusage',
            'requirementdefinition', 'caseusage', 'casedefinition',
            'calculationusage', 'calculationdefinition', 'viewusage',
            'viewdefinition', 'viewpointdefinition', 'renderingusage',
            'renderingdefinition', 'metadatausage', 'metadatadefinition',
            'enumerationusage', 'enumerationdefinition', 'successionusage',
            'allocationusage', 'featureusage', 'connectionusage',
            'flowconnectionusage', 'analysiscaseusage', 'analysiscasedefinition',
            'verificationcaseusage', 'verificationcasedefinition',
            'usecaseusage', 'usecasedefinition'
        }
        
        if node_name.lower() in valid_exceptions:
            return True
        
        # 無効パターンに一致する場合は除外
        for pattern in invalid_patterns:
            if re.match(pattern, node_name.lower()):
                return False
        
        return False
    
    def _find_alias_matches(self, keyphrases: List[str]) -> List[Dict]:
        """
        エイリアス辞書でマッチングして候補を検索
        
        Args:
            keyphrases: キーフレーズのリスト
        
        Returns:
            List[Dict]: マッチした候補のリスト
        """
        matches = []
        
        if not hasattr(config, 'NODE_ALIASES') or not config.NODE_ALIASES:
            return matches
        
        for phrase in keyphrases:
            phrase_lower = phrase.lower()
            
            # エイリアス辞書から検索
            for alias, node_names in config.NODE_ALIASES.items():
                if node_names is None:
                    continue
                alias_lower = alias.lower()
                
                # 完全一致
                if phrase_lower == alias_lower:
                    for node_name in node_names:
                        if node_name in self.node_names:
                            matches.append({
                                "node_name": node_name,
                                "match_type": "alias_exact",
                                "matched_phrase": phrase,
                                "alias": alias,
                                "base_score": 0.9
                            })
                
                # 部分一致
                elif phrase_lower in alias_lower or alias_lower in phrase_lower:
                    overlap = len(set(phrase_lower.split()) & set(alias_lower.split()))
                    total_words = len(set(phrase_lower.split()) | set(alias_lower.split()))
                    score = overlap / total_words if total_words > 0 else 0
                    
                    if score > 0.4:  # 40%以上の一致
                        for node_name in node_names:
                            if node_name in self.node_names:
                                matches.append({
                                    "node_name": node_name,
                                    "match_type": "alias_partial",
                                    "matched_phrase": phrase,
                                    "alias": alias,
                                    "base_score": score * 0.8
                                })
        
        return matches
    
    def _find_fuzzy_matches(self, keyphrases: List[str], min_score: float) -> List[Dict]:
        """
        ファジーマッチングで候補を検索
        
        Args:
            keyphrases: キーフレーズのリスト
            min_score: 最小マッチスコア
        
        Returns:
            List[Dict]: マッチした候補のリスト
        """
        matches = []
        
        for phrase in keyphrases:
            if len(phrase) < 3:  # 短すぎるフレーズはスキップ
                continue
            
            phrase_lower = phrase.lower()
            
            for node_name in self.node_names:
                node_lower = node_name.lower()
                
                # レーベンシュタイン距離ベースの類似度
                similarity = self._calculate_similarity(phrase_lower, node_lower)
                
                if similarity >= min_score:
                    matches.append({
                        "node_name": node_name,
                        "match_type": "fuzzy",
                        "matched_phrase": phrase,
                        "base_score": similarity * 0.7  # ファジーマッチは少し低めのスコア
                    })
        
        return matches
    
    def _find_attribute_matches(self, keyphrases: List[str]) -> List[Dict]:
        """
        ノード属性でマッチングして候補を検索
        
        Args:
            keyphrases: キーフレーズのリスト
        
        Returns:
            List[Dict]: マッチした候補のリスト
        """
        matches = []
        
        if not self.node_attributes:
            return matches
        
        for phrase in keyphrases:
            phrase_lower = phrase.lower()
            
            for node_name, attributes in self.node_attributes.items():
                if not attributes:
                    continue
                for attr in attributes:
                    if phrase_lower in attr or attr in phrase_lower:
                        # 一致度を計算
                        overlap = len(set(phrase_lower.split()) & set(attr.split()))
                        total_words = len(set(phrase_lower.split()) | set(attr.split()))
                        score = overlap / total_words if total_words > 0 else 0
                        
                        if score > 0.3:  # 30%以上の一致
                            matches.append({
                                "node_name": node_name,
                                "match_type": "attribute",
                                "matched_phrase": phrase,
                                "matched_attribute": attr,
                                "base_score": score * 0.6  # 属性マッチは低めのスコア
                            })
        
        return matches
    
    def _calculate_similarity(self, s1: str, s2: str) -> float:
        """
        2つの文字列の類似度を計算（レーベンシュタイン距離ベース）
        
        Args:
            s1: 文字列1
            s2: 文字列2
        
        Returns:
            float: 類似度（0.0-1.0）
        """
        if not s1 or not s2:
            return 0.0
        
        # 長さの差が大きすぎる場合は類似度を下げる
        len_diff = abs(len(s1) - len(s2))
        max_len = max(len(s1), len(s2))
        if len_diff / max_len > 0.5:
            return 0.0
        
        # レーベンシュタイン距離を計算
        distance = self._levenshtein_distance(s1, s2)
        max_len = max(len(s1), len(s2))
        
        # 類似度に変換
        similarity = 1.0 - (distance / max_len) if max_len > 0 else 0.0
        return max(0.0, similarity)
    
    def _levenshtein_distance(self, s1: str, s2: str) -> int:
        """
        レーベンシュタイン距離を計算
        
        Args:
            s1: 文字列1
            s2: 文字列2
        
        Returns:
            int: レーベンシュタイン距離
        """
        if len(s1) < len(s2):
            return self._levenshtein_distance(s2, s1)
        
        if len(s2) == 0:
            return len(s1)
        
        previous_row = list(range(len(s2) + 1))
        for i, c1 in enumerate(s1):
            current_row = [i + 1]
            for j, c2 in enumerate(s2):
                insertions = previous_row[j + 1] + 1
                deletions = current_row[j] + 1
                substitutions = previous_row[j] + (c1 != c2)
                current_row.append(min(insertions, deletions, substitutions))
            previous_row = current_row
        
        return previous_row[-1]
    
    def _score_and_deduplicate(self, candidates: List[Dict], original_query: str) -> List[Dict]:
        """
        候補をスコアリングして重複除去
        
        Args:
            candidates: 候補のリスト
            original_query: 元のクエリ
        
        Returns:
            List[Dict]: スコアリング済み・重複除去済みの候補
        """
        if not candidates:
            return []
        
        # ノード名でグループ化
        node_groups = {}
        for candidate in candidates:
            if not candidate or "node_name" not in candidate:
                continue
            node_name = candidate["node_name"]
            if node_name not in node_groups:
                node_groups[node_name] = []
            node_groups[node_name].append(candidate)
        
        # 各ノードの最高スコアを計算
        scored_candidates = []
        for node_name, group in node_groups.items():
            if not group:
                continue
            # 基本スコアの最大値
            max_base_score = max(c.get("base_score", 0.0) for c in group)
            
            # マッチタイプボーナス
            match_types = [c["match_type"] for c in group]
            type_bonus = 0.0
            if "exact" in match_types:
                type_bonus = 0.2
            elif "alias_exact" in match_types:
                type_bonus = 0.15
            elif "partial" in match_types:
                type_bonus = 0.1
            elif "alias_partial" in match_types:
                type_bonus = 0.05
            
            # グラフ構造ボーナス（接続数が多いノードを優先）
            node_degree = self.graph.degree(node_name)
            degree_bonus = min(0.1, node_degree * 0.01)  # 最大0.1のボーナス
            
            # 最終スコア
            final_score = min(1.0, max_base_score + type_bonus + degree_bonus)
            
            # 代表的な候補を選択（最高スコアのもの）
            best_candidate = max(group, key=lambda x: x["base_score"])
            
            scored_candidates.append({
                "node_name": node_name,
                "score": final_score,
                "match_info": {
                    "match_type": best_candidate["match_type"],
                    "matched_phrase": best_candidate["matched_phrase"],
                    "base_score": max_base_score,
                    "type_bonus": type_bonus,
                    "degree_bonus": degree_bonus,
                    "node_degree": node_degree
                },
                "all_matches": len(group)
            })
        
        return scored_candidates
    
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
        try:
            # 基本的な拡張を実行
            expansion_result = self.expand_query(query, max_candidates=max_suggestions * 2)
            
            if not expansion_result["success"]:
                return expansion_result
            
            candidates = expansion_result["candidates"]
            
            # 提案を生成
            suggestions = []
            for candidate in candidates[:max_suggestions]:
                node_name = candidate["node_name"]
                
                # 関連ノードを取得
                related_nodes = list(self.graph.neighbors(node_name))[:3]
                
                # 提案テキストを生成
                suggestion_text = f"'{node_name}'"
                if related_nodes:
                    suggestion_text += f" (関連: {', '.join(related_nodes)})"
                
                suggestions.append({
                    "node_name": node_name,
                    "suggestion_text": suggestion_text,
                    "score": candidate["score"],
                    "match_info": candidate["match_info"],
                    "related_nodes": related_nodes
                })
            
            return {
                "success": True,
                "original_query": query,
                "suggestions": suggestions,
                "total_candidates": len(candidates)
            }
        
        # expand_query呼び出し〜提案生成の複数処理をまとめてAPI応答（success/error）に変換するため意図的に広く捕捉
        except Exception as e:  # noqa: BLE001
            return {
                "success": False,
                "error": str(e),
                "original_query": query
            }