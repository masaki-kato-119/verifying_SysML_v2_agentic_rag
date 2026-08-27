"""
MCPサーバー（FastMCP使用）
オントロジー駆動GraphRAGパイプラインをMCPサーバーとして公開
"""
import json
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

import networkx as nx
from fastmcp import FastMCP
from graphrag.config import CACHE_DIR, GRAPHS_DIR, PROJECT_ROOT, SESSION_FILE_PATH
from graphrag.pipeline import OntologyGraphPipeline
from graphrag.query_engine import GraphQueryEngine
from graphrag.workflow_engine import WorkflowEngine

logger = logging.getLogger(__name__)

# MCPサーバーを初期化
mcp = FastMCP("Ontology GraphRAG Server")

# パイプラインインスタンス（シングルトン）
_pipeline: Optional[OntologyGraphPipeline] = None

# グラフキャッシュ（グラフID -> グラフオブジェクト）
_graphs_cache: Dict[str, nx.DiGraph] = {}

# グラフID -> ファイルパスのマッピング
_graph_id_to_filepath: Dict[str, str] = {}

# デフォルトグラフID
_default_graph_id: Optional[str] = None

# アクティブグラフID（コンテキスト管理）
_active_graph_id: Optional[str] = None


def get_query_engine(graph: nx.DiGraph) -> GraphQueryEngine:
    """
    GraphQueryEngineを取得（キャッシュ設定付き）
    
    Args:
        graph: グラフオブジェクト
    
    Returns:
        GraphQueryEngine: 設定済みのクエリエンジン
    """
    pipeline = get_pipeline()
    return GraphQueryEngine(
        graph, 
        chunk_storage=pipeline.chunk_storage,
        cache_dir=str(CACHE_DIR),  # キャッシュディレクトリを設定（cwd 非依存）
        enable_query_cache=True,
        query_cache_persistent=True
    )


def get_pipeline() -> OntologyGraphPipeline:
    """パイプラインインスタンスを取得（シングルトン）"""
    global _pipeline
    if _pipeline is None:
        _pipeline = OntologyGraphPipeline(use_llm=False)
    return _pipeline


def tool_fn(tool):
    """``@mcp.tool()`` で登録された関数を、サーバ内部から呼び出すための実体を返す。

    FastMCP は ``@mcp.tool()`` を適用した名前を ``FunctionTool`` オブジェクトへ
    差し替えるため、モジュール内から ``search_graph(...)`` のように直接呼ぶと
    ``'FunctionTool' object is not callable`` で失敗する。ツールから別のツールを
    呼んでいる箇所（smart_search / query_all_graphs）はこの関数を経由すること。

    Args:
        tool: ``FunctionTool`` または素の関数。

    Returns:
        Callable: 呼び出し可能な実体。
    """
    fn = getattr(tool, "fn", None)
    if fn is not None:
        return fn
    if callable(tool):
        return tool
    raise TypeError(f"呼び出し可能なツール実体を取得できません: {tool!r}")


def resolve_graph_path(filepath: str) -> str:
    """グラフファイルパスを cwd 非依存に解決し、プロジェクト外へのアクセスを拒否する。

    セッションファイルや DB には ``data/graphs/xxx.pkl`` という
    プロジェクトルート基準の相対パスが保存されている。これを cwd 基準で
    開くと、MCP サーバをリポジトリルートから起動した場合に必ず失敗する。

    このパスは最終的に ``pickle.load()`` に渡される（GraphPersistence.load_pickle
    参照）。pickle の逆シリアライズは任意コード実行につながり得るため、
    ``filepath`` にプロジェクト外の絶対パス（例: LLM がプロンプトインジェクション等で
    誘導した先の共有ファイル）を許すと、公開後は任意ファイル読み込み+デシリアライズの
    攻撃面になる。プロジェクトルート配下のみを許可することでこれを防ぐ。

    Args:
        filepath: 絶対パス、またはプロジェクトルート基準の相対パス。

    Returns:
        str: 解決済みのパス（プロジェクトルート配下であることを検証済み）。

    Raises:
        ValueError: 解決後のパスがプロジェクトルート配下にない場合。
    """
    path = Path(filepath)
    resolved = path.resolve() if path.is_absolute() else (PROJECT_ROOT / path).resolve()
    try:
        resolved.relative_to(PROJECT_ROOT.resolve())
    except ValueError:
        raise ValueError(
            f"プロジェクトルート外のパスは指定できません: {resolved} "
            f"(root={PROJECT_ROOT.resolve()})。信頼できないグラフファイルの"
            "pickle読み込みは任意コード実行につながるおそれがあります。"
        ) from None
    return str(resolved)


def get_graph_by_id(graph_id: Optional[str] = None) -> Optional[nx.DiGraph]:
    """
    グラフIDからグラフを取得（改善版）
    
    優先順位:
    1. graph_id（明示的指定）
    2. _active_graph_id（アクティブグラフ）
    3. _default_graph_id（デフォルトグラフ）
    
    Args:
        graph_id: グラフID（省略時はアクティブ→デフォルトの順で自動選択）
    
    Returns:
        nx.DiGraph: グラフオブジェクト、見つからない場合はNone
    """
    # 1. 明示的なgraph_id指定
    if graph_id:
        if graph_id in _graphs_cache:
            return _graphs_cache[graph_id]
        elif graph_id in _graph_id_to_filepath:
            filepath = _graph_id_to_filepath[graph_id]
            return load_graph_from_filepath(filepath, graph_id)
        else:
            return None
    
    # 2. アクティブグラフを使用
    if _active_graph_id:
        if _active_graph_id in _graphs_cache:
            return _graphs_cache[_active_graph_id]
        elif _active_graph_id in _graph_id_to_filepath:
            filepath = _graph_id_to_filepath[_active_graph_id]
            return load_graph_from_filepath(filepath, _active_graph_id)
    
    # 3. デフォルトグラフを使用
    if _default_graph_id:
        if _default_graph_id in _graphs_cache:
            return _graphs_cache[_default_graph_id]
        elif _default_graph_id in _graph_id_to_filepath:
            filepath = _graph_id_to_filepath[_default_graph_id]
            return load_graph_from_filepath(filepath, _default_graph_id)
    
    return None


def load_graph_from_filepath(filepath: str, graph_id: Optional[str] = None) -> Optional[nx.DiGraph]:
    """
    ファイルパスからグラフを読み込み
    
    Args:
        filepath: ファイルパス
        graph_id: グラフID（キャッシュ用）
    
    Returns:
        nx.DiGraph: グラフオブジェクト、失敗時はNone
    """
    try:
        pipeline = get_pipeline()
        graph = pipeline.load_graph(resolve_graph_path(filepath))

        # graph_filepathが設定されていない場合のみ設定（既存の値を保護）
        # 保存する値は解決前の相対パス（DB・セッションの表記と揃えるため）
        if 'graph_filepath' not in graph.graph:
            graph.graph['graph_filepath'] = filepath
        
        # キャッシュに保存
        cache_id = graph_id or filepath
        _graphs_cache[cache_id] = graph
        
        if graph_id:
            _graph_id_to_filepath[graph_id] = filepath
        
        return graph
    
    # MCPツール境界: 想定外の例外もクライアントへのエラー応答に変換するため意図的に広く捕捉する
    except Exception as e:  # noqa: BLE001
        logger.error(f"グラフ読み込みエラー: {filepath} - {e}")
        return None


def initialize_graphs_on_startup() -> List[str]:
    """
    MCPサーバー起動時に GraphRAG/data/graphs/ 内のグラフを自動検出・登録

    Returns:
        List[str]: 自動登録されたグラフIDのリスト
    """
    global _default_graph_id

    graphs_dir = GRAPHS_DIR
    if not graphs_dir.exists():
        logger.warning(
            f"グラフディレクトリが存在しません: {graphs_dir} "
            "（グラフ 0 件で起動します。検索系ツールはすべて失敗します）"
        )
        return []

    auto_registered = []

    # .pklファイルを自動検出
    pkl_files = list(graphs_dir.glob("*.pkl"))
    logger.info(f"{graphs_dir} 内で {len(pkl_files)} 個の .pkl ファイルを検出")
    
    for pkl_file in pkl_files:
        try:
            # ファイル名をgraph_idとして使用
            graph_id = pkl_file.stem
            # セッションファイルへは環境非依存の相対パス（data/graphs/xxx.pkl）で残す。
            # 絶対パスを書き込むと別マシンでセッションを再利用できなくなる。
            filepath = str(pkl_file.relative_to(PROJECT_ROOT))
            
            # 自動登録
            result = register_graph_internal(graph_id, filepath)
            if result["success"]:
                auto_registered.append(graph_id)
                logger.info(f"自動登録成功: {graph_id} <- {filepath}")
            else:
                logger.warning(f"自動登録失敗: {graph_id} - {result.get('error', 'Unknown error')}")
        
        # MCPツール境界: 想定外の例外もクライアントへのエラー応答に変換するため意図的に広く捕捉する
        except Exception as e:  # noqa: BLE001
            logger.warning(f"自動登録エラー: {pkl_file} - {e}")
    
    # 最初に見つかったグラフをデフォルトに設定
    if auto_registered and not _default_graph_id:
        _default_graph_id = auto_registered[0]
        logger.info(f"デフォルトグラフ設定: {_default_graph_id}")
    
    logger.info(f"自動グラフ検出完了: {len(auto_registered)} 個のグラフを登録")
    return auto_registered


