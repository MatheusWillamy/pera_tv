"""
Módulo de Integração com The Movie Database (TMDB v3 API).
Inclui:
  - Busca difusa com desempate inteligente (título normalizado + ano + vote_count)
  - Extração de Watch Providers BR (JustWatch) com suporte a múltiplos IDs (ex.: HBO Max 1899 + 384)
  - Motor invertido TMDB Discover por plataforma BR (watch_region=BR) com cache SQLite 24h
  - Extração de Trailer YouTube sob demanda para o Hero
"""
import asyncio
import logging
from typing import Any, Dict, List, Optional
import httpx
import cache as cache_module
from config import (
    DISCOVER_PAGES_PER_PROVIDER,
    HUB_CACHE_TTL_SECONDS,
    TMDB_BASE,
    TMDB_IMG_BASE,
    TMDB_PROVIDER_IDS,
    TMDB_REQUEST_TIMEOUT,
)
from normalizer import chave_match

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


def _provider_id_list(slug: str) -> List[int]:
    val = TMDB_PROVIDER_IDS.get(slug)
    if isinstance(val, (list, tuple, set)):
        return [int(x) for x in val]
    if val is not None:
        return [int(val)]
    return []


def _slugs_for_provider_id(pid: Any) -> List[str]:
    try:
        pid_int = int(pid)
    except (TypeError, ValueError):
        return []
    hits = []
    for slug in TMDB_PROVIDER_IDS.keys():
        if pid_int in _provider_id_list(slug):
            hits.append(slug)
    return hits


