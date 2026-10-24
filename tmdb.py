"""
Módulo de Integração com The Movie Database (TMDB v3 API).
Inclui busca difusa (filmes e séries), extração de Watch Providers BR (JustWatch)
e integração com banco de cache local (TTL de 7 dias).
"""
import logging
from typing import Any, Dict, List, Optional
import httpx
from config import (
    TMDB_BASE,
    TMDB_PROVIDER_IDS,
    TMDB_REQUEST_TIMEOUT,
)
from cache import cache_instance

logger = logging.getLogger(__name__)

# Mapa estático de gêneros TMDB em Português (PT-BR) para enriquecimento instantâneo
GENRES_MAP_PT = {
    # Filmes
    28: "Ação",
    12: "Aventura",
    16: "Animação",
    35: "Comédia",
    80: "Crime",
    99: "Documentário",
    18: "Drama",
    10751: "Família",
    14: "Fantasia",
    36: "História",
    27: "Terror",
    10402: "Música",
    9648: "Mistério",
    10749: "Romance",
    878: "Ficção científica",
    10770: "Cinema TV",
    53: "Thriller",
    10752: "Guerra",
    37: "Faroeste",
    # Séries
    10759: "Ação & Aventura",
    10762: "Kids",
    10763: "Notícias",
    10764: "Reality",
    10765: "Sci-Fi & Fantasy",
    10766: "Soap (Novela)",
    10767: "Talk Show",
    10768: "Guerra & Política",
}


def formatar_generos(genre_ids: List[int]) -> str:
    if not genre_ids:
        return ""
    nomes = [GENRES_MAP_PT[gid] for gid in genre_ids if gid in GENRES_MAP_PT]
    return ", ".join(nomes)


async def buscar_watch_providers(
    client: httpx.AsyncClient,
    media_type: str,
    tmdb_id: int,
    api_key: str,
) -> List[str]:
    """
    Consulta os provedores de streaming no Brasil (BR) associados ao título (JustWatch).
    """
    endpoint = f"{TMDB_BASE}/{media_type}/{tmdb_id}/watch/providers"
    params = {"api_key": api_key}
    providers: List[str] = []

    try:
        r = await client.get(endpoint, params=params, timeout=TMDB_REQUEST_TIMEOUT)
        if r.status_code == 200:
            br_data = (
                r.json().get("results", {}).get("BR", {})
            )
            # Analisa provedores em flatrate (assinaturas) e opcionalmente ads / buy
            flatrate = br_data.get("flatrate", [])
            for p in flatrate:
                pid = p.get("provider_id")
                for slug, target_id in TMDB_PROVIDER_IDS.items():
                    if pid == target_id:
                        providers.append(slug)
    except Exception as exc:
        logger.debug(f"Erro ao buscar watch providers para {media_type}/{tmdb_id}: {exc}")

    return list(set(providers))


async def buscar_tmdb(
    client: httpx.AsyncClient,
    title: str,
    year: Optional[int],
    api_key: str,
    media_type: str = "movie",
    force_refresh: bool = False,
) -> Optional[Dict[str, Any]]:
    """
    Executa busca difusa no TMDB para filmes ('movie') ou séries ('tv').
    Retorna metadados oficiais e provedores no Brasil com cache local.
    """
    if not title:
        return None

    cache_key = f"tmdb:{media_type}:{title.strip().lower()}:{year or 0}"

    # 1. Consulta o cache local (TTL 7 dias) se force_refresh=False
    if not force_refresh:
        cached = cache_instance.get(cache_key)
        if cached is not None:
            return cached

    # 2. Busca na API TMDB
    search_endpoint = f"{TMDB_BASE}/search/{media_type}"
    params = {
        "api_key": api_key,
        "query": title,
        "language": "pt-BR",
        "include_adult": "false",
    }
    if year:
        if media_type == "movie":
            params["year"] = str(year)
        else:
            params["first_air_date_year"] = str(year)

    try:
        r = await client.get(search_endpoint, params=params, timeout=TMDB_REQUEST_TIMEOUT)
        if r.status_code != 200:
            return None

        results = r.json().get("results", [])

        # Fallback: Se não encontrou com o ano, tenta busca ampla apenas com o título
        if not results and year:
            params.pop("year", None)
            params.pop("first_air_date_year", None)
            r = await client.get(search_endpoint, params=params, timeout=TMDB_REQUEST_TIMEOUT)
            results = r.json().get("results", []) if r.status_code == 200 else []

        if not results:
            return None

        best = results[0]
        tmdb_id = best.get("id")
        if not tmdb_id:
            return None

        # 3. Consulta Watch Providers BR
        providers = await buscar_watch_providers(client, media_type, tmdb_id, api_key)

        poster_path = best.get("poster_path")
        backdrop_path = best.get("backdrop_path")
        display_title = best.get("title") or best.get("name") or title
        genre_str = formatar_generos(best.get("genre_ids", []))

        data = {
            "tmdb_id": tmdb_id,
            "title": display_title,
            "overview": best.get("overview", ""),
            "poster": f"https://image.tmdb.org/t/p/w500{poster_path}" if poster_path else None,
            "backdrop": f"https://image.tmdb.org/t/p/original{backdrop_path}" if backdrop_path else None,
            "vote_average": float(best.get("vote_average", 0.0)),
            "genre": genre_str,
            "providers": providers,
        }

        # 4. Grava no cache SQLite para próximas consultas
        cache_instance.set(cache_key, data)
        return data

    except Exception as exc:
        logger.debug(f"Erro na consulta TMDB para '{title}': {exc}")
        return None