def register_graph_internal(graph_id: str, filepath: str) -> Dict:
    """
    グラフを登録する内部関数
    
    Args:
        graph_id: グラフID
        filepath: ファイルパス
    
    Returns:
        Dict: 登録結果
    """
    try:
        # ファイルの存在確認（相対パスはプロジェクトルート基準で解決する）
        if not Path(resolve_graph_path(filepath)).exists():
            return {
                "success": False,
                "error": f"ファイルが見つかりません: {resolve_graph_path(filepath)}"
            }
        
        # グラフを読み込み
        graph = load_graph_from_filepath(filepath, graph_id)
        if graph is None:
            return {
                "success": False,
                "error": f"グラフの読み込みに失敗しました: {filepath}"
            }
        
        # 統計情報を取得
        pipeline = get_pipeline()
        stats = pipeline.get_statistics(graph)
        
        return {
            "success": True,
            "graph_id": graph_id,
            "filepath": filepath,
            "node_count": stats["node_count"],
            "edge_count": stats["edge_count"],
            "auto_registered": True
        }
    
    # MCPツール境界: 想定外の例外もクライアントへのエラー応答に変換するため意図的に広く捕捉する
    except Exception as e:  # noqa: BLE001
        return {
            "success": False,
            "error": str(e)
        }


def save_session_state():
    """
    セッション状態を永続化
    """
    try:
        session_file = SESSION_FILE_PATH
        session_file.parent.mkdir(parents=True, exist_ok=True)
        
        session_data = {
            "graph_id_to_filepath": _graph_id_to_filepath,
            "default_graph_id": _default_graph_id,
            "active_graph_id": _active_graph_id,
            "last_updated": datetime.now().isoformat()
        }
        
        with open(session_file, 'w', encoding='utf-8') as f:
            json.dump(session_data, f, indent=2, ensure_ascii=False)
        
        logger.info(f"セッション状態を保存: {len(_graph_id_to_filepath)} 個のグラフ")
    
    # MCPツール境界: 想定外の例外もクライアントへのエラー応答に変換するため意図的に広く捕捉する
    except Exception as e:  # noqa: BLE001
        logger.warning(f"セッション状態の保存に失敗: {e}")


def load_session_state():
    """
    セッション状態を復元
    """
    global _graph_id_to_filepath, _default_graph_id, _active_graph_id
    
    session_file = SESSION_FILE_PATH
    if not session_file.exists():
        logger.info("セッションファイルが存在しません（初回起動）")
        return
    
    try:
        with open(session_file, 'r', encoding='utf-8') as f:
            session_data = json.load(f)
        
        _graph_id_to_filepath.update(session_data.get("graph_id_to_filepath", {}))
        _default_graph_id = session_data.get("default_graph_id")
        _active_graph_id = session_data.get("active_graph_id")
        
        logger.info(f"セッション状態を復元: {len(_graph_id_to_filepath)} 個のグラフ")
    
    # MCPツール境界: 想定外の例外もクライアントへのエラー応答に変換するため意図的に広く捕捉する
    except Exception as e:  # noqa: BLE001
        logger.warning(f"セッション状態の復元に失敗: {e}")




@mcp.tool()
def load_graph(filepath: str, format: str = "auto") -> Dict:
    """
    保存されたグラフを読み込みます。
    
    Args:
        filepath: 読み込み先ファイルパス
        format: 読み込み形式('pickle', 'auto')
    
    Returns:
        dict: グラフの統計情報
    """
    try:
        pipeline = get_pipeline()
        graph = pipeline.load_graph(resolve_graph_path(filepath), format=format)
        stats = pipeline.get_statistics(graph)
        
        return {
            "success": True,
            "filepath": filepath,
            "node_count": stats["node_count"],
            "edge_count": stats["edge_count"],
            "nodes": stats["nodes"],
            "edges": [
                {
                    "source": edge[0],
                    "target": edge[1],
                    "data": edge[2] if len(edge) > 2 else {}
                }
                for edge in stats["edges"]
            ]
        }
    # MCPツール境界: 想定外の例外もクライアントへのエラー応答に変換するため意図的に広く捕捉する
    except Exception as e:  # noqa: BLE001
        return {
            "success": False,
            "error": str(e)
        }


@mcp.tool()
def get_graph_statistics(filepath: str) -> Dict:
    """
    保存されたグラフの統計情報を取得します。
    
    Args:
        filepath: グラフファイルのパス
    
    Returns:
        dict: グラフの統計情報
    """
    try:
        pipeline = get_pipeline()
        graph = pipeline.load_graph(filepath)
        stats = pipeline.get_statistics(graph)
        
        return {
            "success": True,
            "filepath": filepath,
            "node_count": stats["node_count"],
            "edge_count": stats["edge_count"],
            "nodes": stats["nodes"],
            "edges_count": len(stats["edges"])
        }
    # MCPツール境界: 想定外の例外もクライアントへのエラー応答に変換するため意図的に広く捕捉する
    except Exception as e:  # noqa: BLE001
        return {
            "success": False,
            "error": str(e)
        }


@mcp.tool()
def compare_graphs(filepath1: str, filepath2: str) -> Dict:
    """
    2つのグラフを比較します（グラフ安定度の計算）。
    
    Args:
        filepath1: 比較するグラフのファイルパス
        filepath2: 比較するグラフのファイルパス
    
    Returns:
        dict: 比較結果（ノード差分、エッジ差分など）
    """
    try:
        pipeline = get_pipeline()
        graph1 = pipeline.load_graph(filepath1)
        graph2 = pipeline.load_graph(filepath2)
        
        comparison = pipeline.compare_graphs(graph1, graph2)
        
        return {
            "success": True,
            "node_diff_rate": comparison["node_diff_rate"],
            "edge_diff_rate": comparison["edge_diff_rate"],
            "node_count_1": comparison["node_count_1"],
            "node_count_2": comparison["node_count_2"],
            "edge_count_1": comparison["edge_count_1"],
            "edge_count_2": comparison["edge_count_2"],
            "common_nodes": len(comparison["node_diff"]["common"]),
            "only_in_1_nodes": len(comparison["node_diff"]["only_in_1"]),
            "only_in_2_nodes": len(comparison["node_diff"]["only_in_2"])
        }
    # MCPツール境界: 想定外の例外もクライアントへのエラー応答に変換するため意図的に広く捕捉する
    except Exception as e:  # noqa: BLE001
        return {
            "success": False,
            "error": str(e)
        }


# デバッグ用: 環境変数がサーバーに渡っているか確認するツール
@mcp.tool()
def is_env_set(var_name: str) -> Dict:
    """指定した環境変数がサーバープロセスに設定されているかを返す。

    Returns:
        {"name": str, "present": bool, "value_masked": Optional[str]}
    """
    try:
        val = os.environ.get(var_name)
        if val is None:
            return {"name": var_name, "present": False, "value_masked": None}
        # マスクして返す（セキュリティ上の配慮）
        if len(val) > 8:
            masked = val[:4] + "..." + val[-4:]
        else:
            masked = val
        return {"name": var_name, "present": True, "value_masked": masked}
    except (TypeError, ValueError) as e:
        return {"name": var_name, "present": False, "error": str(e)}


@mcp.tool()
def get_env_masked(var_name: str) -> Dict:
    """環境変数の値をマスクして返す（テスト用途）"""
    try:
        val = os.environ.get(var_name)
        if val is None:
            return {"name": var_name, "value": None}
        if len(val) > 8:
            masked = val[:4] + "..." + val[-4:]
        else:
            masked = val
        return {"name": var_name, "value": masked}
    except (TypeError, ValueError) as e:
        return {"name": var_name, "error": str(e)}


# テキスト処理APIは削除されました（PDF処理のみサポート）

# テキスト処理APIは削除されました（PDF処理のみサポート）


