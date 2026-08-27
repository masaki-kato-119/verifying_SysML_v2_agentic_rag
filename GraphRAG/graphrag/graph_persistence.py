"""
グラフ永続化モジュール（仕様書 技術スタック: JSON / pickle）
"""
import json
import pickle
from pathlib import Path

import networkx as nx


class GraphPersistence:
    """
    グラフ永続化クラス
    
    NetworkXグラフをJSONまたはpickle形式で保存・読み込み
    """
    
    @staticmethod
    def save_json(graph: nx.DiGraph, filepath: str) -> None:
        """
        NetworkXグラフをJSON形式で保存
        チャンク情報は除外（SQLite3で管理）
        
        Args:
            graph: 保存するNetworkX有向グラフ
            filepath: 保存先ファイルパス
        """
        # チャンク情報を一時的に削除（グラフのコピーを作成）
        graph_copy = graph.copy()
        
        # チャンク情報を削除（SQLite3で管理するため）
        if 'source_chunks' in graph_copy.graph:
            del graph_copy.graph['source_chunks']
        if 'node_to_chunks' in graph_copy.graph:
            del graph_copy.graph['node_to_chunks']
        if 'edge_to_chunks' in graph_copy.graph:
            del graph_copy.graph['edge_to_chunks']
        
        # NetworkXのnode_link_data形式に変換
        # edges="links"で将来のバージョンとの互換性を確保
        data = nx.node_link_data(graph_copy, edges="links")
        
        # JSONファイルに保存
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    
    @staticmethod
    def load_json(filepath: str) -> nx.DiGraph:
        """
        JSON形式からNetworkXグラフを読み込み
        チャンク情報はSQLite3から取得する必要がある
        
        Args:
            filepath: 読み込み元ファイルパス
        
        Returns:
            nx.DiGraph: 読み込まれたグラフ
        """
        with open(filepath, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        # node_link_graph形式から復元
        # edges="links"で将来のバージョンとの互換性を確保
        graph = nx.node_link_graph(data, directed=True, multigraph=False, edges="links")
        
        # グラフファイルパスを保存（チャンク取得に使用）
        graph.graph['graph_filepath'] = filepath
        
        return graph
    
    @staticmethod
    def save_pickle(graph: nx.DiGraph, filepath: str) -> None:
        """
        NetworkXグラフをpickle形式で保存
        
        Args:
            graph: 保存するNetworkX有向グラフ
            filepath: 保存先ファイルパス
        """
        with open(filepath, 'wb') as f:
            pickle.dump(graph, f)
    
    @staticmethod
    def load_pickle(filepath: str) -> nx.DiGraph:
        """
        pickle形式からNetworkXグラフを読み込み

        セキュリティ注意: pickle.load()は逆シリアライズ時に任意コードを実行し
        得るため、filepathは信頼できる場所（自分で生成したグラフファイル）に
        限定すること。呼び出し元のGraphRAG/mcp_server.py `resolve_graph_path`が
        プロジェクトルート外のパスを拒否しており、MCPツール経由の外部入力に
        対する主な防御はそちらで行っている。この関数を直接、外部指定パスへ
        呼び出すよう変更しないこと。

        Args:
            filepath: 読み込み元ファイルパス

        Returns:
            nx.DiGraph: 読み込まれたグラフ
        """
        with open(filepath, 'rb') as f:
            graph = pickle.load(f)
        
        # グラフファイルパスを保存（チャンク取得に使用）
        # 既に設定されている場合でも、正規化して統一（データベースのパス形式と一致させる）
        # 注意: ChunkStorage()を新規作成すると_init_database()が呼ばれるため、
        # 既存のChunkStorageインスタンスを使用するか、_normalize_to_relative_path()を静的メソッドにする
        from .chunk_storage import ChunkStorage
        # 既存のインスタンスがあればそれを使用、なければ新規作成
        # ただし、新規作成しても_init_database()は既存データを削除しない（修正済み）
        chunk_storage = ChunkStorage()
        normalized_filepath = chunk_storage._normalize_to_relative_path(filepath)
        graph.graph['graph_filepath'] = normalized_filepath
        
        return graph
    
    @staticmethod
    def save(graph: nx.DiGraph, filepath: str, format: str = 'pickle') -> None:
        """
        グラフを保存（形式を自動判定）
        
        Args:
            graph: 保存するNetworkX有向グラフ
            filepath: 保存先ファイルパス
            format: 保存形式 ('pickle' のみサポート)
                  ファイル拡張子から自動判定も可能
        """
        path = Path(filepath)
        
        # 拡張子から形式を判定
        if format == 'auto' or format is None:
            if path.suffix.lower() in ['.pkl', '.pickle']:
                format = 'pickle'
            else:
                format = 'pickle'  # デフォルト
        
        if format == 'pickle':
            GraphPersistence.save_pickle(graph, filepath)
        else:
            raise ValueError(f"サポートされていない形式: {format} (pickleのみサポート)")
    
    @staticmethod
    def load(filepath: str, format: str = 'auto') -> nx.DiGraph:
        """
        グラフを読み込み（形式を自動判定）
        
        Args:
            filepath: 読み込み元ファイルパス
            format: 読み込み形式 ('pickle', 'auto')
                   'auto'の場合は拡張子から自動判定
        
        Returns:
            nx.DiGraph: 読み込まれたグラフ
        """
        path = Path(filepath)
        
        # 拡張子から形式を判定
        if format == 'auto' or format is None:
            if path.suffix.lower() in ['.pkl', '.pickle']:
                format = 'pickle'
            else:
                format = 'pickle'  # デフォルト
        
        if format == 'pickle':
            return GraphPersistence.load_pickle(filepath)
        else:
            raise ValueError(f"サポートされていない形式: {format} (pickleのみサポート)")
    
    @staticmethod
    def compare_graphs(graph1: nx.DiGraph, graph2: nx.DiGraph) -> dict:
        """
        2つのグラフを比較（グラフ安定度の計算に使用、仕様書 9章）
        
        Args:
            graph1: 比較するグラフ1
            graph2: 比較するグラフ2
        
        Returns:
            dict: 比較結果
                - node_diff: ノードの差分
                - edge_diff: エッジの差分
                - node_diff_rate: ノード差分率
                - edge_diff_rate: エッジ差分率
        """
        nodes1 = set(graph1.nodes())
        nodes2 = set(graph2.nodes())
        edges1 = set(graph1.edges())
        edges2 = set(graph2.edges())
        
        node_union = nodes1 | nodes2
        edge_union = edges1 | edges2
        
        node_diff = {
            'only_in_1': nodes1 - nodes2,
            'only_in_2': nodes2 - nodes1,
            'common': nodes1 & nodes2
        }
        
        edge_diff = {
            'only_in_1': edges1 - edges2,
            'only_in_2': edges2 - edges1,
            'common': edges1 & edges2
        }
        
        node_diff_rate = len(node_diff['only_in_1'] | node_diff['only_in_2']) / len(node_union) if node_union else 0.0
        edge_diff_rate = len(edge_diff['only_in_1'] | edge_diff['only_in_2']) / len(edge_union) if edge_union else 0.0
        
        return {
            'node_diff': node_diff,
            'edge_diff': edge_diff,
            'node_diff_rate': node_diff_rate,
            'edge_diff_rate': edge_diff_rate,
            'node_count_1': len(nodes1),
            'node_count_2': len(nodes2),
            'edge_count_1': len(edges1),
            'edge_count_2': len(edges2)
        }

