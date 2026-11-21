"""
Schemas Pydantic para validação de dados de entrada e contratos de saída da API.
"""
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class SyncRequest(BaseModel):
    iptv_url: Optional[str] = Field(None, description="URL oficial ou Link (domínio) do servidor IPTV Xtream Codes")
    fallback_ip: Optional[str] = Field(None, description="IP direto de contingência para fallback em caso de falha de conexão com a URL principal")
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
    version: str = "2.2.0"


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


class StreamingHubItem(BaseModel):
    id: str
    media_type: str  # "movie" | "series"
    title: str
    raw_title: str
    year: str = ""
    rating: float = 0.0
    quality: str = "HD"
    audio: str = ""
    is_legendado: bool = False
    poster: str = ""
    backdrop: str = ""
    overview: str = ""
    genre: str = ""
    duration_secs: int = 0
    container_extension: str = "mp4"
    category_id: str = "0"
    category_name: str = ""
    tmdb_id: Optional[int] = None
    trailer_key: Optional[str] = None
    source: str = "iptv"  # "tmdb_discover+iptv" | "iptv_category" | "manual_override"
    versions_count: int = 1


class StreamingHubResponse(BaseModel):
    status: str = "success"
    provider: Dict[str, Any]
    cached: bool = False
    generated_at: int
    stats: Dict[str, int]
    hero: Optional[StreamingHubItem] = None
    shelves: Dict[str, List[StreamingHubItem]]
    search_results: Optional[List[StreamingHubItem]] = None


class StreamingHubsSummaryResponse(BaseModel):
    status: str = "success"
    generated_at: int
    providers: List[Dict[str, Any]]


class ManualMatchItemInput(BaseModel):
    id: str
    name: str
    media_type: str = "movie"
    category_name: str = ""
    year: Optional[str] = None
    poster: str = ""
    rating: Optional[Any] = None
    container_extension: str = "mp4"


class StreamingBatchMatchRequest(BaseModel):
    items: Optional[List[ManualMatchItemInput]] = None
    providers: Optional[List[str]] = None
    use_tmdb_discover: bool = True
    use_tmdb_search_fallback: bool = False
    max_search_fallback: int = 30
    force_refresh: bool = False
    iptv_url: Optional[str] = None
    fallback_ip: Optional[str] = None
    username: Optional[str] = None
    password: Optional[str] = None
    tmdb_api_key: Optional[str] = None


class ManualOverrideRequest(BaseModel):
    item_id: str
    media_type: str = "movie"
    title: str
    year: Optional[int] = None
    providers: List[str] = []
    tmdb_id: Optional[int] = None
    auto_lookup_tmdb: bool = True
    tmdb_api_key: Optional[str] = None
    raw_title: Optional[str] = None
    poster: Optional[str] = None
    backdrop: Optional[str] = None
    overview: Optional[str] = None
