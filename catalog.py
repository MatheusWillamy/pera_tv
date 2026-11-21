"""
Serviço de Orquestração, Normalização, Deduplicação e Hubs de Streaming (IPTV + TMDB).
"""
import asyncio
import logging
import time
from typing import Any, Dict, List, Optional, Tuple
import httpx
import cache as cache_module
from config import (
    DEFAULT_IPTV_FALLBACK_IP,
    DEFAULT_IPTV_URL,
    DEFAULT_PASSWORD,
    DEFAULT_USERNAME,
    DISCOVER_PAGES_PER_PROVIDER,
    HUB_CACHE_TTL_SECONDS,
    MAX_ITEMS_ENRICHMENT,
    STREAMING_PROVIDERS_META,
    TMDB_API_KEY,
    TMDB_CONCURRENCY_LIMIT,
    TMDB_PROVIDER_IDS,
)
from iptv import IPTVConnectionError, fetch_iptv_catalog
from normalizer import (
    calcular_rating_5based,
    chave_match,
    detectar_provedores_heuristica,
    extrair_qualidade_audio,
    normalizar_titulo,
)
from schemas import SyncRequest
from tmdb import buscar_discover_provedor, buscar_tmdb, buscar_trailer_youtube

logger = logging.getLogger(__name__)

# Snapshot em memória do catálogo bruto IPTV (evita baixar 40MB a cada troca de aba de streaming)
_IPTV_MEM_TTL_SECONDS = 20 * 60
_iptv_mem_snapshot: Dict[str, Any] = {}


def clear_memory_snapshot() -> None:
    _iptv_mem_snapshot.clear()


def _parse_rating(val: Any) -> float:
    if val is None or val == "":
        return 0.0
    try:
        num = float(str(val).strip().replace(",", "."))
        if num <= 0:
            return 0.0
        if num <= 5.0:
            return round(num * 2.0, 1)
        return round(min(num, 10.0), 1)
    except (ValueError, TypeError):
        return 0.0


def _deduplicar_itens(
    raw_items: List[Dict[str, Any]],
    cat_map: Dict[str, str],
    media_type: str,
) -> Tuple[List[Dict[str, Any]], Dict[str, List[Dict[str, Any]]]]:
    """
    Deduplica cópias repetidas do IPTV (ex.: 4K / FHD / DUB / LEG do mesmo filme)
    escolhendo a melhor versão, e constrói um índice O(1) por chave_match.
    """
    grouped: Dict[str, Dict[str, Any]] = {}
    counts: Dict[str, int] = {}

    for item in raw_items:
        if not isinstance(item, dict):
            continue
        item_id = str(
            item.get("series_id" if media_type == "series" else "stream_id")
            or item.get("stream_id")
            or item.get("series_id")
            or item.get("id")
            or ""
        )
        raw_name = str(item.get("name") or item.get("title") or "").strip()
        if not item_id or not raw_name:
            continue

        clean_name, ano = normalizar_titulo(raw_name)
        match_key = chave_match(clean_name or raw_name)
        if not match_key:
            continue

        cat_id = str(item.get("category_id") or "0")
        cat_name = cat_map.get(cat_id, str(item.get("category_name") or ""))
        qa = extrair_qualidade_audio(raw_name)
        rating = _parse_rating(item.get("rating") or item.get("rating_5based"))
        dedup_key = f"{match_key}:{ano or 0}" if media_type == "movie" else match_key

        counts[dedup_key] = counts.get(dedup_key, 0) + 1
        candidate = {
            "id": item_id,
            "media_type": media_type,
            "title": clean_name or raw_name,
            "raw_title": raw_name,
            "match_key": match_key,
            "year": str(ano) if ano else str(item.get("year") or "").strip()[:4],
            "year_int": ano,
            "rating": rating,
            "quality": qa["quality"],
            "quality_rank": qa["quality_rank"],
            "audio": qa["audio"],
            "is_legendado": qa["is_legendado"],
            "poster": str(item.get("cover" if media_type == "series" else "stream_icon") or item.get("stream_icon") or item.get("cover") or ""),
            "backdrop": str(
                (item.get("backdrop_path")[0] if isinstance(item.get("backdrop_path"), list) and item.get("backdrop_path") else item.get("backdrop_path"))
                or ""
            ),
            "overview": str(item.get("plot") or ""),
            "genre": str(item.get("genre") or ""),
            "duration_secs": int(item.get("duration_secs") or 0),
            "container_extension": str(item.get("container_extension") or "mp4"),
            "category_id": cat_id,
            "category_name": cat_name,
            "tmdb_id": item.get("tmdb_id") or None,
            "trailer_key": None,
            "source": "iptv_category",
            "versions_count": 1,
            "_dedup_key": dedup_key,
            "_all_cats": {cat_name} if cat_name else set(),
        }

        prev = grouped.get(dedup_key)
        if not prev:
            grouped[dedup_key] = candidate
        else:
            if cat_name:
                prev["_all_cats"].add(cat_name)
            # Prefere maior qualidade (4K > FHD > HD > CAM), depois dublado, depois quem tem poster/rating
            prev_score = (prev["quality_rank"], 0 if prev["is_legendado"] else 1, 1 if prev["poster"] else 0, prev["rating"])
            cand_score = (candidate["quality_rank"], 0 if candidate["is_legendado"] else 1, 1 if candidate["poster"] else 0, candidate["rating"])
            if cand_score > prev_score:
                candidate["_all_cats"].update(prev["_all_cats"])
                grouped[dedup_key] = candidate

    items_list: List[Dict[str, Any]] = []
    match_index: Dict[str, List[Dict[str, Any]]] = {}
    for dk, entry in grouped.items():
        entry["versions_count"] = counts.get(dk, 1)
        items_list.append(entry)
        match_index.setdefault(entry["match_key"], []).append(entry)

    return items_list, match_index


