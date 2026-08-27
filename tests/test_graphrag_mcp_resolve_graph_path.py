"""GraphRAG/mcp_server.pyのresolve_graph_pathパス制限。優先度: 公開準備(q1_pickle_security_review)。

resolve_graph_pathが解決した結果はpickle.load()に渡される(GraphPersistence.load_pickle
参照)。pickleの逆シリアライズは任意コード実行につながり得るため、load_graph等のMCP
ツール経由でプロジェクト外の任意パスを読み込めてしまうと、公開後は任意ファイル読み込み+
デシリアライズの攻撃面になる。プロジェクトルート配下のみを許可する制限を検証する。
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "GraphRAG"))

import mcp_server  # noqa: E402


def test_resolve_graph_path_allows_relative_path_under_project_root():
    resolved = mcp_server.resolve_graph_path("data/graphs/example.pkl")

    assert Path(resolved).is_relative_to(mcp_server.PROJECT_ROOT.resolve())


def test_resolve_graph_path_allows_absolute_path_under_project_root():
    inside = mcp_server.PROJECT_ROOT.resolve() / "data" / "graphs" / "example.pkl"

    resolved = mcp_server.resolve_graph_path(str(inside))

    assert Path(resolved) == inside


def test_resolve_graph_path_rejects_absolute_path_outside_project_root(tmp_path):
    outside = tmp_path / "malicious.pkl"

    with pytest.raises(ValueError, match="プロジェクトルート外"):
        mcp_server.resolve_graph_path(str(outside))


def test_resolve_graph_path_rejects_traversal_out_of_project_root():
    with pytest.raises(ValueError, match="プロジェクトルート外"):
        mcp_server.resolve_graph_path("../../../../etc/passwd")
