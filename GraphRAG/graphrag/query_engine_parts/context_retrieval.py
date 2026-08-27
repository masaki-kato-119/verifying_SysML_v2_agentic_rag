"""context_retrievalのMixin。

graphrag.query_engine.GraphQueryEngine に多重継承で合成される。
単独では使わない(self.graph/self.cache等、本体側__init__の状態に依存する)。
"""

from __future__ import annotations

import logging
import re
from typing import Dict, List

from .. import config

logger = logging.getLogger(__name__)


class ContextRetrievalMixin:
    def get_context_for_query(
        self, 
        query: str, 
        max_context_nodes: int = 10
    ) -> Dict:
        """
        クエリに対するコンテキストを構築
        
        LLMが直接使える形式で返す
        
        Args:
            query: クエリ
            max_context_nodes: 最大コンテキストノード数
        
        Returns:
            Dict: コンテキスト情報
        """
        # クエリから関連ノードを検索
        query_result = self.query_graph(query, max_nodes=5, explore_depth=1)
        
        if not query_result['success'] or not query_result['matched_nodes']:
            return {
                'success': False,
                'error': 'クエリに関連するノードが見つかりませんでした'
            }
        
        # コンテキストを構築
        context_nodes = set(query_result['matched_nodes'])
        context_nodes.update(query_result['related_nodes'][:max_context_nodes])
        
        # ノードの詳細情報を取得
        node_details = []
        for node in list(context_nodes)[:max_context_nodes]:
            if node in self.graph.nodes():
                node_data = self.graph.nodes[node]
                neighbors = list(self.graph.neighbors(node))
                predecessors = list(self.graph.predecessors(node))
                
                node_details.append({
                    'node': node,
                    'attributes': dict(node_data),
                    'neighbors': neighbors,
                    'predecessors': predecessors
                })
        
        # コンテキストテキストを生成
        context_text = self._generate_context_text(node_details, query_result['edges'])
        
        return {
            'success': True,
            'query': query,
            'context_nodes': list(context_nodes)[:max_context_nodes],
            'node_details': node_details,
            'edges': query_result['edges'],
            'context_text': context_text,
            'node_count': len(node_details),
            'edge_count': len(query_result['edges'])
        }
    def _generate_context_text(self, node_details: List[Dict], edges: List[Dict]) -> str:
        """
        ノード詳細とエッジからコンテキストテキストを生成
        
        Args:
            node_details: ノード詳細のリスト
            edges: エッジのリスト
        
        Returns:
            str: コンテキストテキスト
        """
        lines = []
        
        # ノード情報
        for node_info in node_details:
            node_name = node_info['node']
            attrs = node_info['attributes']
            lines.append(f"ノード: {node_name}")
            
            if attrs.get('is_abstract'):
                lines.append("  - 抽象概念")
            if attrs.get('is_proper'):
                lines.append("  - 固有名詞")
        
        # 関係情報
        if edges:
            lines.append("\n関係:")
            for edge in edges[:10]:  # 最大10個の関係
                relation = edge.get('relation', 'unknown')
                lines.append(f"  - {edge['source']} --[{relation}]--> {edge['target']}")
        
        return "\n".join(lines)
    def get_source_text(self, node_name: str, max_chunks: int = 5) -> List[str]:
        """
        ノードに関連する元のテキストチャンクを取得
        
        Args:
            node_name: ノード名
            max_chunks: 最大チャンク数
        
        Returns:
            List[str]: 元のテキストチャンクのリスト
        """
        import logging
        logger = logging.getLogger(__name__)
        
        if not self.graph_id:
            logger.warning(f"get_source_text: graph_idが設定されていません。node_name={node_name}")
            return []
        
        logger.info(f"get_source_text: graph_id={self.graph_id}, node_name={node_name}, max_chunks={max_chunks}")
        
        # ノードに関連するチャンクIDを取得（SQLite3から）
        chunk_ids = self.chunk_storage.get_node_chunks(self.graph_id, node_name)
        logger.debug(f"get_source_text: chunk_ids={len(chunk_ids) if chunk_ids else 0}")
        
        # チャンクIDからテキストを取得（SQLite3から）
        if chunk_ids:
            chunks = self.chunk_storage.get_chunks(self.graph_id, chunk_ids[:max_chunks])
            logger.debug(f"get_source_text: 取得したチャンク数={len(chunks)}")
            
            # Phase 1: 目次チャンクをフィルタリング（既存グラフでも適用）
            filtered_chunks = []
            for chunk_text in chunks.values():
                if not config.is_table_of_contents(chunk_text):
                    filtered_chunks.append(chunk_text)
                else:
                    logger.debug(f"get_source_text: 目次チャンクを除外しました。node_name={node_name}")
            
            if filtered_chunks:
                return filtered_chunks
            else:
                logger.warning(f"get_source_text: すべてのチャンクが目次として除外されました。node_name={node_name}, graph_id={self.graph_id}")
        
        # チャンクが見つからない場合、ノード名の正規化やエイリアスを試す
        if not chunk_ids:
            # ノード名のバリエーションを生成
            node_variations = set()
            node_variations.add(node_name.lower())
            node_variations.add(node_name.replace(" ", ""))
            node_variations.add(node_name.replace("_", " "))
            node_variations.add(node_name.replace("-", " "))
            
            # 複数形/単数形の変換を試す（簡易版）
            if node_name.endswith('s') and len(node_name) > 1:
                node_variations.add(node_name[:-1])  # "actionusages" -> "actionusage"
            if not node_name.endswith('s') and len(node_name) > 1:
                node_variations.add(node_name + 's')  # "actionusage" -> "actionusages"
            
            # エイリアス辞書から候補を取得（より厳格な条件）
            # 注意: 特定のインスタンス名（例: "action as1", "a.6 action"）の場合は、
            # エイリアス検索をスキップして、より直接的なマッチングのみを試す
            is_instance_name = bool(re.search(r'\s+(as|aa|if|au)\d+', node_name.lower()) or 
                                   re.search(r'^[a-z]\.\d+\s+', node_name.lower()))
            
            if not is_instance_name and hasattr(config, 'SYSML_V2_ALIASES'):
                node_lower = node_name.lower()
                for alias, terms in config.SYSML_V2_ALIASES.items():
                    # より厳格な条件: 完全一致または、ノード名が用語の主要部分と一致する場合のみ
                    for t in terms:
                        t_lower = t.lower()
                        # 完全一致
                        if node_lower == t_lower:
                            node_variations.update([t_lower])
                            node_variations.update([t_lower.replace(" ", "")])
                        # ノード名が用語の主要部分（スペース区切りの最初の単語）と一致
                        elif ' ' in t_lower:
                            first_word = t_lower.split()[0]
                            if node_lower == first_word or node_lower.startswith(first_word + ' '):
                                node_variations.update([t_lower])
                                node_variations.update([t_lower.replace(" ", "")])
                        # 用語がノード名の主要部分と一致（逆方向）
                        elif ' ' in node_lower:
                            node_first_word = node_lower.split()[0]
                            if t_lower == node_first_word or t_lower.startswith(node_first_word):
                                node_variations.update([t_lower])
                                node_variations.update([t_lower.replace(" ", "")])
            
            # 各バリエーションでチャンクを検索（元のノード名は既に試したのでスキップ）
            for variation in node_variations:
                if variation == node_name:
                    continue  # 既に試したのでスキップ
                chunk_ids = self.chunk_storage.get_node_chunks(self.graph_id, variation)
                if chunk_ids:
                    chunks = self.chunk_storage.get_chunks(self.graph_id, chunk_ids[:max_chunks])
                    filtered_chunks = [chunk_text for chunk_text in chunks.values() 
                                     if not config.is_table_of_contents(chunk_text)]
                    if filtered_chunks:
                        logger.info(f"get_source_text: ノード名のバリエーション '{variation}' でチャンクを発見。node_name={node_name}")
                        return filtered_chunks
        
        logger.warning(f"get_source_text: チャンクが見つかりませんでした。node_name={node_name}, graph_id={self.graph_id}")
        return []
    def get_edge_source_text(self, source: str, target: str, max_chunks: int = 5) -> List[str]:
        """
        エッジに関連する元のテキストチャンクを取得
        
        Args:
            source: ソースノード名
            target: ターゲットノード名
            max_chunks: 最大チャンク数
        
        Returns:
            List[str]: 元のテキストチャンクのリスト
        """
        if not self.graph_id:
            return []
        
        # エッジに関連するチャンクIDを取得（SQLite3から）
        # self.graph_idは既に後方互換性を考慮して設定されているため、graph_filepathは不要
        chunk_ids = self.chunk_storage.get_edge_chunks(self.graph_id, source, target)
        
        # チャンクIDからテキストを取得（SQLite3から）
        if chunk_ids:
            chunks = self.chunk_storage.get_chunks(self.graph_id, chunk_ids[:max_chunks])
            # Phase 1: 目次チャンクをフィルタリング
            filtered_chunks = [chunk_text for chunk_text in chunks.values() 
                             if not config.is_table_of_contents(chunk_text)]
            return filtered_chunks
        
        return []