async def _obter_catalogo_iptv_cacheado(
    http_client: httpx.AsyncClient,
    iptv_url: str,
    fallback_ip: Optional[str],
    username: str,
    password: str,
    force_refresh: bool = False,
) -> Dict[str, Any]:
    """
    Baixa e indexa (com deduplicação e índice O(1)) todo o catálogo IPTV uma vez,
    mantendo em memória por 20 minutos para que trocas entre Netflix/HBO/Disney sejam instantâneas.
    """
    snap_key = f"{iptv_url}|{username}"
    now = time.time()
    cached = _iptv_mem_snapshot.get(snap_key)
    if cached and not force_refresh and (now - cached["ts"]) < _IPTV_MEM_TTL_SECONDS:
        return cached

    try:
        vod_streams, vod_categories, series_streams, series_categories = await fetch_iptv_catalog(
            http_client,
            iptv_url=iptv_url,
            username=username,
            password=password,
            include_series=True,
        )
    except IPTVConnectionError as exc:
        if fallback_ip and fallback_ip != iptv_url:
            logger.warning(
                f"Falha ao conectar no Link oficial ({iptv_url}): {exc}. "
                f"Acionando IP direto de contingência ({fallback_ip})..."
            )
            vod_streams, vod_categories, series_streams, series_categories = await fetch_iptv_catalog(
                http_client,
                iptv_url=fallback_ip,
                username=username,
                password=password,
                include_series=True,
            )
        else:
            raise

    vod_cat_map = {str(c.get("category_id")): str(c.get("category_name", "")) for c in vod_categories}
    series_cat_map = {str(c.get("category_id")): str(c.get("category_name", "")) for c in series_categories}

    movies_dedup, movies_index = _deduplicar_itens(vod_streams, vod_cat_map, "movie")
    series_dedup, series_index = _deduplicar_itens(series_streams, series_cat_map, "series")

    snapshot = {
        "ts": now,
        "vod_raw_count": len(vod_streams),
        "series_raw_count": len(series_streams),
        "movies": movies_dedup,
        "movies_index": movies_index,
        "series": series_dedup,
        "series_index": series_index,
    }
    _iptv_mem_snapshot[snap_key] = snapshot
    return snapshot