@mcp.tool()
def process_pdf(pdf_filepath: str, language: Optional[str] = None, pages: Optional[List[int]] = None) -> Dict:
    """
    PDFファイルを処理してグラフを構築します。
    
    Args:
        pdf_filepath: PDFファイルのパス
        language: 言語指定（'ja', 'en', None=自動検出）
        pages: 処理するページ番号のリスト（Noneの場合は全ページ、0-indexed）
    
    Returns:
        dict: グラフの統計情報
    """
    pipeline = get_pipeline()
    try:
        if not pipeline.pdf_supported:
            return {
                "success": False,
                "error": "PDF support requires pypdf or pdfplumber",
                "message": "Install with: pip install pypdf or pip install pdfplumber"
            }
        
        graph = pipeline.process_pdf(pdf_filepath, language=language, pages=pages)
        stats = pipeline.get_statistics(graph)
        
        return {
            "success": True,
            "pdf_filepath": pdf_filepath,
            "node_count": stats["node_count"],
            "edge_count": stats["edge_count"],
            "nodes": stats["nodes"],
            "edges": [
                {
                    "source": edge[0],
                    "target": edge[1],
                    "data": edge[2] if len(edge) > 2 else {}
                }
                for edge in stats["edges"]
            ]
        }
    except FileNotFoundError as e:
        return {
            "success": False,
            "error": str(e)
        }
    except ImportError as e:
        return {
            "success": False,
            "error": str(e),
            "message": "PDF support requires pypdf or pdfplumber. Install with: pip install pypdf or pip install pdfplumber"
        }
    # MCPツール境界: 想定外の例外もクライアントへのエラー応答に変換するため意図的に広く捕捉する
    except Exception as e:  # noqa: BLE001
        return {
            "success": False,
            "error": str(e)
        }


@mcp.tool()
def process_pdf_and_save(pdf_filepath: str, language: Optional[str] = None, pages: Optional[List[int]] = None) -> Dict:
    """
    PDFファイルを処理してグラフを生成し、自動的に保存します。
    保存先は常に data/graphs/{PDFファイル名}.pkl です。
    
    Args:
        pdf_filepath: PDFファイルのパス
        language: 言語指定（'ja', 'en', None=自動検出）
        pages: 処理するページ番号のリスト（Noneの場合は全ページ、0-indexed）
    
    Returns:
        dict: 処理結果と保存結果
    """
    from pathlib import Path
    pipeline = get_pipeline()
    try:
        if not pipeline.pdf_supported:
            return {
                "success": False,
                "error": "PDF support requires pypdf or pdfplumber",
                "message": "Install with: pip install pypdf or pip install pdfplumber"
            }
        
        # process_pdf内で自動的に保存される（常に GraphRAG/data/graphs/{PDFファイル名}.pkl）
        graph = pipeline.process_pdf(pdf_filepath, language=language, pages=pages)

        # 保存先ファイルパスを取得（自動生成されたパス）
        graphs_dir = GRAPHS_DIR
        pdf_name = Path(pdf_filepath).stem
        output_filepath = str(graphs_dir / f"{pdf_name}.pkl")
        
        # ドキュメント名を取得
        document_name = graph.graph.get('document_name', Path(pdf_filepath).name)
        
        stats = pipeline.get_statistics(graph)
        
        return {
            "success": True,
            "pdf_filepath": pdf_filepath,
            "output_filepath": output_filepath,
            "document_name": document_name,
            "format": "pickle",
            "node_count": stats["node_count"],
            "edge_count": stats["edge_count"],
            "nodes": stats["nodes"],
            "message": f"PDFを処理してグラフを {output_filepath} に保存しました"
        }
    # MCPツール境界: 想定外の例外もクライアントへのエラー応答に変換するため意図的に広く捕捉する
    except Exception as e:  # noqa: BLE001
        return {
            "success": False,
            "error": str(e)
        }


@mcp.tool()
def get_pdf_metadata(pdf_filepath: str) -> Dict:
    """
    PDFファイルのメタデータを取得します。
    
    Args:
        pdf_filepath: PDFファイルのパス
    
    Returns:
        dict: PDFのメタデータ（タイトル、著者、ページ数など）
    """
    pipeline = get_pipeline()
    try:
        if not pipeline.pdf_supported:
            return {
                "success": False,
                "error": "PDF support requires pypdf or pdfplumber",
                "message": "Install with: pip install pypdf or pip install pdfplumber"
            }
        
        metadata = pipeline.get_pdf_metadata(pdf_filepath)
        return {
            "success": True,
            **metadata
        }
    # MCPツール境界: 想定外の例外もクライアントへのエラー応答に変換するため意図的に広く捕捉する
    except Exception as e:  # noqa: BLE001
        return {
            "success": False,
            "error": str(e)
        }


@mcp.tool()
def register_graph(graph_id: str, filepath: str) -> Dict:
    """
    グラフを登録してIDで管理します。
    
    Args:
        graph_id: グラフID（識別子）
        filepath: グラフファイルのパス
    
    Returns:
        dict: 登録結果
    """
    result = register_graph_internal(graph_id, filepath)
    
    if result["success"]:
        # 最初に登録されたグラフをデフォルトに設定
        global _default_graph_id
        if _default_graph_id is None:
            _default_graph_id = graph_id
        
        # セッション状態を保存
        save_session_state()
    
    return result


@mcp.tool()
def set_active_graph(graph_id_or_filepath: str) -> Dict:
    """
    アクティブグラフを設定（コンテキスト管理）
    
    Args:
        graph_id_or_filepath: グラフIDまたはファイルパス
    
    Returns:
        dict: 設定結果
    """
    global _active_graph_id
    
    # グラフIDとして存在するかチェック
    if graph_id_or_filepath in _graphs_cache or graph_id_or_filepath in _graph_id_to_filepath:
        _active_graph_id = graph_id_or_filepath
        save_session_state()  # セッション状態を保存
        return {
            "success": True,
            "active_graph": graph_id_or_filepath,
            "message": f"アクティブグラフを '{graph_id_or_filepath}' に設定しました"
        }
    
    # ファイルパスとして存在するかチェック
    if Path(graph_id_or_filepath).exists():
        # 自動登録してアクティブに設定
        graph_id = Path(graph_id_or_filepath).stem
        register_result = register_graph_internal(graph_id, graph_id_or_filepath)
        if register_result["success"]:
            _active_graph_id = graph_id
            save_session_state()  # セッション状態を保存
            return {
                "success": True,
                "active_graph": graph_id,
                "auto_registered": True,
                "message": f"'{graph_id}' を自動登録してアクティブに設定しました"
            }
    
    return {
        "success": False,
        "error": f"グラフまたはファイル '{graph_id_or_filepath}' が見つかりません"
    }


@mcp.tool()
def get_active_graph() -> Dict:
    """
    現在のアクティブグラフ情報を取得
    
    Returns:
        dict: アクティブグラフ情報
    """
    return {
        "success": True,
        "active_graph_id": _active_graph_id,
        "default_graph_id": _default_graph_id,
        "registered_graphs": list(_graph_id_to_filepath.keys()),
        "total_registered": len(_graph_id_to_filepath)
    }


@mcp.tool()
def list_graphs() -> Dict:
    """
    登録済みグラフの一覧を取得します。
    
    Returns:
        dict: 登録済みグラフの一覧
    """
    graphs = []
    for graph_id, filepath in _graph_id_to_filepath.items():
        if graph_id in _graphs_cache:
            graph = _graphs_cache[graph_id]
            graphs.append({
                "graph_id": graph_id,
                "filepath": filepath,
                "node_count": graph.number_of_nodes(),
                "edge_count": graph.number_of_edges(),
                "is_default": graph_id == _default_graph_id
            })
    
    return {
        "success": True,
        "graphs": graphs,
        "default_graph_id": _default_graph_id,
        "count": len(graphs)
    }


@mcp.tool()
def set_default_graph(graph_id: str) -> Dict:
    """
    デフォルトグラフを設定します。
    
    Args:
        graph_id: グラフID
    
    Returns:
        dict: 設定結果
    """
    global _default_graph_id
    
    if graph_id not in _graphs_cache and graph_id not in _graph_id_to_filepath:
        return {
            "success": False,
            "error": f"グラフ'{graph_id}' が見つかりません。先に register_graph で登録してください。"
        }
    
    _default_graph_id = graph_id
    
    return {
        "success": True,
        "graph_id": graph_id,
        "message": f"デフォルトグラフを '{graph_id}' に設定しました"
    }


