"""
Testes unitários para o módulo cache.py (SQLite com TTL).
"""
import time
from cache import SQLiteCache


def test_cache_set_and_get(tmp_path):
    db_file = str(tmp_path / "cache_test.db")
    c = SQLiteCache(db_path=db_file, default_ttl=3600)

    key = "tmdb:movie:matrix:1999"
    payload = {"title": "Matrix", "year": 1999, "tmdb_id": 603}

    c.set(key, payload)
    retrieved = c.get(key)
    assert retrieved is not None
    assert retrieved["title"] == "Matrix"
    assert retrieved["tmdb_id"] == 603


def test_cache_miss_and_expiration(tmp_path):
    db_file = str(tmp_path / "cache_expired.db")
    # TTL de 1 segundo
    c = SQLiteCache(db_path=db_file, default_ttl=1)

    key = "tmdb:movie:teste:2020"
    payload = {"title": "Teste"}
    c.set(key, payload)

    # Imediato: Hit
    assert c.get(key) is not None

    # Espera 1.1s para expirar
    time.sleep(1.1)

    # Após TTL: Miss
    assert c.get(key) is None


def test_cache_clear_and_stats(tmp_path):
    db_file = str(tmp_path / "cache_stats.db")
    c = SQLiteCache(db_path=db_file, default_ttl=3600)

    c.set("k1", {"val": 1})
    c.set("k2", {"val": 2})

    stats = c.stats()
    assert stats["total_records"] == 2
    assert stats["active_records"] == 2

    deleted = c.clear()
    assert deleted == 2

    stats_after = c.stats()
    assert stats_after["total_records"] == 0
