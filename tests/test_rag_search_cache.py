"""HybridRAG rag.cache（SearchCache）のテスト。優先度: HybridRAG/rag。"""

import time
from pathlib import Path

from rag.cache import CachedSearchResult, SearchCache


def test_search_cache_memory_hit_and_stats():
    c = SearchCache(max_size=10, ttl_seconds=None, persist_path=None)
    assert c.get("q") is None
    c.set("q", [{"id": 1}])
    assert c.get("q") == [{"id": 1}]
    stats = c.get_stats()
    assert stats["hits"] >= 1
    assert stats["misses"] >= 1


def test_search_cache_ttl_expires():
    c = SearchCache(max_size=10, ttl_seconds=0.02, persist_path=None)
    c.set("q", [{"a": 1}])
    assert c.get("q") == [{"a": 1}]
    time.sleep(0.05)
    assert c.get("q") is None


def test_search_cache_clear():
    c = SearchCache(max_size=10, ttl_seconds=None, persist_path=None)
    c.set("x", [])
    c.clear()
    assert len(c._memory_cache) == 0
    st = c.get_stats()
    assert st["hits"] == 0 and st["misses"] == 0


def test_search_cache_sqlite_roundtrip(tmp_path: Path):
    db = tmp_path / "cache.db"
    with SearchCache(max_size=10, ttl_seconds=None, persist_path=db) as c:
        c.set("query", [{"chunk": "a"}], top_k_vector=5)
        assert c.get("query", top_k_vector=5) == [{"chunk": "a"}]
    c2 = SearchCache(max_size=10, ttl_seconds=None, persist_path=db)
    try:
        got = c2.get("query", top_k_vector=5)
        assert got == [{"chunk": "a"}]
    finally:
        c2.close()


def test_search_cache_key_stable():
    c = SearchCache(persist_path=None)
    k1 = c._generate_cache_key("hello", top_k_vector=3)
    k2 = c._generate_cache_key("hello", top_k_vector=3)
    assert k1 == k2


def test_cached_search_result_dataclass():
    r = CachedSearchResult(results=[{}], timestamp=0.0, query_hash="h")
    assert r.query_hash == "h"


def test_search_cache_max_size_eviction():
    c = SearchCache(max_size=2, ttl_seconds=None, persist_path=None)
    c.set("a", [1])
    c.set("b", [2])
    c.set("c", [3])
    assert len(c._memory_cache) <= 2


def test_search_cache_evicts_least_recently_used():
    c = SearchCache(max_size=2, ttl_seconds=None, persist_path=None)
    c.set("a", [1])
    c.set("b", [2])
    # "a"にアクセスして最近使用済みにする（"b"が最も長くアクセスされていないエントリになる）
    assert c.get("a") == [1]
    c.set("c", [3])
    # LRUなら"b"が削除され、アクセスされた"a"と新規の"c"が残る
    assert c.get("b") is None
    assert c.get("a") == [1]
    assert c.get("c") == [3]
