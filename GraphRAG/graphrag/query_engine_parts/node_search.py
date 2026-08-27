"""node_searchのMixin。

graphrag.query_engine.GraphQueryEngine に多重継承で合成される。
単独では使わない(self.graph/self.cache等、本体側__init__の状態に依存する)。
"""

from __future__ import annotations

import logging
import re
from typing import Dict, List, Optional

from .. import config

logger = logging.getLogger(__name__)


class NodeSearchMixin:
    def _calculate_node_score(self, node: str, keyword: str, match_type: str) -> float:
        """
        ノードの検索スコアを計算（ルールベース）
        
        Args:
            node: ノード名
            keyword: 検索キーワード
            match_type: マッチタイプ（'exact', 'partial', 'alias'）
        
        Returns:
            float: スコア（0.0-1.0）
        """
        score = 0.0
        
        # マッチタイプによる基本スコア（完全一致と部分一致を明確に差別化）
        if match_type == 'exact':
            score = 1.0
        elif match_type == 'partial':
            # 部分一致の場合は、一致度に応じてスコアを調整
            keyword_len = len(keyword)
            node_len = len(node)
            # 一致度を計算（キーワードがノード名に占める割合）
            match_ratio = keyword_len / max(node_len, 1)
            # 部分一致の基本スコアを0.3に下げる（以前は0.5）
            score = 0.2 + (match_ratio * 0.3)  # 0.2-0.5の範囲
        elif match_type == 'alias':
            score = 0.4  # エイリアスは部分一致より少し高く（以前は0.6）
        
        # ノードの重要度（degree）を考慮（重みを下げる）
        degree = self.graph.degree(node)
        all_degrees = [self.graph.degree(n) for n in self.graph.nodes()]
        max_degree = max(all_degrees) if all_degrees else 1
        if max_degree > 0:
            degree_score = min(degree / max_degree, 1.0) * 0.2  # 0.3から0.2に下げる
        else:
            degree_score = 0.0
        
        # 最終スコア
        final_score = score + degree_score
        return min(final_score, 1.0)
    def search_nodes(self, keyword: str, max_results: int = 10, use_query_expansion: bool = True) -> List[Dict]:
        """
        ノード名のキーワード検索（エイリアス対応、スコアリング付き）
        
        Args:
            keyword: 検索キーワード
            max_results: 最大結果数
            use_query_expansion: クエリ拡張を使用するか
        
        Returns:
            List[Dict]: マッチしたノードのリスト（スコア付き）
        """
        
        # クエリ拡張
        expanded_queries = [keyword]
        if use_query_expansion:
            expanded_queries = self._expand_query(keyword, use_llm=False)
        
        results = []
        seen_nodes = set()
        
        # 最小文字数制限（1文字や2文字のノードを除外）
        MIN_KEYWORD_LENGTH = 3
        
        for query in expanded_queries:
            query_lower = query.lower().strip()
            # クエリが短すぎる場合はスキップ
            if len(query_lower) < MIN_KEYWORD_LENGTH:
                continue
                
            keyword_words = [w for w in query_lower.split() if len(w) >= MIN_KEYWORD_LENGTH]
            
            # キーワードが1つもない場合はスキップ
            if not keyword_words:
                continue
            
            for node in self.graph.nodes():
                if node in seen_nodes:
                    continue
                
                # ノードの有効性をチェック（ストップワードや部分一致ノードを除外）
                from ..config import is_valid_node_name
                if not is_valid_node_name(str(node)):
                    continue
                
                node_lower = str(node).lower()
                # ノード名が短すぎる場合はスキップ（1文字や2文字のノードを除外）
                if len(node_lower) < MIN_KEYWORD_LENGTH:
                    continue
                
                match_type = None
                score = 0.0
                
                # 完全一致
                if query_lower == node_lower:
                    match_type = 'exact'
                    score = self._calculate_node_score(node, query, 'exact')
                # 部分一致（単語境界を考慮）
                elif len(keyword_words) == 1:
                    # 単一キーワードの場合
                    word = keyword_words[0]
                    # 単語境界を考慮したマッチング
                    pattern = r'\b' + re.escape(word) + r'\b'
                    if re.search(pattern, node_lower):
                        match_type = 'partial'
                        score = self._calculate_node_score(node, query, 'partial')
                    # 単語境界なしの部分一致（フォールバック）
                    elif word in node_lower:
                        match_type = 'partial'
                        score = self._calculate_node_score(node, query, 'partial') * 0.8  # スコアを下げる
                # 複数キーワードの場合、すべてのキーワードが含まれているか確認（AND条件）
                elif len(keyword_words) > 1:
                    # すべてのキーワードが含まれているか確認
                    all_words_match = all(
                        re.search(r'\b' + re.escape(word) + r'\b', node_lower) 
                        for word in keyword_words
                    )
                    if all_words_match:
                        match_type = 'partial'
                        # 複数キーワードのマッチはスコアを高く設定
                        base_score = self._calculate_node_score(node, query, 'partial')
                        # マッチしたキーワード数に応じてスコアを調整
                        match_ratio = len(keyword_words) / max(len(query_lower.split()), 1)
                        score = base_score * (0.7 + 0.3 * match_ratio)
                    # 一部のキーワードが含まれている場合（フォールバック）
                    elif any(
                        re.search(r'\b' + re.escape(word) + r'\b', node_lower)
                        for word in keyword_words
                    ):
                        match_type = 'partial'
                        # 一部マッチの場合はスコアを低く設定
                        score = self._calculate_node_score(node, query, 'partial') * 0.5
                
                if match_type:
                    node_data = self.graph.nodes[node]
                    results.append({
                        'node': node,
                        'attributes': dict(node_data),
                        'degree': self.graph.degree(node),
                        'score': score,
                        'match_type': match_type
                    })
                    seen_nodes.add(node)
        
        # スコアでソート
        results.sort(key=lambda x: x['score'], reverse=True)
        return results[:max_results]
    def get_related_nodes(
        self, 
        node_name: str, 
        relation_type: Optional[str] = None,
        max_depth: int = 1
    ) -> Dict:
        """
        特定ノードに関連するノードを取得
        
        Args:
            node_name: 起点ノード名
            relation_type: 関係タイプでフィルタ（Noneの場合はすべて）
            max_depth: 探索深度
        
        Returns:
            Dict: 関連ノードとその関係
        """
        if node_name not in self.graph.nodes():
            return {
                'success': False,
                'error': f"ノード '{node_name}' が見つかりません"
            }
        
        related_nodes = set()
        edges = []
        
        # 直接接続されたノードを取得
        for neighbor in self.graph.neighbors(node_name):
            edge_data = self.graph.get_edge_data(node_name, neighbor, {})
            relation = edge_data.get('relation', 'unknown')
            
            if relation_type is None or relation == relation_type:
                related_nodes.add(neighbor)
                edges.append({
                    'source': node_name,
                    'target': neighbor,
                    'relation': relation,
                    'data': edge_data
                })
        
        # 逆方向の関係も取得
        for predecessor in self.graph.predecessors(node_name):
            edge_data = self.graph.get_edge_data(predecessor, node_name, {})
            relation = edge_data.get('relation', 'unknown')
            
            if relation_type is None or relation == relation_type:
                related_nodes.add(predecessor)
                edges.append({
                    'source': predecessor,
                    'target': node_name,
                    'relation': relation,
                    'data': edge_data
                })
        
        # ストップワードノードを含むエッジを除外
        filtered_edges = []
        for edge in edges:
            source = edge.get('source', '')
            target = edge.get('target', '')
            
            # ストップワードノードを含むエッジを除外
            if source.lower() in config.STOPWORDS or target.lower() in config.STOPWORDS:
                continue
            
            # 短語ノードを含むエッジを除外
            if len(source) < config.MIN_WORD_LENGTH or len(target) < config.MIN_WORD_LENGTH:
                continue
            
            filtered_edges.append(edge)
        
        return {
            'success': True,
            'start_node': node_name,
            'related_nodes': list(related_nodes),
            'edges': filtered_edges,
            'count': len(related_nodes)
        }
    def explore_graph(
        self, 
        start_node: str, 
        depth: int = 2,
        max_nodes: int = 50
    ) -> Dict:
        """
        特定ノードから指定深度まで探索
        
        Args:
            start_node: 起点ノード名
            depth: 探索深度
            max_nodes: 最大ノード数
        
        Returns:
            Dict: 探索結果（サブグラフ）
        """
        if start_node not in self.graph.nodes():
            return {
                'success': False,
                'error': f"ノード '{start_node}' が見つかりません"
            }
        
        visited = set()
        nodes_to_explore = [(start_node, 0)]
        subgraph_nodes = set()
        subgraph_edges = []
        
        while nodes_to_explore and len(subgraph_nodes) < max_nodes:
            current_node, current_depth = nodes_to_explore.pop(0)
            
            if current_node in visited or current_depth > depth:
                continue
            
            visited.add(current_node)
            subgraph_nodes.add(current_node)
            
            if current_depth < depth:
                # 隣接ノードを探索
                for neighbor in self.graph.neighbors(current_node):
                    if neighbor not in visited:
                        nodes_to_explore.append((neighbor, current_depth + 1))
                        edge_data = self.graph.get_edge_data(current_node, neighbor, {})
                        subgraph_edges.append({
                            'source': current_node,
                            'target': neighbor,
                            'relation': edge_data.get('relation', 'unknown'),
                            'data': edge_data
                        })
                
                # 逆方向も探索
                for predecessor in self.graph.predecessors(current_node):
                    if predecessor not in visited:
                        nodes_to_explore.append((predecessor, current_depth + 1))
                        edge_data = self.graph.get_edge_data(predecessor, current_node, {})
                        subgraph_edges.append({
                            'source': predecessor,
                            'target': current_node,
                            'relation': edge_data.get('relation', 'unknown'),
                            'data': edge_data
                        })
        
        # ストップワードノードを含むエッジを除外
        filtered_edges = []
        for edge in subgraph_edges:
            source = edge.get('source', '')
            target = edge.get('target', '')
            
            # ストップワードノードを含むエッジを除外
            if source.lower() in config.STOPWORDS or target.lower() in config.STOPWORDS:
                continue
            
            # 短語ノードを含むエッジを除外
            if len(source) < config.MIN_WORD_LENGTH or len(target) < config.MIN_WORD_LENGTH:
                continue
            
            filtered_edges.append(edge)
        
        return {
            'success': True,
            'start_node': start_node,
            'depth': depth,
            'nodes': list(subgraph_nodes),
            'edges': filtered_edges,
            'node_count': len(subgraph_nodes),
            'edge_count': len(filtered_edges)
        }
    def query_graph(
        self, 
        query: str, 
        max_nodes: int = 10,
        explore_depth: int = 1,
        use_query_expansion: bool = True,
        max_source_chunks: int = 3,
        max_edges: Optional[int] = None,
        explore_max_nodes: int = 20,
        use_cache: bool = True
    ) -> Dict:
        """
        クエリに対してグラフから関連ノードを検索（スコアリング付き）
        
        Args:
            query: 検索クエリ
            max_nodes: 最大ノード数
            explore_depth: マッチしたノードからの探索深度
            use_query_expansion: クエリ拡張を使用するか
            max_source_chunks: ノードあたりの最大ソースチャンク数（デフォルト: 3）
            max_edges: 返却するエッジの最大数（Noneの場合は制限なし）
            explore_max_nodes: 探索時の最大ノード数（デフォルト: 20）
            use_cache: キャッシュを使用するか（デフォルト: True）
        
        Returns:
            Dict: 検索結果（スコア付き）
        """
        # キャッシュから取得を試みる
        if use_cache:
            cache_key_params = {
                'max_nodes': max_nodes,
                'explore_depth': explore_depth,
                'use_query_expansion': use_query_expansion,
                'max_source_chunks': max_source_chunks,
                'max_edges': max_edges,
                'explore_max_nodes': explore_max_nodes
            }
            cached_result = self.cache.get_query_result(query, **cache_key_params)
            if cached_result is not None:
                return cached_result
        
        # Phase 4: クエリパターンからの学習 - 提案を取得
        query_suggestions = self.query_learner.get_query_suggestions(query)
        if query_suggestions and query_suggestions.get('suggested_expansions'):
            # 学習した拡張を使用
            expanded_queries = query_suggestions['suggested_expansions']
        else:
            expanded_queries = []
        
        # キーワード検索（エイリアス対応、スコアリング付き）
        import time
        start_time = time.time()
        matched_nodes = self.search_nodes(query, max_results=max_nodes, use_query_expansion=use_query_expansion)
        response_time = time.time() - start_time
        
        # Phase 2: マッチしない場合はエントリーファインダーを使用
        if not matched_nodes:
            try:
                entry_points = self.entry_finder.find_entry_points(query, max_entries=max_nodes)
                if entry_points:
                    # エントリーポイントをmatched_nodes形式に変換
                    matched_nodes = [
                        {
                            'node': ep,
                            'score': 0.7,  # エントリーポイントのスコア
                            'match_type': 'entry_point'
                        }
                        for ep in entry_points
                    ]
            # entry_finderへの委譲呼び出し。内部実装（キーワード抽出/概念階層/networkx中心性計算など）が
            # 将来変更されても検索フロー全体を壊さないよう、失敗時はログのみでフォールバックする意図的な広い捕捉。
            except Exception as e:  # noqa: BLE001
                import logging
                logger = logging.getLogger(__name__)
                logger.warning(f"エントリーファインダーの使用中にエラーが発生しました: {e}")
        
        if not matched_nodes:
            return {
                'success': True,
                'query': query,
                'matched_nodes': [],
                'matched_nodes_with_scores': [],
                'matched_nodes_with_text': [],
                'related_nodes': [],
                'edges': [],
                'node_count': 0,
                'edge_count': 0,
                'message': 'マッチするノードが見つかりませんでした'
            }
        
        # マッチしたノードから探索
        all_related_nodes = set()
        all_edges = []
        
        for matched in matched_nodes:
            node_name = matched['node']
            exploration = self.explore_graph(node_name, depth=explore_depth, max_nodes=explore_max_nodes)
            
            if exploration['success']:
                all_related_nodes.update(exploration['nodes'])
                all_edges.extend(exploration['edges'])
        
        # 重複を除去し、ストップワードノードを含むエッジを除外
        unique_edges = []
        seen_edges = set()
        for edge in all_edges:
            source = edge.get('source', '')
            target = edge.get('target', '')
            
            # ストップワードノードを含むエッジを除外
            if source.lower() in config.STOPWORDS or target.lower() in config.STOPWORDS:
                continue
            
            # 短語ノードを含むエッジを除外
            if len(source) < config.MIN_WORD_LENGTH or len(target) < config.MIN_WORD_LENGTH:
                continue
            
            edge_key = (source, target)
            if edge_key not in seen_edges:
                seen_edges.add(edge_key)
                unique_edges.append(edge)
        
        # エッジ数の制限
        if max_edges is not None and len(unique_edges) > max_edges:
            unique_edges = unique_edges[:max_edges]
        
        # 検索結果にスコアを含める
        matched_nodes_with_scores = [
            {
                'node': m['node'],
                'score': m.get('score', 0.0),
                'match_type': m.get('match_type', 'unknown')
            }
            for m in matched_nodes
        ]
        
        # 検索結果に元のテキストの抜粋を含める
        matched_nodes_with_text = []
        for m in matched_nodes:
            node_name = m['node']
            source_texts = self.get_source_text(node_name, max_chunks=max_source_chunks)
            
            # Phase 2: 標識情報を追加
            signage = self.signage_manager.get_signage(node_name)
            
            matched_nodes_with_text.append({
                'node': node_name,
                'score': m.get('score', 0.0),
                'match_type': m.get('match_type', 'unknown'),
                'source_texts': source_texts,  # max_source_chunksで制限済み
                'signage': signage  # 標識情報
            })
        
        result = {
            'success': True,
            'query': query,
            'matched_nodes': [m['node'] for m in matched_nodes],
            'matched_nodes_with_scores': matched_nodes_with_scores,
            'matched_nodes_with_text': matched_nodes_with_text,
            'related_nodes': list(all_related_nodes),
            'edges': unique_edges,
            'node_count': len(all_related_nodes),
            'edge_count': len(unique_edges)
        }
        
        # キャッシュに保存
        if use_cache:
            cache_key_params = {
                'max_nodes': max_nodes,
                'explore_depth': explore_depth,
                'use_query_expansion': use_query_expansion,
                'max_source_chunks': max_source_chunks,
                'max_edges': max_edges,
                'explore_max_nodes': explore_max_nodes
            }
            self.cache.set_query_result(query, result, **cache_key_params)
        
        # Phase 4: クエリパターンからの学習 - クエリを記録
        matched_node_names = [m['node'] for m in matched_nodes] if matched_nodes else []
        success = result.get('success', False) and len(matched_node_names) > 0
        self.query_learner.record_query(
            query=query,
            expanded_queries=expanded_queries if expanded_queries else [query],
            matched_nodes=matched_node_names,
            success=success,
            response_time=response_time
        )
        
        return result
