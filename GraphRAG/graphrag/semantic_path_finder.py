"""
セマンティック・パスファインダー（Phase 5）

明示的なエッジがない場合でも、意味的な関係性を推論して発見
LLM-based 意味的関係推論を実装
"""
import logging
import re
from typing import Dict, List, Optional

import networkx as nx

from . import config
from .query_engine import GraphQueryEngine

logger = logging.getLogger(__name__)


class SemanticPathFinder:
    """
    セマンティック・パスファインダー
    
    明示的なエッジがない場合でも、意味的な関係性を推論して発見
    """
    
    def __init__(
        self, 
        graph: nx.DiGraph,
        graph_query_engine: GraphQueryEngine,
        llm_client: Optional[object] = None
    ):
        """
        セマンティック・パスファインダーを初期化
        
        Args:
            graph: 対象のグラフ
            graph_query_engine: グラフクエリエンジン（直接パス探索用）
            llm_client: LLMクライアント（Noneの場合は簡易版を使用）
        """
        self.graph = graph
        self.graph_query_engine = graph_query_engine
        self.llm_client = llm_client
        self.relationship_cache = {}
    
    def find_semantic_path(
        self, 
        start: str, 
        end: str, 
        max_depth: int = 3
    ) -> Dict:
        """
        セマンティックパス探索
        
        Args:
            start: 開始ノード
            end: 終了ノード
            max_depth: 最大探索深度
        
        Returns:
            Dict: パス情報
        """
        if start not in self.graph.nodes():
            return {
                "type": "error",
                "error": f"開始ノード '{start}' が見つかりません",
                "confidence": 0.0
            }
        
        if end not in self.graph.nodes():
            return {
                "type": "error",
                "error": f"終了ノード '{end}' が見つかりません",
                "confidence": 0.0
            }
        
        # 1. 直接パス探索を試行
        try:
            direct_path = self.graph_query_engine.find_path(
                start, 
                end, 
                max_depth=max_depth
            )
            
            if direct_path and direct_path.get('success') and direct_path.get('path'):
                return {
                    "type": "direct",
                    "path": direct_path['path'],
                    "confidence": 1.0,
                    "method": "graph_traversal"
                }
        # graph_query_engineの実装詳細に依らず、直接探索が失敗したら
        # 意味的推論によるフォールバック探索へ処理を継続させるため意図的に広く捕捉
        except Exception as e:  # noqa: BLE001
            logger.debug(f"直接パス探索エラー: {e}")
        
        # 2. セマンティック推論でパス探索
        semantic_path = self._find_semantic_relationship(start, end)
        
        return semantic_path
    
    def _find_semantic_relationship(self, start: str, end: str) -> Dict:
        """
        LLMで意味的関係を推論
        
        Args:
            start: 開始ノード
            end: 終了ノード
        
        Returns:
            Dict: 意味的関係情報
        """
        # キャッシュチェック
        cache_key = f"{start}_{end}"
        if cache_key in self.relationship_cache:
            return self.relationship_cache[cache_key]
        
        # 1. LLMで中間概念を推論（LLMが利用可能な場合）
        if self.llm_client:
            bridge_concepts = self._infer_bridge_concepts_with_llm(start, end)
        else:
            bridge_concepts = self._infer_bridge_concepts_simple(start, end)
        
        # 2. 中間概念をグラフで検証
        verified_bridges = self._verify_bridge_concepts(
            start, end, bridge_concepts
        )
        
        # 3. 結果を構築
        result = {
            "type": "semantic",
            "start": start,
            "end": end,
            "bridge_concepts": verified_bridges,
            "confidence": self._calculate_semantic_confidence(verified_bridges),
            "method": "llm_inference + graph_verification" if self.llm_client else "simple_inference + graph_verification"
        }
        
        # キャッシュして返却
        self.relationship_cache[cache_key] = result
        return result
    
    def _infer_bridge_concepts_with_llm(self, start: str, end: str) -> List[str]:
        """
        LLMで中間概念を推論
        
        Args:
            start: 開始ノード
            end: 終了ノード
        
        Returns:
            List[str]: 中間概念のリスト
        """
        prompt = f"""
SysML v2の文脈で、{start}と{end}という2つの概念を繋ぐ中間的な概念や関係性を推論してください。

【分析観点】
1. 直接的な関係性（例: AがBを使用する、AがBを含む）
2. 間接的な関係性（例: AとBが共通の概念Cを通じて関連）
3. 仕様上の関係性（例: AがBを満たす、AがBに準拠する）

【回答形式】
- 中間概念名を1つずつ列挙
- 各概念がなぜ{start}と{end}を繋ぐのか簡潔に説明

中間概念:
"""
        
        try:
            # LLMクライアントがgenerateメソッドを持つことを想定
            if hasattr(self.llm_client, 'generate'):
                response = self.llm_client.generate(prompt)
            elif hasattr(self.llm_client, 'chat') and hasattr(self.llm_client.chat, 'completions'):
                # OpenAI API形式
                response_obj = self.llm_client.chat.completions.create(
                    model=config.LLM_MODEL,
                    messages=[
                        {"role": "system", "content": "あなたはSysML v2の専門家です。概念間の関係性を推論してください。"},
                        {"role": "user", "content": prompt}
                    ],
                    # reasoning モデルは temperature 非対応、max_tokens も使えない。
                    # reasoning トークン分の余裕を見て予算を広げている。
                    reasoning_effort="low",
                    max_completion_tokens=900,
                )
                response = response_obj.choices[0].message.content
            else:
                # LLMが利用できない場合は簡易版にフォールバック
                return self._infer_bridge_concepts_simple(start, end)
            
            # レスポンスから概念名を抽出
            bridge_concepts = self._extract_concepts_from_response(response)
            return bridge_concepts
        except Exception as e:  # noqa: BLE001 - LLM API呼び出しの失敗理由を問わず簡易版フォールバックに委ねるため意図的に広く捕捉
            logger.warning(f"LLM推論エラー: {e}。簡易版にフォールバックします。")
            return self._infer_bridge_concepts_simple(start, end)
    
    def _infer_bridge_concepts_simple(self, start: str, end: str) -> List[str]:
        """
        簡易版中間概念推論（LLMなし、改善版）
        
        Args:
            start: 開始ノード
            end: 終了ノード
        
        Returns:
            List[str]: 中間概念のリスト
        """
        bridge_concepts = []
        
        # 1. 共通の隣接ノードを探す（最も直接的な関係）
        start_neighbors = set(self.graph.neighbors(start))
        end_neighbors = set(self.graph.neighbors(end))
        common_neighbors = start_neighbors & end_neighbors
        
        if common_neighbors:
            # 共通ノードを優先的に追加（最大3個）
            bridge_concepts.extend(list(common_neighbors)[:3])
        
        # 2. 開始ノードから2ホップ以内で終了ノードに到達可能なノードを探す
        for neighbor in list(start_neighbors)[:10]:  # より多くの隣接ノードをチェック
            neighbor_neighbors = set(self.graph.neighbors(neighbor))
            # 終了ノードに直接接続しているか、終了ノードの隣接ノードに接続しているか
            if end in neighbor_neighbors:
                bridge_concepts.append(neighbor)
            else:
                # 2ホップ先をチェック
                for second_hop in list(neighbor_neighbors)[:5]:
                    if end in set(self.graph.neighbors(second_hop)):
                        bridge_concepts.append(neighbor)
                        break
        
        # 3. 逆方向もチェック（終了ノードから開始ノードへのパス）
        for neighbor in list(end_neighbors)[:10]:
            neighbor_neighbors = set(self.graph.neighbors(neighbor))
            if start in neighbor_neighbors:
                bridge_concepts.append(neighbor)
        
        # 4. 重複除去して最大5個返す
        unique_bridges = list(set(bridge_concepts))[:5]
        
        # 5. ノードの重要度でソート（次数が高いノードを優先）
        if unique_bridges:
            unique_bridges.sort(key=lambda n: self.graph.degree(n), reverse=True)
        
        return unique_bridges
    
    def _extract_concepts_from_response(self, response: str) -> List[str]:
        """
        LLMレスポンスから概念名を抽出
        
        Args:
            response: LLMレスポンス
        
        Returns:
            List[str]: 抽出された概念名のリスト
        """
        concepts = []
        
        # 行ごとに処理
        for line in response.split('\n'):
            line = line.strip()
            if not line:
                continue
            
            # 概念名を抽出（簡易版: 最初の単語または引用符内のテキスト）
            # パターン1: "- concept_name" 形式
            match = re.match(r'[-•]\s*([A-Za-z][A-Za-z0-9_]*)', line)
            if match:
                concepts.append(match.group(1))
            # パターン2: "concept_name:" 形式
            elif ':' in line:
                concept = line.split(':')[0].strip()
                if concept and len(concept) > 2:
                    concepts.append(concept)
            # パターン3: 引用符内
            elif '"' in line or "'" in line:
                matches = re.findall(r'["\']([^"\']+)["\']', line)
                concepts.extend(matches)
        
        # グラフ内に存在する概念のみを返す
        valid_concepts = [c for c in concepts if c in self.graph.nodes()]
        
        return valid_concepts[:5]  # 最大5個
    
    def _verify_bridge_concepts(
        self, 
        start: str, 
        end: str, 
        bridge_concepts: List[str]
    ) -> List[Dict]:
        """
        グラフで中間概念を検証
        
        Args:
            start: 開始ノード
            end: 終了ノード
            bridge_concepts: 中間概念のリスト
        
        Returns:
            List[Dict]: 検証済み中間概念情報
        """
        verified_bridges = []
        
        for concept in bridge_concepts:
            if concept not in self.graph.nodes():
                continue
            
            # 開始ノードから中間概念へのパスを確認
            start_to_bridge = False
            try:
                path_result = self.graph_query_engine.find_path(start, concept, max_depth=2)
                if path_result and path_result.get('success') and path_result.get('path'):
                    start_to_bridge = True
            except Exception:
                # パス探索の失敗は「パスなし」として扱い、信頼度計算を継続する。
                logger.debug(
                    "開始ノード -> 中間概念のパス探索に失敗: %s -> %s", start, concept, exc_info=True
                )

            # 中間概念から終了ノードへのパスを確認
            bridge_to_end = False
            try:
                path_result = self.graph_query_engine.find_path(concept, end, max_depth=2)
                if path_result and path_result.get('success') and path_result.get('path'):
                    bridge_to_end = True
            except Exception:
                logger.debug(
                    "中間概念 -> 終了ノードのパス探索に失敗: %s -> %s", concept, end, exc_info=True
                )
            
            # 検証結果に基づいて信頼度を計算
            if start_to_bridge and bridge_to_end:
                confidence = 0.9
            elif start_to_bridge or bridge_to_end:
                confidence = 0.6
            else:
                # グラフ内に存在するが、直接パスがない場合でも低い信頼度で含める
                confidence = 0.3
            
            verified_bridges.append({
                'concept': concept,
                'confidence': confidence,
                'start_to_bridge': start_to_bridge,
                'bridge_to_end': bridge_to_end,
                'source': 'graph_verified' if (start_to_bridge or bridge_to_end) else 'graph_exists'
            })
        
        # 信頼度順でソート
        verified_bridges.sort(key=lambda x: x['confidence'], reverse=True)
        return verified_bridges
    
    def _calculate_semantic_confidence(self, verified_bridges: List[Dict]) -> float:
        """
        セマンティック信頼度を計算
        
        Args:
            verified_bridges: 検証済み中間概念情報
        
        Returns:
            float: 信頼度（0.0-1.0）
        """
        if not verified_bridges:
            return 0.0
        
        # 検証された中間概念の信頼度の平均
        confidences = [bridge['confidence'] for bridge in verified_bridges]
        return sum(confidences) / len(confidences)
