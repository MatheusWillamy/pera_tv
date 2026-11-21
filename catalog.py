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
    chave_match_sem_artigo,
    chaves_match_alternativas,
    detectar_provedores_heuristica,
    extrair_qualidade_audio,
    normalizar_titulo,
    titulos_equivalentes,
)
from schemas import ManualOverrideRequest, StreamingBatchMatchRequest, SyncRequest
from tmdb import (
    buscar_discover_provedor,
    buscar_tmdb,
    buscar_tmdb_por_id,
    buscar_trailer_youtube,
    buscar_trending_semana,
)

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


def _construir_indices_match(
    items_list: List[Dict[str, Any]],
) -> Tuple[Dict[str, List[Dict[str, Any]]], Dict[str, List[Dict[str, Any]]], Dict[str, List[Dict[str, Any]]]]:
    """
    Constrói 3 índices O(1) para cruzamento IPTV <-> TMDB:
    1. match_index (chave normalizada com algarismos romanos convertidos)
    2. alt_index (chave sem artigo inicial: O, A, Os, As, The...)
    3. prefix_index (prefixo compacto de 3 chars para fallback fuzzy com bigramas Dice)
    """
    match_index: Dict[str, List[Dict[str, Any]]] = {}
    alt_index: Dict[str, List[Dict[str, Any]]] = {}
    prefix_index: Dict[str, List[Dict[str, Any]]] = {}

    for entry in items_list:
        mk = entry.get("match_key") or chave_match(entry.get("title") or entry.get("raw_title") or "")
        if not mk:
            continue
        entry["match_key"] = mk
        match_index.setdefault(mk, []).append(entry)

        ak = chave_match_sem_artigo(mk)
        if ak:
            alt_index.setdefault(ak, []).append(entry)
        for alt_k in chaves_match_alternativas(entry.get("title") or entry.get("raw_title") or ""):
            if alt_k and alt_k != mk:
                alt_index.setdefault(alt_k, []).append(entry)

        compact = mk.replace(" ", "")
        if len(compact) >= 3:
            prefix_index.setdefault(compact[:3], []).append(entry)

    return match_index, alt_index, prefix_index


