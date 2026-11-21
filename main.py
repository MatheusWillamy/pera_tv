"""
Pera TV - Backend de Ingestão e Normalização IPTV + TMDB (BFF).
Implementação FastAPI com suporte a CORS, Docker, Easypanel, Hubs de Streaming
com motor invertido TMDB Discover BR (JustWatch) e contratos IndexedDB.
"""
import logging
from typing import Optional
from fastapi import FastAPI, HTTPException, Query, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

import cache as cache_module
from catalog import clear_memory_snapshot, obter_hub_provedor, obter_hubs_resumo, sincronizar_catalogo
from iptv import IPTVAuthError, IPTVConnectionError
from schemas import (
    HealthResponse,
    StreamingHubResponse,
    StreamingHubsSummaryResponse,
    SyncCatalogResponse,
    SyncRequest,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("pera_tv_api")

app = FastAPI(
    title="Pera TV - IPTV TMDB Enrichment BFF",
    description="Middleware de alto desempenho para enriquecimento e categorização de IPTV com TMDB",
    version="2.1.0",
)

# ==============================================================================
# CORS COMPLETO ATIVADO (inclui origem file:/// -> Origin: null)
# ==============================================================================
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ==============================================================================
# TRATAMENTO DE ERROS CUSTOMIZADOS
# ==============================================================================
@app.exception_handler(IPTVAuthError)
async def iptv_auth_exception_handler(request: Request, exc: IPTVAuthError):
    return JSONResponse(
        status_code=status.HTTP_401_UNAUTHORIZED,
        content={"status": "error", "error_code": "IPTV_AUTH_FAILED", "detail": str(exc)},
    )


@app.exception_handler(IPTVConnectionError)
async def iptv_connection_exception_handler(request: Request, exc: IPTVConnectionError):
    return JSONResponse(
        status_code=status.HTTP_504_GATEWAY_TIMEOUT,
        content={"status": "error", "error_code": "IPTV_CONNECTION_FAILED", "detail": str(exc)},
    )


# ==============================================================================
# ROTAS PRINCIPAIS
# ==============================================================================
@app.get("/", tags=["Info"])
async def root():
    return {
        "service": "pera-tv-api",
        "version": "2.1.0",
        "status": "online",
        "documentation": "/docs",
        "health": "/health",
        "sync_endpoint": "/api/v1/sync/catalog",
        "streaming_hubs": "/api/v1/streaming/hubs",
        "streaming_hub_detail": "/api/v1/streaming/hub/{provider}",
    }


@app.get("/health", response_model=HealthResponse, tags=["Health"])
async def health():
    return {
        "status": "ok",
        "service": "pera-tv-api",
        "version": "2.1.0",
    }


# ==============================================================================
# HUBS DE STREAMING (PROCESSAMENTO 100% NO SERVIDOR - ZERO PESO NA TV BOX)
# ==============================================================================
@app.get("/api/v1/streaming/hubs", response_model=StreamingHubsSummaryResponse, tags=["Streaming Hubs"])
async def list_streaming_hubs():
    """Retorna metadados, logos oficiais TMDB e contadores em cache de todas as plataformas."""
    return await obter_hubs_resumo(req=None)


@app.get("/api/v1/streaming/hub/{provider}", response_model=StreamingHubResponse, tags=["Streaming Hubs"])
async def get_streaming_hub(
    provider: str,
    media_type: str = Query("all", pattern="^(all|movie|series)$"),
    q: Optional[str] = Query(None, description="Filtro de busca instantânea no provedor"),
    force_refresh: bool = Query(False, description="Ignora cache SQLite 24h e reconstrói o hub"),
    iptv_url: Optional[str] = Query(None),
    username: Optional[str] = Query(None),
    password: Optional[str] = Query(None),
):
    """
    Entrega o Hub completo de um streaming (Netflix, HBO Max, Disney+, Prime Video, etc.)
    já deduplicado, enriquecido com TMDB Discover BR (backdrop w780, poster w342, sinopse PT-BR,
    nota real e trailer YouTube do Hero) e cacheado no SQLite por 24h.
    """
    try:
        req_obj = (
            SyncRequest(iptv_url=iptv_url, username=username, password=password, force_refresh=force_refresh)
            if (iptv_url or username or password)
            else None
        )
        return await obter_hub_provedor(
            provider_slug=provider,
            req=req_obj,
            media_type=media_type,
            query=q,
            force_refresh=force_refresh,
        )
    except (IPTVAuthError, IPTVConnectionError):
        raise
    except Exception as exc:
        logger.exception(f"Erro ao montar hub de streaming '{provider}': {exc}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Falha interna ao montar hub de streaming: {str(exc)}",
        )


@app.post("/api/v1/streaming/hub/{provider}", response_model=StreamingHubResponse, tags=["Streaming Hubs"])
async def post_streaming_hub(
    provider: str,
    req: Optional[SyncRequest] = None,
    media_type: str = Query("all", pattern="^(all|movie|series)$"),
    q: Optional[str] = Query(None),
):
    """Versão POST do Hub de Streaming aceitando credenciais IPTV/TMDB no corpo JSON."""
    try:
        req_obj = req or SyncRequest()
        return await obter_hub_provedor(
            provider_slug=provider,
            req=req_obj,
            media_type=media_type,
            query=q,
            force_refresh=bool(req_obj.force_refresh),
        )
    except (IPTVAuthError, IPTVConnectionError):
        raise
    except Exception as exc:
        logger.exception(f"Erro no POST hub de streaming '{provider}': {exc}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Falha interna ao montar hub de streaming: {str(exc)}",
        )


# ==============================================================================
# SINCRONIZAÇÃO COMPLETA DE CATÁLOGO (CONTRATO INDEXEDDB)
# ==============================================================================
@app.get("/api/v1/sync/catalog", response_model=SyncCatalogResponse, tags=["Catalog"])
async def sync_catalog_get():
    try:
        return await sincronizar_catalogo(req=None)
    except (IPTVAuthError, IPTVConnectionError):
        raise
    except Exception as exc:
        logger.exception(f"Erro inesperado no sync GET: {exc}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Falha interna ao processar catálogo: {str(exc)}",
        )


@app.post("/api/v1/sync/catalog", response_model=SyncCatalogResponse, tags=["Catalog"])
async def sync_catalog_post(req: Optional[SyncRequest] = None):
    try:
        req_obj = req or SyncRequest()
        return await sincronizar_catalogo(req=req_obj)
    except (IPTVAuthError, IPTVConnectionError):
        raise
    except Exception as exc:
        logger.exception(f"Erro inesperado no sync POST: {exc}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Falha interna ao processar catálogo: {str(exc)}",
        )


# ==============================================================================
# ROTAS DE MONITORAMENTO E ADMINISTRAÇÃO DO CACHE
# ==============================================================================
@app.get("/api/v1/cache/stats", tags=["Cache"])
async def get_cache_stats():
    """Retorna métricas do banco de cache local SQLite (TTL de 7 dias)."""
    return cache_module.cache_instance.stats()


@app.post("/api/v1/cache/clear", tags=["Cache"])
async def clear_cache():
    """Limpa todos os dados armazenados no cache SQLite e snapshot em memória."""
    deleted = cache_module.cache_instance.clear()
    clear_memory_snapshot()
    return {"status": "success", "deleted_records": deleted}


@app.post("/api/v1/cache/purge", tags=["Cache"])
async def purge_expired_cache():
    """Remove registros antigos que ultrapassaram o TTL de 7 dias."""
    purged = cache_module.cache_instance.purge_expired()
    return {"status": "success", "purged_records": purged}


if __name__ == "__main__":
    import uvicorn
    from config import PORT
    uvicorn.run("main:app", host="0.0.0.0", port=PORT, reload=False)
