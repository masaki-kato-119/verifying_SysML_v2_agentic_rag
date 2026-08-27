"""GraphRAG cache_manager の主要パス（TTL・永続化・統計）。"""

import time

from graphrag.cache_manager import CacheManager


def test_query_cache_ttl_expires(tmp_path):
    cm = CacheManager(
        enable_query_cache=True,
        query_cache_ttl=0.01,
        query_cache_persistent=False,
        cache_dir=None,
    )
    cm.set_query_result("q", {"v": 1})
    assert cm.get_query_result("q") == {"v": 1}
    time.sleep(0.05)
    assert cm.get_query_result("q") is None


def test_persistent_roundtrip(tmp_path):
    d = tmp_path / "cache_dir"
    cm = CacheManager(
        enable_query_cache=True,
        query_cache_ttl=None,
        query_cache_persistent=True,
        cache_dir=str(d),
    )
    cm.set_query_result("key1", {"a": 2})
    cm2 = CacheManager(
        enable_query_cache=True,
        query_cache_ttl=None,
        query_cache_persistent=True,
        cache_dir=str(d),
    )
    assert cm2.get_query_result("key1") == {"a": 2}
    assert (d / "query_cache.json").exists()


def test_clear_cache_query_removes_file(tmp_path):
    d = tmp_path / "c"
    cm = CacheManager(
        enable_query_cache=True,
        query_cache_persistent=True,
        cache_dir=str(d),
    )
    cm.set_query_result("k", 1)
    cm.clear_cache("query")
    assert not (d / "query_cache.json").exists()


def test_get_cache_stats_with_ttl():
    cm = CacheManager(enable_query_cache=True, query_cache_ttl=0.001, cache_dir=None)
    cm.set_query_result("x", 1)
    time.sleep(0.02)
    stats = cm.get_cache_stats()
    assert stats["enable_query_cache"] is True
    assert stats["query_cache_ttl"] == 0.001
    assert stats["expired_cache_count"] >= 0
