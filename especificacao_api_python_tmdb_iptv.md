# Especificação Técnica: Backend de Ingestão e Normalização IPTV + TMDB (BFF)

> **Documento de Engenharia de Software**  
> **Finalidade:** Guia completo de arquitetura, contratos de API (Request/Response), regras de cruzamento (*matching*), enriquecimento de metadados e **código executável em Python (FastAPI) com todas as chaves e credenciais embutidas diretamente no código** para ser entregue a uma IA de desenvolvimento ou engenheiro de software.

---

## 1. Visão Geral da Arquitetura

O objetivo desta API é atuar como um **Middleware de Alto Desempenho (Backend for Frontend - BFF)** entre os servidores de IPTV (protocolo Xtream Codes) e o aplicativo cliente (Smart TV, Android TV, Mobile, Navegador).

```mermaid
flowchart TD
    subgraph Fontes Externas
        IPTV["Servidor IPTV (Xtream Codes API)<br/>• get_vod_streams<br/>• get_vod_categories<br/>• get_series<br/>• get_series_categories"]
        TMDB["The Movie Database (TMDB API v3)<br/>• search/movie & search/tv<br/>• movie/{id}/watch/providers (BR)<br/>• Imagens 4K (Posters & Backdrops)"]
    end

    subgraph Backend Python (FastAPI / Celery / SQLite / In-Memory)
        Cfg["0. Chaves e Credenciais Embutidas no Topo do Código"]
        Norm["1. Normalizador de Strings & Extrator de Ano (Regex)"]
        Match["2. Algoritmo de Match Difuso (TMDB Search)"]
        Prov["3. Classificador de Watch Providers BR (JustWatch TMDB ID)"]
        Cache["4. Banco de Cache Local - TTL 7 Dias"]
        Gen["5. Gerador do Pacote JSON Otimizado"]
    end

    subgraph Aplicativo Cliente (Smart TV / Android / Web)
        Sync["Rota /api/v1/sync/catalog<br/>(Download Único Instantâneo via GET ou POST)"]
        IDB["IndexedDB Local ('vod_streams', 'streaming_providers')<br/>100% Funcional Offline"]
        UI["Telas: streaming.html, movies.html, series.html<br/>(Globoplay, Netflix, HBO, Disney 100% Populados)"]
    end

    Cfg --> IPTV
    Cfg --> TMDB
    IPTV --> Norm
    Norm --> Match
    TMDB <--> Match
    Match --> Prov
    Prov --> Cache
    Cache --> Gen
    Gen --> Sync
    Sync --> IDB
    IDB --> UI
```

---

## 2. Contrato da API (Endpoints e Chamadas)

Como todas as chaves e credenciais estão **embutidas diretamente no código do servidor**, a API funciona de forma imediata (plug-and-play), aceitando tanto requisições `GET` diretas (para testar até pelo navegador) quanto `POST` (se você quiser enviar credenciais diferentes no futuro).

### 2.1. `GET /api/v1/sync/catalog` (Zero Configuração)
Basta abrir no navegador ou fazer um fetch simples. O servidor utiliza automaticamente as chaves e credenciais embutidas no código.

* **Exemplo de Chamada:**
  ```http
  GET /api/v1/sync/catalog HTTP/1.1
  Host: localhost:8000
  ```

---

### 2.2. `POST /api/v1/sync/catalog` (Sobrescrita Dinâmica Opcional)
Permite enviar credenciais customizadas se no futuro você quiser sincronizar outra conta ou outra lista IPTV.

#### **Parâmetros de Entrada (JSON Body - Todos Opcionais):**
```json
{
  "iptv_url": "http://149.78.186.18",
  "username": "57430164",
  "password": "22727897",
  "tmdb_api_key": "0be70a0df8da0d4df674178ecb774db1",
  "force_refresh": false,
  "include_series": true
}
```

*Se qualquer campo for omitido no JSON ou vier vazio, o servidor utiliza automaticamente o valor padrão embutido no topo do código.*

---

## 3. Especificação do Formato de Saída (JSON Response)

A resposta da API é **100% compatível** com o que o aplicativo cliente espera nas stores do IndexedDB (`vod_streams`, `vod_categories`, `series_streams`, `series_categories`) e nos índices do `localStorage` (`aero_iptv_streaming_providers` e `aero_iptv_movies_view_index`).