def _clean_public_item(entry: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id": entry["id"],
        "media_type": entry["media_type"],
        "title": entry["title"],
        "raw_title": entry["raw_title"],
        "year": entry.get("year") or "",
        "rating": round(float(entry.get("rating") or 0.0), 1),
        "quality": entry.get("quality") or "HD",
        "audio": entry.get("audio") or "",
        "poster": entry.get("poster") or "",
        "backdrop": entry.get("backdrop") or "",
        "overview": entry.get("overview") or "",
        "genre": entry.get("genre") or "",
        "duration_secs": int(entry.get("duration_secs") or 0),
        "container_extension": entry.get("container_extension") or "mp4",
        "category_id": entry.get("category_id") or "0",
        "category_name": entry.get("category_name") or "",
        "tmdb_id": entry.get("tmdb_id"),
        "trailer_key": entry.get("trailer_key"),
        "source": entry.get("source") or "iptv_category",
        "versions_count": int(entry.get("versions_count") or 1),
    }


def _cruzar_discover_com_indice(
    discover_list: List[Dict[str, Any]],
    index_map: Dict[str, List[Dict[str, Any]]],
) -> List[Dict[str, Any]]:
    matched_items: List[Dict[str, Any]] = []
    seen_ids = set()

    for tmdb_entry in discover_list:
        keys = []
        k1 = chave_match(tmdb_entry.get("title") or "")
        k2 = chave_match(tmdb_entry.get("original_title") or "")
        if k1:
            keys.append(k1)
        if k2 and k2 != k1:
            keys.append(k2)

        candidates: List[Dict[str, Any]] = []
        for k in keys:
            candidates.extend(index_map.get(k, []))

        if not candidates:
            continue

        target_year = tmdb_entry.get("year")
        best = candidates[0]
        if target_year and len(candidates) > 1:
            for c in candidates:
                cy = c.get("year_int")
                if cy and abs(cy - target_year) <= 1:
                    best = c
                    break

        uid = f"{best['media_type']}:{best['id']}"
        if uid in seen_ids:
            continue
        seen_ids.add(uid)

        enriched = dict(best)
        enriched["tmdb_id"] = tmdb_entry.get("tmdb_id")
        enriched["source"] = "tmdb_discover+iptv"
        if tmdb_entry.get("backdrop"):
            enriched["backdrop"] = tmdb_entry["backdrop"]
        if tmdb_entry.get("poster") and not enriched.get("poster"):
            enriched["poster"] = tmdb_entry["poster"]
        elif tmdb_entry.get("poster"):
            # Prefere pôster HD oficial TMDB (w342) que sempre carrega sem quebrar
            enriched["poster"] = tmdb_entry["poster"]
        if tmdb_entry.get("overview"):
            enriched["overview"] = tmdb_entry["overview"]
        if tmdb_entry.get("vote_average"):
            enriched["rating"] = float(tmdb_entry["vote_average"])
        if tmdb_entry.get("genre"):
            enriched["genre"] = tmdb_entry["genre"]
        if tmdb_entry.get("year") and not enriched.get("year"):
            enriched["year"] = str(tmdb_entry["year"])
        enriched["_popularity"] = float(tmdb_entry.get("popularity") or 0.0)
        matched_items.append(enriched)

    return matched_items


def _filtrar_categorias_iptv(
    items: List[Dict[str, Any]],
    provider_slug: str,
) -> List[Dict[str, Any]]:
    hits = []
    for item in items:
        all_cats = item.get("_all_cats") or {item.get("category_name", "")}
        matched = False
        for cname in all_cats:
            if provider_slug in detectar_provedores_heuristica("", cname):
                matched = True
                break
        if not matched and provider_slug in detectar_provedores_heuristica(item.get("raw_title", ""), ""):
            matched = True
        if matched:
            copy_item = dict(item)
            copy_item["source"] = "iptv_category"
            copy_item["_popularity"] = 0.0
            hits.append(copy_item)
    return hits


