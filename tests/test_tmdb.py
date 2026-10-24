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
