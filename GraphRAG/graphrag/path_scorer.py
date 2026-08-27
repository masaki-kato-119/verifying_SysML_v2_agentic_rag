"""
パス品質スコアリングモジュール
パスの意味的妥当性を評価する
"""
from typing import List, Optional, Set

import networkx as nx

from . import config


class PathScorer:
    """
    パス品質スコアラー
    
    パスの意味的妥当性を評価し、スコアを計算する
    """
    
    def __init__(self, graph: nx.DiGraph):
        """
        パススコアラーを初期化
        
        Args:
            graph: 評価対象のグラフ
        """
        self.graph = graph
        
        # ノード重要度スコア（出現頻度・接続数に基づく）
        self._node_importance_cache = {}
        self._calculate_node_importance()
        
        # 関係タイプ重要度スコア
        self.relation_importance = {
            'specializes': 1.0,
            'contains': 0.9,
            'is-a': 0.8,
            'part-of': 0.8,
            'depends-on': 0.7,
            'satisfies': 0.7,
            'uses': 0.6,
            'unknown': 0.3
        }
    
    def _calculate_node_importance(self):
        """ノード重要度を計算（接続数に基づく）"""
        for node in self.graph.nodes():
            # 接続数（入次数 + 出次数）に基づく重要度
            in_degree = self.graph.in_degree(node)
            out_degree = self.graph.out_degree(node)
            degree = in_degree + out_degree
            
            # 正規化（0.0-1.0の範囲）
            # 最大接続数を100と仮定（実際のグラフに応じて調整可能）
            max_degree = 100
            importance = min(degree / max_degree, 1.0) if max_degree > 0 else 0.0
            
            self._node_importance_cache[node] = importance
    
    def score_path(
        self,
        path: List[str],
        exclude_stopwords: bool = True,
        node_type_filter: Optional[Set[str]] = None
    ) -> float:
        """
        パスの品質スコアを計算
        
        Args:
            path: パス（ノード名のリスト）
            exclude_stopwords: ストップワードを含む場合にペナルティを適用
            node_type_filter: 許可するノード種別（Noneの場合はすべて許可）
        
        Returns:
            float: パスの品質スコア（0.0-1.0）
        """
        if len(path) < 2:
            return 0.0
        
        # ノード重要度スコアの平均
        node_scores = []
        for node in path:
            # ノード種別フィルタ
            if node_type_filter is not None:
                node_data = self.graph.nodes.get(node, {})
                node_type = node_data.get('type', 'unknown')
                if node_type not in node_type_filter:
                    return 0.0  # フィルタに合わない場合は0点
            
            # ストップワードチェック
            if exclude_stopwords:
                if node.lower() in config.STOPWORDS:
                    return 0.0  # ストップワードを含む場合は0点
            
            # ノード重要度
            importance = self._node_importance_cache.get(node, 0.5)
            node_scores.append(importance)
        
        avg_node_score = sum(node_scores) / len(node_scores) if node_scores else 0.0
        
        # 関係タイプ重要度スコアの平均
        relation_scores = []
        for i in range(len(path) - 1):
            u, v = path[i], path[i + 1]
            edge_data = self.graph.get_edge_data(u, v, {})
            relation = edge_data.get('relation', 'unknown')
            importance = self.relation_importance.get(relation, 0.5)
            relation_scores.append(importance)
        
        avg_relation_score = sum(relation_scores) / len(relation_scores) if relation_scores else 0.0
        
        # パス長ペナルティ（長いパスほどスコア減）
        path_length_penalty = 1.0 / (1.0 + (len(path) - 2) * 0.1)  # パス長が長いほど減点
        
        # 総合スコア（ノード重要度40%、関係重要度40%、パス長20%）
        total_score = (
            avg_node_score * 0.4 +
            avg_relation_score * 0.4 +
            path_length_penalty * 0.2
        )
        
        return total_score
    
    def filter_paths_by_quality(
        self,
        paths: List[List[str]],
        min_quality: float = 0.3,
        exclude_stopwords: bool = True,
        node_type_filter: Optional[Set[str]] = None
    ) -> List[tuple[List[str], float]]:
        """
        パスを品質スコアでフィルタリング
        
        Args:
            paths: パスのリスト
            min_quality: 最小品質スコア
            exclude_stopwords: ストップワードを含むパスを除外
            node_type_filter: 許可するノード種別
        
        Returns:
            List[tuple[List[str], float]]: (パス, スコア)のリスト（スコア順）
        """
        scored_paths = []
        for path in paths:
            score = self.score_path(
                path,
                exclude_stopwords=exclude_stopwords,
                node_type_filter=node_type_filter
            )
            if score >= min_quality:
                scored_paths.append((path, score))
        
        # スコア順にソート（降順）
        scored_paths.sort(key=lambda x: x[1], reverse=True)
        return scored_paths