def _montar_prateleiras_hub(
    all_items: List[Dict[str, Any]],
) -> Tuple[Optional[Dict[str, Any]], Dict[str, List[Dict[str, Any]]]]:
    if not all_items:
        return None, {
            "featured": [],
            "series": [],
            "movies": [],
            "recent": [],
            "top_rated": [],
        }

    def hero_score(item: Dict[str, Any]) -> Tuple[int, float, float, int]:
        has_backdrop = 1 if item.get("backdrop") and "image.tmdb.org" in item["backdrop"] else 0
        from_tmdb = 1 if item.get("source") == "tmdb_discover+iptv" else 0
        rating = float(item.get("rating") or 0.0)
        pop = float(item.get("_popularity") or 0.0)
        year_val = int(item["year"]) if str(item.get("year") or "").isdigit() else 0
        return (has_backdrop + from_tmdb, rating, pop, year_val)

    ranked = sorted(all_items, key=hero_score, reverse=True)
    hero = ranked[0] if ranked else None

    featured = ranked[:18]
    series_list = sorted(
        [x for x in all_items if x["media_type"] == "series"],
        key=lambda x: (1 if x.get("backdrop") else 0, float(x.get("rating") or 0.0), float(x.get("_popularity") or 0.0)),
        reverse=True,
    )[:24]
    movies_list = sorted(
        [x for x in all_items if x["media_type"] == "movie"],
        key=lambda x: (1 if x.get("backdrop") else 0, float(x.get("rating") or 0.0), float(x.get("_popularity") or 0.0)),
        reverse=True,
    )[:24]
    recent = sorted(
        all_items,
        key=lambda x: (
            int(x["year"]) if str(x.get("year") or "").isdigit() else 0,
            int(x["id"]) if str(x.get("id") or "").isdigit() else 0,
        ),
        reverse=True,
    )[:20]
    top_rated = sorted(
        [x for x in all_items if float(x.get("rating") or 0.0) >= 7.0],
        key=lambda x: (float(x.get("rating") or 0.0), float(x.get("_popularity") or 0.0)),
        reverse=True,
    )[:20]

    return hero, {
        "featured": featured,
        "series": series_list,
        "movies": movies_list,
        "recent": recent,
        "top_rated": top_rated,
    }