@mcp.tool()
def unregister_graph(graph_id: str) -> Dict:
    """
    登録済みグラフを削除します。
    
    Args:
        graph_id: 削除するグラフID
    
    Returns:
        dict: 削除結果
    """
    global _default_graph_id, _active_graph_id
    
    if graph_id not in _graph_id_to_filepath:
        return {
            "success": False,
            "error": f"グラフ'{graph_id}' は登録されていません。",
            "registered_graphs": list(_graph_id_to_filepath.keys())
        }
    
    # ファイルパスを取得（ログ用）
    filepath = _graph_id_to_filepath.get(graph_id)
    
    # キャッシュから削除
    if graph_id in _graphs_cache:
        del _graphs_cache[graph_id]
    
    # マッピングから削除
    del _graph_id_to_filepath[graph_id]
    
    # デフォルトグラフが削除された場合の処理
    if _default_graph_id == graph_id:
        # 他に登録されているグラフがあれば最初のものをデフォルトに
        if _graph_id_to_filepath:
            _default_graph_id = next(iter(_graph_id_to_filepath.keys()))
            logger.info(f"デフォルトグラフを '{_default_graph_id}' に変更しました")
        else:
            _default_graph_id = None
            logger.info("デフォルトグラフをクリアしました")
    
    # アクティブグラフが削除された場合の処理
    if _active_graph_id == graph_id:
        # デフォルトグラフがあればそれをアクティブに、なければクリア
        _active_graph_id = _default_graph_id
        if _active_graph_id:
            logger.info(f"アクティブグラフを '{_active_graph_id}' に変更しました")
        else:
            logger.info("アクティブグラフをクリアしました")
    
    # セッション状態を保存
    save_session_state()
    
    return {
        "success": True,
        "graph_id": graph_id,
        "filepath": filepath,
        "message": f"グラフ '{graph_id}' を削除しました",
        "new_default_graph": _default_graph_id,
        "new_active_graph": _active_graph_id,
        "remaining_graphs": list(_graph_id_to_filepath.keys()),
        "remaining_count": len(_graph_id_to_filepath)
    }


@mcp.tool()
def clear_all_graphs() -> Dict:
    """
    登録済みグラフを全て削除します。
    
    Returns:
        dict: 削除結果
    """
    global _default_graph_id, _active_graph_id
    
    if not _graph_id_to_filepath:
        return {
            "success": False,
            "error": "削除するグラフがありません。",
            "message": "グラフは既に空です。"
        }
    
    # 削除前の状態を記録
    deleted_count = len(_graph_id_to_filepath)
    deleted_graphs = list(_graph_id_to_filepath.keys())
    
    # 全てクリア
    _graphs_cache.clear()
    _graph_id_to_filepath.clear()
    _default_graph_id = None
    _active_graph_id = None
    
    # セッション状態を保存
    save_session_state()
    
    logger.info(f"全グラフを削除しました: {deleted_graphs}")
    
    return {
        "success": True,
        "message": f"{deleted_count}個のグラフを全て削除しました",
        "deleted_graphs": deleted_graphs,
        "deleted_count": deleted_count
    }


@mcp.tool()
def search_graph(
    query: str,
    graph_id: Optional[str] = None,
    mode: str = "query",
    max_nodes: int = 10,
    explore_depth: int = 1,
    max_results: int = 10,
    max_context_nodes: int = 10,
    max_source_chunks: int = 3,
    max_edges: Optional[int] = None,
    explore_max_nodes: int = 20,
    auto_expand_query: bool = False,
    expansion_min_score: float = 0.5,
    use_cache: bool = True
) -> Dict:
    """
    グラフから情報を検索します（統合検索インターフェース）。
    
    Args:
        query: 検索クエリまたはキーワード
        graph_id: グラフID（省略時はアクティブ→デフォルトの順で自動選択）
        mode: 検索モード
            - "query": クエリ検索（関連ノードも探索、デフォルト）
            - "keyword": キーワード検索（ノード名の部分一致のみ）
            - "context": コンテキスト取得（LLMが直接使える形式）
        max_nodes: 最大ノード数（mode="query"の場合）
        explore_depth: マッチしたノードからの探索深度（mode="query"の場合）
        max_results: 最大結果数（mode="keyword"の場合）
        max_context_nodes: 最大コンテキストノード数（mode="context"の場合、デフォルト 10）
        max_source_chunks: ノードあたりの最大ソースチャンク数（mode="query"の場合、デフォルト 3）
        max_edges: 返却するエッジの最大数（mode="query"の場合、Noneの場合は制限なし）
        explore_max_nodes: 探索時の最大ノード数（mode="query"の場合、デフォルト 20）
        auto_expand_query: 自動クエリ拡張を使用するか（mode="query"の場合）
        expansion_min_score: 拡張時の最小スコア（auto_expand_queryがTrueの場合）
        use_cache: キャッシュを使用するか（デフォルト True）
    
    Returns:
        dict: 検索結果
    """
    try:
        graph = get_graph_by_id(graph_id=graph_id)
        
        if graph is None:
            return {
                "success": False,
                "error": "グラフが見つかりません。",
                "suggestions": [
                    "set_active_graph()でアクティブグラフを設定",
                    "graph_idパラメータで登録済みグラフを指定"
                ],
                "registered_graphs": list(_graph_id_to_filepath.keys()),
                "active_graph": _active_graph_id,
                "default_graph": _default_graph_id
            }
        
        query_engine = get_query_engine(graph)
        
        if mode == "keyword":
            # キーワード検索
            results = query_engine.search_nodes(query, max_results=max_results)
            return {
                "success": True,
                "mode": mode,
                "keyword": query,
                "results": results,
                "count": len(results)
            }
        elif mode == "context":
            # コンテキスト取得
            result = query_engine.get_context_for_query(query, max_context_nodes=max_context_nodes)
            result["mode"] = mode
            return result
        else:
            # デフォルト クエリ検索
            if auto_expand_query:
                # 自動クエリ拡張を使用
                result = query_engine.search_with_auto_expansion(
                    query=query,
                    max_nodes=max_nodes,
                    explore_depth=explore_depth,
                    max_source_chunks=max_source_chunks,
                    max_edges=max_edges,
                    explore_max_nodes=explore_max_nodes,
                    expansion_min_score=expansion_min_score
                )
            else:
                # 通常のクエリ検索
                result = query_engine.query_graph(
                    query, 
                    max_nodes=max_nodes, 
                    explore_depth=explore_depth,
                    max_source_chunks=max_source_chunks,
                    max_edges=max_edges,
                    explore_max_nodes=explore_max_nodes,
                    use_cache=use_cache
                )
            result["mode"] = mode
            return {
                "success": True,
                **result
            }
    # MCPツール境界: 想定外の例外もクライアントへのエラー応答に変換するため意図的に広く捕捉する
    except Exception as e:  # noqa: BLE001
        return {
            "success": False,
            "error": str(e),
            "mode": mode
        }


@mcp.tool()
def explore_graph(
    start_node: str,
    graph_id: Optional[str] = None,
    mode: str = "depth",
    depth: int = 2,
    max_nodes: int = 50,
    relation_type: Optional[str] = None
) -> Dict:
    """
    グラフを探索します（統合探索インターフェース）。
    
    Args:
        start_node: 起点ノード名
        graph_id: グラフID（省略時はアクティブ→デフォルトの順で自動選択）
        mode: 探索モード
            - "depth": 指定深度まで探索（デフォルト）
            - "related": 関連ノードのみ取得（depth=1相当）
            - "details": ノード詳細情報を取得
        depth: 探索深度（mode="depth"の場合）
        max_nodes: 最大ノード数（mode="depth"の場合）
        relation_type: 関係タイプでフィルタ（mode="related"の場合）
    
    Returns:
        dict: 探索結果
    """
    try:
        graph = get_graph_by_id(graph_id=graph_id)
        
        if graph is None:
            return {
                "success": False,
                "error": "グラフが見つかりません。",
                "suggestions": [
                    "set_active_graph()でアクティブグラフを設定",
                    "graph_idパラメータで登録済みグラフを指定"
                ],
                "registered_graphs": list(_graph_id_to_filepath.keys()),
                "active_graph": _active_graph_id,
                "default_graph": _default_graph_id
            }
        
        query_engine = get_query_engine(graph)
        
        if mode == "related":
            # 関連ノード取得
            result = query_engine.get_related_nodes(start_node, relation_type=relation_type)
            result["mode"] = mode
            return result
        elif mode == "details":
            # ノード詳細取得
            if start_node not in graph.nodes():
                return {
                    "success": False,
                    "error": f"ノード'{start_node}' が見つかりません",
                    "mode": mode
                }
            
            node_data = graph.nodes[start_node]
            neighbors = list(graph.neighbors(start_node))
            predecessors = list(graph.predecessors(start_node))
            
            return {
                "success": True,
                "mode": mode,
                "node_name": start_node,
                "attributes": dict(node_data),
                "neighbors": neighbors,
                "predecessors": predecessors,
                "degree": graph.degree(start_node)
            }
        else:
            # デフォルト 深度探索
            result = query_engine.explore_graph(start_node, depth=depth, max_nodes=max_nodes)
            result["mode"] = mode
            return result
    # MCPツール境界: 想定外の例外もクライアントへのエラー応答に変換するため意図的に広く捕捉する
    except Exception as e:  # noqa: BLE001
        return {
            "success": False,
            "error": str(e),
            "mode": mode
        }