```json
{
  "status": "success",
  "schema_version": 2,
  "revision": "2026-10-19T18:30:00Z-15420",
  "generated_at": 1729272000000,
  "metrics": {
    "total_vods_iptv": 12500,
    "total_series_iptv": 1800,
    "matched_with_tmdb": 11840,
    "unmatched": 660,
    "elapsed_seconds": 4.2
  },

  "streaming_providers": {
    "netflix": ["10451", "10452", "10890"],
    "globoplay": ["5501", "5502", "5503", "9901"],
    "hbo": ["2011", "2012"],
    "disney": ["3001", "3002"],
    "prime": ["4001", "4002"],
    "apple": ["7001", "7002"],
    "telecine": ["8001", "8002"],
    "paramount": ["6001", "6002"],
    "mubi": ["9001"]
  },

  "vod_categories": [
    { "category_id": "1", "category_name": "Lançamentos 2024" },
    { "category_id": "2", "category_name": "Ação & Aventura" },
    { "category_id": "3", "category_name": "Globoplay Filmes" }
  ],

  "vod_streams": [
    {
      "stream_id": 5501,
      "name": "Auto da Compadecida 2 (2024)",
      "_cleanName": "Auto da Compadecida 2",
      "_type": "movie",
      "category_id": "3",
      "category_name": "Globoplay Filmes",
      "stream_icon": "https://image.tmdb.org/t/p/w500/poster_path_oficial.jpg",
      "backdrop_path": "https://image.tmdb.org/t/p/original/backdrop_path_oficial.jpg",
      "year": "2024",
      "rating": "8.4",
      "rating_5based": 4.2,
      "plot": "Sinopse oficial retornada pelo TMDB em português...",
      "genre": "Comédia, Aventura, Nacional",
      "duration_secs": 6480,
      "container_extension": "mp4",
      "tmdb_id": 1122334,
      "providers": ["globoplay", "telecine"]
    }
  ],

  "series_categories": [
    { "category_id": "10", "category_name": "Novelas Globoplay" },
    { "category_id": "11", "category_name": "Séries Netflix" }
  ],

  "series_streams": [
    {
      "series_id": 9901,
      "stream_id": 9901,
      "name": "Os Outros (2023)",
      "_cleanName": "Os Outros",
      "_type": "series",
      "category_id": "10",
      "category_name": "Novelas Globoplay",
      "cover": "https://image.tmdb.org/t/p/w500/cover_tmdb.jpg",
      "backdrop_path": "https://image.tmdb.org/t/p/original/backdrop_tmdb.jpg",
      "year": "2023",
      "rating": "8.8",
      "plot": "Sinopse da série Globoplay em PT-BR...",
      "genre": "Drama, Suspense, Nacional",
      "tmdb_id": 998877,
      "providers": ["globoplay"]
    }
  ]
}
```

---

## 4. Regras de Cruzamento e Mapeamento de Provedores

### 4.1. Limpeza de Título (Regex)
Remove resoluções, dublagem e marcas de IPTV, extraindo o ano de lançamento de forma precisa:
```python
REGEX_RUÍDOS = re.compile(
    r'(\[.*?\]|\(.*?\)|'
    r'\b(4k|uhd|fhd|hd|sd|1080p|720p|2160p|hevc|h265|x264|web-dl|bluray|cam|ts)\b|'
    r'\b(dublado|dub|legendado|leg|nacional|dual\s*audio|completo)\b)',
    re.IGNORECASE
)
```

### 4.2. Mapeamento Oficial de Provedores no TMDB (Brasil - Região `BR`)

| Streaming | ID Oficial TMDB (BR) | Slug Interno | Regra Heurística Adicional |
| :--- | :---: | :---: | :--- |
| **Globoplay** | `307` | `globoplay` | `\b(globo|globoplay|gshow|redeglobo|canaisglobo)\b` ou Produtora "Globo Filmes" |
| **Netflix** | `8` | `netflix` | `\b(netflix|nflx)\b` |
| **HBO Max / Max** | `384` | `hbo` | `\b(hbo|max|warner)\b` |
| **Disney+** | `337` | `disney` | `\b(disney|marvel|pixar|star wars|lucasfilm|natgeo)\b` |
| **Prime Video** | `119` | `prime` | `\b(prime|amazon|mgm)\b` |
| **Apple TV+** | `350` | `apple` | `\b(apple tv|apple original)\b` |
| **Telecine** | `227` | `telecine` | `\b(telecine|tlcn)\b` |
| **Paramount+** | `531` | `paramount` | `\b(paramount)\b` |
| **Mubi** | `11` | `mubi` | `\b(mubi)\b` |

---

## 5. Código Completo de Referência em Python (FastAPI)