def escolher_melhor_candidato(
    title: str,
    year: Optional[int],
    results: List[Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    """
    Seleciona o candidato TMDB mais preciso priorizando:
    1) Título exato normalizado (title/name ou original_title/original_name)
    2) Ano próximo (±1)
    3) Maior vote_count
    """
    if not results:
        return None

    target_norm = chave_match(title)
    exact = []
    for r in results:
        if not isinstance(r, dict):
            continue
        n1 = chave_match(str(r.get("title") or r.get("name") or ""))
        n2 = chave_match(str(r.get("original_title") or r.get("original_name") or ""))
        if target_norm and (n1 == target_norm or n2 == target_norm):
            exact.append(r)

    pool = exact if exact else results
    if year:
        same_year = []
        for r in pool:
            date_str = str(r.get("release_date") or r.get("first_air_date") or "")
            if len(date_str) >= 4 and date_str[:4].isdigit():
                if abs(int(date_str[:4]) - int(year)) <= 1:
                    same_year.append(r)
        if same_year:
            pool = same_year

    return max(pool, key=lambda item: int(item.get("vote_count") or 0))


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
            br_data = r.json().get("results", {}).get("BR", {})
            flatrate = br_data.get("flatrate", [])
            for p in flatrate:
                for slug in _slugs_for_provider_id(p.get("provider_id")):
                    providers.append(slug)
    except Exception as exc:
        logger.debug(f"Erro ao buscar watch providers para {media_type}/{tmdb_id}: {exc}")

    return list(set(providers))


async def buscar_trailer_youtube(
    client: httpx.AsyncClient,
    media_type: str,
    tmdb_id: int,
    api_key: str,
    force_refresh: bool = False,
) -> Optional[str]:
    """
    Busca a chave YouTube do trailer oficial (PT-BR -> EN fallback) com cache SQLite.
    """
    if not tmdb_id or not api_key:
        return None
    cache_key = f"tmdb_trailer:{media_type}:{tmdb_id}"
    if not force_refresh:
        cached = cache_module.cache_instance.get(cache_key)
        if isinstance(cached, dict) and "key" in cached:
            return cached.get("key")

    endpoint = f"{TMDB_BASE}/{media_type}/{tmdb_id}/videos"
    params = {
        "api_key": api_key,
        "language": "pt-BR",
        "include_video_language": "pt,en,null",
    }
    trailer_key: Optional[str] = None
    try:
        r = await client.get(endpoint, params=params, timeout=TMDB_REQUEST_TIMEOUT)
        if r.status_code == 200:
            videos = r.json().get("results", []) or []
            for preferred_type in ("Trailer", "Teaser"):
                for v in videos:
                    if v.get("site") == "YouTube" and v.get("type") == preferred_type and v.get("key"):
                        trailer_key = str(v["key"])
                        break
                if trailer_key:
                    break
        cache_module.cache_instance.set(cache_key, {"key": trailer_key})
    except Exception as exc:
        logger.debug(f"Erro ao buscar trailer para {media_type}/{tmdb_id}: {exc}")
    return trailer_key


async def buscar_discover_provedor(
    client: httpx.AsyncClient,
    provider_slug: str,
    api_key: str,
    pages: int = DISCOVER_PAGES_PER_PROVIDER,
    force_refresh: bool = False,
) -> Dict[str, List[Dict[str, Any]]]:
    """
    Motor Invertido TMDB/JustWatch BR:
    Consulta /3/discover/movie e /3/discover/tv para o provedor no Brasil (watch_region=BR)
    com cache SQLite de 24h. Com apenas ~4-6 requests traz centenas de títulos populares
    e aclamados já com backdrop widescreen (w780), pôster (w342), sinopse PT-BR e nota.
    """
    ids = _provider_id_list(provider_slug)
    if not ids or not api_key:
        return {"movie": [], "tv": []}

    cache_key = f"tmdb_discover_br_v2:{provider_slug}:{pages}"
    if not force_refresh:
        cached = cache_module.cache_instance.get(cache_key, max_age_seconds=HUB_CACHE_TTL_SECONDS)
        if isinstance(cached, dict) and ("movie" in cached or "tv" in cached):
            return {
                "movie": cached.get("movie", []),
                "tv": cached.get("tv", []),
            }

    provider_param = "|".join(str(x) for x in ids)
    safe_pages = max(1, min(int(pages or 2), 5))

    async def fetch_page(media_type: str, page: int, sort_by: str) -> List[Dict[str, Any]]:
        url = f"{TMDB_BASE}/discover/{media_type}"
        params = {
            "api_key": api_key,
            "language": "pt-BR",
            "watch_region": "BR",
            "with_watch_providers": provider_param,
            "sort_by": sort_by,
            "include_adult": "false",
            "page": str(page),
        }
        if sort_by == "vote_average.desc":
            params["vote_count.gte"] = "150"
        try:
            r = await client.get(url, params=params, timeout=TMDB_REQUEST_TIMEOUT)
            if r.status_code != 200:
                return []
            out = []
            for item in r.json().get("results", []) or []:
                tmdb_id = item.get("id")
                if not tmdb_id:
                    continue
                poster_path = item.get("poster_path")
                backdrop_path = item.get("backdrop_path")
                date_str = str(item.get("release_date") or item.get("first_air_date") or "")
                year = int(date_str[:4]) if len(date_str) >= 4 and date_str[:4].isdigit() else None
                out.append(
                    {
                        "tmdb_id": tmdb_id,
                        "media_type": media_type,
                        "title": item.get("title") or item.get("name") or "",
                        "original_title": item.get("original_title") or item.get("original_name") or "",
                        "overview": item.get("overview") or "",
                        "poster": f"{TMDB_IMG_BASE}/w342{poster_path}" if poster_path else None,
                        "backdrop": f"{TMDB_IMG_BASE}/w780{backdrop_path}" if backdrop_path else None,
                        "vote_average": round(float(item.get("vote_average") or 0.0), 1),
                        "vote_count": int(item.get("vote_count") or 0),
                        "popularity": float(item.get("popularity") or 0.0),
                        "year": year,
                        "genre": formatar_generos(item.get("genre_ids", []) or []),
                    }
                )
            return out
        except Exception as exc:
            logger.debug(f"Erro discover {provider_slug} {media_type} p{page}: {exc}")
            return []

    tasks = []
    for media_type in ("movie", "tv"):
        for p in range(1, safe_pages + 1):
            tasks.append(fetch_page(media_type, p, "popularity.desc"))
        tasks.append(fetch_page(media_type, 1, "vote_average.desc"))

    batches = await asyncio.gather(*tasks)
    dedup: Dict[str, Dict[int, Dict[str, Any]]] = {"movie": {}, "tv": {}}
    for batch in batches:
        for entry in batch:
            mt = entry["media_type"]
            tid = entry["tmdb_id"]
            if tid not in dedup[mt]:
                dedup[mt][tid] = entry

    result = {
        "movie": list(dedup["movie"].values()),
        "tv": list(dedup["tv"].values()),
    }
    if result["movie"] or result["tv"]:
        cache_module.cache_instance.set(cache_key, result)
    return result


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
        cached = cache_module.cache_instance.get(cache_key)
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

        best = escolher_melhor_candidato(title, year, results)
        if not best:
            return None
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
            "poster": f"{TMDB_IMG_BASE}/w500{poster_path}" if poster_path else None,
            "backdrop": f"{TMDB_IMG_BASE}/w780{backdrop_path}" if backdrop_path else None,
            "vote_average": float(best.get("vote_average", 0.0)),
            "genre": genre_str,
            "providers": providers,
        }

        # 4. Grava no cache SQLite para próximas consultas
        cache_module.cache_instance.set(cache_key, data)
        return data

    except Exception as exc:
        logger.debug(f"Erro na consulta TMDB para '{title}': {exc}")
        return None
