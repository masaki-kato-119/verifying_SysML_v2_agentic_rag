"""
キャッシュ管理モジュール
ノード・エッジのメモリキャッシュとクエリ結果のキャッシュを管理
"""
import hashlib
import json
import logging
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


class CacheManager:
    """
    キャッシュマネージャー
    
    ノード・エッジのメモリキャッシュとクエリ結果のキャッシュを管理
    """
    
    def __init__(
        self,
        enable_query_cache: bool = True,
        query_cache_ttl: Optional[float] = None,
        query_cache_persistent: bool = True,
        cache_dir: Optional[str] = None
    ):
        """
        キャッシュマネージャーを初期化
        
        Args:
            enable_query_cache: クエリ結果キャッシュを有効にするか
            query_cache_ttl: クエリキャッシュのTTL（秒、Noneの場合は永続化）
            query_cache_persistent: クエリキャッシュを永続化するか
            cache_dir: キャッシュディレクトリ（Noneの場合はメモリのみ）
        """
        self.enable_query_cache = enable_query_cache
        self.query_cache_ttl = query_cache_ttl
        self.query_cache_persistent = query_cache_persistent
        
        # メモリキャッシュ（Phase 3: LRUキャッシュに変更）
        self.node_cache: Dict[str, Any] = {}
        self.edge_cache: Dict[Tuple[str, str], Any] = {}
        
        # クエリ結果キャッシュ（Phase 3: LRUキャッシュに変更）
        self.query_cache: Dict[str, Tuple[Any, float]] = {}  # key -> (result, timestamp)
        self.query_cache_access_order: List[str] = []  # LRU用のアクセス順序
        self.max_memory_cache_size = 1000  # 最大メモリキャッシュサイズ
        
        # 永続化キャッシュ
        if cache_dir:
            self.cache_dir = Path(cache_dir)
            self.cache_dir.mkdir(parents=True, exist_ok=True)
        else:
            self.cache_dir = None
        
        # 永続化キャッシュを読み込み
        if self.query_cache_persistent and self.cache_dir:
            self._load_persistent_cache()
    
    def _get_cache_key(self, query: str, **kwargs) -> str:
        """
        キャッシュキーを生成
        
        Args:
            query: クエリ文字列
            **kwargs: その他のパラメータ
        
        Returns:
            str: キャッシュキー（ハッシュ）
        """
        # パラメータをソートして一意のキーを生成
        params_str = json.dumps(kwargs, sort_keys=True)
        key_str = f"{query}:{params_str}"
        return hashlib.md5(key_str.encode()).hexdigest()
    
    def get_node(self, node_name: str) -> Optional[Any]:
        """
        ノード情報をキャッシュから取得
        
        Args:
            node_name: ノード名
        
        Returns:
            Optional[Any]: ノード情報（キャッシュにない場合はNone）
        """
        return self.node_cache.get(node_name)
    
    def set_node(self, node_name: str, node_data: Any):
        """
        ノード情報をキャッシュに保存
        
        Args:
            node_name: ノード名
            node_data: ノード情報
        """
        self.node_cache[node_name] = node_data
    
    def get_edge(self, source: str, target: str) -> Optional[Any]:
        """
        エッジ情報をキャッシュから取得
        
        Args:
            source: ソースノード名
            target: ターゲットノード名
        
        Returns:
            Optional[Any]: エッジ情報（キャッシュにない場合はNone）
        """
        return self.edge_cache.get((source, target))
    
    def set_edge(self, source: str, target: str, edge_data: Any):
        """
        エッジ情報をキャッシュに保存
        
        Args:
            source: ソースノード名
            target: ターゲットノード名
            edge_data: エッジ情報
        """
        self.edge_cache[(source, target)] = edge_data
    
    def get_query_result(self, query: str, **kwargs) -> Optional[Any]:
        """
        クエリ結果をキャッシュから取得（Phase 3: LRUキャッシュ対応）
        
        Args:
            query: クエリ文字列
            **kwargs: その他のパラメータ
        
        Returns:
            Optional[Any]: クエリ結果（キャッシュにない場合や期限切れの場合はNone）
        """
        if not self.enable_query_cache:
            return None
        
        cache_key = self._get_cache_key(query, **kwargs)
        
        # メモリキャッシュから取得
        if cache_key in self.query_cache:
            result, timestamp = self.query_cache[cache_key]
            
            # TTLチェック
            if self.query_cache_ttl is not None:
                if time.time() - timestamp > self.query_cache_ttl:
                    # 期限切れ
                    del self.query_cache[cache_key]
                    if cache_key in self.query_cache_access_order:
                        self.query_cache_access_order.remove(cache_key)
                    return None
            
            # LRU: アクセス順序を更新
            if cache_key in self.query_cache_access_order:
                self.query_cache_access_order.remove(cache_key)
            self.query_cache_access_order.append(cache_key)
            
            return result
        
        # 永続化キャッシュから取得
        if self.query_cache_persistent and self.cache_dir:
            result = self._load_from_persistent_cache(cache_key)
            if result is not None:
                # メモリキャッシュにも保存（LRU管理）
                self._add_to_memory_cache(cache_key, result)
            return result
        
        return None
    
    def set_query_result(self, query: str, result: Any, **kwargs):
        """
        クエリ結果をキャッシュに保存（Phase 3: LRUキャッシュ対応）
        
        Args:
            query: クエリ文字列
            result: クエリ結果
            **kwargs: その他のパラメータ
        """
        if not self.enable_query_cache:
            return
        
        cache_key = self._get_cache_key(query, **kwargs)
        timestamp = time.time()
        
        # メモリキャッシュに保存（LRU管理）
        self._add_to_memory_cache(cache_key, result, timestamp)
        
        # 永続化キャッシュに保存
        if self.query_cache_persistent and self.cache_dir:
            self._save_to_persistent_cache(cache_key, result, timestamp)
    
    def _add_to_memory_cache(self, cache_key: str, result: Any, timestamp: Optional[float] = None):
        """
        メモリキャッシュに追加（LRU管理）
        
        Args:
            cache_key: キャッシュキー
            result: キャッシュする結果
            timestamp: タイムスタンプ（Noneの場合は現在時刻）
        """
        if timestamp is None:
            timestamp = time.time()
        
        # 既に存在する場合は更新
        if cache_key in self.query_cache:
            self.query_cache[cache_key] = (result, timestamp)
            # アクセス順序を更新
            if cache_key in self.query_cache_access_order:
                self.query_cache_access_order.remove(cache_key)
            self.query_cache_access_order.append(cache_key)
            return
        
        # キャッシュサイズ制限チェック
        if len(self.query_cache) >= self.max_memory_cache_size:
            # 最も古いエントリを削除（LRU）
            if self.query_cache_access_order:
                oldest_key = self.query_cache_access_order.pop(0)
                if oldest_key in self.query_cache:
                    del self.query_cache[oldest_key]
        
        # 新しいエントリを追加
        self.query_cache[cache_key] = (result, timestamp)
        self.query_cache_access_order.append(cache_key)
    
    def _load_persistent_cache(self):
        """永続化キャッシュを読み込み"""
        if not self.cache_dir:
            return
        
        cache_file = self.cache_dir / "query_cache.json"
        if not cache_file.exists():
            return
        
        try:
            with open(cache_file, 'r', encoding='utf-8') as f:
                cache_data = json.load(f)
            
            current_time = time.time()
            for key, data in cache_data.items():
                result = data.get('result')
                timestamp = data.get('timestamp', 0)
                
                # TTLチェック
                if self.query_cache_ttl is not None:
                    if current_time - timestamp > self.query_cache_ttl:
                        continue  # 期限切れはスキップ
                
                self.query_cache[key] = (result, timestamp)
            
            logger.info(f"永続化キャッシュを読み込みました: {len(self.query_cache)}件")
        except Exception as e:  # noqa: BLE001 - キャッシュファイル破損等の未知のエラーでも初期化処理全体を止めない
            logger.warning(f"永続化キャッシュの読み込みに失敗: {e}")
    
    def _save_to_persistent_cache(self, cache_key: str, result: Any, timestamp: float):
        """永続化キャッシュに保存"""
        if not self.cache_dir:
            return
        
        cache_file = self.cache_dir / "query_cache.json"
        
        try:
            # 既存のキャッシュを読み込み
            cache_data = {}
            if cache_file.exists():
                with open(cache_file, 'r', encoding='utf-8') as f:
                    cache_data = json.load(f)
            
            # 新しいエントリを追加
            cache_data[cache_key] = {
                'result': result,
                'timestamp': timestamp
            }
            
            # 保存
            with open(cache_file, 'w', encoding='utf-8') as f:
                json.dump(cache_data, f, ensure_ascii=False, indent=2)
        except Exception as e:  # noqa: BLE001 - キャッシュ保存はベストエフォート。失敗しても検索処理本体は継続させる
            logger.warning(f"永続化キャッシュの保存に失敗: {e}")
    
    def _load_from_persistent_cache(self, cache_key: str) -> Optional[Any]:
        """永続化キャッシュから読み込み"""
        if not self.cache_dir:
            return None
        
        cache_file = self.cache_dir / "query_cache.json"
        if not cache_file.exists():
            return None
        
        try:
            with open(cache_file, 'r', encoding='utf-8') as f:
                cache_data = json.load(f)
            
            if cache_key not in cache_data:
                return None
            
            data = cache_data[cache_key]
            result = data.get('result')
            timestamp = data.get('timestamp', 0)
            
            # TTLチェック
            if self.query_cache_ttl is not None:
                if time.time() - timestamp > self.query_cache_ttl:
                    return None  # 期限切れ
            
            # メモリキャッシュにも保存
            self.query_cache[cache_key] = (result, timestamp)
            
            return result
        except Exception as e:  # noqa: BLE001 - キャッシュファイル破損等の未知のエラーでもキャッシュ未ヒット扱いにして継続する
            logger.warning(f"永続化キャッシュの読み込みに失敗: {e}")
            return None
    
    def clear_cache(self, cache_type: Optional[str] = None):
        """
        キャッシュをクリア
        
        Args:
            cache_type: クリアするキャッシュの種類（'node', 'edge', 'query', None=すべて）
        """
        if cache_type is None or cache_type == 'node':
            self.node_cache.clear()
        if cache_type is None or cache_type == 'edge':
            self.edge_cache.clear()
        if cache_type is None or cache_type == 'query':
            self.query_cache.clear()
            
            # 永続化キャッシュも削除
            if self.query_cache_persistent and self.cache_dir:
                cache_file = self.cache_dir / "query_cache.json"
                if cache_file.exists():
                    cache_file.unlink()
    
    def get_cache_stats(self) -> Dict[str, Any]:
        """
        キャッシュ統計情報を取得（Phase 3: 詳細統計を追加）
        
        Returns:
            Dict[str, Any]: キャッシュ統計情報
        """
        # キャッシュヒット率の計算（簡易版）
        expired_count = 0
        if self.query_cache_ttl is not None:
            current_time = time.time()
            for key, (result, timestamp) in self.query_cache.items():
                if current_time - timestamp > self.query_cache_ttl:
                    expired_count += 1
        
        return {
            'node_cache_size': len(self.node_cache),
            'edge_cache_size': len(self.edge_cache),
            'query_cache_size': len(self.query_cache),
            'query_cache_max_size': self.max_memory_cache_size,
            'query_cache_usage_rate': len(self.query_cache) / self.max_memory_cache_size if self.max_memory_cache_size > 0 else 0.0,
            'expired_cache_count': expired_count,
            'enable_query_cache': self.enable_query_cache,
            'query_cache_ttl': self.query_cache_ttl,
            'query_cache_persistent': self.query_cache_persistent
        }