@mcp.tool()
def search_graph_workflow(
    keyword: str,
    workflow_type: str = "keyword_explore",
    graph_id: Optional[str] = None,
    max_nodes: int = 5,
    explore_depth: int = 1,
    explore_max_nodes: int = 10,
    max_source_chunks: int = 3,
    max_edges: Optional[int] = 20
) -> Dict:
    """
    ワークフローを使用してグラフから情報を検索します。
    
    Args:
        keyword: 検索キーワード
        workflow_type: ワークフロータイプ（現在は "keyword_explore" のみ対応）
        graph_id: グラフID（省略時はアクティブ→デフォルトの順で自動選択）
        max_nodes: 最大ノード数（検索結果）
        explore_depth: 探索深度
        explore_max_nodes: 探索時の最大ノード数
        max_source_chunks: ノードあたりの最大ソースチャンク数
        max_edges: 返却するエッジの最大数（Noneの場合は制限なし）
    
    Returns:
        dict: ワークフロー実行結果
    """
    try:
        graph = get_graph_by_id(graph_id=graph_id)
        
        if graph is None:
            return {
                "success": False,
                "error": "グラフが見つかりません。",
                "suggestions": [
                    "set_active_graph()でアクティブグラフを設定",
                    "graph_idパラメータで登録済みグラフを指定"
                ],
                "registered_graphs": list(_graph_id_to_filepath.keys()),
                "active_graph": _active_graph_id,
                "default_graph": _default_graph_id
            }
        
        pipeline = get_pipeline()
        workflow_engine = WorkflowEngine(graph, chunk_storage=pipeline.chunk_storage)
        
        if workflow_type == "keyword_explore":
            result = workflow_engine.keyword_explore(
                keyword=keyword,
                max_nodes=max_nodes,
                explore_depth=explore_depth,
                explore_max_nodes=explore_max_nodes,
                max_source_chunks=max_source_chunks,
                max_edges=max_edges
            )
            return result
        else:
            return {
                "success": False,
                "error": f"不明なワークフロータイプ: {workflow_type}",
                "supported_workflows": ["keyword_explore"]
            }
    # MCPツール境界: 想定外の例外もクライアントへのエラー応答に変換するため意図的に広く捕捉する
    except Exception as e:  # noqa: BLE001
        return {
            "success": False,
            "error": str(e),
            "workflow_type": workflow_type
        }


@mcp.tool()
def query_multiple_graphs(
    query: str,
    graph_ids: Optional[List[str]] = None,
    filepaths: Optional[List[str]] = None,
    max_nodes_per_graph: int = 10,
    explore_depth: int = 1
) -> Dict:
    """
    複数のグラフから横断的に検索します。
    
    Args:
        query: 検索クエリ
        graph_ids: グラフIDのリスト（登録済みグラフを使用する場合）
        filepaths: グラフファイルのパスのリスト（graph_idsが指定されていない場合）
        max_nodes_per_graph: グラフあたりの最大ノード数
        explore_depth: マッチしたノードからの探索深度
    
    Returns:
        dict: 統合された検索結果
    """
    try:
        graphs = []
        
        # グラフIDが指定されている場合
        if graph_ids:
            for graph_id in graph_ids:
                graph = get_graph_by_id(graph_id=graph_id)
                if graph is None:
                    return {
                        "success": False,
                        "error": f"グラフ'{graph_id}' が見つかりません。先に register_graph で登録してください。"
                    }
                graphs.append(graph)
        # ファイルパスが指定されている場合
        elif filepaths:
            for filepath in filepaths:
                graph = load_graph_from_filepath(filepath)
                if graph is None:
                    return {
                        "success": False,
                        "error": f"グラフファイル '{filepath}' が見つかりません。"
                    }
                graphs.append(graph)
        else:
            return {
                "success": False,
                "error": "graph_idsまたはfilepathsを指定してください。"
            }
        
        # query_multiple_graphsは内部で各グラフのgraph_filepathからchunk_storageを取得する
        result = GraphQueryEngine.query_multiple_graphs(
            graphs, query, max_nodes_per_graph=max_nodes_per_graph, explore_depth=explore_depth
        )
        
        return {
            "success": True,
            **result
        }
    # MCPツール境界: 想定外の例外もクライアントへのエラー応答に変換するため意図的に広く捕捉する
    except Exception as e:  # noqa: BLE001
        return {
            "success": False,
            "error": str(e)
        }


@mcp.tool()
def query_all_graphs(
    query: str,
    max_nodes_per_graph: int = 5,
    explore_depth: int = 1,
    include_inactive: bool = True
) -> Dict:
    """
    登録済み全グラフから横断検索
    
    Args:
        query: 検索クエリ
        max_nodes_per_graph: グラフあたりの最大ノード数
        explore_depth: 探索深度
        include_inactive: 非アクティブグラフも含めるか
    
    Returns:
        dict: 横断検索結果
    """
    try:
        # 対象グラフを自動収集
        target_graph_ids = []
        
        if include_inactive:
            # 登録済み全グラフを対象
            target_graph_ids = list(_graph_id_to_filepath.keys())
        else:
            # アクティブグラフのみ
            if _active_graph_id:
                target_graph_ids = [_active_graph_id]
        
        if not target_graph_ids:
            return {
                "success": False,
                "error": "検索対象のグラフがありません"
            }
        
        # 既存のquery_multiple_graphsを呼び出し
        return tool_fn(query_multiple_graphs)(
            query=query,
            graph_ids=target_graph_ids,
            max_nodes_per_graph=max_nodes_per_graph,
            explore_depth=explore_depth
        )
    
    # MCPツール境界: 想定外の例外もクライアントへのエラー応答に変換するため意図的に広く捕捉する
    except Exception as e:  # noqa: BLE001
        return {
            "success": False,
            "error": str(e)
        }


