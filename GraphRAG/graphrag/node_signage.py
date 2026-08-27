"""
標識・案内板システム
ノードにナビゲーション情報を付与する機能
"""
from typing import Dict, List, Optional

import networkx as nx


class NodeSignageManager:
    """
    ノード標識・案内板マネージャー
    
    ノードにentry_point, exit_routes, warningsなどの
    ナビゲーション情報を付与する機能
    """
    
    def __init__(self, graph: nx.DiGraph):
        """
        標識マネージャーを初期化
        
        Args:
            graph: 対象のグラフ
        """
        self.graph = graph
        self._build_signage()
    
    def _build_signage(self):
        """
        グラフ内のすべてのノードに標識を構築
        """
        for node in self.graph.nodes():
            signage = self._generate_signage(node)
            if signage:
                # ノード属性に標識情報を保存
                if 'signage' not in self.graph.nodes[node]:
                    self.graph.nodes[node]['signage'] = {}
                self.graph.nodes[node]['signage'].update(signage)
    
    def _generate_signage(self, node: str) -> Dict:
        """
        ノードの標識情報を生成
        
        Args:
            node: ノード名
        
        Returns:
            Dict: 標識情報
        """
        signage = {}
        
        # 1. エントリーポイント情報
        entry_point = self._generate_entry_point(node)
        if entry_point:
            signage['entry_point'] = entry_point
        
        # 2. 出口ルート情報
        exit_routes = self._generate_exit_routes(node)
        if exit_routes:
            signage['exit_routes'] = exit_routes
        
        # 3. 警告情報
        warnings = self._generate_warnings(node)
        if warnings:
            signage['warnings'] = warnings
        
        return signage
    
    def _generate_entry_point(self, node: str) -> Optional[str]:
        """
        エントリーポイント情報を生成
        
        Args:
            node: ノード名
        
        Returns:
            Optional[str]: エントリーポイント情報
        """
        node_lower = node.lower()
        
        # SysML v2定義ノード
        if 'definition' in node_lower:
            if 'action' in node_lower:
                return "action定義を探している場合はここ"
            elif 'part' in node_lower:
                return "part定義を探している場合はここ"
            elif 'item' in node_lower:
                return "item定義を探している場合はここ"
            elif 'port' in node_lower:
                return "port定義を探している場合はここ"
            elif 'interface' in node_lower:
                return "interface定義を探している場合はここ"
            elif 'constraint' in node_lower:
                return "constraint定義を探している場合はここ"
            elif 'requirement' in node_lower:
                return "requirement定義を探している場合はここ"
            else:
                return "定義を探している場合はここ"
        
        # SysML v2使用ノード
        if 'usage' in node_lower:
            if 'action' in node_lower:
                return "action使用を探している場合はここ"
            elif 'part' in node_lower:
                return "part使用を探している場合はここ"
            elif 'item' in node_lower:
                return "item使用を探している場合はここ"
            else:
                return "使用を探している場合はここ"
        
        # パラメータ関連
        if 'parameter' in node_lower or 'param' in node_lower:
            return "parameterを探している場合はここ"
        
        # 制約関連
        if 'constraint' in node_lower:
            return "constraintを探している場合はここ"
        
        # 要求関連
        if 'requirement' in node_lower:
            return "requirementを探している場合はここ"
        
        return None
    
    def _generate_exit_routes(self, node: str) -> List[str]:
        """
        出口ルート情報を生成
        
        Args:
            node: ノード名
        
        Returns:
            List[str]: 出口ルートのリスト
        """
        exit_routes = []
        node_lower = node.lower()
        
        # このノードから出るエッジを取得
        out_edges = list(self.graph.out_edges(node, data=True))
        
        # エッジの関係タイプに基づいて出口ルートを生成
        for source, target, edge_data in out_edges:
            relation = edge_data.get('relation', 'unknown')
            
            # 関係タイプに基づいた案内
            if relation == 'has_parameter':
                exit_routes.append(f"{target} → has_parameter")
            elif relation == 'requires_input':
                exit_routes.append(f"{target} → requires_input")
            elif relation == 'produces_output':
                exit_routes.append(f"{target} → produces_output")
            elif relation == 'is_defined_in':
                exit_routes.append(f"{target} → is_defined_in")
            elif relation == 'governs_flow_of':
                exit_routes.append(f"{target} → governs_flow_of")
            elif relation == 'splits_into':
                exit_routes.append(f"{target} → splits_into")
            elif relation == 'merges_from':
                exit_routes.append(f"{target} → merges_from")
            elif relation == 'specializes':
                exit_routes.append(f"{target} → specializes")
            elif relation == 'subsets':
                exit_routes.append(f"{target} → subsets")
            elif relation == 'redefines':
                exit_routes.append(f"{target} → redefines")
            elif relation == 'is-a':
                exit_routes.append(f"{target} → is-a")
            elif relation == 'part-of':
                exit_routes.append(f"{target} → part-of")
            elif relation == 'uses':
                exit_routes.append(f"{target} → uses")
            elif relation == 'depends-on':
                exit_routes.append(f"{target} → depends-on")
            else:
                exit_routes.append(f"{target} → {relation}")
        
        # ノードタイプに基づいた一般的な出口ルート
        if 'definition' in node_lower:
            # 定義ノードからは使用ノードへの案内
            if 'action' in node_lower:
                exit_routes.append("actionusage → 使用例を参照")
            elif 'part' in node_lower:
                exit_routes.append("partusage → 使用例を参照")
            elif 'item' in node_lower:
                exit_routes.append("itemusage → 使用例を参照")
        
        if 'parameter' in node_lower:
            exit_routes.append("action → has_parameter")
            exit_routes.append("constraint → constraint_parameter")
        
        if 'constraint' in node_lower:
            exit_routes.append("requirement → constraint")
            exit_routes.append("action → constraint")
        
        # 重複除去
        return list(set(exit_routes))
    
    def _generate_warnings(self, node: str) -> List[str]:
        """
        警告情報を生成
        
        Args:
            node: ノード名
        
        Returns:
            List[str]: 警告のリスト
        """
        warnings = []
        node_lower = node.lower()
        
        # 定義ノードの場合
        if 'definition' in node_lower:
            warnings.append("詳細実装は別ノード参照")
            if 'action' in node_lower:
                warnings.append("actionusageノードで使用例を確認")
            elif 'part' in node_lower:
                warnings.append("partusageノードで使用例を確認")
        
        # 使用ノードの場合
        if 'usage' in node_lower:
            warnings.append("定義は対応するdefinitionノードを参照")
        
        # パラメータノードの場合
        if 'parameter' in node_lower:
            warnings.append("パラメータの詳細はactionノードを参照")
        
        # 制約ノードの場合
        if 'constraint' in node_lower:
            warnings.append("制約の詳細はrequirementノードを参照")
        
        # エッジが少ないノード（孤立ノード）
        if self.graph.degree(node) < 2:
            warnings.append("このノードは接続が少ないため、関連情報が限定的です")
        
        return warnings
    
    def get_signage(self, node: str) -> Dict:
        """
        ノードの標識情報を取得
        
        Args:
            node: ノード名
        
        Returns:
            Dict: 標識情報
        """
        if node not in self.graph:
            return {}
        
        return self.graph.nodes[node].get('signage', {})
    
    def update_signage(self, node: str, signage: Dict):
        """
        ノードの標識情報を更新
        
        Args:
            node: ノード名
            signage: 標識情報
        """
        if node not in self.graph:
            return
        
        if 'signage' not in self.graph.nodes[node]:
            self.graph.nodes[node]['signage'] = {}
        
        self.graph.nodes[node]['signage'].update(signage)
