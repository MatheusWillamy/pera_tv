import os
import sys

# Garante que a raiz do projeto esteja no sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest
from fastapi.testclient import TestClient
from cache import SQLiteCache
import cache as cache_module
from main import app


@pytest.fixture(autouse=True)
def setup_test_cache(tmp_path):
    """
    Configura um banco de dados temporário para testes do cache SQLite.
    """
    test_db = str(tmp_path / "test_cache.db")
    test_cache = SQLiteCache(db_path=test_db, default_ttl=604800)
    cache_module.cache_instance = test_cache
    yield test_cache
    if os.path.exists(test_db):
        try:
            os.remove(test_db)
        except Exception:
            pass


@pytest.fixture
def client():
    """
    Cliente de teste para endpoints FastAPI.
    """
    with TestClient(app) as test_client:
        yield test_client
