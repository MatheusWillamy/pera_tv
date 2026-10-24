# 📺 Pera TV - Backend de Ingestão e Normalização IPTV + TMDB (BFF)

> **Middleware de Alto Desempenho (Backend for Frontend - BFF)** para ingestão de catálogos IPTV (protocolo Xtream Codes), enriquecimento com The Movie Database (TMDB v3 API), classificação automática de provedores de streaming no Brasil (Globoplay, Netflix, HBO Max, Disney+, Prime Video, etc.) e persistência em cache local (TTL de 7 dias).

---

## 🚀 1. Funcionalidades Principais

- **Zero Configuração (Plug-and-Play)**: Chaves do TMDB e credenciais padrão do servidor IPTV embutidas diretamente no código (`config.py`).
- **Normalização Inteligente de Títulos**: Remoção via Regex de ruídos de transmissão (`[4K]`, `UHD`, `Dublado`, `1080p`, `FHD`, etc.) e extração precisa do ano de lançamento.
- **Enriquecimento com TMDB v3**:
  - Pôsteres oficiais em alta resolução (`w500`) e backdrops originais (`original`).
  - Sinopses oficiais em Português do Brasil (PT-BR).
  - Notas de avaliação e cálculo de escala `rating_5based` (0 a 5 estrelas).
  - Mapeamento de gêneros em PT-BR.
- **Detecção de Provedores de Streaming (Brasil)**:
  - Cruzamento com a API de **Watch Providers (JustWatch)** do TMDB para a região `BR`.
  - Heurística avançada de fallback para nomes e categorias de IPTV.
  - Indexação direta para as plataformas: `globoplay`, `netflix`, `hbo`, `disney`, `prime`, `apple`, `telecine`, `paramount`, `mubi`.
- **Banco de Cache Local SQLite (TTL de 7 Dias)**: Evita consultas redundantes ao TMDB, acelera respostas subsequentes e previne *rate limits*.
- **Contrato 100% Compatível com IndexedDB**: Resposta padronizada para armazenamento offline imediato no cliente (`vod_streams`, `vod_categories`, `series_streams`, `series_categories`).
- **Pronto para Docker e Easypanel**: Build leve em `python:3.12-slim`, healthcheck nativo em Python sem dependência de curl/wget, suporte à rede externa `easypanel`.

---

## 🏗️ 2. Arquitetura da Solução

