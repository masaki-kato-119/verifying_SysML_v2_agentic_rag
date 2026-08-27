"""
学習・適応機能（Phase 4）
クエリパターンからの学習、探索履歴による最適化、動的標識調整機能
"""
import json
import logging
import time
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import networkx as nx

from .node_signage import NodeSignageManager

logger = logging.getLogger(__name__)


class QueryPatternLearner:
    """
    クエリパターン学習器
    
    クエリパターンから学習し、将来のクエリ処理を最適化
    """
    
    def __init__(self, history_file: Optional[str] = None):
        """
        クエリパターン学習器を初期化
        
        Args:
            history_file: 履歴ファイルのパス（Noneの場合はメモリのみ）
        """
        self.history_file = history_file
        self.query_patterns: Dict[str, Dict[str, Any]] = {}
    
    def _get_pattern(self, pattern_key: str) -> Dict[str, Any]:
        """
        パターンを取得（存在しない場合は作成）
        
        Args:
            pattern_key: パターンキー
        
        Returns:
            Dict[str, Any]: パターン辞書
        """
        if pattern_key not in self.query_patterns:
            self.query_patterns[pattern_key] = {
                'count': 0,
                'success_rate': 0.0,
                'avg_response_time': 0.0,
                'common_expansions': defaultdict(int),
                'common_nodes': defaultdict(int)
            }
        return self.query_patterns[pattern_key]
        self._load_history()
    
    def record_query(
        self,
        query: str,
        expanded_queries: List[str],
        matched_nodes: List[str],
        success: bool,
        response_time: float
    ):
        """
        クエリを記録
        
        Args:
            query: 元のクエリ
            expanded_queries: 拡張されたクエリのリスト
            matched_nodes: マッチしたノードのリスト
            success: 成功したかどうか
            response_time: レスポンス時間（秒）
        """
        pattern_key = self._normalize_query(query)
        pattern = self._get_pattern(pattern_key)
        
        # 統計を更新
        pattern['count'] += 1
        if success:
            pattern['success_rate'] = (
                (pattern['success_rate'] * (pattern['count'] - 1) + 1.0) / pattern['count']
            )
        else:
            pattern['success_rate'] = (
                (pattern['success_rate'] * (pattern['count'] - 1)) / pattern['count']
            )
        
        # 平均レスポンス時間を更新
        pattern['avg_response_time'] = (
            (pattern['avg_response_time'] * (pattern['count'] - 1) + response_time) / pattern['count']
        )
        
        # よく使われる拡張を記録
        for expanded in expanded_queries:
            pattern['common_expansions'][expanded] += 1
        
        # よくマッチするノードを記録
        for node in matched_nodes:
            pattern['common_nodes'][node] += 1
        
        # 履歴を保存
        self._save_history()
    
    def get_query_suggestions(self, query: str) -> Dict[str, Any]:
        """
        クエリの提案を取得
        
        Args:
            query: クエリ
        
        Returns:
            Dict[str, Any]: 提案情報
        """
        pattern_key = self._normalize_query(query)
        pattern = self.query_patterns.get(pattern_key)
        
        if not pattern or pattern['count'] < 2:
            return {}
        
        # defaultdictを通常のdictに変換
        common_expansions = dict(pattern['common_expansions']) if isinstance(pattern['common_expansions'], defaultdict) else pattern['common_expansions']
        common_nodes = dict(pattern['common_nodes']) if isinstance(pattern['common_nodes'], defaultdict) else pattern['common_nodes']
        
        # よく使われる拡張を取得
        common_expansions_sorted = sorted(
            common_expansions.items(),
            key=lambda x: x[1],
            reverse=True
        )[:5]
        
        # よくマッチするノードを取得
        common_nodes_sorted = sorted(
            common_nodes.items(),
            key=lambda x: x[1],
            reverse=True
        )[:5]
        
        return {
            'suggested_expansions': [exp for exp, _ in common_expansions_sorted],
            'suggested_nodes': [node for node, _ in common_nodes_sorted],
            'success_rate': pattern['success_rate'],
            'avg_response_time': pattern['avg_response_time']
        }
    
    def _normalize_query(self, query: str) -> str:
        """
        クエリを正規化
        
        Args:
            query: クエリ
        
        Returns:
            str: 正規化されたクエリ
        """
        return query.lower().strip()
    
    def _load_history(self):
        """履歴を読み込み"""
        if self.history_file and Path(self.history_file).exists():
            try:
                with open(self.history_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    # データを読み込む際にdefaultdictに変換
                    for key, value in data.items():
                        pattern = {
                            'count': value.get('count', 0),
                            'success_rate': value.get('success_rate', 0.0),
                            'avg_response_time': value.get('avg_response_time', 0.0),
                            'common_expansions': defaultdict(int, value.get('common_expansions', {})),
                            'common_nodes': defaultdict(int, value.get('common_nodes', {}))
                        }
                        self.query_patterns[key] = pattern
            except Exception:
                # 学習履歴は最適化用のため、読み込み失敗は致命的ではない。
                # ただし破損したファイルに気づけるよう警告は残す。
                logger.warning(
                    "クエリパターン履歴の読み込みに失敗しました。学習結果なしで続行します: %s",
                    self.history_file,
                    exc_info=True,
                )
    
    def _save_history(self):
        """履歴を保存"""
        if self.history_file:
            try:
                # defaultdictを通常のdictに変換
                data = {}
                for key, value in self.query_patterns.items():
                    data[key] = {
                        'count': value['count'],
                        'success_rate': value['success_rate'],
                        'avg_response_time': value['avg_response_time'],
                        'common_expansions': dict(value['common_expansions']),
                        'common_nodes': dict(value['common_nodes'])
                    }
                
                with open(self.history_file, 'w', encoding='utf-8') as f:
                    json.dump(data, f, ensure_ascii=False, indent=2)
            except Exception:
                # 保存失敗は次回の学習結果が失われるだけなので処理は継続する。
                logger.warning(
                    "クエリパターン履歴の保存に失敗しました: %s",
                    self.history_file,
                    exc_info=True,
                )


class ExplorationHistoryOptimizer:
    """
    探索履歴最適化器
    
    探索履歴から学習し、パス探索を最適化
    """
    
    def __init__(self, history_file: Optional[str] = None):
        """
        探索履歴最適化器を初期化
        
        Args:
            history_file: 履歴ファイルのパス（Noneの場合はメモリのみ）
        """
        self.history_file = history_file
        self.path_history: Dict[Tuple[str, str], List[Dict[str, Any]]] = defaultdict(list)
        self.node_importance: Dict[str, float] = defaultdict(float)
        self._load_history()
    
    def record_path(
        self,
        start_node: str,
        end_node: str,
        path: List[str],
        success: bool,
        quality_score: float
    ):
        """
        パス探索を記録
        
        Args:
            start_node: 開始ノード
            end_node: 終了ノード
            path: 探索されたパス
            success: 成功したかどうか
            quality_score: パスの品質スコア
        """
        path_key = (start_node, end_node)
        self.path_history[path_key].append({
            'path': path,
            'success': success,
            'quality_score': quality_score,
            'timestamp': time.time()
        })
        
        # ノードの重要度を更新
        if success and path:
            for node in path:
                self.node_importance[node] += quality_score / len(path)
        
        # 履歴を保存
        self._save_history()
    
    def get_optimal_path_hint(
        self,
        start_node: str,
        end_node: str
    ) -> Optional[List[str]]:
        """
        最適なパスのヒントを取得
        
        Args:
            start_node: 開始ノード
            end_node: 終了ノード
        
        Returns:
            Optional[List[str]]: 最適なパスのヒント（見つからない場合はNone）
        """
        path_key = (start_node, end_node)
        history = self.path_history.get(path_key, [])
        
        if not history:
            return None
        
        # 成功したパスの中で、品質スコアが最も高いものを取得
        successful_paths = [
            h for h in history
            if h['success'] and h['quality_score'] > 0.5
        ]
        
        if not successful_paths:
            return None
        
        # 品質スコアが最も高いパスを返す
        best_path = max(successful_paths, key=lambda x: x['quality_score'])
        return best_path['path']
    
    def get_node_importance(self, node: str) -> float:
        """
        ノードの重要度を取得
        
        Args:
            node: ノード名
        
        Returns:
            float: 重要度（0.0-1.0）
        """
        importance = self.node_importance.get(node, 0.0)
        # 正規化（最大値を1.0に）
        max_importance = max(self.node_importance.values()) if self.node_importance else 1.0
        return importance / max_importance if max_importance > 0 else 0.0
    
    def _load_history(self):
        """履歴を読み込み

        注意: ``defaultdict`` を素の ``dict`` で置き換えないこと。
        ``record_path`` は ``self.path_history[key].append(...)`` としており、
        未知のノード対で ``KeyError`` になる（= 履歴に無い探索がすべて失敗する）。
        """
        if self.history_file and Path(self.history_file).exists():
            try:
                with open(self.history_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)

                history: Dict[Tuple[str, str], List[Dict[str, Any]]] = defaultdict(list)
                raw = data.get('path_history')
                if isinstance(raw, list):
                    # 現行形式: [{"start": ..., "end": ..., "paths": [...]}, ...]
                    for record in raw:
                        start = record.get('start')
                        end = record.get('end')
                        if start is None or end is None:
                            continue
                        history[(start, end)].extend(record.get('paths') or [])
                elif isinstance(raw, dict):
                    # 旧形式: "start,end" をキーにした dict。
                    # ノード名にカンマを含む場合は復元できないため読み飛ばす。
                    for key, paths in raw.items():
                        start, sep, end = str(key).rpartition(',')
                        if not sep:
                            continue
                        history[(start, end)].extend(paths or [])

                self.path_history = history
                importance: Dict[str, float] = defaultdict(float)
                importance.update(data.get('node_importance') or {})
                self.node_importance = importance
            except Exception:
                # 探索履歴は最適化用のため、読み込み失敗は致命的ではない。
                logger.warning(
                    "探索履歴の読み込みに失敗しました。履歴なしで続行します: %s",
                    self.history_file,
                    exc_info=True,
                )
    
    def _save_history(self):
        """履歴を保存"""
        if self.history_file:
            try:
                # ノード名にカンマが含まれても復元できるよう、キーを連結せず
                # start / end を別フィールドで持つ（旧形式は読み込み側で吸収）。
                data = {
                    'path_history': [
                        {'start': start, 'end': end, 'paths': paths}
                        for (start, end), paths in self.path_history.items()
                    ],
                    'node_importance': dict(self.node_importance)
                }
                
                with open(self.history_file, 'w', encoding='utf-8') as f:
                    json.dump(data, f, ensure_ascii=False, indent=2)
            except Exception:
                logger.warning(
                    "探索履歴の保存に失敗しました: %s",
                    self.history_file,
                    exc_info=True,
                )


class DynamicSignageAdjuster:
    """
    動的標識調整器
    
    探索履歴に基づいて標識を動的に調整
    """
    
    def __init__(
        self,
        graph: nx.DiGraph,
        signage_manager: NodeSignageManager,
        exploration_optimizer: ExplorationHistoryOptimizer
    ):
        """
        動的標識調整器を初期化
        
        Args:
            graph: グラフ
            signage_manager: 標識マネージャー
            exploration_optimizer: 探索履歴最適化器
        """
        self.graph = graph
        self.signage_manager = signage_manager
        self.exploration_optimizer = exploration_optimizer
        self.adjustment_history: Dict[str, int] = defaultdict(int)
    
    def adjust_signage(self, node: str):
        """
        ノードの標識を動的に調整
        
        Args:
            node: ノード名
        """
        if node not in self.graph.nodes():
            return
        
        # ノードの重要度を取得
        importance = self.exploration_optimizer.get_node_importance(node)
        
        # 標識を取得
        signage = self.signage_manager.get_signage(node)
        
        # 重要度に基づいて標識を調整
        if importance > 0.7:
            # 重要度が高い場合は、エントリーポイント情報を強化
            if 'entry_point' not in signage or not signage['entry_point']:
                signage['entry_point'] = f"よく探索される重要なノード: {node}"
        
        # よく使われる出口ルートを優先
        exit_routes = signage.get('exit_routes', [])
        if exit_routes:
            # 重要度に基づいてソート
            exit_routes.sort(key=lambda x: self._get_route_importance(x), reverse=True)
            signage['exit_routes'] = exit_routes[:5]  # 上位5つを保持
        
        # 標識を更新
        self.signage_manager.update_signage(node, signage)
        self.adjustment_history[node] += 1
    
    def _get_route_importance(self, route: str) -> float:
        """
        ルートの重要度を取得
        
        Args:
            route: ルート文字列（例: "parameter → has_parameter"）
        
        Returns:
            float: 重要度
        """
        # 簡易的な実装（実際の実装ではより詳細な計算が必要）
        if '→' in route:
            target = route.split('→')[-1].strip()
            return self.exploration_optimizer.get_node_importance(target)
        return 0.0
    
    def adjust_all_signage(self):
        """すべてのノードの標識を調整"""
        for node in self.graph.nodes():
            self.adjust_signage(node)
