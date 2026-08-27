"""semantic_delegationのMixin。

graphrag.query_engine.GraphQueryEngine に多重継承で合成される。
単独では使わない(self.graph/self.cache等、本体側__init__の状態に依存する)。
"""

from __future__ import annotations

import logging
from typing import Dict, Optional

logger = logging.getLogger(__name__)


class SemanticDelegationMixin:
    def _get_semantic_entry_finder(self):
        """セマンティックエントリーファインダーを取得（遅延初期化）"""
        if self._semantic_entry_finder is None:
            from ..semantic_entry_finder import SemanticEntryFinder
            self._semantic_entry_finder = SemanticEntryFinder(
                graph=self.graph,
                chunk_storage=self.chunk_storage
            )
        return self._semantic_entry_finder
    def _get_node_summarizer(self):
        """ノード要約機能を取得（遅延初期化）"""
        if self._node_summarizer is None:
            from ..node_summarizer import NodeSummarizer
            self._node_summarizer = NodeSummarizer(
                graph=self.graph,
                chunk_storage=self.chunk_storage,
                llm_client=self.llm_client
            )
        return self._node_summarizer
    def _get_semantic_path_finder(self):
        """セマンティック・パスファインダーを取得（遅延初期化）"""
        if self._semantic_path_finder is None:
            from ..semantic_path_finder import SemanticPathFinder
            self._semantic_path_finder = SemanticPathFinder(
                graph=self.graph,
                graph_query_engine=self,
                llm_client=self.llm_client
            )
        return self._semantic_path_finder
    def smart_search(self, query: str, search_type: str = "auto") -> Dict:
        """
        スマート検索（Phase 5統合機能）
        
        Args:
            query: 自然言語クエリ
            search_type: 検索タイプ（auto/semantic/traditional）
        
        Returns:
            Dict: 統合検索結果
        """
        import time
        
        result = {
            'query': query,
            'search_type': search_type,
            'timestamp': time.time()
        }
        
        # 1. セマンティックエントリーポイント発見
        try:
            semantic_finder = self._get_semantic_entry_finder()
            semantic_entries = semantic_finder.find_semantic_entry_points(query, max_entries=3)
            result['semantic_entries'] = semantic_entries
        # semantic_entry_finderはembeddingモデル（sentence-transformers/numpy等）に依存し、
        # 失敗モードを網羅できないため意図的に広く捕捉し、従来検索へのフォールバックを優先する。
        except Exception as e:  # noqa: BLE001
            logger.warning(f"セマンティックエントリーポイント発見エラー: {e}")
            result['semantic_entries'] = []
        
        # 2. 最適なエントリーポイントを選択
        if result['semantic_entries']:
            best_entry = result['semantic_entries'][0]['node']
            
            # 3. ノード要約生成
            try:
                summarizer = self._get_node_summarizer()
                summary = summarizer.summarize_node(best_entry, "overview")
                result['summary'] = summary
            # NodeSummarizerはllm_client（OpenAI API等）を呼び得るため失敗モードが多様。
            # 意図的に広く捕捉し、要約なしでも全体結果を返せるようにする。
            except Exception as e:  # noqa: BLE001
                logger.warning(f"ノード要約生成エラー: {e}")
                result['summary'] = None
            
            # 4. 関連ノード探索
            try:
                related_nodes = self.explore_graph(
                    best_entry, 
                    depth=2, 
                    max_nodes=5
                )
                result['related_nodes'] = related_nodes
            # explore_graphは他Mixin経由でグラフ探索・エントリーファインダー等に委譲しており、
            # 失敗モードを一意に絞れないため意図的に広く捕捉し、この一部機能の失敗で全体を落とさない。
            except Exception as e:  # noqa: BLE001
                logger.warning(f"関連ノード探索エラー: {e}")
                result['related_nodes'] = None
        else:
            # セマンティックエントリーポイントが見つからない場合、従来の検索を使用
            try:
                traditional_result = self.query_graph(query, max_nodes=5, explore_depth=2)
                result['traditional_search'] = traditional_result
            # query_graphは複数のMixin（エントリーファインダー/クエリ拡張等）へ委譲する複合処理で、
            # 失敗モードを網羅できないため意図的に広く捕捉し、smart_search全体の失敗を避ける。
            except Exception as e:  # noqa: BLE001
                logger.warning(f"従来の検索エラー: {e}")
                result['traditional_search'] = None
        
        return result
    def find_relationship(self, concept1: str, concept2: str) -> Dict:
        """
        概念間の関係性を発見（Phase 5機能）
        
        Args:
            concept1: 概念1
            concept2: 概念2
        
        Returns:
            Dict: 関係性情報
        """
        try:
            path_finder = self._get_semantic_path_finder()
            return path_finder.find_semantic_path(concept1, concept2)
        # SemanticPathFinderはllm_client（OpenAI API等）を呼び得るため失敗モードが多様。
        # 意図的に広く捕捉し、エラー情報を含む結果として返す。
        except Exception as e:  # noqa: BLE001
            logger.error(f"関係性発見エラー: {e}")
            return {
                "type": "error",
                "error": str(e),
                "confidence": 0.0
            }
    def explain_concept(self, concept: str, detail_level: str = "overview") -> Dict:
        """
        概念の説明生成（Phase 5機能）
        
        Args:
            concept: 概念名
            detail_level: 詳細レベル（overview/detailed/technical）
        
        Returns:
            Dict: 説明情報
        """
        try:
            summarizer = self._get_node_summarizer()
            return summarizer.summarize_node(concept, detail_level)
        # NodeSummarizerはllm_client（OpenAI API等）を呼び得るため失敗モードが多様。
        # 意図的に広く捕捉し、エラー情報を含む結果として返す。
        except Exception as e:  # noqa: BLE001
            logger.error(f"概念説明生成エラー: {e}")
            return {
                'node': concept,
                'summary': f"説明の生成中にエラーが発生しました: {str(e)}",
                'summary_type': detail_level,
                'error': str(e)
            }
    def search_with_auto_expansion(
        self,
        query: str,
        max_nodes: int = 10,
        explore_depth: int = 1,
        max_source_chunks: int = 3,
        max_edges: Optional[int] = None,
        explore_max_nodes: int = 20,
        expansion_min_score: float = 0.5,
        use_fuzzy_matching: bool = True
    ) -> Dict:
        """
        自動クエリ拡張を使用した検索
        
        Args:
            query: 自然文クエリ
            max_nodes: 最大ノード数
            explore_depth: 探索深度
            max_source_chunks: ノードあたりの最大ソースチャンク数
            max_edges: 返却するエッジの最大数
            explore_max_nodes: 探索時の最大ノード数
            expansion_min_score: 拡張時の最小スコア
            use_fuzzy_matching: ファジーマッチングを使用するか
        
        Returns:
            dict: 検索結果（拡張情報を含む）
        """
        try:
            # 1. クエリを拡張
            expansion_result = self.expand_query_enhanced(
                query=query,
                max_candidates=5,
                min_score=expansion_min_score,
                use_fuzzy_matching=use_fuzzy_matching
            )
            
            if not expansion_result["success"]:
                # 拡張に失敗した場合は元のクエリで検索
                search_result = self.query_graph(
                    query=query,
                    max_nodes=max_nodes,
                    explore_depth=explore_depth,
                    max_source_chunks=max_source_chunks,
                    max_edges=max_edges,
                    explore_max_nodes=explore_max_nodes
                )
                search_result["expansion_used"] = False
                search_result["expansion_error"] = expansion_result.get("error")
                return search_result
            
            # 2. 拡張された用語で検索
            candidates = expansion_result["candidates"]
            if not candidates:
                # 候補が見つからない場合は元のクエリで検索
                search_result = self.query_graph(
                    query=query,
                    max_nodes=max_nodes,
                    explore_depth=explore_depth,
                    max_source_chunks=max_source_chunks,
                    max_edges=max_edges,
                    explore_max_nodes=explore_max_nodes
                )
                search_result["expansion_used"] = False
                search_result["expansion_candidates"] = []
                return search_result
            
            # 3. 最高スコアの候補を使用して検索
            best_candidate = candidates[0]
            expanded_query = best_candidate["node_name"]
            
            search_result = self.query_graph(
                query=expanded_query,
                max_nodes=max_nodes,
                explore_depth=explore_depth,
                max_source_chunks=max_source_chunks,
                max_edges=max_edges,
                explore_max_nodes=explore_max_nodes
            )
            
            # 拡張情報を追加
            search_result["expansion_used"] = True
            search_result["original_query"] = query
            search_result["expanded_query"] = expanded_query
            search_result["expansion_candidates"] = candidates
            search_result["expansion_score"] = best_candidate["score"]
            
            return search_result

        # expand_query_enhanced/query_graphは複数Mixin（クエリ拡張・エントリーファインダー等）へ
        # 委譲する複合処理で、失敗モードを網羅できないため意図的に広く捕捉しエラー結果を返す。
        except Exception as e:  # noqa: BLE001
            return {
                "success": False,
                "error": str(e),
                "expansion_used": False,
                "original_query": query
            }