async def obter_hub_provedor(
    provider_slug: str,
    req: Optional[SyncRequest] = None,
    media_type: str = "all",
    query: Optional[str] = None,
    force_refresh: bool = False,
    client: Optional[httpx.AsyncClient] = None,
) -> Dict[str, Any]:
    """
    Constrói ou retorna do cache SQLite (TTL 24h) o Hub Cinematográfico completo
    de um provedor de streaming (Netflix, HBO Max, Disney+, Prime Video, etc.)
    combinando 100% do catálogo local (Filmes + Séries) com TMDB Discover BR (JustWatch).
    """
    slug = (provider_slug or "netflix").strip().lower()
    if slug not in STREAMING_PROVIDERS_META:
        slug = "netflix"

    iptv_url = (req.iptv_url if req and req.iptv_url else DEFAULT_IPTV_URL).rstrip("/")
    fallback_ip = (
        (req.fallback_ip if req and req.fallback_ip else DEFAULT_IPTV_FALLBACK_IP).rstrip("/")
        if (req and req.fallback_ip) or DEFAULT_IPTV_FALLBACK_IP
        else None
    )
    username = req.username if req and req.username else DEFAULT_USERNAME
    password = req.password if req and req.password else DEFAULT_PASSWORD
    api_key = req.tmdb_api_key if req and req.tmdb_api_key else TMDB_API_KEY

    hub_cache_key = f"streaming_hub_v2:{slug}:{iptv_url}:{username}"
    hub_data = None
    from_cache = False

    if not force_refresh:
        cached_hub = cache_module.cache_instance.get(hub_cache_key, max_age_seconds=HUB_CACHE_TTL_SECONDS)
        if isinstance(cached_hub, dict) and "shelves" in cached_hub:
            hub_data = cached_hub
            from_cache = True

    if hub_data is None:
        async def _build(http_client: httpx.AsyncClient) -> Dict[str, Any]:
            snapshot, discover_data = await asyncio.gather(
                _obter_catalogo_iptv_cacheado(
                    http_client,
                    iptv_url=iptv_url,
                    fallback_ip=fallback_ip,
                    username=username,
                    password=password,
                    force_refresh=force_refresh,
                ),
                buscar_discover_provedor(
                    http_client,
                    provider_slug=slug,
                    api_key=api_key,
                    pages=DISCOVER_PAGES_PER_PROVIDER,
                    force_refresh=force_refresh,
                ),
            )

            # Camada 1: Cruzamento TMDB Discover BR (JustWatch) × 100% do catálogo local (O(1))
            tmdb_movies = _cruzar_discover_com_indice(discover_data.get("movie", []), snapshot["movies_index"])
            tmdb_series = _cruzar_discover_com_indice(discover_data.get("tv", []), snapshot["series_index"])

            # Camada 2: Categorias nativas do IPTV + regex sem falsos positivos
            cat_movies = _filtrar_categorias_iptv(snapshot["movies"], slug)
            cat_series = _filtrar_categorias_iptv(snapshot["series"], slug)

            # Merge sem duplicar (prioriza versão enriquecida com TMDB Discover)
            merged: Dict[str, Dict[str, Any]] = {}
            for item in tmdb_movies + tmdb_series + cat_movies + cat_series:
                uid = f"{item['media_type']}:{item['id']}"
                if uid not in merged:
                    merged[uid] = item

            combined_items = list(merged.values())
            hero, shelves = _montar_prateleiras_hub(combined_items)

            # Garante backdrop HD + trailer YouTube no Hero com no máximo 1-2 chamadas leves
            if hero and api_key:
                mt_tmdb = "tv" if hero["media_type"] == "series" else "movie"
                if not hero.get("tmdb_id") or not hero.get("backdrop"):
                    extra = await buscar_tmdb(
                        http_client,
                        title=hero["title"],
                        year=hero.get("year_int"),
                        api_key=api_key,
                        media_type=mt_tmdb,
                        force_refresh=force_refresh,
                    )
                    if extra:
                        hero["tmdb_id"] = hero.get("tmdb_id") or extra.get("tmdb_id")
                        if extra.get("backdrop"):
                            hero["backdrop"] = extra["backdrop"]
                        if extra.get("overview") and not hero.get("overview"):
                            hero["overview"] = extra["overview"]
                        if extra.get("vote_average") and hero.get("rating", 0) <= 0:
                            hero["rating"] = float(extra["vote_average"])
                        if extra.get("genre") and not hero.get("genre"):
                            hero["genre"] = extra["genre"]

                if hero.get("tmdb_id"):
                    hero["trailer_key"] = await buscar_trailer_youtube(
                        http_client,
                        media_type=mt_tmdb,
                        tmdb_id=int(hero["tmdb_id"]),
                        api_key=api_key,
                        force_refresh=force_refresh,
                    )

            total_movies = sum(1 for x in combined_items if x["media_type"] == "movie")
            total_series = sum(1 for x in combined_items if x["media_type"] == "series")
            tmdb_enriched = sum(1 for x in combined_items if x.get("source") == "tmdb_discover+iptv")

            built = {
                "provider": STREAMING_PROVIDERS_META[slug],
                "generated_at": int(time.time() * 1000),
                "stats": {
                    "total": len(combined_items),
                    "movies": total_movies,
                    "series": total_series,
                    "tmdb_matched": tmdb_enriched,
                },
                "hero": _clean_public_item(hero) if hero else None,
                "shelves": {
                    k: [_clean_public_item(it) for it in v]
                    for k, v in shelves.items()
                },
                "catalog_index": [_clean_public_item(it) for it in combined_items[:400]],
            }
            cache_module.cache_instance.set(hub_cache_key, built)
            return built

        if client is not None:
            hub_data = await _build(client)
        else:
            async with httpx.AsyncClient(timeout=60.0) as local_client:
                hub_data = await _build(local_client)

    # Aplica filtros leves (media_type e busca q) em cima do snapshot pronto
    mt = (media_type or "all").strip().lower()
    shelves_out = {}
    for shelf_name, shelf_items in (hub_data.get("shelves") or {}).items():
        if mt in ("movie", "series"):
            shelves_out[shelf_name] = [it for it in shelf_items if it.get("media_type") == mt]
        else:
            shelves_out[shelf_name] = shelf_items

    hero_out = hub_data.get("hero")
    if mt in ("movie", "series") and hero_out and hero_out.get("media_type") != mt:
        fallback_list = shelves_out.get("series" if mt == "series" else "movies") or shelves_out.get("featured") or []
        hero_out = fallback_list[0] if fallback_list else hero_out

    search_results = None
    q_clean = (query or "").strip().lower()
    if q_clean:
        pool = hub_data.get("catalog_index") or []
        search_results = [
            it
            for it in pool
            if (mt == "all" or it.get("media_type") == mt)
            and (q_clean in str(it.get("title", "")).lower() or q_clean in str(it.get("raw_title", "")).lower())
        ][:48]

    return {
        "status": "success",
        "provider": hub_data["provider"],
        "cached": from_cache,
        "generated_at": hub_data["generated_at"],
        "stats": hub_data["stats"],
        "hero": hero_out,
        "shelves": shelves_out,
        "search_results": search_results,
    }


