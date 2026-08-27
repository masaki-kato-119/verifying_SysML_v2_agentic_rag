"""
GraphRAG Workflow Engine
段階的なAPI呼び出しをテンプレート化したワークフローエンジン
"""
from typing import Dict, Optional

import networkx as nx

from .query_engine import GraphQueryEngine


class WorkflowEngine:
    """
    ワークフローエンジン
    
    段階的なAPI呼び出しをテンプレート化し、
    返却サイズを制御しながら効率的に情報を取得する
    """
    
    def __init__(self, graph: nx.DiGraph, chunk_storage=None):
        """
        ワークフローエンジンを初期化
        
        Args:
            graph: 検索対象のグラフ
            chunk_storage: チャンクストレージ（オプション）
        """
        self.query_engine = GraphQueryEngine(graph, chunk_storage=chunk_storage)
    
    def keyword_explore(
        self,
        keyword: str,
        max_nodes: int = 5,
        explore_depth: int = 1,
        explore_max_nodes: int = 10,
        max_source_chunks: int = 3,
        max_edges: Optional[int] = 20
    ) -> Dict:
        """
        keyword_exploreワークフロー
        
        1. search_nodes でノード同定
        2. explore_graph で関係探索（max_nodes制限付き）
        3. get_source_text で根拠取得（max_chunks制限付き）
        4. 結果を統合してサマリ生成
        
        Args:
            keyword: 検索キーワード
            max_nodes: 最大ノード数（検索結果）
            explore_depth: 探索深度
            explore_max_nodes: 探索時の最大ノード数
            max_source_chunks: ノードあたりの最大ソースチャンク数
            max_edges: 返却するエッジの最大数
        
        Returns:
            Dict: ワークフロー実行結果
        """
        # ステップ1: ノード同定
        matched_nodes = self.query_engine.search_nodes(keyword, max_results=max_nodes)
        
        if not matched_nodes:
            return {
                'success': True,
                'workflow': 'keyword_explore',
                'keyword': keyword,
                'matched_nodes': [],
                'explored_nodes': [],
                'edges': [],
                'source_texts': [],
                'summary': f"キーワード '{keyword}' にマッチするノードが見つかりませんでした",
                'node_count': 0,
                'edge_count': 0
            }
        
        # ステップ2: 関係探索
        all_explored_nodes = set()
        all_edges = []
        
        for matched in matched_nodes[:max_nodes]:
            node_name = matched['node']
            exploration = self.query_engine.explore_graph(
                node_name, 
                depth=explore_depth, 
                max_nodes=explore_max_nodes
            )
            
            if exploration['success']:
                all_explored_nodes.update(exploration['nodes'])
                all_edges.extend(exploration['edges'])
        
        # 重複を除去（エッジ数制限の前に行う。制限を先に適用すると、
        # 制限対象の先頭部分に重複が含まれる場合、本来残るはずの
        # 後方のユニークなエッジが誤って捨てられてしまう）
        unique_edges = []
        seen_edges = set()
        for edge in all_edges:
            edge_key = (edge['source'], edge['target'])
            if edge_key not in seen_edges:
                seen_edges.add(edge_key)
                unique_edges.append(edge)

        # エッジ数の制限
        if max_edges is not None and len(unique_edges) > max_edges:
            unique_edges = unique_edges[:max_edges]
        
        # ステップ3: 根拠取得
        source_texts = []
        for matched in matched_nodes[:max_nodes]:
            node_name = matched['node']
            texts = self.query_engine.get_source_text(node_name, max_chunks=max_source_chunks)
            if texts:
                source_texts.append({
                    'node': node_name,
                    'chunks': texts,
                    'chunk_count': len(texts)
                })
        
        # ステップ4: サマリ生成
        summary_lines = [
            f"キーワード '{keyword}' の検索結果:",
            f"- マッチしたノード数: {len(matched_nodes)}",
            f"- 探索されたノード数: {len(all_explored_nodes)}",
            f"- エッジ数: {len(unique_edges)}",
            f"- ソースチャンク数: {sum(len(st['chunks']) for st in source_texts)}"
        ]
        
        if matched_nodes:
            summary_lines.append("\nマッチしたノード:")
            for matched in matched_nodes[:5]:  # 最大5つまで
                summary_lines.append(f"  - {matched['node']} (スコア: {matched.get('score', 0.0):.2f})")
        
        if unique_edges:
            summary_lines.append("\n主要な関係:")
            for edge in unique_edges[:5]:  # 最大5つまで
                relation = edge.get('relation', 'unknown')
                summary_lines.append(f"  - {edge['source']} --[{relation}]--> {edge['target']}")
        
        summary = "\n".join(summary_lines)
        
        return {
            'success': True,
            'workflow': 'keyword_explore',
            'keyword': keyword,
            'matched_nodes': [m['node'] for m in matched_nodes],
            'matched_nodes_with_scores': [
                {
                    'node': m['node'],
                    'score': m.get('score', 0.0),
                    'match_type': m.get('match_type', 'unknown')
                }
                for m in matched_nodes
            ],
            'explored_nodes': list(all_explored_nodes),
            'edges': unique_edges,
            'source_texts': source_texts,
            'summary': summary,
            'node_count': len(all_explored_nodes),
            'edge_count': len(unique_edges)
        }