```mermaid
flowchart TD
    subgraph Fontes Externas
        IPTV["Servidor IPTV (Xtream Codes API)<br/>• get_vod_streams<br/>• get_vod_categories<br/>• get_series<br/>• get_series_categories"]
        TMDB["The Movie Database (TMDB API v3)<br/>• search/movie & search/tv<br/>• movie/{id}/watch/providers (BR)<br/>• Imagens 4K (Posters & Backdrops)"]
    end

    subgraph Backend Python (FastAPI / SQLite / In-Memory)
        Cfg["0. Chaves e Credenciais Embutidas (config.py)"]
        Norm["1. Normalizador de Strings & Extrator de Ano (normalizer.py)"]
        Match["2. Algoritmo de Match Difuso TMDB (tmdb.py)"]
        Prov["3. Classificador de Watch Providers BR"]
        Cache["4. Banco de Cache Local SQLite - TTL 7 Dias (cache.py)"]
        Gen["5. Gerador do Pacote JSON Otimizado (catalog.py)"]
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

## 📡 3. Endpoints da API

### 3.1. `GET /health`
Healthcheck nativo utilizado pelo contêiner Docker e monitoramento de uptime.
```json
{
  "status": "ok",
  "service": "pera-tv-api",
  "version": "2.1.0"
}
```

### 3.2. `GET /api/v1/sync/catalog` (Zero Configuração)
Utiliza as credenciais padrão embutidas no código. Pode ser aberto diretamente no navegador ou chamado via `fetch()`.

### 3.3. `POST /api/v1/sync/catalog` (Sobrescrita Dinâmica Opcional)
Permite enviar credenciais customizadas se você desejar sincronizar outra conta ou servidor.
```json
{
  "iptv_url": "http://seu-servidor-iptv.com:8080",
  "username": "usuario_teste",
  "password": "senha_teste",
  "tmdb_api_key": "sua_chave_tmdb_opcional",
  "force_refresh": false,
  "include_series": true
}
```

### 3.4. `GET /api/v1/cache/stats`
Exibe métricas do banco de cache local SQLite (registros totais, ativos e expirados).

### 3.5. `POST /api/v1/cache/clear` e `POST /api/v1/cache/purge`
Administração para limpeza total ou expurgo de registros com mais de 7 dias.

---

## 💻 4. Como Executar Localmente

### Pré-requisitos
- Python 3.10+ (Recomendado: Python 3.12)
- Pip

### Passo a passo
1. Clone o repositório:
   ```bash
   git clone https://github.com/MatheusWillamy/pera_tv.git
   cd pera_tv
   ```

2. Instale as dependências:
   ```bash
   pip install -r requirements.txt
   ```

3. Inicie o servidor:
   ```bash
   python server.py
   # Ou via uvicorn direto:
   uvicorn main:app --host 0.0.0.0 --port 8000 --reload
   ```

4. Acesse:
   - **Documentação Interativa (Swagger)**: [http://localhost:8000/docs](http://localhost:8000/docs)
   - **Healthcheck**: [http://localhost:8000/health](http://localhost:8000/health)
   - **Sincronização de Catálogo**: [http://localhost:8000/api/v1/sync/catalog](http://localhost:8000/api/v1/sync/catalog)

---

## 🐳 5. Execução com Docker & Easypanel

### Executando no Easypanel (Produção)
O arquivo `docker-compose.yml` está 100% otimizado para o **Easypanel**:
- Sem `container_name` fixo (permite deploy contínuo sem conflitos de recriação de contêiner).
- Sem `ports` com bind direto no host (o Traefik do Easypanel gerencia o tráfego de domínio e SSL via `expose: 8000` na rede `easypanel`, eliminando avisos de conflito de portas).

### Executando Localmente com Docker Compose
Para expor a porta `8000` diretamente no `localhost` da sua máquina:
```bash
# Crie a rede se não existir:
docker network create easypanel

# Inicialize publicando na porta 8000 do localhost:
docker compose -f docker-compose.yml -f docker-compose.local.yml up -d --build
```


### Build e Execução Manual com Docker
```bash
docker build -t pera_tv_api .
docker run -d -p 8000:8000 --name pera_tv_api pera_tv_api
```

### Deploy no Easypanel
1. Crie um novo **App Service** no Easypanel apontando para o repositório GitHub `https://github.com/MatheusWillamy/pera_tv.git`.
2. Selecione **Build Type**: `Dockerfile`.
3. Defina a porta do contêiner como `8000`.
4. (Opcional) Configure as variáveis de ambiente:
   - `TMDB_API_KEY`: sua chave de API v3 do TMDB
   - `IPTV_URL`: URL base do servidor IPTV
   - `IPTV_USERNAME`: Usuário
   - `IPTV_PASSWORD`: Senha

---

## 🧪 6. Testes Automatizados

O projeto possui cobertura completa de testes unitários e de integração utilizando `pytest` e `pytest-asyncio`.

Para rodar a suíte de testes:
```bash
pytest -v
```

---

## 📱 7. Integração com o Aplicativo Cliente (Frontend)

Exemplo de chamada em JavaScript para download instantâneo e persistência no IndexedDB:

```javascript
async function syncFromPythonApi() {
    const API_URL = "http://localhost:8000/api/v1/sync/catalog"; // ou URL da sua VPS
    
    const response = await fetch(API_URL);
    const data = await response.json();
    
    // 1. Salva no IndexedDB
    await window.writeStore('vod_streams', data.vod_streams);
    await window.writeStore('vod_categories', data.vod_categories);
    if (data.series_streams) {
        await window.writeStore('series_streams', data.series_streams);
        await window.writeStore('series_categories', data.series_categories);
    }
    
    // 2. Salva o mapa de plataformas de streaming (Globoplay, Netflix, etc.)
    localStorage.setItem('aero_iptv_streaming_providers', JSON.stringify({
        schemaVersion: 2,
        revision: data.revision,
        providers: data.streaming_providers
    }));
    
    localStorage.setItem('aero_iptv_movies_catalog_revision', data.revision);
}
```

---

## 📄 Licença
Distribuído sob licença MIT.
