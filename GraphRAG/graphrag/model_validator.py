"""
SysMLモデル検証機能（Phase 4）
SysMLモデルとの意味的比較、制約違反の自動検出、仕様書との整合性チェック
"""
from typing import Any, Dict, List, Optional

import networkx as nx

from .chunk_storage import ChunkStorage
from .query_engine import GraphQueryEngine


class SysMLModelValidator:
    """
    SysMLモデル検証器
    
    GraphRAGシステムを使用してSysMLモデルを検証する機能
    """
    
    def __init__(
        self,
        graph: nx.DiGraph,
        query_engine: Optional[GraphQueryEngine] = None,
        chunk_storage: Optional[ChunkStorage] = None
    ):
        """
        SysMLモデル検証器を初期化
        
        Args:
            graph: 検証に使用するグラフ（SysML仕様書から構築）
            query_engine: クエリエンジン（Noneの場合は自動生成）
            chunk_storage: チャンクストレージ（Noneの場合は自動生成）
        """
        self.graph = graph
        self.query_engine = query_engine or GraphQueryEngine(graph, chunk_storage=chunk_storage)
        self.chunk_storage = chunk_storage
    
    def validate_model(
        self,
        sysml_model_text: str,
        check_constraints: bool = True,
        check_specification_compliance: bool = True
    ) -> Dict[str, Any]:
        """
        SysMLモデルを検証
        
        Args:
            sysml_model_text: 検証するSysMLモデルのテキスト
            check_constraints: 制約違反をチェックするか
            check_specification_compliance: 仕様書との整合性をチェックするか
        
        Returns:
            Dict[str, Any]: 検証結果
        """
        results = {
            'success': True,
            'semantic_comparison': {},
            'constraint_violations': [],
            'specification_compliance': {},
            'recommendations': []
        }
        
        # 1. 意味的比較
        semantic_comparison = self._semantic_comparison(sysml_model_text)
        results['semantic_comparison'] = semantic_comparison
        
        # 2. 制約違反の検出
        if check_constraints:
            constraint_violations = self._detect_constraint_violations(sysml_model_text)
            results['constraint_violations'] = constraint_violations
        
        # 3. 仕様書との整合性チェック
        if check_specification_compliance:
            compliance = self._check_specification_compliance(sysml_model_text)
            results['specification_compliance'] = compliance
        
        # 4. 推奨事項の生成
        recommendations = self._generate_recommendations(results)
        results['recommendations'] = recommendations
        
        return results
    
    def _semantic_comparison(self, sysml_model_text: str) -> Dict[str, Any]:
        """
        SysMLモデルとの意味的比較
        
        Args:
            sysml_model_text: 検証するSysMLモデルのテキスト
        
        Returns:
            Dict[str, Any]: 意味的比較結果
        """
        # SysMLモデルから主要な概念を抽出
        concepts = self._extract_concepts(sysml_model_text)
        
        comparison_results = {
            'matched_concepts': [],
            'unmatched_concepts': [],
            'similar_concepts': []
        }
        
        # グラフ内のノードと比較
        for concept in concepts:
            # クエリエンジンで検索
            query_result = self.query_engine.query_graph(
                concept,
                max_nodes=5,
                explore_depth=1
            )
            
            if query_result.get('success') and query_result.get('matched_nodes'):
                comparison_results['matched_concepts'].append({
                    'concept': concept,
                    'matched_nodes': query_result['matched_nodes'],
                    'confidence': 1.0
                })
            else:
                # 類似概念を検索
                similar = self._find_similar_concepts(concept)
                if similar:
                    comparison_results['similar_concepts'].append({
                        'concept': concept,
                        'similar': similar
                    })
                else:
                    comparison_results['unmatched_concepts'].append(concept)
        
        return comparison_results
    
    def _extract_concepts(self, sysml_model_text: str) -> List[str]:
        """
        SysMLモデルから主要な概念を抽出
        
        Args:
            sysml_model_text: SysMLモデルのテキスト
        
        Returns:
            List[str]: 抽出された概念のリスト
        """
        concepts = []
        
        # 基本的なSysML v2要素を抽出
        import re
        
        # part def, action def, item def などを抽出
        patterns = [
            r'part\s+def\s+(\w+)',
            r'action\s+def\s+(\w+)',
            r'item\s+def\s+(\w+)',
            r'port\s+def\s+(\w+)',
            r'interface\s+def\s+(\w+)',
            r'constraint\s+def\s+(\w+)',
            r'requirement\s+def\s+(\w+)',
        ]
        
        for pattern in patterns:
            matches = re.findall(pattern, sysml_model_text, re.IGNORECASE)
            concepts.extend(matches)
        
        return list(set(concepts))  # 重複除去
    
    def _find_similar_concepts(self, concept: str) -> List[Dict[str, Any]]:
        """
        類似概念を検索
        
        Args:
            concept: 検索する概念
        
        Returns:
            List[Dict[str, Any]]: 類似概念のリスト
        """
        # クエリエンジンで類似ノードを検索
        query_result = self.query_engine.query_graph(
            concept,
            max_nodes=3,
            explore_depth=2
        )
        
        similar = []
        if query_result.get('success') and query_result.get('matched_nodes'):
            for node in query_result['matched_nodes']:
                similar.append({
                    'node': node,
                    'similarity': 0.7  # 簡易的な類似度
                })
        
        return similar
    
    def _detect_constraint_violations(self, sysml_model_text: str) -> List[Dict[str, Any]]:
        """
        制約違反を自動検出
        
        Args:
            sysml_model_text: 検証するSysMLモデルのテキスト
        
        Returns:
            List[Dict[str, Any]]: 検出された制約違反のリスト
        """
        violations = []
        
        # グラフから制約情報を取得
        constraint_nodes = [
            node for node in self.graph.nodes()
            if 'constraint' in node.lower() or 'requirement' in node.lower()
        ]
        
        # 各制約について、モデルが満たしているかチェック
        for constraint_node in constraint_nodes:
            # 制約の詳細を取得
            constraint_info = self._get_constraint_info(constraint_node)
            
            # モデルが制約を満たしているかチェック
            if not self._check_constraint_satisfaction(sysml_model_text, constraint_info):
                violations.append({
                    'constraint': constraint_node,
                    'violation_type': 'constraint_not_satisfied',
                    'description': f"制約 '{constraint_node}' が満たされていません"
                })
        
        return violations
    
    def _get_constraint_info(self, constraint_node: str) -> Dict[str, Any]:
        """
        制約ノードの情報を取得
        
        Args:
            constraint_node: 制約ノード名
        
        Returns:
            Dict[str, Any]: 制約情報
        """
        # ノードの属性を取得
        node_data = self.graph.nodes.get(constraint_node, {})
        
        # ソーステキストを取得
        source_texts = []
        if self.query_engine:
            source_texts = self.query_engine.get_source_text(constraint_node, max_chunks=3)
        
        return {
            'node': constraint_node,
            'attributes': node_data,
            'source_texts': source_texts
        }
    
    def _check_constraint_satisfaction(
        self,
        sysml_model_text: str,
        constraint_info: Dict[str, Any]
    ) -> bool:
        """
        モデルが制約を満たしているかチェック
        
        Args:
            sysml_model_text: 検証するSysMLモデルのテキスト
            constraint_info: 制約情報
        
        Returns:
            bool: 制約を満たしている場合True
        """
        # 簡易的なチェック（実際の実装ではより詳細なチェックが必要）
        constraint_name = constraint_info['node'].lower()
        
        # 制約名がモデルに含まれているかチェック
        if constraint_name in sysml_model_text.lower():
            return True
        
        # ソーステキストから制約の内容を確認
        for source_text in constraint_info.get('source_texts', []):
            if source_text and source_text.lower() in sysml_model_text.lower():
                return True
        
        return False
    
    def _check_specification_compliance(self, sysml_model_text: str) -> Dict[str, Any]:
        """
        仕様書との整合性チェック
        
        Args:
            sysml_model_text: 検証するSysMLモデルのテキスト
        
        Returns:
            Dict[str, Any]: 整合性チェック結果
        """
        compliance = {
            'compliant': True,
            'issues': [],
            'coverage': 0.0
        }
        
        # モデルから主要な概念を抽出
        model_concepts = self._extract_concepts(sysml_model_text)
        
        # 仕様書（グラフ）から主要な概念を取得
        spec_concepts = list(self.graph.nodes())
        
        # モデルの概念が仕様書に存在するかチェック
        matched_count = 0
        for concept in model_concepts:
            if concept in spec_concepts:
                matched_count += 1
            else:
                # 類似概念を検索
                similar = self._find_similar_concepts(concept)
                if not similar:
                    compliance['issues'].append({
                        'concept': concept,
                        'issue': '仕様書に存在しない概念',
                        'severity': 'warning'
                    })
        
        # カバレッジを計算
        if model_concepts:
            compliance['coverage'] = matched_count / len(model_concepts)
        
        # カバレッジが低い場合は非準拠
        if compliance['coverage'] < 0.7:
            compliance['compliant'] = False
        
        return compliance
    
    def _generate_recommendations(self, validation_results: Dict[str, Any]) -> List[str]:
        """
        推奨事項を生成
        
        Args:
            validation_results: 検証結果
        
        Returns:
            List[str]: 推奨事項のリスト
        """
        recommendations = []
        
        # 意味的比較の結果から推奨事項を生成
        semantic_comparison = validation_results.get('semantic_comparison', {})
        unmatched = semantic_comparison.get('unmatched_concepts', [])
        if unmatched:
            recommendations.append(
                f"以下の概念が仕様書に存在しません: {', '.join(unmatched[:5])}"
            )
        
        # 制約違反から推奨事項を生成
        violations = validation_results.get('constraint_violations', [])
        if violations:
            recommendations.append(
                f"{len(violations)}個の制約違反が検出されました。制約を確認してください。"
            )
        
        # 仕様書との整合性から推奨事項を生成
        compliance = validation_results.get('specification_compliance', {})
        if not compliance.get('compliant', True):
            coverage = compliance.get('coverage', 0.0)
            recommendations.append(
                f"仕様書との整合性が低いです（カバレッジ: {coverage:.1%}）。"
            )
        
        return recommendations
