"""
Testes para o módulo tmdb.py (Busca, Provedores e Cache).
"""
import pytest
import httpx
from tmdb import buscar_tmdb, formatar_generos
from config import TMDB_API_KEY


def test_formatar_generos():
    assert "Ação" in formatar_generos([28])
    assert "Comédia" in formatar_generos([35])
    assert "Aventura" in formatar_generos([12, 28])
    assert formatar_generos([]) == ""


@pytest.mark.asyncio
async def test_buscar_tmdb_real_ou_mock():
    """
    Testa a busca no TMDB utilizando a chave configurada.
    """
    async with httpx.AsyncClient(timeout=10.0) as client:
        resultado = await buscar_tmdb(
            client=client,
            title="Matrix",
            year=1999,
            api_key=TMDB_API_KEY,
            media_type="movie",
            force_refresh=True,
        )

        assert resultado is not None
        assert resultado["tmdb_id"] == 603
        assert "Matrix" in resultado["title"]
        assert resultado["poster"] is not None
        assert resultado["vote_average"] > 0


@pytest.mark.asyncio
async def test_discover_provedor_usa_flatrate_e_trending(monkeypatch):
    from unittest.mock import AsyncMock, MagicMock
    from tmdb import buscar_discover_provedor, buscar_trending_semana
    import cache as cache_module

    cache_module.cache_instance.delete_by_prefix("tmdb_discover_br_v4:")
    cache_module.cache_instance.delete_by_prefix("tmdb_trending_week_v1:")

    captured_params = []

    class FakeResp:
        def __init__(self, payload):
            self.status_code = 200
            self._payload = payload

        def json(self):
            return self._payload

    async def fake_get(url, params=None, timeout=None):
        captured_params.append((url, dict(params or {})))
        return FakeResp({
            "results": [
                {
                    "id": 157336,
                    "title": "Interestelar",
                    "original_title": "Interstellar",
                    "overview": "Espaco",
                    "poster_path": "/p.jpg",
                    "backdrop_path": "/b.jpg",
                    "vote_average": 8.4,
                    "vote_count": 30000,
                    "popularity": 150.0,
                    "release_date": "2014-11-06",
                    "genre_ids": [12, 878],
                }
            ]
        })

    fake_client = MagicMock()
    fake_client.get = AsyncMock(side_effect=fake_get)

    disc = await buscar_discover_provedor(fake_client, "prime", TMDB_API_KEY, pages=1, force_refresh=True)
    assert len(disc["movie"]) == 1
    assert any(p.get("with_watch_monetization_types") == "flatrate" for _, p in captured_params)

    trend = await buscar_trending_semana(fake_client, TMDB_API_KEY, pages=1, force_refresh=True)
    assert len(trend["movie"]) == 1
    assert len(trend["tv"]) == 1
