"""
Configurações, chaves e credenciais embutidas do projeto Pera TV (BFF).
Todas as credenciais funcionam 'out-of-the-box' diretamente no código e
também aceitam sobrescrita via variáveis de ambiente.
"""
import os
import re

# ==============================================================================
# CONFIGURAÇÕES E CHAVES EMBUTIDAS (PLUG-AND-PLAY)
# ==============================================================================
TMDB_API_KEY = os.getenv("TMDB_API_KEY", "0be70a0df8da0d4df674178ecb774db1")
TMDB_READ_TOKEN = os.getenv(
    "TMDB_READ_TOKEN",
    (
        "eyJhbGciOiJIUzI1NiJ9.eyJhdWQiOiIwYmU3MGEwZGY4ZGEwZDRkZjY3NDE3OGVjYjc3NGRiMSIs"
        "Im5iZiI6MTc4NDMxNDk0My40Nywic3ViIjoiNmE1YTdjM2ZlMzFjZmYzOWQwMWYzNjIxIiwic2NvcGVzIjp"
        "bImFwaV9yZWFkIl0sInZlcnNpb24iOjF9.CdW7Gix6ncyw6F681hAt00KtmfWb3ZSEjcXqePZ-5hk"
    ),
)

DEFAULT_IPTV_URL = os.getenv("IPTV_URL", "http://149.78.186.18")
DEFAULT_USERNAME = os.getenv("IPTV_USERNAME", "57430164")
DEFAULT_PASSWORD = os.getenv("IPTV_PASSWORD", "22727897")

TMDB_BASE = "https://api.themoviedb.org/3"

# IDs Oficiais de Streaming no TMDB para o Brasil (JustWatch)
TMDB_PROVIDER_IDS = {
    "globoplay": 307,
    "netflix": 8,
    "hbo": 384,
    "disney": 337,
    "prime": 119,
    "apple": 350,
    "telecine": 227,
    "paramount": 531,
    "mubi": 11,
}

# Regex Heurístico para categorias/nomes do IPTV
REGEX_CATEGORIA_FALLBACK = {
    "globoplay": re.compile(
        r"\b(globoplay|globo\s*play|globo\s*filmes|rede\s*globo|gshow|canaisglobo)\b|\[globo\]|\bglobo\b",
        re.I,
    ),
    "netflix": re.compile(r"\b(netflix|nflx)\b", re.I),
    "hbo": re.compile(r"\b(hbo(\s*max)?|max\s*original|warner)\b", re.I),
    "disney": re.compile(
        r"\b(disney\+?|marvel|pixar|star\s*wars|natgeo|lucasfilm)\b", re.I
    ),
    "prime": re.compile(r"\b(prime\s*video|amazon\s*prime|amazon|mgm)\b", re.I),
    "apple": re.compile(r"\b(apple\s*tv\+?|apple\s*original)\b", re.I),
    "telecine": re.compile(r"\b(telecine|tlcn)\b", re.I),
    "paramount": re.compile(r"\b(paramount\+?)\b", re.I),
    "mubi": re.compile(r"\b(mubi)\b", re.I),
}

# Regex de ruídos para limpeza de títulos IPTV
REGEX_RUIDOS = re.compile(
    r"(\[.*?\]|\(.*?\)|"
    r"\b(4k|uhd|fhd|hd|sd|1080p|720p|2160p|hevc|h265|x264|web-dl|bluray|cam|ts)\b|"
    r"\b(dublado|dub|legendado|leg|nacional|dual\s*audio|completo)\b)",
    re.IGNORECASE,
)

# Configurações de Cache Local (TTL 7 dias = 604800 segundos)
CACHE_DB_PATH = os.getenv("CACHE_DB_PATH", "cache.db")
CACHE_TTL_SECONDS = int(os.getenv("CACHE_TTL_SECONDS", str(7 * 24 * 3600)))

# Concorrência e Timeouts
TMDB_CONCURRENCY_LIMIT = int(os.getenv("TMDB_CONCURRENCY_LIMIT", "15"))
IPTV_REQUEST_TIMEOUT = float(os.getenv("IPTV_REQUEST_TIMEOUT", "45.0"))
TMDB_REQUEST_TIMEOUT = float(os.getenv("TMDB_REQUEST_TIMEOUT", "6.0"))
MAX_ITEMS_ENRICHMENT = int(os.getenv("MAX_ITEMS_ENRICHMENT", "800"))
