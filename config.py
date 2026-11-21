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

# Link Oficial (Domínio/DNS) exibido como configuração principal
DEFAULT_IPTV_URL = os.getenv("IPTV_URL", "http://dg25.me")
# IP Direto de Contingência (para uso direto de emergência caso haja problema no link)
DEFAULT_IPTV_FALLBACK_IP = os.getenv("IPTV_FALLBACK_IP", "http://50.7.178.191")
DEFAULT_USERNAME = os.getenv("IPTV_USERNAME", "57430164")
DEFAULT_PASSWORD = os.getenv("IPTV_PASSWORD", "22727897")

TMDB_BASE = "https://api.themoviedb.org/3"
TMDB_IMG_BASE = "https://image.tmdb.org/t/p"

# IDs Oficiais de Streaming no TMDB para o Brasil (JustWatch - múltiplos IDs suportados)
# Nota: HBO Max passou a usar ID 1899 no TMDB BR (mantemos 384 como legado).
TMDB_PROVIDER_IDS = {
    "globoplay": [307],
    "netflix": [8, 1796],
    "hbo": [1899, 384, 1825],
    "disney": [337],
    "prime": [119, 2100],
    "apple": [350],
    "telecine": [227, 2156],
    "paramount": [531, 582, 2303],
    "mubi": [11],
}

# Metadados visuais e logos oficiais TMDB para os Hubs de Streaming
STREAMING_PROVIDERS_META = {
    "netflix": {
        "id": "netflix",
        "name": "Netflix",
        "badge": "ORIGINAL NETFLIX",
        "color": "#E50914",
        "glow": "rgba(229, 9, 20, 0.45)",
        "logo": f"{TMDB_IMG_BASE}/original/rK1KljqmbvO9HQa1PBFLILWah72.png",
    },
    "hbo": {
        "id": "hbo",
        "name": "HBO Max",
        "badge": "MAX ORIGINAL & HBO",
        "color": "#9933FF",
        "glow": "rgba(153, 51, 255, 0.48)",
        "logo": f"{TMDB_IMG_BASE}/original/skypuy7SXuugIQeYg0IglmzoKaS.png",
    },
    "disney": {
        "id": "disney",
        "name": "Disney+",
        "badge": "DISNEY, PIXAR & MARVEL",
        "color": "#0063E5",
        "glow": "rgba(0, 99, 229, 0.48)",
        "logo": f"{TMDB_IMG_BASE}/original/5eZ872CghnHFLB1j8grszbrx0dx.png",
    },
    "prime": {
        "id": "prime",
        "name": "Prime Video",
        "badge": "AMAZON EXCLUSIVE & MGM",
        "color": "#00A8E1",
        "glow": "rgba(0, 168, 225, 0.45)",
        "logo": f"{TMDB_IMG_BASE}/original/gMZdpavHmxFNnLpMHwVxfqeux2g.png",
    },
    "apple": {
        "id": "apple",
        "name": "Apple TV+",
        "badge": "APPLE ORIGINAL",
        "color": "#F8FAFC",
        "glow": "rgba(248, 250, 252, 0.35)",
        "logo": f"{TMDB_IMG_BASE}/original/v9SnyvYt0U3KGgBH3Sbh3z4yODe.png",
    },
    "globoplay": {
        "id": "globoplay",
        "name": "Globoplay",
        "badge": "ORIGINAL GLOBOPLAY",
        "color": "#FF5722",
        "glow": "rgba(255, 87, 34, 0.45)",
        "logo": f"{TMDB_IMG_BASE}/original/9A6Oxd3F7iXm7mds7CxYOBicojs.png",
    },
    "paramount": {
        "id": "paramount",
        "name": "Paramount+",
        "badge": "PARAMOUNT+ ORIGINAL",
        "color": "#0064FF",
        "glow": "rgba(0, 100, 255, 0.45)",
        "logo": f"{TMDB_IMG_BASE}/original/pkx3klJlwW5JdtaulvDx6hDNtch.png",
    },
    "telecine": {
        "id": "telecine",
        "name": "Telecine",
        "badge": "TELECINE PREMIUM",
        "color": "#E74C3C",
        "glow": "rgba(231, 76, 60, 0.45)",
        "logo": "",
    },
    "mubi": {
        "id": "mubi",
        "name": "Mubi",
        "badge": "MUBI SELECTION",
        "color": "#1ABC9C",
        "glow": "rgba(26, 188, 156, 0.45)",
        "logo": f"{TMDB_IMG_BASE}/original/k7iSlvgWzZuO4zU5PcBjhABMuia.png",
    },
}

