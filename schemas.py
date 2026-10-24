"""
Schemas Pydantic para validação de dados de entrada e contratos de saída da API.
"""
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class SyncRequest(BaseModel):
    iptv_url: Optional[str] = Field(None, description="URL base ou IP do servidor IPTV Xtream Codes")
    username: Optional[str] = Field(None, description="Usuário IPTV")
    password: Optional[str] = Field(None, description="Senha IPTV")
    tmdb_api_key: Optional[str] = Field(None, description="Chave de API v3 do The Movie Database (TMDB)")
    force_refresh: bool = Field(False, description="Se True, ignora o cache e força nova busca no TMDB")
    include_series: bool = Field(True, description="Se True, sincroniza também séries")
    limit_vods: Optional[int] = Field(None, description="Limite máximo de VODs a enriquecer (opcional)")
    limit_series: Optional[int] = Field(None, description="Limite máximo de séries a enriquecer (opcional)")


class HealthResponse(BaseModel):
    status: str = "ok"
    service: str = "pera-tv-api"
    version: str = "2.1.0"


class CatalogMetrics(BaseModel):
    total_vods_iptv: int
    total_series_iptv: int
    matched_with_tmdb: int
    unmatched: int
    elapsed_seconds: float
    total_vods: int
    total_series: int


class SyncCatalogResponse(BaseModel):
    status: str = "success"
    schema_version: int = 2
    revision: str
    generated_at: int
    metrics: CatalogMetrics
    streaming_providers: Dict[str, List[str]]
    vod_categories: List[Dict[str, Any]]
    vod_streams: List[Dict[str, Any]]
    series_categories: List[Dict[str, Any]]
    series_streams: List[Dict[str, Any]]
