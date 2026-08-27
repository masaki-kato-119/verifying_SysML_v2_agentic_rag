"""
Parallel Processor（並列処理器）
複数ノード探索とソーステキスト取得の並列化機能
"""
import concurrent.futures
import threading
from functools import wraps
from typing import Any, Callable, Dict, List, Optional

import networkx as nx

from .chunk_storage import ChunkStorage


class ParallelProcessor:
    """
    並列処理器
    
    グラフ探索とソーステキスト取得の並列化機能を提供
    """
    
    def __init__(
        self,
        max_workers: Optional[int] = None,
        timeout: float = 30.0,
        enable_early_termination: bool = True
    ):
        """
        並列処理器を初期化（Phase 3: 最適化）
        
        Args:
            max_workers: 最大ワーカー数（Noneの場合は自動設定、CPU数に基づく）
            timeout: タイムアウト時間（秒）
            enable_early_termination: 早期終了を有効にするか
        """
        import os
        # Phase 3: CPU数に基づいて自動設定
        if max_workers is None:
            cpu_count = os.cpu_count() or 4
            # I/Oバウンドな処理なので、CPU数の2倍まで許可
            self.max_workers = min(cpu_count * 2, 16)  # 最大16ワーカー
        else:
            self.max_workers = max_workers
        self.timeout = timeout
        self.enable_early_termination = enable_early_termination
        self._stop_event = threading.Event()
    
    def parallel_node_exploration(
        self,
        graph: nx.DiGraph,
        start_nodes: List[str],
        exploration_func: Callable[[str], Dict],
        max_results: Optional[int] = None,
        quality_threshold: float = 0.0
    ) -> List[Dict]:
        """
        複数ノードの並列探索
        
        Args:
            graph: グラフオブジェクト
            start_nodes: 開始ノードのリスト
            exploration_func: 探索関数（ノード名を受け取り、結果辞書を返す）
            max_results: 最大結果数（早期終了用）
            quality_threshold: 品質閾値（この値以上の結果のみ保持）
        
        Returns:
            List[Dict]: 探索結果のリスト
        """
        results = []
        results_lock = threading.Lock()
        
        def explore_node(node_name: str) -> Optional[Dict]:
            """単一ノードの探索"""
            if self._stop_event.is_set():
                return None
            
            try:
                result = exploration_func(node_name)
                
                # 品質チェック
                quality_score = result.get('quality_score', 1.0)
                if quality_score < quality_threshold:
                    return None
                
                # 早期終了チェック
                if self.enable_early_termination and max_results:
                    with results_lock:
                        if len(results) >= max_results:
                            self._stop_event.set()
                            return None
                
                return result

            # exploration_func は呼び出し元から渡される任意の探索関数のため、
            # 1タスクの失敗でスレッドプール全体を止めないよう意図的に広く捕捉する
            except Exception as e:  # noqa: BLE001
                return {
                    'error': str(e),
                    'node_name': node_name,
                    'success': False
                }
        
        # 並列実行
        with concurrent.futures.ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            # タスクを投入
            future_to_node = {
                executor.submit(explore_node, node): node 
                for node in start_nodes
            }
            
            try:
                # 結果を収集
                for future in concurrent.futures.as_completed(
                    future_to_node, 
                    timeout=self.timeout
                ):
                    if self._stop_event.is_set():
                        break
                    
                    result = future.result()
                    if result is not None:
                        with results_lock:
                            results.append(result)
                            
                            # 早期終了チェック
                            if (self.enable_early_termination and 
                                max_results and 
                                len(results) >= max_results):
                                self._stop_event.set()
                                break
            
            except concurrent.futures.TimeoutError:
                # タイムアウト時は部分結果を返す
                pass
        
        # 停止イベントをリセット
        self._stop_event.clear()
        
        return results
    
    def parallel_source_text_retrieval(
        self,
        chunk_storage: ChunkStorage,
        graph_id: str,
        node_names: List[str],
        max_chunks_per_node: int = 5
    ) -> Dict[str, List[str]]:
        """
        複数ノードのソーステキスト並列取得
        
        Args:
            chunk_storage: チャンクストレージ
            graph_id: グラフID
            node_names: ノード名のリスト
            max_chunks_per_node: ノードあたりの最大チャンク数
        
        Returns:
            Dict[str, List[str]]: ノード名 -> ソーステキストのリストのマッピング
        """
        def get_node_source_text(node_name: str) -> tuple:
            """単一ノードのソーステキスト取得"""
            try:
                # チャンクIDを取得
                chunk_ids = chunk_storage.get_node_chunks(graph_id, node_name)
                
                if not chunk_ids:
                    return node_name, []
                
                # チャンクを取得
                limited_chunk_ids = chunk_ids[:max_chunks_per_node]
                chunks = chunk_storage.get_chunks(graph_id, limited_chunk_ids)
                
                return node_name, list(chunks.values())

            # 1ノード分の取得失敗でスレッドプール全体を止めないよう意図的に広く捕捉する
            except Exception:  # noqa: BLE001
                return node_name, []
        
        results = {}
        
        # 並列実行
        with concurrent.futures.ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            # タスクを投入
            future_to_node = {
                executor.submit(get_node_source_text, node): node 
                for node in node_names
            }
            
            try:
                # 結果を収集
                for future in concurrent.futures.as_completed(
                    future_to_node, 
                    timeout=self.timeout
                ):
                    node_name, source_texts = future.result()
                    results[node_name] = source_texts
            
            except concurrent.futures.TimeoutError:
                # タイムアウト時は部分結果を返す
                pass
        
        return results
    
    def parallel_edge_source_text_retrieval(
        self,
        chunk_storage: ChunkStorage,
        graph_id: str,
        edge_pairs: List[tuple],
        max_chunks_per_edge: int = 5
    ) -> Dict[tuple, List[str]]:
        """
        複数エッジのソーステキスト並列取得
        
        Args:
            chunk_storage: チャンクストレージ
            graph_id: グラフID
            edge_pairs: エッジペア（source, target）のリスト
            max_chunks_per_edge: エッジあたりの最大チャンク数
        
        Returns:
            Dict[tuple, List[str]]: エッジペア -> ソーステキストのリストのマッピング
        """
        def get_edge_source_text(edge_pair: tuple) -> tuple:
            """単一エッジのソーステキスト取得"""
            try:
                source, target = edge_pair
                
                # チャンクIDを取得
                chunk_ids = chunk_storage.get_edge_chunks(graph_id, source, target)
                
                if not chunk_ids:
                    return edge_pair, []
                
                # チャンクを取得
                limited_chunk_ids = chunk_ids[:max_chunks_per_edge]
                chunks = chunk_storage.get_chunks(graph_id, limited_chunk_ids)
                
                return edge_pair, list(chunks.values())

            # 1エッジ分の取得失敗でスレッドプール全体を止めないよう意図的に広く捕捉する
            except Exception:  # noqa: BLE001
                return edge_pair, []
        
        results = {}
        
        # 並列実行
        with concurrent.futures.ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            # タスクを投入
            future_to_edge = {
                executor.submit(get_edge_source_text, edge): edge 
                for edge in edge_pairs
            }
            
            try:
                # 結果を収集
                for future in concurrent.futures.as_completed(
                    future_to_edge, 
                    timeout=self.timeout
                ):
                    edge_pair, source_texts = future.result()
                    results[edge_pair] = source_texts
            
            except concurrent.futures.TimeoutError:
                # タイムアウト時は部分結果を返す
                pass
        
        return results
    
    def parallel_path_finding(
        self,
        graph: nx.DiGraph,
        start_nodes: List[str],
        target_nodes: List[str],
        path_finding_func: Callable[[str, str], Dict],
        max_paths: Optional[int] = None,
        quality_threshold: float = 0.0
    ) -> List[Dict]:
        """
        複数パスの並列探索
        
        Args:
            graph: グラフオブジェクト
            start_nodes: 開始ノードのリスト
            target_nodes: 終了ノードのリスト
            path_finding_func: パス探索関数（開始ノード、終了ノードを受け取り、結果辞書を返す）
            max_paths: 最大パス数（早期終了用）
            quality_threshold: 品質閾値
        
        Returns:
            List[Dict]: パス探索結果のリスト
        """
        # 全ての組み合わせを生成
        path_pairs = [(start, target) for start in start_nodes for target in target_nodes]
        
        results = []
        results_lock = threading.Lock()
        
        def find_path(pair: tuple) -> Optional[Dict]:
            """単一パスの探索"""
            if self._stop_event.is_set():
                return None
            
            start, target = pair
            
            try:
                result = path_finding_func(start, target)
                
                # 品質チェック
                if not result.get('success', False):
                    return None
                
                quality_score = result.get('quality_score', 1.0)
                if quality_score < quality_threshold:
                    return None
                
                # 早期終了チェック
                if self.enable_early_termination and max_paths:
                    with results_lock:
                        if len(results) >= max_paths:
                            self._stop_event.set()
                            return None
                
                return result

            # path_finding_func は呼び出し元から渡される任意の探索関数のため、
            # 1タスクの失敗でスレッドプール全体を止めないよう意図的に広く捕捉する
            except Exception as e:  # noqa: BLE001
                return {
                    'error': str(e),
                    'start': start,
                    'target': target,
                    'success': False
                }
        
        # 並列実行
        with concurrent.futures.ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            # タスクを投入
            future_to_pair = {
                executor.submit(find_path, pair): pair 
                for pair in path_pairs
            }
            
            try:
                # 結果を収集
                for future in concurrent.futures.as_completed(
                    future_to_pair, 
                    timeout=self.timeout
                ):
                    if self._stop_event.is_set():
                        break
                    
                    result = future.result()
                    if result is not None:
                        with results_lock:
                            results.append(result)
                            
                            # 早期終了チェック
                            if (self.enable_early_termination and 
                                max_paths and 
                                len(results) >= max_paths):
                                self._stop_event.set()
                                break
            
            except concurrent.futures.TimeoutError:
                # タイムアウト時は部分結果を返す
                pass
        
        # 停止イベントをリセット
        self._stop_event.clear()
        
        return results
    
    def batch_process_with_progress(
        self,
        items: List[Any],
        process_func: Callable[[Any], Any],
        batch_size: int = 10,
        progress_callback: Optional[Callable[[int, int], None]] = None
    ) -> List[Any]:
        """
        バッチ処理（進捗コールバック付き）
        
        Args:
            items: 処理対象のアイテムのリスト
            process_func: 処理関数
            batch_size: バッチサイズ
            progress_callback: 進捗コールバック関数（現在の進捗、総数を受け取る）
        
        Returns:
            List[Any]: 処理結果のリスト
        """
        results = []
        total_items = len(items)
        processed_count = 0
        
        # バッチに分割
        for i in range(0, len(items), batch_size):
            if self._stop_event.is_set():
                break
            
            batch = items[i:i + batch_size]
            
            # バッチを並列処理
            with concurrent.futures.ThreadPoolExecutor(max_workers=self.max_workers) as executor:
                futures = [executor.submit(process_func, item) for item in batch]
                
                try:
                    for future in concurrent.futures.as_completed(futures, timeout=self.timeout):
                        if self._stop_event.is_set():
                            break
                        
                        result = future.result()
                        results.append(result)
                        processed_count += 1
                        
                        # 進捗コールバック
                        if progress_callback:
                            progress_callback(processed_count, total_items)
                
                except concurrent.futures.TimeoutError:
                    # タイムアウト時は部分結果を返す
                    break
        
        return results
    
    def stop_processing(self):
        """処理を停止"""
        self._stop_event.set()
    
    def reset(self):
        """状態をリセット"""
        self._stop_event.clear()


def parallel_execution_decorator(max_workers: Optional[int] = None, timeout: float = 30.0):
    """
    並列実行デコレータ
    
    Args:
        max_workers: 最大ワーカー数
        timeout: タイムアウト時間
    
    Returns:
        デコレータ関数
    """
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            # 並列処理可能な引数を検出
            parallel_args = kwargs.get('parallel_items')
            if not parallel_args:
                # 通常の実行
                return func(*args, **kwargs)
            
            # 並列実行
            processor = ParallelProcessor(max_workers=max_workers, timeout=timeout)
            
            def process_item(item):
                # 引数を更新して関数を実行
                updated_kwargs = kwargs.copy()
                updated_kwargs.update(item)
                updated_kwargs.pop('parallel_items', None)
                return func(*args, **updated_kwargs)
            
            return processor.batch_process_with_progress(
                items=parallel_args,
                process_func=process_item
            )
        
        return wrapper
    return decorator