def _normalizar_itens_cliente(
    client_items: List[Any],
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """
    Converte itens enviados manualmente pelo cliente (POST /api/v1/streaming/match)
    no mesmo formato padronizado usado pelo pipeline interno de deduplicação.
    """
    raw_movies: List[Dict[str, Any]] = []
    raw_series: List[Dict[str, Any]] = []

    for it in client_items:
        obj = it.model_dump() if hasattr(it, "model_dump") else dict(it)
        mt = "series" if str(obj.get("media_type", "")).lower() in ("series", "tv") else "movie"
        base = {
            "id": str(obj.get("id") or ""),
            "name": str(obj.get("name") or ""),
            "category_name": str(obj.get("category_name") or ""),
            "category_id": "0",
            "year": obj.get("year") or "",
            "rating": obj.get("rating"),
            "container_extension": obj.get("container_extension") or "mp4",
        }
        if mt == "series":
            base["series_id"] = base["id"]
            base["cover"] = str(obj.get("poster") or "")
            raw_series.append(base)
        else:
            base["stream_id"] = base["id"]
            base["stream_icon"] = str(obj.get("poster") or "")
            raw_movies.append(base)

    movies_dedup, _ = _deduplicar_itens(raw_movies, {}, "movie")
    series_dedup, _ = _deduplicar_itens(raw_series, {}, "series")
    return movies_dedup, series_dedup


async def _obter_catalogo_iptv_cacheado(
    http_client: httpx.AsyncClient,
    iptv_url: str,
    fallback_ip: Optional[str],
    username: str,
    password: str,
    force_refresh: bool = False,
) -> Dict[str, Any]:
    """
    Baixa e indexa (com deduplicação e índices O(1)/fuzzy) todo o catálogo IPTV uma vez,
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

    movies_dedup, _ = _deduplicar_itens(vod_streams, vod_cat_map, "movie")
    series_dedup, _ = _deduplicar_itens(series_streams, series_cat_map, "series")
    movies_index, movies_alt_index, movies_prefix_index = _construir_indices_match(movies_dedup)
    series_index, series_alt_index, series_prefix_index = _construir_indices_match(series_dedup)

    snapshot = {
        "ts": now,
        "vod_raw_count": len(vod_streams),
        "series_raw_count": len(series_streams),
        "movies": movies_dedup,
        "movies_index": movies_index,
        "movies_alt_index": movies_alt_index,
        "movies_prefix_index": movies_prefix_index,
        "movies_by_id": {m["id"]: m for m in movies_dedup},
        "series": series_dedup,
        "series_index": series_index,
        "series_alt_index": series_alt_index,
        "series_prefix_index": series_prefix_index,
        "series_by_id": {s["id"]: s for s in series_dedup},
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
        "is_legendado": bool(entry.get("is_legendado", False)),
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
    alt_index: Optional[Dict[str, List[Dict[str, Any]]]] = None,
    prefix_index: Optional[Dict[str, List[Dict[str, Any]]]] = None,
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

        # 2) Fallback: chave sem artigo inicial e variantes '&' <-> 'and'/'e'
        if not candidates and alt_index:
            seen_alt_keys = set()
            for raw_alt in (tmdb_entry.get("title") or "", tmdb_entry.get("original_title") or ""):
                for ak in chaves_match_alternativas(raw_alt):
                    if ak and ak not in seen_alt_keys:
                        seen_alt_keys.add(ak)
                        candidates.extend(alt_index.get(ak, []))

        # 3) Fallback fuzzy: prefixo de 3 chars + Dice >= 0.85 com trava numérica
        if not candidates and prefix_index:
            seen_cand_ids = set()
            for k in keys:
                compact = k.replace(" ", "")
                if len(compact) < 3:
                    continue
                for cand in prefix_index.get(compact[:3], []):
                    cid = f"{cand['media_type']}:{cand['id']}"
                    if cid in seen_cand_ids:
                        continue
                    seen_cand_ids.add(cid)
                    if titulos_equivalentes(cand.get("match_key") or "", k):
                        candidates.append(cand)

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
        if tmdb_entry.get("poster"):
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


def _resolver_overrides_para_provedor(
    provider_slug: str,
    movies_by_id: Dict[str, Dict[str, Any]],
    series_by_id: Dict[str, Dict[str, Any]],
) -> List[Dict[str, Any]]:
    overrides = cache_module.cache_instance.list_manual_matches(provider=provider_slug)
    out: List[Dict[str, Any]] = []
    for ov in overrides:
        mt = "series" if ov.get("media_type") == "series" else "movie"
        iid = str(ov.get("item_id") or "")
        if not iid:
            continue
        base_map = series_by_id if mt == "series" else movies_by_id
        local_entry = base_map.get(iid)
        merged = dict(local_entry) if local_entry else {
            "id": iid,
            "media_type": mt,
            "title": ov.get("title") or "Título",
            "raw_title": ov.get("raw_title") or ov.get("title") or "Título",
            "year": str(ov.get("year") or ""),
            "rating": float(ov.get("rating") or 0.0),
            "quality": "HD",
            "audio": "",
            "is_legendado": False,
            "poster": "",
            "backdrop": "",
            "overview": "",
            "genre": "",
            "duration_secs": 0,
            "container_extension": "mp4",
            "category_id": "0",
            "category_name": "Manual Match",
            "versions_count": 1,
        }
        if ov.get("tmdb_id"):
            merged["tmdb_id"] = ov["tmdb_id"]
        if ov.get("poster"):
            merged["poster"] = ov["poster"]
        if ov.get("backdrop"):
            merged["backdrop"] = ov["backdrop"]
        if ov.get("overview"):
            merged["overview"] = ov["overview"]
        if ov.get("genre"):
            merged["genre"] = ov["genre"]
        if ov.get("rating"):
            merged["rating"] = float(ov["rating"])
        if ov.get("trailer_key"):
            merged["trailer_key"] = ov["trailer_key"]
        if ov.get("year") and not merged.get("year"):
            merged["year"] = str(ov["year"])
        merged["source"] = "manual_override"
        merged["_popularity"] = 999.0
        out.append(merged)
    return out


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

    def _platform_rank_key(item: Dict[str, Any]) -> Tuple[int, int, float, int]:
        is_manual = 1 if item.get("source") == "manual_override" else 0
        has_backdrop = 1 if item.get("backdrop") and "image.tmdb.org" in item["backdrop"] else 0
        native_bonus = 35.0 if item.get("_native_cat") else 0.0
        pop = float(item.get("_popularity") or 0.0)
        rating = float(item.get("rating") or 0.0)
        blended_score = round(pop + (rating * 5.0) + native_bonus, 2)
        year_val = int(item["year"]) if str(item.get("year") or "").isdigit() else 0
        return (is_manual, has_backdrop, blended_score, year_val)

    ranked = sorted(all_items, key=_platform_rank_key, reverse=True)
    hero = ranked[0] if ranked else None

    featured = ranked[:18]
    series_list = sorted(
        [x for x in all_items if x["media_type"] == "series"],
        key=_platform_rank_key,
        reverse=True,
    )[:24]
    movies_list = sorted(
        [x for x in all_items if x["media_type"] == "movie"],
        key=_platform_rank_key,
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

    hub_cache_key = f"streaming_hub_v3:{slug}:{iptv_url}:{username}"
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

            # Camada 0: Overrides manuais persistidos no SQLite (prioridade máxima)
            manual_items = _resolver_overrides_para_provedor(
                slug,
                snapshot.get("movies_by_id", {}),
                snapshot.get("series_by_id", {}),
            )

            # Camada 1: Cruzamento TMDB Discover BR (JustWatch) × 100% do catálogo local (O(1) + Fuzzy)
            tmdb_movies = _cruzar_discover_com_indice(
                discover_data.get("movie", []),
                snapshot["movies_index"],
                alt_index=snapshot.get("movies_alt_index"),
                prefix_index=snapshot.get("movies_prefix_index"),
            )
            tmdb_series = _cruzar_discover_com_indice(
                discover_data.get("tv", []),
                snapshot["series_index"],
                alt_index=snapshot.get("series_alt_index"),
                prefix_index=snapshot.get("series_prefix_index"),
            )

            # Camada 2: Categorias nativas do IPTV + regex sem falsos positivos
            cat_movies = _filtrar_categorias_iptv(snapshot["movies"], slug)
            cat_series = _filtrar_categorias_iptv(snapshot["series"], slug)
            native_uids = {f"{x['media_type']}:{x['id']}" for x in cat_movies + cat_series}

            # Merge sem duplicar (prioriza manual_override -> TMDB Discover -> categorias IPTV)
            merged: Dict[str, Dict[str, Any]] = {}
            for item in manual_items + tmdb_movies + tmdb_series + cat_movies + cat_series:
                uid = f"{item['media_type']}:{item['id']}"
                if uid in native_uids:
                    item["_native_cat"] = True
                if uid not in merged:
                    merged[uid] = item
                elif uid in native_uids:
                    merged[uid]["_native_cat"] = True

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
            tmdb_enriched = sum(1 for x in combined_items if x.get("source") in ("tmdb_discover+iptv", "manual_override"))

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
        hub_cache_key = f"streaming_hub_v3:{slug}:{iptv_url}:{username}"
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

        # Amplia cobertura de streaming_providers para 100% do catálogo via Motor Invertido Discover BR + Overrides Manuais
        if api_key and (vod_streams or series_streams):
            try:
                all_m_dedup, _ = _deduplicar_itens(vod_streams, vod_cat_map, "movie")
                all_s_dedup, _ = _deduplicar_itens(series_streams if include_series else [], series_cat_map, "series")
                m_idx, m_alt, m_pref = _construir_indices_match(all_m_dedup)
                s_idx, s_alt, s_pref = _construir_indices_match(all_s_dedup)

                discover_tasks = [
                    buscar_discover_provedor(http_client, prov_slug, api_key, force_refresh=force_refresh)
                    for prov_slug in TMDB_PROVIDER_IDS.keys()
                ]
                discover_results = await asyncio.gather(*discover_tasks, return_exceptions=True)

                enriched_vod_map = {str(v["stream_id"]): v for v in enriched_vods}
                enriched_ser_map = {str(s["series_id"]): s for s in enriched_series}

                for prov_slug, disc in zip(TMDB_PROVIDER_IDS.keys(), discover_results):
                    if isinstance(disc, Exception) or not isinstance(disc, dict):
                        continue
                    for hit in _cruzar_discover_com_indice(disc.get("movie", []), m_idx, m_alt, m_pref):
                        streaming_providers[prov_slug].append(str(hit["id"]))
                        ev = enriched_vod_map.get(str(hit["id"]))
                        if ev and prov_slug not in ev["providers"]:
                            ev["providers"].append(prov_slug)
                    for hit in _cruzar_discover_com_indice(disc.get("tv", []), s_idx, s_alt, s_pref):
                        streaming_providers[prov_slug].append(str(hit["id"]))
                        es = enriched_ser_map.get(str(hit["id"]))
                        if es and prov_slug not in es["providers"]:
                            es["providers"].append(prov_slug)
            except Exception as exc:
                logger.debug(f"Discover global no sync ignorado com segurança: {exc}")

        for ov in cache_module.cache_instance.list_manual_matches():
            oid = str(ov.get("item_id") or "")
            for prov_slug in (ov.get("providers") or []):
                ps = str(prov_slug).strip().lower()
                if ps in streaming_providers and oid:
                    streaming_providers[ps].append(oid)

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


async def executar_match_streaming(
    req: StreamingBatchMatchRequest,
    client: Optional[httpx.AsyncClient] = None,
) -> Dict[str, Any]:
    """
    Executa match completo sob demanda (POST /api/v1/streaming/match):
    - Modo A ('client_items'): recebe `req.items` enviados manualmente pelo cliente
      e devolve os IDs classificados por plataforma + metadados TMDB em uma resposta.
    - Modo B ('iptv_catalog'): lê o catálogo do servidor IPTV configurado/cacheado.
    """
    start_time = time.time()
    iptv_url = (req.iptv_url or DEFAULT_IPTV_URL).rstrip("/")
    fallback_ip = (req.fallback_ip or DEFAULT_IPTV_FALLBACK_IP).rstrip("/") if (req.fallback_ip or DEFAULT_IPTV_FALLBACK_IP) else None
    username = req.username or DEFAULT_USERNAME
    password = req.password or DEFAULT_PASSWORD
    api_key = req.tmdb_api_key or TMDB_API_KEY

    valid_slugs = list(STREAMING_PROVIDERS_META.keys())
    target_providers = [
        p.strip().lower() for p in (req.providers or valid_slugs)
        if isinstance(p, str) and p.strip().lower() in STREAMING_PROVIDERS_META
    ] or valid_slugs

    async def _run(http_client: httpx.AsyncClient) -> Dict[str, Any]:
        if req.items is not None:
            source_mode = "client_items"
            movies_list, series_list = _normalizar_itens_cliente(req.items)
            m_idx, m_alt, m_pref = _construir_indices_match(movies_list)
            s_idx, s_alt, s_pref = _construir_indices_match(series_list)
            movies_by_id = {m["id"]: m for m in movies_list}
            series_by_id = {s["id"]: s for s in series_list}
        else:
            source_mode = "iptv_catalog"
            snap = await _obter_catalogo_iptv_cacheado(
                http_client,
                iptv_url=iptv_url,
                fallback_ip=fallback_ip,
                username=username,
                password=password,
                force_refresh=bool(req.force_refresh),
            )
            movies_list = snap["movies"]
            series_list = snap["series"]
            m_idx = snap["movies_index"]
            m_alt = snap.get("movies_alt_index")
            m_pref = snap.get("movies_prefix_index")
            s_idx = snap["series_index"]
            s_alt = snap.get("series_alt_index")
            s_pref = snap.get("series_prefix_index")
            movies_by_id = snap.get("movies_by_id", {})
            series_by_id = snap.get("series_by_id", {})

        discover_by_provider: Dict[str, Dict[str, Any]] = {p: {"movie": [], "tv": []} for p in target_providers}
        if req.use_tmdb_discover and api_key:
            disc_batches = await asyncio.gather(
                *[
                    buscar_discover_provedor(
                        http_client,
                        provider_slug=p,
                        api_key=api_key,
                        pages=DISCOVER_PAGES_PER_PROVIDER,
                        force_refresh=bool(req.force_refresh),
                    )
                    for p in target_providers
                ],
                return_exceptions=True,
            )
            for p, res in zip(target_providers, disc_batches):
                if isinstance(res, dict):
                    discover_by_provider[p] = res

        streaming_providers: Dict[str, List[str]] = {}
        by_provider_stats: Dict[str, Dict[str, int]] = {}
        matched_items_by_uid: Dict[str, Dict[str, Any]] = {}

        for prov in target_providers:
            disc = discover_by_provider.get(prov, {})
            manual_hits = _resolver_overrides_para_provedor(prov, movies_by_id, series_by_id)
            tm_movies = _cruzar_discover_com_indice(disc.get("movie", []), m_idx, alt_index=m_alt, prefix_index=m_pref)
            tm_series = _cruzar_discover_com_indice(disc.get("tv", []), s_idx, alt_index=s_alt, prefix_index=s_pref)
            cat_movies = _filtrar_categorias_iptv(movies_list, prov)
            cat_series = _filtrar_categorias_iptv(series_list, prov)

            seen_prov = set()
            prov_ids: List[str] = []
            m_cnt = 0
            s_cnt = 0
            for item in manual_hits + tm_movies + tm_series + cat_movies + cat_series:
                uid = f"{item['media_type']}:{item['id']}"
                if uid in seen_prov:
                    continue
                seen_prov.add(uid)
                prov_ids.append(str(item["id"]))
                if item["media_type"] == "series":
                    s_cnt += 1
                else:
                    m_cnt += 1
                existing = matched_items_by_uid.get(uid)
                if not existing:
                    entry_copy = _clean_public_item(item)
                    entry_copy["matched_providers"] = [prov]
                    matched_items_by_uid[uid] = entry_copy
                else:
                    if prov not in existing["matched_providers"]:
                        existing["matched_providers"].append(prov)
                    if not existing.get("backdrop") and item.get("backdrop"):
                        existing["backdrop"] = item["backdrop"]

            streaming_providers[prov] = prov_ids
            by_provider_stats[prov] = {"total": len(prov_ids), "movies": m_cnt, "series": s_cnt}

        # Fallback por item individual no TMDB apenas se explicitamente solicitado
        if req.use_tmdb_search_fallback and api_key and int(req.max_search_fallback or 0) > 0:
            unmatched_pool = [
                it for it in (movies_list + series_list)
                if f"{it['media_type']}:{it['id']}" not in matched_items_by_uid
            ][: max(1, min(int(req.max_search_fallback), 80))]
            sem = asyncio.Semaphore(TMDB_CONCURRENCY_LIMIT)

            async def _search_one(it: Dict[str, Any]) -> None:
                mt_tmdb = "tv" if it["media_type"] == "series" else "movie"
                async with sem:
                    info = await buscar_tmdb(
                        http_client,
                        title=it["title"],
                        year=it.get("year_int"),
                        api_key=api_key,
                        media_type=mt_tmdb,
                        force_refresh=bool(req.force_refresh),
                    )
                if not info:
                    return
                hits_p = [p for p in info.get("providers", []) if p in streaming_providers]
                if not hits_p:
                    return
                uid = f"{it['media_type']}:{it['id']}"
                enriched = dict(it)
                enriched["tmdb_id"] = info.get("tmdb_id")
                enriched["source"] = "tmdb_search+iptv"
                if info.get("backdrop"):
                    enriched["backdrop"] = info["backdrop"]
                if info.get("poster"):
                    enriched["poster"] = info["poster"]
                if info.get("overview"):
                    enriched["overview"] = info["overview"]
                if info.get("vote_average"):
                    enriched["rating"] = float(info["vote_average"])
                cleaned = _clean_public_item(enriched)
                cleaned["matched_providers"] = []
                for p in hits_p:
                    if str(it["id"]) not in streaming_providers[p]:
                        streaming_providers[p].append(str(it["id"]))
                        by_provider_stats[p]["total"] += 1
                        if it["media_type"] == "series":
                            by_provider_stats[p]["series"] += 1
                        else:
                            by_provider_stats[p]["movies"] += 1
                    cleaned["matched_providers"].append(p)
                matched_items_by_uid[uid] = cleaned

            await asyncio.gather(*(_search_one(u) for u in unmatched_pool))

        return {
            "status": "success",
            "source_mode": source_mode,
            "total_input": len(movies_list) + len(series_list),
            "total_matched": len(matched_items_by_uid),
            "streaming_providers": streaming_providers,
            "by_provider_stats": by_provider_stats,
            "matched_items": list(matched_items_by_uid.values())[:500],
            "elapsed_seconds": round(time.time() - start_time, 2),
        }

    if client is not None:
        return await _run(client)

    async with httpx.AsyncClient(timeout=60.0) as local_client:
        return await _run(local_client)


async def salvar_match_manual(
    req: ManualOverrideRequest,
    client: Optional[httpx.AsyncClient] = None,
) -> Dict[str, Any]:
    """
    Salva um match manual persistente no SQLite e invalida caches dos hubs afetados
    para que o item apareça imediatamente nas plataformas corretas.
    """
    mt = "series" if str(req.media_type).lower() in ("series", "tv") else "movie"
    api_key = req.tmdb_api_key or TMDB_API_KEY
    clean_title, extracted_year = normalizar_titulo(req.title or "")
    target_year = req.year or extracted_year
    providers_set = {
        str(p).strip().lower() for p in (req.providers or [])
        if str(p).strip().lower() in STREAMING_PROVIDERS_META
    }

    tmdb_info = None
    if req.auto_lookup_tmdb and api_key:
        async def _lookup(http_client: httpx.AsyncClient) -> Optional[Dict[str, Any]]:
            if req.tmdb_id:
                res = await buscar_tmdb_por_id(http_client, mt, int(req.tmdb_id), api_key)
                if res:
                    return res
            mt_tmdb = "tv" if mt == "series" else "movie"
            return await buscar_tmdb(
                http_client,
                title=clean_title or req.title,
                year=target_year,
                api_key=api_key,
                media_type=mt_tmdb,
            )

        if client is not None:
            tmdb_info = await _lookup(client)
        else:
            async with httpx.AsyncClient(timeout=30.0) as local_client:
                tmdb_info = await _lookup(local_client)

    if tmdb_info:
        for p in tmdb_info.get("providers", []):
            if p in STREAMING_PROVIDERS_META:
                providers_set.add(p)

    record = {
        "item_id": str(req.item_id).strip(),
        "media_type": mt,
        "title": (tmdb_info and tmdb_info.get("title")) or clean_title or req.title,
        "raw_title": req.raw_title or req.title,
        "year": (tmdb_info and tmdb_info.get("year")) or target_year,
        "providers": sorted(providers_set),
        "tmdb_id": req.tmdb_id or (tmdb_info and tmdb_info.get("tmdb_id")),
        "poster": req.poster or (tmdb_info and tmdb_info.get("poster")) or "",
        "backdrop": req.backdrop or (tmdb_info and tmdb_info.get("backdrop")) or "",
        "overview": req.overview or (tmdb_info and tmdb_info.get("overview")) or "",
        "genre": (tmdb_info and tmdb_info.get("genre")) or "",
        "rating": (tmdb_info and tmdb_info.get("vote_average")) or 0.0,
        "trailer_key": (tmdb_info and tmdb_info.get("trailer_key")) or None,
    }
    saved = cache_module.cache_instance.set_manual_match(mt, req.item_id, record)

    # Invalida apenas os hubs afetados (ou todos caso providers tenha mudado)
    for slug in STREAMING_PROVIDERS_META.keys():
        cache_module.cache_instance.delete_by_prefix(f"streaming_hub_v3:{slug}:")

    return {
        "status": "success",
        "override": saved,
        "tmdb_enriched": bool(tmdb_info),
    }


async def warmup_iptv_snapshot_background() -> None:
    """
    Pré-carrega o catálogo bruto IPTV em memória ao subir o servidor,
    eliminando a espera fria (~19s) na primeira abertura de streaming.
    """
    start_ts = time.time()
    try:
        async with httpx.AsyncClient(timeout=60.0) as http_client:
            fallback_ip = DEFAULT_IPTV_FALLBACK_IP.rstrip("/") if DEFAULT_IPTV_FALLBACK_IP else None
            snap = await _obter_catalogo_iptv_cacheado(
                http_client,
                iptv_url=DEFAULT_IPTV_URL.rstrip("/"),
                fallback_ip=fallback_ip,
                username=DEFAULT_USERNAME,
                password=DEFAULT_PASSWORD,
                force_refresh=False,
            )
        logger.info(
            f"[Warmup] Catálogo IPTV pronto em {time.time() - start_ts:.2f}s "
            f"(filmes={len(snap.get('movies', []))}, séries={len(snap.get('series', []))})"
        )
    except Exception as exc:
        logger.warning(f"[Warmup] Pré-aquecimento inicial ignorado sem afetar o boot: {exc}")


async def obter_trending_match(
    req: Optional[SyncRequest] = None,
    force_refresh: bool = False,
    client: Optional[httpx.AsyncClient] = None,
) -> Dict[str, Any]:
    """
    Cruza /trending/movie/week e /trending/tv/week do TMDB com 100% do catálogo IPTV,
    entregando os lançamentos e populares em alta disponíveis no servidor.
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

    async def _run(http_client: httpx.AsyncClient) -> Dict[str, Any]:
        snap, trending = await asyncio.gather(
            _obter_catalogo_iptv_cacheado(
                http_client,
                iptv_url=iptv_url,
                fallback_ip=fallback_ip,
                username=username,
                password=password,
                force_refresh=force_refresh,
            ),
            buscar_trending_semana(http_client, api_key=api_key, pages=2, force_refresh=force_refresh),
        )
        m_hits = _cruzar_discover_com_indice(
            trending.get("movie", []),
            snap["movies_index"],
            alt_index=snap.get("movies_alt_index"),
            prefix_index=snap.get("movies_prefix_index"),
        )
        s_hits = _cruzar_discover_com_indice(
            trending.get("tv", []),
            snap["series_index"],
            alt_index=snap.get("series_alt_index"),
            prefix_index=snap.get("series_prefix_index"),
        )
        return {
            "status": "success",
            "generated_at": int(time.time() * 1000),
            "counts": {
                "movies": len(m_hits),
                "series": len(s_hits),
                "total": len(m_hits) + len(s_hits),
            },
            "movies": [_clean_public_item(it) for it in m_hits[:40]],
            "series": [_clean_public_item(it) for it in s_hits[:40]],
            "elapsed_seconds": round(time.time() - start_time, 2),
        }

    if client is not None:
        return await _run(client)
    async with httpx.AsyncClient(timeout=60.0) as local_client:
        return await _run(local_client)


async def aquecer_todos_hubs(
    req: Optional[SyncRequest] = None,
    force_refresh: bool = False,
    client: Optional[httpx.AsyncClient] = None,
) -> Dict[str, Any]:
    """
    Reconstrói todos os hubs em servidor compartilhando uma única leitura de catálogo IPTV.
    """
    start_time = time.time()
    summary: Dict[str, Any] = {}

    async def _warm(http_client: httpx.AsyncClient) -> None:
        for slug in STREAMING_PROVIDERS_META.keys():
            hub = await obter_hub_provedor(
                provider_slug=slug,
                req=req,
                force_refresh=force_refresh,
                client=http_client,
            )
            summary[slug] = hub.get("stats", {})

    if client is not None:
        await _warm(client)
    else:
        async with httpx.AsyncClient(timeout=60.0) as local_client:
            await _warm(local_client)

    return {
        "status": "success",
        "providers_warmed": len(summary),
        "stats": summary,
        "elapsed_seconds": round(time.time() - start_time, 2),
    }