async def obter_hubs_resumo(
    req: Optional[SyncRequest] = None,
) -> Dict[str, Any]:
    """
    Retorna lista ordenada das plataformas suportadas (logos, cores e contadores do cache se já construídos).
    Resposta instantânea (< 5ms).
    """
    iptv_url = (req.iptv_url if req and req.iptv_url else DEFAULT_IPTV_URL).rstrip("/")
    username = req.username if req and req.username else DEFAULT_USERNAME
    providers_out = []
    for slug, meta in STREAMING_PROVIDERS_META.items():
        hub_cache_key = f"streaming_hub_v2:{slug}:{iptv_url}:{username}"
        cached_hub = cache_module.cache_instance.get(hub_cache_key, max_age_seconds=HUB_CACHE_TTL_SECONDS)
        stats = cached_hub.get("stats") if isinstance(cached_hub, dict) else None
        providers_out.append(
            {
                **meta,
                "cached": bool(stats),
                "stats": stats or {"total": 0, "movies": 0, "series": 0, "tmdb_matched": 0},
            }
        )
    return {
        "status": "success",
        "generated_at": int(time.time() * 1000),
        "providers": providers_out,
    }


async def sincronizar_catalogo(
    req: Optional[SyncRequest] = None,
    client: Optional[httpx.AsyncClient] = None,
) -> Dict[str, Any]:
    """
    Executa o fluxo completo de sincronização retrocompatível (/api/v1/sync/catalog):
    1. Obtém dados brutos do IPTV (com fallback de contingência)
    2. Normaliza títulos e extrai ano
    3. Cruza com TMDB para pôsteres HD, sinopse em PT-BR e Watch Providers BR (incluindo HBO Max 1899)
    4. Categoriza provedores de streaming (Globoplay, Netflix, HBO Max, Disney+, etc.)
    5. Retorna o contrato pronto para IndexedDB e localStorage do cliente
    """
    start_time = time.time()

    iptv_url = (req.iptv_url if req and req.iptv_url else DEFAULT_IPTV_URL).rstrip("/")
    fallback_ip = (
        (req.fallback_ip if req and req.fallback_ip else DEFAULT_IPTV_FALLBACK_IP).rstrip("/")
        if (req and req.fallback_ip) or DEFAULT_IPTV_FALLBACK_IP
        else None
    )
    username = req.username if req and req.username else DEFAULT_USERNAME
    password = req.password if req and req.password else DEFAULT_PASSWORD
    api_key = req.tmdb_api_key if req and req.tmdb_api_key else TMDB_API_KEY
    force_refresh = req.force_refresh if req else False
    include_series = req.include_series if req else True
    limit_vods = req.limit_vods if req and req.limit_vods else MAX_ITEMS_ENRICHMENT
    limit_series = req.limit_series if req and req.limit_series else MAX_ITEMS_ENRICHMENT

    async def _process(http_client: httpx.AsyncClient) -> Dict[str, Any]:
        # 1. Download dos dados brutos do IPTV (com fallback de contingência)
        try:
            vod_streams, vod_categories, series_streams, series_categories = await fetch_iptv_catalog(
                http_client,
                iptv_url=iptv_url,
                username=username,
                password=password,
                include_series=include_series,
            )
        except IPTVConnectionError as exc:
            if fallback_ip and fallback_ip != iptv_url:
                logger.warning(
                    f"Falha ao conectar no Link oficial ({iptv_url}): {exc}. "
                    f"Acionando IP direto de contingência ({fallback_ip})..."
                )
                vod_streams, vod_categories, series_streams, series_categories = await fetch_iptv_catalog(
                    http_client,
                    iptv_url=fallback_ip,
                    username=username,
                    password=password,
                    include_series=include_series,
                )
            else:
                raise

        total_vods_raw = len(vod_streams)
        total_series_raw = len(series_streams)

        vod_cat_map = {str(c.get("category_id")): str(c.get("category_name", "")) for c in vod_categories}
        series_cat_map = {str(c.get("category_id")): str(c.get("category_name", "")) for c in series_categories}

        streaming_providers: Dict[str, List[str]] = {prov: [] for prov in TMDB_PROVIDER_IDS.keys()}
        sem = asyncio.Semaphore(TMDB_CONCURRENCY_LIMIT)
        matched_count = 0

        async def process_movie(item: Dict[str, Any]) -> Dict[str, Any]:
            nonlocal matched_count
            stream_id = str(item.get("stream_id") or item.get("id", ""))
            raw_name = str(item.get("name") or "")
            cat_id = str(item.get("category_id", "0"))
            cat_name = vod_cat_map.get(cat_id, "")

            clean_name, ano = normalizar_titulo(raw_name)
            matched_providers = detectar_provedores_heuristica(raw_name, cat_name)

            tmdb_info = None
            if api_key and clean_name:
                async with sem:
                    tmdb_info = await buscar_tmdb(
                        http_client,
                        title=clean_name,
                        year=ano,
                        api_key=api_key,
                        media_type="movie",
                        force_refresh=force_refresh,
                    )

            if tmdb_info:
                matched_count += 1
                for p in tmdb_info.get("providers", []):
                    matched_providers.add(p)

            for p in matched_providers:
                if p in streaming_providers:
                    streaming_providers[p].append(stream_id)

            rating_str = str(tmdb_info.get("vote_average")) if tmdb_info else str(item.get("rating") or "7.5")
            rating_5based = calcular_rating_5based(rating_str)

            return {
                "stream_id": stream_id,
                "name": raw_name,
                "_cleanName": clean_name,
                "_type": "movie",
                "category_id": cat_id,
                "category_name": cat_name,
                "stream_icon": (tmdb_info and tmdb_info.get("poster")) or item.get("stream_icon") or "",
                "backdrop_path": (tmdb_info and tmdb_info.get("backdrop")) or item.get("backdrop_path") or "",
                "year": str(ano) if ano else str(item.get("year") or "2024"),
                "rating": rating_str,
                "rating_5based": rating_5based,
                "plot": (tmdb_info and tmdb_info.get("overview")) or item.get("plot") or "",
                "genre": (tmdb_info and tmdb_info.get("genre")) or item.get("genre") or "",
                "duration_secs": int(item.get("duration_secs") or 0),
                "container_extension": item.get("container_extension") or "mp4",
                "tmdb_id": (tmdb_info and tmdb_info.get("tmdb_id")) or item.get("tmdb_id"),
                "providers": sorted(list(matched_providers)),
            }

        async def process_series(item: Dict[str, Any]) -> Dict[str, Any]:
            nonlocal matched_count
            series_id = str(item.get("series_id") or item.get("stream_id") or item.get("id", ""))
            raw_name = str(item.get("name") or "")
            cat_id = str(item.get("category_id", "0"))
            cat_name = series_cat_map.get(cat_id, "")

            clean_name, ano = normalizar_titulo(raw_name)
            matched_providers = detectar_provedores_heuristica(raw_name, cat_name)

            tmdb_info = None
            if api_key and clean_name:
                async with sem:
                    tmdb_info = await buscar_tmdb(
                        http_client,
                        title=clean_name,
                        year=ano,
                        api_key=api_key,
                        media_type="tv",
                        force_refresh=force_refresh,
                    )

            if tmdb_info:
                matched_count += 1
                for p in tmdb_info.get("providers", []):
                    matched_providers.add(p)

            for p in matched_providers:
                if p in streaming_providers:
                    streaming_providers[p].append(series_id)

            rating_str = str(tmdb_info.get("vote_average")) if tmdb_info else str(item.get("rating") or "8.0")
            rating_5based = calcular_rating_5based(rating_str)

            return {
                "series_id": series_id,
                "stream_id": series_id,
                "name": raw_name,
                "_cleanName": clean_name,
                "_type": "series",
                "category_id": cat_id,
                "category_name": cat_name,
                "cover": (tmdb_info and tmdb_info.get("poster")) or item.get("cover") or item.get("stream_icon") or "",
                "backdrop_path": (tmdb_info and tmdb_info.get("backdrop")) or item.get("backdrop_path") or "",
                "year": str(ano) if ano else str(item.get("year") or "2023"),
                "rating": rating_str,
                "rating_5based": rating_5based,
                "plot": (tmdb_info and tmdb_info.get("overview")) or item.get("plot") or "",
                "genre": (tmdb_info and tmdb_info.get("genre")) or item.get("genre") or "",
                "tmdb_id": (tmdb_info and tmdb_info.get("tmdb_id")) or item.get("tmdb_id"),
                "providers": sorted(list(matched_providers)),
            }

        vods_to_enrich = vod_streams[:limit_vods]
        series_to_enrich = series_streams[:limit_series] if include_series else []

        enriched_vods = await asyncio.gather(*(process_movie(v) for v in vods_to_enrich))
        enriched_series = await asyncio.gather(*(process_series(s) for s in series_to_enrich))

        for p in streaming_providers:
            streaming_providers[p] = sorted(list(set(streaming_providers[p])))

        total_processed = len(enriched_vods) + len(enriched_series)
        unmatched_count = max(0, total_processed - matched_count)
        elapsed = round(time.time() - start_time, 2)

        metrics = {
            "total_vods_iptv": total_vods_raw,
            "total_series_iptv": total_series_raw,
            "matched_with_tmdb": matched_count,
            "unmatched": unmatched_count,
            "elapsed_seconds": elapsed,
            "total_vods": total_vods_raw,
            "total_series": total_series_raw,
        }

        now_ms = int(time.time() * 1000)
        revision = f"{int(time.time())}-{total_vods_raw}"

        return {
            "status": "success",
            "schema_version": 2,
            "revision": revision,
            "generated_at": now_ms,
            "metrics": metrics,
            "streaming_providers": streaming_providers,
            "vod_categories": vod_categories,
            "vod_streams": enriched_vods,
            "series_categories": series_categories,
            "series_streams": enriched_series,
        }

    if client is not None:
        return await _process(client)

    async with httpx.AsyncClient(timeout=60.0) as local_client:
        return await _process(local_client)