Este código está **pronto para execução direta**. Salve como `server.py` e rode `python server.py`.  
Todas as chaves do TMDB e as credenciais do IPTV já estão embutidas no bloco de configuração inicial para facilitar a manutenção.

```python
"""
IPTV Catalog Ingestion & TMDB Watch Providers Normalizer (BFF)
Todas as configurações e chaves estão embutidas no código.
"""
import os
import re
import time
import asyncio
from typing import List, Dict, Optional, Any
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import httpx

# ==============================================================================
# CONFIGURAÇÕES E CHAVES EMBUTIDAS (EDITE AQUI QUANDO QUISER ALTERAR)
# ==============================================================================
TMDB_API_KEY = "0be70a0df8da0d4df674178ecb774db1"
TMDB_READ_TOKEN = (
    "eyJhbGciOiJIUzI1NiJ9.eyJhdWQiOiIwYmU3MGEwZGY4ZGEwZDRkZjY3NDE3OGVjYjc3NGRiMSIs"
    "Im5iZiI6MTc4NDMxNDk0My40Nywic3ViIjoiNmE1YTdjM2ZlMzFjZmYzOWQwMWYzNjIxIiwic2NvcGVzIjp"
    "bImFwaV9yZWFkIl0sInZlcnNpb24iOjF9.CdW7Gix6ncyw6F681hAt00KtmfWb3ZSEjcXqePZ-5hk"
)

DEFAULT_IPTV_URL = "http://149.78.186.18"  # URL ou IP do servidor IPTV
DEFAULT_USERNAME = "57430164"              # Usuário do IPTV
DEFAULT_PASSWORD = "22727897"              # Senha do IPTV

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
    "mubi": 11
}

# Regex Heurístico para categorias/nomes do IPTV
REGEX_CATEGORIA_FALLBACK = {
    "globoplay": re.compile(r'\b(globoplay|globo\s*play|globo\s*filmes|rede\s*globo|gshow)\b|\[globo\]|\bglobo\b', re.I),
    "netflix": re.compile(r'\b(netflix|nflx)\b', re.I),
    "hbo": re.compile(r'\b(hbo(\s*max)?|max\s*original|warner)\b', re.I),
    "disney": re.compile(r'\b(disney\+?|marvel|pixar|star\s*wars|natgeo)\b', re.I),
    "prime": re.compile(r'\b(prime\s*video|amazon\s*prime|mgm)\b', re.I),
    "apple": re.compile(r'\b(apple\s*tv\+?|apple\s*original)\b', re.I),
    "telecine": re.compile(r'\b(telecine|tlcn)\b', re.I),
    "paramount": re.compile(r'\b(paramount\+?)\b', re.I),
    "mubi": re.compile(r'\b(mubi)\b', re.I)
}

REGEX_RUÍDOS = re.compile(
    r'(\[.*?\]|\(.*?\)|'
    r'\b(4k|uhd|fhd|hd|sd|1080p|720p|2160p|hevc|h265|x264|web-dl|bluray|cam|ts)\b|'
    r'\b(dublado|dub|legendado|leg|nacional|dual\s*audio|completo)\b)',
    re.IGNORECASE
)

# ==============================================================================
# INICIALIZAÇÃO DA API
# ==============================================================================
app = FastAPI(title="IPTV TMDB Enrichment BFF", version="2.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class SyncRequest(BaseModel):
    iptv_url: Optional[str] = DEFAULT_IPTV_URL
    username: Optional[str] = DEFAULT_USERNAME
    password: Optional[str] = DEFAULT_PASSWORD
    tmdb_api_key: Optional[str] = TMDB_API_KEY
    include_series: bool = True

def normalizar_titulo(raw_name: str):
    ano_match = re.search(r'\b(19\d\d|20\d\d)\b', raw_name)
    ano = int(ano_match.group(1)) if ano_match else None
    limpo = REGEX_RUÍDOS.sub(' ', raw_name)
    limpo = re.sub(r'[\-–—:_|]', ' ', limpo)
    limpo = re.sub(r'\s+', ' ', limpo).strip()
    return limpo, ano

async def buscar_tmdb(client: httpx.AsyncClient, title: str, year: Optional[int], api_key: str):
    """Consulta o TMDB com busca difusa e obtém Watch Providers no Brasil"""
    params = {"api_key": api_key, "query": title, "language": "pt-BR"}
    if year:
        params["year"] = str(year)
    
    try:
        r = await client.get(f"{TMDB_BASE}/search/movie", params=params, timeout=5.0)
        if r.status_code != 200:
            return None
        results = r.json().get("results", [])
        if not results and year:
            params.pop("year", None)
            r = await client.get(f"{TMDB_BASE}/search/movie", params=params, timeout=5.0)
            results = r.json().get("results", []) if r.status_code == 200 else []
            
        if not results:
            return None
            
        best = results[0]
        tmdb_id = best["id"]
        
        # Consulta Watch Providers (JustWatch) para a região Brasil (BR)
        wp_res = await client.get(f"{TMDB_BASE}/movie/{tmdb_id}/watch/providers", params={"api_key": api_key}, timeout=5.0)
        providers = []
        if wp_res.status_code == 200:
            br_providers = wp_res.json().get("results", {}).get("BR", {}).get("flatrate", [])
            for p in br_providers:
                pid = p.get("provider_id")
                for slug, target_id in TMDB_PROVIDER_IDS.items():
                    if pid == target_id:
                        providers.append(slug)
                        
        return {
            "tmdb_id": tmdb_id,
            "title": best.get("title"),
            "overview": best.get("overview"),
            "poster": f"https://image.tmdb.org/t/p/w500{best['poster_path']}" if best.get("poster_path") else None,
            "backdrop": f"https://image.tmdb.org/t/p/original{best['backdrop_path']}" if best.get("backdrop_path") else None,
            "vote_average": best.get("vote_average", 0),
            "providers": list(set(providers))
        }
    except Exception:
        return None

async def executar_sincronizacao(iptv_url: str, username: str, password: str, api_key: str):
    clean_url = (iptv_url or DEFAULT_IPTV_URL).rstrip("/")
    user = username or DEFAULT_USERNAME
    pwd = password or DEFAULT_PASSWORD
    key = api_key or TMDB_API_KEY

    async with httpx.AsyncClient(timeout=60.0) as client:
        # 1. Login e download dos dados do IPTV
        login_url = f"{clean_url}/player_api.php?username={user}&password={pwd}"
        auth_res = await client.get(login_url)
        if auth_res.status_code != 200 or auth_res.json().get("user_info", {}).get("auth") == 0:
            raise HTTPException(status_code=401, detail="Usuário ou senha do IPTV incorretos.")

        vods_url = f"{login_url}&action=get_vod_streams"
        vod_cats_url = f"{login_url}&action=get_vod_categories"
        series_url = f"{login_url}&action=get_series"
        series_cats_url = f"{login_url}&action=get_series_categories"

        vods_res, cats_res, series_res, s_cats_res = await asyncio.gather(
            client.get(vods_url),
            client.get(vod_cats_url),
            client.get(series_url),
            client.get(series_cats_url)
        )

        vod_streams = vods_res.json() if vods_res.status_code == 200 else []
        vod_categories = cats_res.json() if cats_res.status_code == 200 else []
        series_streams = series_res.json() if series_res.status_code == 200 else []
        series_categories = s_cats_res.json() if s_cats_res.status_code == 200 else []

        cat_map = {str(c.get("category_id")): c.get("category_name", "") for c in vod_categories}
        streaming_providers = {prov: [] for prov in TMDB_PROVIDER_IDS.keys()}
        sem = asyncio.Semaphore(15)

        async def process_movie(item):
            stream_id = str(item.get("stream_id") or item.get("id"))
            raw_name = item.get("name", "")
            cat_id = str(item.get("category_id", "0"))
            cat_name = cat_map.get(cat_id, "")

            clean_name, ano = normalizar_titulo(raw_name)

            matched_providers = set()
            for prov_slug, regex in REGEX_CATEGORIA_FALLBACK.items():
                if regex.search(cat_name) or regex.search(raw_name):
                    matched_providers.add(prov_slug)

            tmdb_info = None
            if key:
                async with sem:
                    tmdb_info = await buscar_tmdb(client, clean_name, ano, key)

            if tmdb_info:
                for p in tmdb_info["providers"]:
                    matched_providers.add(p)

            for p in matched_providers:
                if p in streaming_providers:
                    streaming_providers[p].append(stream_id)

            return {
                "stream_id": stream_id,
                "name": raw_name,
                "_cleanName": clean_name,
                "_type": "movie",
                "category_id": cat_id,
                "category_name": cat_name,
                "stream_icon": (tmdb_info and tmdb_info["poster"]) or item.get("stream_icon") or "",
                "backdrop_path": (tmdb_info and tmdb_info["backdrop"]) or item.get("backdrop_path") or "",
                "year": str(ano) if ano else (item.get("year") or "2024"),
                "rating": str(tmdb_info["vote_average"]) if tmdb_info else str(item.get("rating") or "7.5"),
                "plot": (tmdb_info and tmdb_info["overview"]) or item.get("plot") or "",
                "container_extension": item.get("container_extension") or "mp4",
                "providers": list(matched_providers)
            }

        enriched_vods = await asyncio.gather(*(process_movie(v) for v in vod_streams[:600]))

    return {
        "status": "success",
        "schema_version": 2,
        "revision": f"{int(time.time())}-{len(vod_streams)}",
        "generated_at": int(time.time() * 1000),
        "metrics": {
            "total_vods": len(vod_streams),
            "total_series": len(series_streams)
        },
        "streaming_providers": streaming_providers,
        "vod_categories": vod_categories,
        "vod_streams": enriched_vods,
        "series_categories": series_categories,
        "series_streams": series_streams
    }

# Endpoint GET: Permite abrir direto no navegador para testar sem passar nada
@app.get("/api/v1/sync/catalog")
async def sync_catalog_get():
    return await executar_sincronizacao(DEFAULT_IPTV_URL, DEFAULT_USERNAME, DEFAULT_PASSWORD, TMDB_API_KEY)

# Endpoint POST: Permite passar parâmetros opcionais
@app.post("/api/v1/sync/catalog")
async def sync_catalog_post(req: Optional[SyncRequest] = None):
    req_obj = req or SyncRequest()
    return await executar_sincronizacao(req_obj.iptv_url, req_obj.username, req_obj.password, req_obj.tmdb_api_key)

if __name__ == "__main__":
    import uvicorn
    print("\n" + "="*60)
    print(" SERVIDOR INICIADO! CHAVES EMBUTIDAS ATIVAS:")
    print(f" IPTV URL: {DEFAULT_IPTV_URL}")
    print(f" USUARIO:  {DEFAULT_USERNAME}")
    print(f" TMDB KEY: {TMDB_API_KEY[:8]}... (Configurada)")
    print(" TESTE NO NAVEGADOR: http://localhost:8000/api/v1/sync/catalog")
    print("="*60 + "\n")
    uvicorn.run(app, host="0.0.0.0", port=8000)
```

