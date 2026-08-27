"""path_findingのMixin。

graphrag.query_engine.GraphQueryEngine に多重継承で合成される。
単独では使わない(self.graph/self.cache等、本体側__init__の状態に依存する)。
"""

from __future__ import annotations

import logging
from typing import Dict, List, Optional, Set, Union

import networkx as nx

from .. import config

logger = logging.getLogger(__name__)


class PathFindingMixin:
    def _resolve_node_name(self, node_name: str, normalized: str):
        """指定された名前に対応する実際のグラフノードを返す（見つからなければ None）。

        正規化（小文字化＋記号除去）は多対一なので、同じキーへ潰れるノードが
        複数存在しうる。実際、目次のドットリーダー由来のゴミノード
        ``"model ........................"`` が ``"model"`` と同じキーになる。
        単純にループの最後の一致を採ると、こうしたゴミノードが選ばれてしまい、
        本来到達できるパスが「見つかりません」になる。

        優先順位:
          1. 完全一致（元の名前がそのままノードとして存在する）
          2. 正規化一致のうち最も短い名前（装飾の少ない素の語を選ぶ）
          3. スペース無視の正規化一致（連結スペル vs 分かち書きの表記ゆれ対応）

        3.の段は、グラフ構築時に "requirementusage"（BNF文法名由来の連結スペル）
        と "requirement usage"（地の文由来の分かち書き）が同一概念として統合され
        分かち書き側だけがノードとして残る場合（a4_graph_path_precision対応、
        ``GraphBuilder._merge_alias_duplicate_nodes`` 参照）に、利用者が連結
        スペルで問い合わせても解決できるようにするためのフォールバック。

        Args:
            node_name: 利用者が指定したノード名。
            normalized: ``normalize_node_name`` 済みの名前。

        Returns:
            グラフ上の実ノード名。該当なしの場合は None。
        """
        if self.graph.has_node(node_name):
            return node_name

        candidates = [
            node
            for node in self.graph.nodes()
            if config.normalize_node_name(str(node)) == normalized
        ]
        if candidates:
            return min(candidates, key=lambda n: (len(str(n)), str(n)))

        normalized_nospace = normalized.replace(" ", "")
        candidates = [
            node
            for node in self.graph.nodes()
            if config.normalize_node_name(str(node)).replace(" ", "") == normalized_nospace
        ]
        if candidates:
            return min(candidates, key=lambda n: (len(str(n)), str(n)))

        return None
    def find_path(
        self,
        start_node: str,
        end_node: str,
        relation_filter: Optional[Union[str, List[str]]] = None,
        max_depth: Optional[int] = None,
        exclude_stopwords: bool = True,
        node_type_filter: Optional[Set[str]] = None,
        min_path_quality: float = 0.3
    ) -> Dict:
        """
        2つのノード間のパスを探索
        
        Args:
            start_node: 開始ノード
            end_node: 終了ノード
            relation_filter: 関係タイプでフィルタ
            max_depth: 探索深度の上限（Noneの場合は制限なし）
            exclude_stopwords: ストップワードノードを除外（デフォルト: True）
            node_type_filter: 許可するノード種別（Noneの場合はすべて許可）
            min_path_quality: 最小パス品質スコア（0.0-1.0、デフォルト: 0.3）
        
        Returns:
            Dict: パス情報
        """
        # ノード名の正規化と存在確認
        from ..config import normalize_node_name
        
        # 正規化されたノード名で検索
        start_node_normalized = normalize_node_name(start_node)
        end_node_normalized = normalize_node_name(end_node)
        
        # グラフ内のノード名も正規化して比較
        actual_start_node = self._resolve_node_name(start_node, start_node_normalized)
        actual_end_node = self._resolve_node_name(end_node, end_node_normalized)

        if actual_start_node is None:
            # 類似ノード名を提示
            similar_nodes = [
                node for node in self.graph.nodes()
                if start_node_normalized in normalize_node_name(str(node))
            ][:3]
            similar_msg = f" (類似ノード: {similar_nodes})" if similar_nodes else ""
            return {
                'success': False,
                'error': f"開始ノード '{start_node}' (正規化: '{start_node_normalized}') が見つかりません{similar_msg}"
            }
        
        if actual_end_node is None:
            # 類似ノード名を提示
            similar_nodes = [
                node for node in self.graph.nodes()
                if end_node_normalized in normalize_node_name(str(node))
            ][:3]
            similar_msg = f" (類似ノード: {similar_nodes})" if similar_nodes else ""
            return {
                'success': False,
                'error': f"終了ノード '{end_node}' (正規化: '{end_node_normalized}') が見つかりません{similar_msg}"
            }
        
        # ストップワードチェック
        if exclude_stopwords:
            from .. import config
            if actual_start_node.lower() in config.STOPWORDS or actual_end_node.lower() in config.STOPWORDS:
                return {
                    'success': False,
                    'error': '開始ノードまたは終了ノードがストップワードです'
                }
        
        try:
            # 探索対象のグラフを準備
            search_graph = self.graph
            
            # 関係タイプでフィルタ（Phase 3: 複数関係タイプに対応）
            if relation_filter:
                # 関係フィルタをリストに変換
                if isinstance(relation_filter, str):
                    relation_filters = [relation_filter]
                else:
                    relation_filters = list(relation_filter)
                
                filtered_edges = [
                    (u, v) for u, v, d in self.graph.edges(data=True)
                    if d.get('relation') in relation_filters
                ]
                search_graph = nx.DiGraph(filtered_edges)
                if actual_start_node not in search_graph or actual_end_node not in search_graph:
                    return {
                        'success': False,
                        'error': f"関係タイプ {relation_filters} でフィルタした場合、パスが見つかりません"
                    }
            
            # 探索深度の制限がある場合
            if max_depth is not None:
                # BFSで探索深度を制限
                from collections import deque
                queue = deque([(actual_start_node, [actual_start_node])])
                visited = set()
                found_paths = []
                
                while queue:
                    current, path = queue.popleft()
                    
                    if len(path) > max_depth + 1:  # max_depthはエッジ数なので+1
                        continue
                    
                    if current == actual_end_node:
                        found_paths.append(path)
                        continue
                    
                    if current in visited:
                        continue
                    visited.add(current)
                    
                    # 隣接ノードを探索（Phase 3: ストップワードノードを経由しない）
                    for neighbor in search_graph.neighbors(current):
                        if neighbor not in path:  # 循環を避ける
                            # ストップワードノードを除外
                            if exclude_stopwords:
                                if neighbor.lower() in config.STOPWORDS:
                                    continue
                                if len(neighbor) < config.MIN_WORD_LENGTH:
                                    continue
                            
                            # ノード種別フィルタ
                            if node_type_filter is not None:
                                node_data = self.graph.nodes.get(neighbor, {})
                                node_type = node_data.get('type', 'unknown')
                                if node_type not in node_type_filter:
                                    continue
                            
                            queue.append((neighbor, path + [neighbor]))
                
                if not found_paths:
                    return {
                        'success': False,
                        'error': f"深度{max_depth}以内で '{start_node}' から '{end_node}' へのパスが見つかりません"
                    }
                
                # 最短パスを選択
                path = min(found_paths, key=len)
            else:
                # 最短パスを探索
                path = nx.shortest_path(search_graph, actual_start_node, actual_end_node)
            
            # パス品質スコアリング
            from ..path_scorer import PathScorer
            scorer = PathScorer(self.graph)
            path_score = scorer.score_path(
                path,
                exclude_stopwords=exclude_stopwords,
                node_type_filter=node_type_filter
            )
            
            # 品質スコアが基準を満たさない場合
            if path_score < min_path_quality:
                return {
                    'success': False,
                    'error': f"パスの品質スコア ({path_score:.2f}) が基準 ({min_path_quality:.2f}) を満たしません",
                    'path_score': path_score
                }
            
            # パス上のエッジ情報を取得
            path_edges = []
            for i in range(len(path) - 1):
                u, v = path[i], path[i + 1]
                edge_data = self.graph.get_edge_data(u, v, {})
                path_edges.append({
                    'source': u,
                    'target': v,
                    'relation': edge_data.get('relation', 'unknown'),
                    'data': edge_data
                })
            
            result = {
                'success': True,
                'start_node': start_node,
                'end_node': end_node,
                'path': path,
                'path_length': len(path) - 1,
                'edges': path_edges,
                'path_score': path_score
            }
            
            # Phase 4: 探索履歴による最適化 - パスを記録
            self.exploration_optimizer.record_path(
                start_node=actual_start_node,
                end_node=actual_end_node,
                path=path,
                success=True,
                quality_score=path_score
            )
            
            return result
        except nx.NetworkXNoPath:
            return {
                'success': False,
                'error': f"'{start_node}' から '{end_node}' へのパスが見つかりません"
            }

    @staticmethod
    def query_multiple_graphs(
        graphs: List[nx.DiGraph],
        query: str,
        max_nodes_per_graph: int = 10,
        explore_depth: int = 1
    ) -> Dict:
        """
        複数のグラフから横断的に検索
        
        Args:
            graphs: 検索対象のグラフのリスト
            query: 検索クエリ
            max_nodes_per_graph: グラフあたりの最大ノード数
            explore_depth: マッチしたノードからの探索深度
        
        Returns:
            Dict: 統合された検索結果
        """
        all_matched_nodes = []
        all_related_nodes = set()
        all_edges = []
        graph_results = []
        
        # 各グラフに対してQueryEngineを作成（chunk_storageは各グラフのgraph_filepathから取得）
        for i, graph in enumerate(graphs):
            # graph_filepathからchunk_storageを取得（可能な場合）
            graph_filepath = graph.graph.get('graph_filepath')
            chunk_storage = None
            if graph_filepath:
                # デフォルトのChunkStorageを使用（各グラフのgraph_filepathから自動的に取得）
                from ..chunk_storage import ChunkStorage
                chunk_storage = ChunkStorage()
            from ..query_engine import GraphQueryEngine  # 循環import回避のため遅延import

            query_engine = GraphQueryEngine(graph, chunk_storage=chunk_storage)
            result = query_engine.query_graph(query, max_nodes=max_nodes_per_graph, explore_depth=explore_depth)
            
            if result['success']:
                graph_results.append({
                    'graph_index': i,
                    'matched_nodes': result.get('matched_nodes', []),
                    'related_nodes': result.get('related_nodes', []),
                    'edge_count': result.get('edge_count', 0)
                })
                
                all_matched_nodes.extend(result.get('matched_nodes', []))
                all_related_nodes.update(result.get('related_nodes', []))
                all_edges.extend(result.get('edges', []))
        
        # 重複を除去
        unique_matched_nodes = list(set(all_matched_nodes))
        unique_edges = []
        seen_edges = set()
        for edge in all_edges:
            edge_key = (edge.get('source'), edge.get('target'))
            if edge_key not in seen_edges:
                seen_edges.add(edge_key)
                unique_edges.append(edge)
        
        return {
            'success': True,
            'query': query,
            'num_graphs': len(graphs),
            'matched_nodes': unique_matched_nodes,
            'related_nodes': list(all_related_nodes),
            'edges': unique_edges,
            'node_count': len(all_related_nodes),
            'edge_count': len(unique_edges),
            'graph_results': graph_results
        }
