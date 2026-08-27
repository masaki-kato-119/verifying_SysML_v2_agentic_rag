"""GraphRAG のデータパスが作業ディレクトリに依存しないことのテスト。優先度: GraphRAG。

MCP サーバをリポジトリルートから起動すると cwd 基準の "data/graphs" が
GraphRAG/data/graphs を指さず、登録グラフが 0 件になる退行があった。
その再発を検知する。
"""

import os
from pathlib import Path

import pytest
from graphrag.chunk_storage import ChunkStorage
from graphrag.config import (
    CACHE_DIR,
    CHUNKS_DB_PATH,
    DATA_DIR,
    GRAPHS_DIR,
    PROJECT_ROOT,
    SESSION_FILE_PATH,
)


@pytest.fixture
def elsewhere(tmp_path, monkeypatch):
    """GraphRAG の外側を作業ディレクトリにする。"""
    monkeypatch.chdir(tmp_path)
    return tmp_path


def test_project_root_is_the_graphrag_directory():
    assert PROJECT_ROOT.name == "GraphRAG"
    assert (PROJECT_ROOT / "mcp_server.py").exists()


@pytest.mark.parametrize(
    "path",
    [DATA_DIR, GRAPHS_DIR, CHUNKS_DB_PATH, SESSION_FILE_PATH, CACHE_DIR],
)
def test_data_paths_are_absolute_and_under_project_root(path):
    assert path.is_absolute()
    assert PROJECT_ROOT in path.parents


def test_data_paths_do_not_change_with_cwd(elsewhere):
    """cwd を変えても定数が指す先は変わらない（import 済みモジュールの再評価は不要）。"""
    assert Path(os.getcwd()) == elsewhere
    from graphrag.config import GRAPHS_DIR as reloaded

    assert reloaded == GRAPHS_DIR
    assert PROJECT_ROOT in reloaded.parents


def test_chunk_storage_defaults_to_project_data_dir(elsewhere):
    """db_path 省略時は cwd ではなく GraphRAG/data/chunks.db を使う。"""
    cs = ChunkStorage()

    assert cs.db_path == CHUNKS_DB_PATH
    assert not (elsewhere / "data").exists()


def test_chunk_storage_still_accepts_explicit_path(tmp_path):
    db = tmp_path / "nested" / "chunks.db"
    cs = ChunkStorage(str(db))

    assert cs.db_path == db
    assert db.exists()


def test_normalize_absolute_path_is_relative_to_project_root(tmp_path):
    """DB に保存する表記は cwd ではなくプロジェクトルート基準にする。"""
    cs = ChunkStorage(str(tmp_path / "chunks.db"))
    absolute = str(GRAPHS_DIR / "sample.pkl")

    assert cs._normalize_to_relative_path(absolute) == "data/graphs/sample.pkl"


def test_normalize_outside_project_root_falls_back_to_graphs_dir(tmp_path):
    outside = tmp_path / "somewhere" / "other.pkl"
    cs = ChunkStorage(str(tmp_path / "chunks.db"))

    assert cs._normalize_to_relative_path(str(outside)) == "data/graphs/other.pkl"


def test_normalize_keeps_relative_path_as_is(tmp_path):
    cs = ChunkStorage(str(tmp_path / "chunks.db"))

    assert cs._normalize_to_relative_path("data/graphs/a.pkl") == "data/graphs/a.pkl"