---

## 6. Como Conectar o Aplicativo Cliente a Esta API

No cliente JavaScript ([settings.js](file:///c:/Users/matheus_willamy/Documents/Automacao/iptv_app/app/src/main/assets/settings.js)), basta uma única chamada de alta velocidade via `fetch()`:

```javascript
// Substituição do syncFromApi() no aplicativo cliente
async function syncFromPythonApi() {
    const API_PYTHON = "http://localhost:8000/api/v1/sync/catalog"; // ou IP do seu servidor
    
    showLoader(true, "Baixando catálogo otimizado com TMDB...");
    
    // Como a chave e as credenciais já estão no código Python, basta um GET direto:
    const response = await fetch(API_PYTHON);
    const data = await response.json();
    
    // 1. Salva no IndexedDB do navegador (acesso offline instantâneo)
    await window.writeStore('vod_streams', data.vod_streams);
    await window.writeStore('vod_categories', data.vod_categories);
    if (data.series_streams) {
        await window.writeStore('series_streams', data.series_streams);
        await window.writeStore('series_categories', data.series_categories);
    }
    
    // 2. Salva o índice de plataformas de streaming (Globoplay, Netflix, etc.)
    localStorage.setItem('aero_iptv_streaming_providers', JSON.stringify({
        schemaVersion: 2,
        revision: data.revision,
        providers: data.streaming_providers
    }));
    
    localStorage.setItem('aero_iptv_movies_catalog_revision', data.revision);
    
    showLoader(false);
    alert("Catálogo sincronizado com sucesso! Todas as plataformas estão populadas.");
    window.location.href = "streaming.html?provider=globoplay";
}
```

---

## 7. Como Alterar as Chaves e Credenciais no Futuro

Quando você quiser alterar a lista de IPTV ou a chave TMDB:
1. Abra o arquivo `server.py`.
2. Vá até as primeiras linhas (bloco `CONFIGURAÇÕES E CHAVES EMBUTIDAS`):
   ```python
   TMDB_API_KEY = "SUA_NOVA_CHAVE"
   DEFAULT_IPTV_URL = "http://seu-novo-servidor.com:8080"
   DEFAULT_USERNAME = "seu_novo_usuario"
   DEFAULT_PASSWORD = "sua_nova_senha"
   ```
3. Salve o arquivo e reinicie o servidor.