@mcp.tool()
def smart_search(
    query: str,
    search_scope: str = "active",  # "active", "all", "auto"
    max_results: int = 10
) -> Dict:
    """
    スマート検索（自動的に最適なグラフを選択）
    
    Args:
        query: 検索クエリ
        search_scope: 検索範囲（"active", "all", "auto"）
        max_results: 最大結果数
    
    Returns:
        dict: 検索結果
    """
    try:
        if search_scope == "active":
            # アクティブグラフのみで検索
            return tool_fn(search_graph)(query=query, max_nodes=max_results)

        elif search_scope == "all":
            # 全グラフで横断検索
            return tool_fn(query_all_graphs)(query=query, max_nodes_per_graph=max_results//2)

        elif search_scope == "auto":
            # 自動判定：まずアクティブで検索、結果が少なければ全グラフ
            active_result = tool_fn(search_graph)(query=query, max_nodes=max_results)

            if active_result.get("success") and len(active_result.get("matched_nodes", [])) >= 3:
                # アクティブグラフで十分な結果
                active_result["search_scope_used"] = "active"
                return active_result
            else:
                # 全グラフで再検索
                all_result = tool_fn(query_all_graphs)(
                    query=query, max_nodes_per_graph=max_results // 3
                )
                if all_result.get("success"):
                    all_result["search_scope_used"] = "all"
                    all_result["fallback_reason"] = "アクティブグラフでの結果が不十分"
                return all_result
        
        return {
            "success": False,
            "error": f"不正な検索範囲: {search_scope}。'active', 'all', 'auto' のいずれかを指定してください。"
        }
    
    # MCPツール境界: 想定外の例外もクライアントへのエラー応答に変換するため意図的に広く捕捉する
    except Exception as e:  # noqa: BLE001
        return {
            "success": False,
            "error": str(e)
        }


@mcp.tool()
def get_source_text(
    node_name: str,
    graph_id: Optional[str] = None,
    max_chunks: int = 5
) -> Dict:
    """
    ノードに関連する元のテキストチャンクを取得します。
    
    Args:
        node_name: ノード名
        graph_id: グラフID（省略時はアクティブ→デフォルトの順で自動選択）
        max_chunks: 最大チャンク数
    
    Returns:
        dict: 元のテキストチャンクのリスト
    """
    try:
        graph = get_graph_by_id(graph_id=graph_id)
        
        if graph is None:
            return {
                "success": False,
                "error": "グラフが見つかりません。",
                "suggestions": [
                    "set_active_graph()でアクティブグラフを設定",
                    "graph_idパラメータで登録済みグラフを指定"
                ],
                "registered_graphs": list(_graph_id_to_filepath.keys()),
                "active_graph": _active_graph_id,
                "default_graph": _default_graph_id
            }
        
        pipeline = get_pipeline()
        query_engine = GraphQueryEngine(graph, chunk_storage=pipeline.chunk_storage)
        
        # デバッグ情報を取得
        graph_filepath = graph.graph.get('graph_filepath')
        graph_id = query_engine.graph_id
        
        # デバッグログ
        logger.info(f"MCP get_source_text: graph_id={graph_id}, graph_filepath={graph_filepath}, node_name={node_name}")
        
        # デバッグ: 直接ChunkStorageから取得してみる
        direct_chunk_ids = None
        if graph_id:
            logger.info(f"MCP get_source_text: 直接ChunkStorageから取得開始 graph_id={graph_id}, node_name={node_name}")
            direct_chunk_ids = pipeline.chunk_storage.get_node_chunks(
                graph_id, 
                node_name
            )
            logger.info(f"MCP get_source_text: 直接ChunkStorageから取得結果, chunk_ids={len(direct_chunk_ids) if direct_chunk_ids else 0}, chunk_ids={direct_chunk_ids[:5] if direct_chunk_ids else []}")
        
        logger.info(f"MCP get_source_text: query_engine.get_source_text()を呼び出し node_name={node_name}, max_chunks={max_chunks}")
        source_texts = query_engine.get_source_text(node_name, max_chunks=max_chunks)
        logger.info(f"MCP get_source_text: query_engine.get_source_text()の結果, source_texts数={len(source_texts) if source_texts else 0}")
        
        result = {
            "success": True,
            "node_name": node_name,
            "source_texts": source_texts,
            "count": len(source_texts)
        }
        
        # デバッグ情報を追加（source_textsが空の場合）
        if not source_texts:
            # チャンクIDを直接確認（複数の方法で試す）
            chunk_ids = None
            chunk_ids_direct = direct_chunk_ids  # 上で取得したものを使用
            if graph_id and not chunk_ids_direct:
                # 直接ChunkStorageから取得
                chunk_ids_direct = pipeline.chunk_storage.get_node_chunks(
                    graph_id, 
                    node_name
                )
            
            # さらに、GraphQueryEngine経由でも取得してみる
            if graph_id:
                chunk_ids = query_engine.chunk_storage.get_node_chunks(
                    graph_id, 
                    node_name
                )
            
            # チャンクが存在するか確認
            chunks_exist = False
            if graph_id and chunk_ids_direct:
                chunks = pipeline.chunk_storage.get_chunks(graph_id, chunk_ids_direct[:3])
                chunks_exist = len(chunks) > 0
            
            # デバッグ: データベースパスと存在確認
            db_path = str(pipeline.chunk_storage.db_path)
            import os
            db_exists = os.path.exists(db_path)
            
            # 追加デバッグ: 直接SQLクエリで確認
            debug_sql_count = 0
            try:
                import sqlite3
                with sqlite3.connect(db_path) as conn:
                    cursor = conn.cursor()
                    cursor.execute('SELECT COUNT(*) FROM node_chunks WHERE graph_id = ? AND node_name = ?', (graph_id, node_name))
                    debug_sql_count = cursor.fetchone()[0]
            except sqlite3.Error as sql_e:
                debug_sql_count = f"SQL Error: {sql_e}"
            
            result["debug"] = {
                "graph_filepath": graph_filepath,
                "graph_id": graph_id,
                "has_graph_filepath": graph_filepath is not None,
                "has_graph_id": graph_id is not None,
                "chunk_ids_count": len(chunk_ids) if chunk_ids else 0,
                "chunk_ids_direct_count": len(chunk_ids_direct) if chunk_ids_direct else 0,
                "chunks_exist": chunks_exist,
                "query_engine_graph_id": query_engine.graph_id if hasattr(query_engine, 'graph_id') else None,
                "db_path": db_path,
                "db_exists": db_exists,
                "direct_sql_count": debug_sql_count,
                "pipeline_chunk_storage_db_path": str(pipeline.chunk_storage.db_path),
                "query_engine_chunk_storage_db_path": str(query_engine.chunk_storage.db_path),
                "same_chunk_storage": pipeline.chunk_storage is query_engine.chunk_storage
            }
        
        return result
    # MCPツール境界: 想定外の例外もクライアントへのエラー応答に変換するため意図的に広く捕捉する
    except Exception as e:  # noqa: BLE001
        return {
            "success": False,
            "error": str(e)
        }


@mcp.tool()
def get_edge_source_text(
    source: str,
    target: str,
    graph_id: Optional[str] = None,
    max_chunks: int = 5
) -> Dict:
    """
    エッジに関連する元のテキストチャンクを取得します。
    
    Args:
        source: ソースノード名
        target: ターゲットノード名
        graph_id: グラフID（省略時はアクティブ→デフォルトの順で自動選択）
        max_chunks: 最大チャンク数
    
    Returns:
        dict: 元のテキストチャンクのリスト
    """
    try:
        graph = get_graph_by_id(graph_id=graph_id)
        
        if graph is None:
            return {
                "success": False,
                "error": "グラフが見つかりません。",
                "suggestions": [
                    "set_active_graph()でアクティブグラフを設定",
                    "graph_idパラメータで登録済みグラフを指定"
                ],
                "registered_graphs": list(_graph_id_to_filepath.keys()),
                "active_graph": _active_graph_id,
                "default_graph": _default_graph_id
            }
        
        pipeline = get_pipeline()
        query_engine = GraphQueryEngine(graph, chunk_storage=pipeline.chunk_storage)
        
        source_texts = query_engine.get_edge_source_text(source, target, max_chunks=max_chunks)
        
        return {
            "success": True,
            "source": source,
            "target": target,
            "source_texts": source_texts,
            "count": len(source_texts)
        }
    # MCPツール境界: 想定外の例外もクライアントへのエラー応答に変換するため意図的に広く捕捉する
    except Exception as e:  # noqa: BLE001
        return {
            "success": False,
            "error": str(e)
        }


@mcp.tool()
def find_path(
    start_node: str,
    end_node: str,
    graph_id: Optional[str] = None,
    relation_filter: Optional[Union[str, List[str]]] = None,
    max_depth: Optional[int] = None,
    exclude_stopwords: bool = True,
    node_type_filter: Optional[List[str]] = None,
    min_path_quality: float = 0.3
) -> Dict:
    """
    2つのノード間のパスを探索します（Phase 3改善版）。
    
    Args:
        start_node: 開始ノード名
        end_node: 終了ノード名
        graph_id: グラフID（省略時はアクティブ→デフォルトの順で自動選択）
        relation_filter: 関係タイプでフィルタ（文字列または文字列のリスト、Phase 3）
        max_depth: 最大探索深度（オプション）
        exclude_stopwords: ストップワードノードを除外するか（デフォルト: True、Phase 3）
        node_type_filter: 許可するノード種別のリスト（オプション、Phase 3）
        min_path_quality: 最小パス品質スコア（0.0-1.0、デフォルト: 0.3、Phase 3）
    
    Returns:
        dict: パス探索結果
    """
    try:
        graph = get_graph_by_id(graph_id=graph_id)
        
        if graph is None:
            return {
                "success": False,
                "error": "グラフが見つかりません。",
                "suggestions": [
                    "set_active_graph()でアクティブグラフを設定",
                    "graph_idパラメータで登録済みグラフを指定"
                ],
                "registered_graphs": list(_graph_id_to_filepath.keys()),
                "active_graph": _active_graph_id,
                "default_graph": _default_graph_id
            }
        
        query_engine = get_query_engine(graph)
        
        # node_type_filterをSetに変換
        node_type_filter_set = None
        if node_type_filter:
            node_type_filter_set = set(node_type_filter)
        
        result = query_engine.find_path(
            start_node, 
            end_node, 
            relation_filter=relation_filter, 
            max_depth=max_depth,
            exclude_stopwords=exclude_stopwords,
            node_type_filter=node_type_filter_set,
            min_path_quality=min_path_quality
        )
        
        return {
            "success": True,
            **result
        }
    # MCPツール境界: 想定外の例外もクライアントへのエラー応答に変換するため意図的に広く捕捉する
    except Exception as e:  # noqa: BLE001
        return {
            "success": False,
            "error": str(e)
        }


@mcp.tool()
def find_entry_points(
    query: str,
    graph_id: Optional[str] = None,
    max_entries: int = 3
) -> Dict:
    """
    クエリからエントリーポイント（探索開始ノード）を発見します（Phase 2）。
    
    Args:
        query: 検索クエリ
        graph_id: グラフID（省略時はアクティブ→デフォルトの順で自動選択）
        max_entries: 最大エントリーポイント数（デフォルト: 3）
    
    Returns:
        dict: エントリーポイントのリスト
    """
    try:
        graph = get_graph_by_id(graph_id=graph_id)
        
        if graph is None:
            return {
                "success": False,
                "error": "グラフが見つかりません。",
                "suggestions": [
                    "set_active_graph()でアクティブグラフを設定",
                    "graph_idパラメータで登録済みグラフを指定"
                ],
                "registered_graphs": list(_graph_id_to_filepath.keys()),
                "active_graph": _active_graph_id,
                "default_graph": _default_graph_id
            }
        
        query_engine = get_query_engine(graph)
        
        entry_points = query_engine.entry_finder.find_entry_points(query, max_entries=max_entries)
        
        return {
            "success": True,
            "query": query,
            "entry_points": entry_points,
            "count": len(entry_points)
        }
    # MCPツール境界: 想定外の例外もクライアントへのエラー応答に変換するため意図的に広く捕捉する
    except Exception as e:  # noqa: BLE001
        return {
            "success": False,
            "error": str(e)
        }


@mcp.tool()
def get_node_signage(
    node_name: str,
    graph_id: Optional[str] = None
) -> Dict:
    """
    ノードの標識情報（ナビゲーション情報）を取得します（Phase 2）。
    
    Args:
        node_name: ノード名
        graph_id: グラフID（省略時はアクティブ→デフォルトの順で自動選択）
    
    Returns:
        dict: ノードの標識情報（entry_point, exit_routes, warnings）
    """
    try:
        graph = get_graph_by_id(graph_id=graph_id)
        
        if graph is None:
            return {
                "success": False,
                "error": "グラフが見つかりません。",
                "suggestions": [
                    "set_active_graph()でアクティブグラフを設定",
                    "graph_idパラメータで登録済みグラフを指定"
                ],
                "registered_graphs": list(_graph_id_to_filepath.keys()),
                "active_graph": _active_graph_id,
                "default_graph": _default_graph_id
            }
        
        if node_name not in graph.nodes():
            return {
                "success": False,
                "error": f"ノード '{node_name}' が見つかりません"
            }
        
        query_engine = get_query_engine(graph)
        
        signage = query_engine.signage_manager.get_signage(node_name)
        
        return {
            "success": True,
            "node_name": node_name,
            "signage": signage
        }
    # MCPツール境界: 想定外の例外もクライアントへのエラー応答に変換するため意図的に広く捕捉する
    except Exception as e:  # noqa: BLE001
        return {
            "success": False,
            "error": str(e)
        }


@mcp.tool()
def validate_sysml_model(
    sysml_model_text: str,
    graph_id: Optional[str] = None,
    strict_mode: bool = True
) -> Dict:
    """
    SysMLモデルを高度なリンターで検証します。
    
    既存のsysml_v2_checker_advanced.pyを使用して、完全なSysML v2構文解析と
    高度なルールチェック（参照整合性、型チェック、継承チェックなど）を実行します。
    
    Args:
        sysml_model_text: 検証するSysMLモデルのテキスト
        graph_id: グラフID（省略時はアクティブ→デフォルトの順で自動選択）
        strict_mode: True=仕様準拠モード、False=後方互換モード
    
    Returns:
        dict: 詳細な検証結果（AST、リンター結果、グラフとの照合）
    """
    try:
        # 既存の高度なリンターを使用
        from sysml_v2_checker_advanced import lint_sysml, parse_sysml
        
        # 1. SysML v2構文解析
        ast = parse_sysml(sysml_model_text, strict=strict_mode)
        
        if ast.get("type") == "error":
            return {
                "success": False,
                "error": "SysML v2構文エラー",
                "parse_error": ast.get("message"),
                "recommendation": "SysML v2の構文を確認してください。strict_mode=Falseで後方互換モードを試すこともできます。"
            }
        
        # 2. 高度なリンターチェック
        lint_issues = lint_sysml(ast)
        
        # 3. グラフとの照合（オプション）
        graph_analysis = None
        if graph_id or _active_graph_id or _default_graph_id:
            graph = get_graph_by_id(graph_id=graph_id)
            if graph:
                graph_analysis = _analyze_sysml_with_graph(ast, graph)
        
        # 4. 結果の整理
        errors = [issue for issue in lint_issues if issue.severity == "error"]
        warnings = [issue for issue in lint_issues if issue.severity == "warning"]
        infos = [issue for issue in lint_issues if issue.severity == "info"]
        
        return {
            "success": True,
            "validation_type": "advanced_linter",
            "parse_success": True,
            "ast_summary": _summarize_ast(ast),
            "lint_results": {
                "total_issues": len(lint_issues),
                "errors": len(errors),
                "warnings": len(warnings),
                "infos": len(infos),
                "error_details": [_format_lint_issue(issue) for issue in errors],
                "warning_details": [_format_lint_issue(issue) for issue in warnings],
                "info_details": [_format_lint_issue(issue) for issue in infos]
            },
            "graph_analysis": graph_analysis,
            "recommendations": _generate_validation_recommendations(errors, warnings, graph_analysis),
            "quality_score": _calculate_quality_score(lint_issues),
            "strict_mode": strict_mode
        }
        
    except ImportError:
        return {
            "success": False,
            "error": "SysML v2リンターが利用できません",
            "details": "sysml_v2_checker_advanced.pyが見つかりません",
            "recommendation": "高度なSysML v2検証には、sysml_v2_checker_advanced.pyが必要です"
        }
    # MCPツール境界: 想定外の例外もクライアントへのエラー応答に変換するため意図的に広く捕捉する
    except Exception as e:  # noqa: BLE001
        return {
            "success": False,
            "error": f"検証中にエラーが発生しました: {str(e)}",
            "recommendation": "SysMLモデルの構文を確認してください"
        }


def _summarize_ast(ast: Dict[str, Any]) -> Dict[str, Any]:
    """ASTの概要を生成"""
    def count_nodes_by_type(node, counts=None):
        if counts is None:
            counts = {}
        
        if isinstance(node, dict) and "type" in node:
            node_type = node["type"]
            counts[node_type] = counts.get(node_type, 0) + 1
            
            if "children" in node:
                for child in node["children"]:
                    count_nodes_by_type(child, counts)
        elif isinstance(node, list):
            for item in node:
                count_nodes_by_type(item, counts)
        
        return counts
    
    node_counts = count_nodes_by_type(ast)
    
    # 主要な要素を抽出
    key_elements = {
        "definitions": sum(counts for node_type, counts in node_counts.items() 
                          if "def" in node_type.lower()),
        "parts": node_counts.get("part_def_stmt", 0) + node_counts.get("part_usage_stmt", 0),
        "actions": node_counts.get("action_def_stmt", 0) + node_counts.get("action_usage_stmt", 0),
        "connections": node_counts.get("connection_def_stmt", 0),
        "requirements": node_counts.get("requirement_def_stmt", 0),
        "total_nodes": sum(node_counts.values())
    }
    
    return {
        "key_elements": key_elements,
        "node_type_counts": dict(sorted(node_counts.items(), key=lambda x: x[1], reverse=True)[:10])
    }


def _format_lint_issue(issue) -> Dict[str, Any]:
    """リンター問題を辞書形式にフォーマット"""
    return {
        "severity": issue.severity,
        "rule": issue.rule,
        "message": issue.message,
        "location": issue.location,
        "suggestion": getattr(issue, 'suggestion', None)
    }


def _analyze_sysml_with_graph(ast: Dict[str, Any], graph: nx.DiGraph) -> Dict[str, Any]:
    """SysMLモデルとグラフの照合分析"""
    def extract_identifiers(node, identifiers=None):
        if identifiers is None:
            identifiers = set()
        
        if isinstance(node, dict):
            # 識別子を抽出
            if node.get("type") == "simple_id" and "children" in node:
                for child in node["children"]:
                    if isinstance(child, str):
                        identifiers.add(child)
            
            # 再帰的に探索
            if "children" in node:
                for child in node["children"]:
                    extract_identifiers(child, identifiers)
        elif isinstance(node, list):
            for item in node:
                extract_identifiers(item, identifiers)
        
        return identifiers
    
    model_identifiers = extract_identifiers(ast)
    graph_nodes = set(node.lower() for node in graph.nodes())
    
    matched = []
    unmatched = []
    
    for identifier in model_identifiers:
        if identifier.lower() in graph_nodes:
            matched.append(identifier)
        else:
            # 部分一致を確認
            partial_matches = [node for node in graph.nodes() 
                             if identifier.lower() in node.lower() or node.lower() in identifier.lower()]
            if partial_matches:
                matched.append({
                    "identifier": identifier,
                    "partial_matches": partial_matches[:3]
                })
            else:
                unmatched.append(identifier)
    
    return {
        "model_identifiers": list(model_identifiers),
        "matched_with_graph": matched,
        "unmatched_with_graph": unmatched,
        "match_ratio": len(matched) / len(model_identifiers) if model_identifiers else 0.0,
        "graph_coverage": f"{len(matched)}/{len(model_identifiers)} identifiers matched"
    }


def _generate_validation_recommendations(errors: List, warnings: List, graph_analysis: Optional[Dict]) -> List[str]:
    """検証結果に基づく推奨事項を生成"""
    recommendations = []
    
    if errors:
        recommendations.append(f"{len(errors)}個の構文エラーが検出されました。修正が必要です。")
    
    if warnings:
        recommendations.append(f"{len(warnings)}個の警告があります。品質向上のため確認を推奨します。")
    
    if graph_analysis:
        match_ratio = graph_analysis.get("match_ratio", 0.0)
        if match_ratio < 0.5:
            recommendations.append(f"グラフとの一致率が低いです（{match_ratio:.1%}）。仕様書との整合性を確認してください。")
        elif match_ratio > 0.8:
            recommendations.append(f"グラフとの一致率が高いです（{match_ratio:.1%}）。仕様書に準拠したモデルです。")
    
    if not errors and not warnings:
        recommendations.append("構文エラーは検出されませんでした。高品質なSysMLモデルです。")
    
    return recommendations


def _calculate_quality_score(lint_issues: List) -> Dict[str, Any]:
    """品質スコアを計算"""
    errors = sum(1 for issue in lint_issues if issue.severity == "error")
    warnings = sum(1 for issue in lint_issues if issue.severity == "warning")
    
    # 100点満点でスコア計算
    score = 100
    score -= errors * 20  # エラー1個につき20点減点
    score -= warnings * 5  # 警告1個につき5点減点
    score = max(0, score)  # 0点未満にはしない
    
    if score >= 90:
        grade = "A"
        comment = "優秀"
    elif score >= 80:
        grade = "B"
        comment = "良好"
    elif score >= 70:
        grade = "C"
        comment = "普通"
    elif score >= 60:
        grade = "D"
        comment = "要改善"
    else:
        grade = "F"
        comment = "大幅な改善が必要"
    
    return {
        "score": score,
        "grade": grade,
        "comment": comment,
        "breakdown": {
            "errors": errors,
            "warnings": warnings,
            "error_penalty": errors * 20,
            "warning_penalty": warnings * 5
        }
    }


@mcp.tool()
def get_learning_stats(
    graph_id: Optional[str] = None
) -> Dict:
    """
    学習・適応機能の統計情報を取得します（Phase 4）。
    
    Args:
        graph_id: グラフID（省略時はアクティブ→デフォルトの順で自動選択）
    
    Returns:
        dict: 学習統計情報（クエリパターン、探索履歴、ノード重要度）
    """
    try:
        graph = get_graph_by_id(graph_id=graph_id)
        
        if graph is None:
            return {
                "success": False,
                "error": "グラフが見つかりません。",
                "suggestions": [
                    "set_active_graph()でアクティブグラフを設定",
                    "graph_idパラメータで登録済みグラフを指定"
                ],
                "registered_graphs": list(_graph_id_to_filepath.keys()),
                "active_graph": _active_graph_id,
                "default_graph": _default_graph_id
            }
        
        query_engine = get_query_engine(graph)
        
        # クエリパターン学習の統計
        query_patterns = query_engine.query_learner.query_patterns
        query_stats = {
            "total_patterns": len(query_patterns),
            "patterns": {}
        }
        for pattern_key, pattern_data in list(query_patterns.items())[:10]:  # 最大10個
            query_stats["patterns"][pattern_key] = {
                "count": pattern_data.get("count", 0),
                "success_rate": pattern_data.get("success_rate", 0.0),
                "avg_response_time": pattern_data.get("avg_response_time", 0.0)
            }
        
        # 探索履歴最適化の統計
        exploration_history = query_engine.exploration_optimizer.path_history
        node_importance = query_engine.exploration_optimizer.node_importance
        
        exploration_stats = {
            "total_paths": sum(len(paths) for paths in exploration_history.values()),
            "unique_paths": len(exploration_history),
            "top_important_nodes": dict(sorted(
                node_importance.items(),
                key=lambda x: x[1],
                reverse=True
            )[:10])  # 重要度トップ10
        }
        
        return {
            "success": True,
            "query_pattern_learning": query_stats,
            "exploration_history": exploration_stats
        }
    # MCPツール境界: 想定外の例外もクライアントへのエラー応答に変換するため意図的に広く捕捉する
    except Exception as e:  # noqa: BLE001
        return {
            "success": False,
            "error": str(e)
        }


@mcp.tool()
def semantic_search(
    query: str,
    graph_id: Optional[str] = None,
    search_type: str = "auto"
) -> Dict:
    """
    🆕 Phase 5: セマンティック検索（スマート検索）
    
    自然言語クエリの意図を理解し、最適なエントリーポイントを発見し、
    統合された要約を提供します。
    
    Args:
        query: 自然言語クエリ（例: "behavior modelingについて知りたい"）
        graph_id: グラフID（オプション、指定しない場合はアクティブ/デフォルトグラフ）
        search_type: 検索タイプ（auto/semantic/traditional）
    
    Returns:
        Dict: 統合検索結果
            - semantic_entries: セマンティックエントリーポイント
            - summary: ノード要約
            - related_nodes: 関連ノード
    """
    try:
        graph = get_graph_by_id(graph_id)
        if not graph:
            return {
                "success": False,
                "error": "グラフが見つかりません"
            }
        
        query_engine = get_query_engine(graph)
        result = query_engine.smart_search(query, search_type=search_type)
        
        return {
            "success": True,
            **result
        }
    except Exception as e:
        logger.exception("semantic_search.error")
        return {
            "success": False,
            "error": str(e)
        }


@mcp.tool()
def explain_concept(
    concept: str,
    graph_id: Optional[str] = None,
    detail_level: str = "overview"
) -> Dict:
    """
    🆕 Phase 5: 概念の説明生成
    
    概念について、断片的な情報を統合し、理解しやすい要約を生成します。
    
    Args:
        concept: 概念名（例: "action"）
        graph_id: グラフID（オプション、指定しない場合はアクティブ/デフォルトグラフ）
        detail_level: 詳細レベル（overview/detailed/technical）
    
    Returns:
        Dict: 説明情報
            - summary: 要約テキスト
            - summary_type: 要約タイプ
            - confidence: 信頼度
            - related_nodes: 関連ノード
    """
    try:
        graph = get_graph_by_id(graph_id)
        if not graph:
            return {
                "success": False,
                "error": "グラフが見つかりません"
            }
        
        query_engine = get_query_engine(graph)
        result = query_engine.explain_concept(concept, detail_level=detail_level)
        
        return {
            "success": True,
            **result
        }
    except Exception as e:
        logger.exception("explain_concept.error")
        return {
            "success": False,
            "error": str(e)
        }


@mcp.tool()
def find_relationship(
    concept1: str,
    concept2: str,
    graph_id: Optional[str] = None
) -> Dict:
    """
    🆕 Phase 5: 概念間の関係性を発見
    
    明示的なエッジがない場合でも、意味的な関係性を推論して発見します。
    
    Args:
        concept1: 概念1（例: "action"）
        concept2: 概念2（例: "requirement"）
        graph_id: グラフID（オプション、指定しない場合はアクティブ/デフォルトグラフ）
    
    Returns:
        Dict: 関係性情報
            - type: パスタイプ（direct/semantic/error）
            - path: パス（directの場合）
            - bridge_concepts: 中間概念（semanticの場合）
            - confidence: 信頼度
    """
    try:
        graph = get_graph_by_id(graph_id)
        if not graph:
            return {
                "success": False,
                "error": "グラフが見つかりません"
            }
        
        query_engine = get_query_engine(graph)
        result = query_engine.find_relationship(concept1, concept2)
        
        return {
            "success": True,
            **result
        }
    except Exception as e:
        logger.exception("find_relationship.error")
        return {
            "success": False,
            "error": str(e)
        }


if __name__ == "__main__":
    # セッション状態を復元
    load_session_state()
    
    # 自動グラフ検出・登録
    auto_registered = initialize_graphs_on_startup()
    
    try:
        logger.info("GraphRAG MCPサーバーを起動します")
        if auto_registered:
            logger.info(f"自動登録されたグラフ: {auto_registered}")
        else:
            # グラフ 0 件のまま黙って起動すると、検索系ツールが全滅しているのに
            # 「該当なし」としか返らず原因が分からなくなる。必ず警告を出す。
            logger.warning(
                "登録済みグラフが 0 件です。検索・探索系ツールはすべて失敗します。"
                f" 探索先: {GRAPHS_DIR}（存在: {GRAPHS_DIR.exists()}）"
                f" / セッション: {SESSION_FILE_PATH}（存在: {SESSION_FILE_PATH.exists()}）"
            )
        if _default_graph_id:
            logger.info(f"デフォルトグラフ: {_default_graph_id}")
        if _active_graph_id:
            logger.info(f"アクティブグラフ: {_active_graph_id}")
        
        mcp.run()
    finally:
        # セッション状態を保存
        save_session_state()
        logger.info("GraphRAG MCPサーバーを終了します")