# Regex Heurístico para categorias/nomes do IPTV (sem falsos positivos como "Kurt Warner")
REGEX_CATEGORIA_FALLBACK = {
    "globoplay": re.compile(
        r"\b(globoplay|globo\s*play|globo\s*filmes|rede\s*globo|gshow|canaisglobo)\b|\[globo\]",
        re.I,
    ),
    "netflix": re.compile(r"\b(netflix|nflx|net\s*flix)\b", re.I),
    "hbo": re.compile(
        r"\b(hbo(\s*max)?|max\s*original|warner\s+(bros|channel|filmes|pictures))\b",
        re.I,
    ),
    "disney": re.compile(
        r"\b(disney\s*(\+|plus)?|walt\s*disney|marvel(\s*studios)?|pixar|star\s*wars|natgeo|national\s*geographic|lucasfilm|star\s*(\+|plus))\b",
        re.I,
    ),
    "prime": re.compile(
        r"\b(prime\s*video|amazon\s*prime|amazon\s*studios|amazon\s*original|mgm\+?)\b",
        re.I,
    ),
    "apple": re.compile(r"\b(apple\s*tv\s*(\+|plus)?|apple\s*original)\b", re.I),
    "telecine": re.compile(r"\b(telecine|tlcn)\b", re.I),
    "paramount": re.compile(r"\b(paramount\s*(\+|plus)?|paramount\s*pictures)\b", re.I),
    "mubi": re.compile(r"\b(mubi)\b", re.I),
}

# Regras de rejeição negativa para evitar falsos positivos em títulos
REGEX_CATEGORIA_REJEICAO = {
    "hbo": re.compile(r"\b(mad\s*max|kurt\s*warner|max\s*payne|maximum|climax)\b", re.I),
    "disney": re.compile(r"\b(battle\s+star\s+wars|star\s+wars\s+parody|spaceballs)\b", re.I),
    "prime": re.compile(r"\b(optimus\s*prime|prime\s*time|primeira|amaz[oô]nia|amazonas)\b", re.I),
    "apple": re.compile(r"\b(apple\s*pie|big\s*apple)\b", re.I),
    "globoplay": re.compile(r"\b(globo\s*da\s*morte)\b", re.I),
}

# Regex de ruídos para limpeza de títulos IPTV
REGEX_RUIDOS = re.compile(
    r"(\[.*?\]|\(.*?\)|"
    r"\b(4k|uhd|fhd|hd|sd|1080p|720p|2160p|hevc|h265|x264|web-dl|bluray|cam|ts|hdr|hdr10|dolby)\b|"
    r"\b(dublado|dub|legendado|leg|nacional|dual\s*audio|completo)\b)",
    re.IGNORECASE,
)

# Configurações de Cache Local (TTL 7 dias = 604800 segundos)
CACHE_DB_PATH = os.getenv("CACHE_DB_PATH", "cache.db")
CACHE_TTL_SECONDS = int(os.getenv("CACHE_TTL_SECONDS", str(7 * 24 * 3600)))
HUB_CACHE_TTL_SECONDS = int(os.getenv("HUB_CACHE_TTL_SECONDS", str(24 * 3600)))
DISCOVER_PAGES_PER_PROVIDER = int(os.getenv("DISCOVER_PAGES_PER_PROVIDER", "8"))
DISCOVER_TV_PAGES_PER_PROVIDER = int(os.getenv("DISCOVER_TV_PAGES_PER_PROVIDER", "3"))

# Concorrência e Timeouts
TMDB_CONCURRENCY_LIMIT = int(os.getenv("TMDB_CONCURRENCY_LIMIT", "15"))
IPTV_REQUEST_TIMEOUT = float(os.getenv("IPTV_REQUEST_TIMEOUT", "45.0"))
TMDB_REQUEST_TIMEOUT = float(os.getenv("TMDB_REQUEST_TIMEOUT", "6.0"))
MAX_ITEMS_ENRICHMENT = int(os.getenv("MAX_ITEMS_ENRICHMENT", "800"))

# Porta do Servidor (Padrão: 8001) e warmup em background
PORT = int(os.getenv("PORT", "8001"))
ENABLE_STARTUP_WARMUP = os.getenv("ENABLE_STARTUP_WARMUP", "true").lower() in ("1", "true", "yes")
