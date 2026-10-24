"""
Pera TV - Backend de Ingestão e Normalização IPTV + TMDB (BFF).
Implementação FastAPI com suporte a CORS, Docker, Easypanel e contratos IndexedDB.
"""
import logging
from typing import Any, Dict, Optional
from fastapi import FastAPI, HTTPException, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from cache import cache_instance
from catalog import sincronizar_catalogo
from iptv import IPTVAuthError, IPTVConnectionError
from schemas import HealthResponse, SyncCatalogResponse, SyncRequest

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
# CORS COMPLETO ATIVADO
# ==============================================================================
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
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
    }


@app.get("/health", response_model=HealthResponse, tags=["Health"])
async def health():
    return {
        "status": "ok",
        "service": "pera-tv-api",
        "version": "2.1.0",
    }


@app.get("/api/v1/sync/catalog", response_model=SyncCatalogResponse, tags=["Catalog"])
async def sync_catalog_get():
    """
    Sincronização com Zero Configuração:
    Utiliza automaticamente as chaves e credenciais embutidas no código.
    Pode ser acessado diretamente no navegador ou via GET simples no frontend.
    """
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
    """
    Sincronização com Sobrescrita Dinâmica Opcional:
    Permite enviar credenciais customizadas de IPTV ou chave TMDB no JSON Body.
    Qualquer campo omitido utiliza o valor padrão embutido.
    """
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
    return cache_instance.stats()


@app.post("/api/v1/cache/clear", tags=["Cache"])
async def clear_cache():
    """Limpa todos os dados armazenados no cache SQLite."""
    deleted = cache_instance.clear()
    return {"status": "success", "deleted_records": deleted}


@app.post("/api/v1/cache/purge", tags=["Cache"])
async def purge_expired_cache():
    """Remove registros antigos que ultrapassaram o TTL de 7 dias."""
    purged = cache_instance.purge_expired()
    return {"status": "success", "purged_records": purged}


if __name__ == "__main__":
    import uvicorn
    from config import PORT
    uvicorn.run("main:app", host="0.0.0.0", port=PORT, reload=False)

