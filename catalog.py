"""
Serviço de Orquestração, Normalização e Enriquecimento do Catálogo IPTV + TMDB.
"""
import asyncio
import logging
import time
from typing import Any, Dict, List, Optional
import httpx
from config import (
    DEFAULT_IPTV_URL,
    DEFAULT_PASSWORD,
    DEFAULT_USERNAME,
    MAX_ITEMS_ENRICHMENT,
    TMDB_API_KEY,
    TMDB_CONCURRENCY_LIMIT,
    TMDB_PROVIDER_IDS,
)
from iptv import fetch_iptv_catalog
from normalizer import calcular_rating_5based, detectar_provedores_heuristica, normalizar_titulo
from schemas import CatalogMetrics, SyncCatalogResponse, SyncRequest
from tmdb import buscar_tmdb

logger = logging.getLogger(__name__)


async def sincronizar_catalogo(
    req: Optional[SyncRequest] = None,
    client: Optional[httpx.AsyncClient] = None,
) -> Dict[str, Any]:
    """
    Executa o fluxo completo de sincronização:
    1. Obtém dados brutos do IPTV
    2. Normaliza títulos e extrai ano
    3. Cruza com TMDB para pôsteres 4K, sinopse em PT-BR e Watch Providers
    4. Categoriza provedores de streaming (Globoplay, Netflix, etc.)
    5. Retorna o contrato pronto para IndexedDB e localStorage do cliente
    """
    start_time = time.time()

    iptv_url = (req.iptv_url if req and req.iptv_url else DEFAULT_IPTV_URL).rstrip("/")
    username = req.username if req and req.username else DEFAULT_USERNAME
    password = req.password if req and req.password else DEFAULT_PASSWORD
    api_key = req.tmdb_api_key if req and req.tmdb_api_key else TMDB_API_KEY
    force_refresh = req.force_refresh if req else False
    include_series = req.include_series if req else True
    limit_vods = req.limit_vods if req and req.limit_vods else MAX_ITEMS_ENRICHMENT
    limit_series = req.limit_series if req and req.limit_series else MAX_ITEMS_ENRICHMENT

    async def _process(http_client: httpx.AsyncClient) -> Dict[str, Any]:
        # 1. Download dos dados brutos do IPTV
        vod_streams, vod_categories, series_streams, series_categories = await fetch_iptv_catalog(
            http_client,
            iptv_url=iptv_url,
            username=username,
            password=password,
            include_series=include_series,
        )

        total_vods_raw = len(vod_streams)
        total_series_raw = len(series_streams)

        # Mapeamentos de ID de categoria para nome
        vod_cat_map = {str(c.get("category_id")): str(c.get("category_name", "")) for c in vod_categories}
        series_cat_map = {str(c.get("category_id")): str(c.get("category_name", "")) for c in series_categories}

        # Inicializa lista de IDs por provedor
        streaming_providers: Dict[str, List[str]] = {prov: [] for prov in TMDB_PROVIDER_IDS.keys()}
        sem = asyncio.Semaphore(TMDB_CONCURRENCY_LIMIT)

        matched_count = 0

        # 2. Processamento concorrente de Filmes (VODs)
        async def process_movie(item: Dict[str, Any]) -> Dict[str, Any]:
            nonlocal matched_count
            stream_id = str(item.get("stream_id") or item.get("id", ""))
            raw_name = str(item.get("name") or "")
            cat_id = str(item.get("category_id", "0"))
            cat_name = vod_cat_map.get(cat_id, "")

            clean_name, ano = normalizar_titulo(raw_name)

            # Heurística inicial via nome e categoria
            matched_providers = detectar_provedores_heuristica(raw_name, cat_name)

            # Busca e enriquecimento no TMDB
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

            # Adiciona ao índice por provedor
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

        # 3. Processamento de Séries
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

        # Aplica limite para enriquecimento inicial de alto desempenho
        vods_to_enrich = vod_streams[:limit_vods]
        series_to_enrich = series_streams[:limit_series] if include_series else []

        enriched_vods = await asyncio.gather(*(process_movie(v) for v in vods_to_enrich))
        enriched_series = await asyncio.gather(*(process_series(s) for s in series_to_enrich))

        # Remove duplicatas nos provedores
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
