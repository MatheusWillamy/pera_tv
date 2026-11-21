"""
Testes de Integração para os Endpoints da API FastAPI (Rotas, Contratos e Erros).
"""
from unittest.mock import AsyncMock, patch
import pytest
from iptv import IPTVAuthError, IPTVConnectionError


def test_root_endpoint(client):
    response = client.get("/")
    assert response.status_code == 200
    data = response.json()
    assert data["service"] == "pera-tv-api"
    assert data["status"] == "online"
    assert data["health"] == "/health"


def test_health_endpoint(client):
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data == {
        "status": "ok",
        "service": "pera-tv-api",
        "version": "2.3.0",
    }


def test_cache_endpoints(client):
    stats_res = client.get("/api/v1/cache/stats")
    assert stats_res.status_code == 200
    assert "total_records" in stats_res.json()

    clear_res = client.post("/api/v1/cache/clear")
    assert clear_res.status_code == 200
    assert clear_res.json()["status"] == "success"

    purge_res = client.post("/api/v1/cache/purge")
    assert purge_res.status_code == 200
    assert purge_res.json()["status"] == "success"


@pytest.fixture
def mock_iptv_dataset():
    vod_categories = [
        {"category_id": "1", "category_name": "Lançamentos 2024"},
        {"category_id": "3", "category_name": "Globoplay Filmes"},
        {"category_id": "5", "category_name": "Netflix Filmes"},
    ]
    vod_streams = [
        {
            "stream_id": 5501,
            "name": "Auto da Compadecida 2 (2024) [4K DUBLADO]",
            "category_id": "3",
            "stream_icon": "http://img.test/poster1.jpg",
            "rating": "8.4",
            "duration_secs": 6480,
            "container_extension": "mp4",
        },
        {
            "stream_id": 10451,
            "name": "Resgate 2 (2023) [FHD]",
            "category_id": "5",
            "stream_icon": "http://img.test/poster2.jpg",
            "rating": "7.0",
            "duration_secs": 7200,
            "container_extension": "mkv",
        },
    ]
    series_categories = [
        {"category_id": "10", "category_name": "Novelas Globoplay"},
    ]
    series_streams = [
        {
            "series_id": 9901,
            "name": "Os Outros (2023)",
            "category_id": "10",
            "cover": "http://img.test/cover.jpg",
            "rating": "8.8",
        }
    ]
    return vod_streams, vod_categories, series_streams, series_categories


def test_sync_catalog_get_success(client, mock_iptv_dataset):
    with patch("catalog.fetch_iptv_catalog", new=AsyncMock(return_value=mock_iptv_dataset)):
        response = client.get("/api/v1/sync/catalog")
        assert response.status_code == 200
        data = response.json()

        # Validação do Contrato de Saída (Seção 3 da Especificação)
        assert data["status"] == "success"
        assert data["schema_version"] == 2
        assert "revision" in data
        assert isinstance(data["generated_at"], int)

        # Métricas
        metrics = data["metrics"]
        assert metrics["total_vods_iptv"] == 2
        assert metrics["total_series_iptv"] == 1
        assert "elapsed_seconds" in metrics

        # Provedores indexados
        providers = data["streaming_providers"]
        assert "globoplay" in providers
        assert "5501" in providers["globoplay"] or "9901" in providers["globoplay"]
        assert "netflix" in providers
        assert "10451" in providers["netflix"]

        # VOD streams enriquecidos
        vods = data["vod_streams"]
        assert len(vods) == 2
        primeiro_vod = vods[0]
        assert primeiro_vod["_cleanName"] == "Auto da Compadecida 2"
        assert primeiro_vod["_type"] == "movie"
        assert primeiro_vod["year"] == "2024"
        assert isinstance(primeiro_vod["rating_5based"], float)
        assert primeiro_vod["rating_5based"] > 0
        assert "globoplay" in primeiro_vod["providers"]
        assert primeiro_vod["tmdb_id"] is not None

        # Séries enriquecidas
        series = data["series_streams"]
        assert len(series) == 1
        primeira_serie = series[0]
        assert primeira_serie["_cleanName"] == "Os Outros"
        assert primeira_serie["_type"] == "series"
        assert primeira_serie["year"] == "2023"
        assert isinstance(primeira_serie["rating_5based"], float)
        assert primeira_serie["rating_5based"] > 0
        assert "globoplay" in primeira_serie["providers"]
        assert primeira_serie["tmdb_id"] is not None



def test_sync_catalog_post_custom_credentials(client, mock_iptv_dataset):
    with patch("catalog.fetch_iptv_catalog", new=AsyncMock(return_value=mock_iptv_dataset)):
        payload = {
            "iptv_url": "http://servidor-customizado.com:8080",
            "username": "usuario_novo",
            "password": "senha_nova",
            "force_refresh": True,
            "include_series": True,
        }
        response = client.post("/api/v1/sync/catalog", json=payload)
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "success"
        assert len(data["vod_streams"]) == 2


def test_sync_catalog_auth_failure(client):
    with patch(
        "catalog.fetch_iptv_catalog",
        side_effect=IPTVAuthError("Usuário ou senha do IPTV incorretos."),
    ):
        response = client.get("/api/v1/sync/catalog")
        assert response.status_code == 401
        data = response.json()
        assert data["error_code"] == "IPTV_AUTH_FAILED"
        assert "Usuário ou senha" in data["detail"]


def test_sync_catalog_connection_failure(client):
    with patch(
        "catalog.fetch_iptv_catalog",
        side_effect=IPTVConnectionError("Tempo esgotado ao conectar no servidor IPTV."),
    ):
        response = client.get("/api/v1/sync/catalog")
        assert response.status_code == 504
        data = response.json()
        assert data["error_code"] == "IPTV_CONNECTION_FAILED"
        assert "Tempo esgotado" in data["detail"]


def test_sync_catalog_fallback_to_contingency_ip(client, mock_iptv_dataset):
    """
    Testa se o sistema aciona com sucesso o IP de contingência quando
    o link oficial sofre falha de conexão (DNS/Timeout).
    """
    with patch(
        "catalog.fetch_iptv_catalog",
        side_effect=[
            IPTVConnectionError("Falha de DNS ao resolver link principal"),
            mock_iptv_dataset,
        ],
    ):
        response = client.get("/api/v1/sync/catalog")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "success"
        assert len(data["vod_streams"]) == 2


def test_streaming_hubs_summary_endpoint(client):
    res = client.get("/api/v1/streaming/hubs")
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "success"
    ids = [p["id"] for p in data["providers"]]
    assert "netflix" in ids and "hbo" in ids and "disney" in ids and "mubi" in ids


def test_streaming_hub_hbo_dedup_and_discover_match(client):
    from catalog import clear_memory_snapshot
    clear_memory_snapshot()

    vod_cats = [
        {"category_id": "1", "category_name": "FILMES | DRAMA"},
        {"category_id": "2", "category_name": "FILMES | FICCAO"},
    ]
    vod_streams = [
        # 4 copias de Kurt Warner (nao devem entrar na HBO Max!)
        {"stream_id": 101, "name": "American Underdog: A Historia de Kurt Warner (2021) [FHD]", "category_id": "1", "rating": "7.1"},
        {"stream_id": 102, "name": "American Underdog: A Historia de Kurt Warner (2021) [4K]", "category_id": "1", "rating": "7.1"},
        # 2 copias de Interestelar (devem deduplicar em 1 so e casar via TMDB Discover BR!)
        {"stream_id": 201, "name": "Interestelar (2014) [FHD]", "category_id": "2", "rating": "8.6"},
        {"stream_id": 202, "name": "Interestelar (2014) [4K DUBLADO]", "category_id": "2", "rating": "8.6"},
    ]
    ser_cats = [{"category_id": "10", "category_name": "SERIES | HBO MAX"}]
    ser_streams = [
        {"series_id": 301, "name": "The Last of Us (2023)", "category_id": "10", "cover": "http://img/tlou.jpg", "rating": "8.8"},
    ]
    mock_discover = {
        "movie": [
            {
                "tmdb_id": 157336,
                "media_type": "movie",
                "title": "Interestelar",
                "original_title": "Interstellar",
                "overview": "Uma equipe de exploradores viaja atraves de um buraco de minhoca.",
                "poster": "https://image.tmdb.org/t/p/w342/inter.jpg",
                "backdrop": "https://image.tmdb.org/t/p/w780/inter_bg.jpg",
                "vote_average": 8.4,
                "vote_count": 34000,
                "popularity": 180.0,
                "year": 2014,
                "genre": "Aventura, Drama, Ficção científica",
            }
        ],
        "tv": [],
    }

    with (
        patch("catalog.fetch_iptv_catalog", new=AsyncMock(return_value=(vod_streams, vod_cats, ser_streams, ser_cats))),
        patch("catalog.buscar_discover_provedor", new=AsyncMock(return_value=mock_discover)),
        patch("catalog.buscar_trailer_youtube", new=AsyncMock(return_value="zSWdZVtXT7E")),
    ):
        res = client.get("/api/v1/streaming/hub/hbo")
        assert res.status_code == 200
        data = res.json()
        assert data["provider"]["id"] == "hbo"
        assert data["stats"]["movies"] == 1  # Interestelar deduplicado (sem Kurt Warner!)
        assert data["stats"]["series"] == 1  # The Last of Us da categoria SERIES | HBO MAX
        assert data["hero"]["id"] == "202"   # Preferiu versao 4K DUBLADO!
        assert data["hero"]["versions_count"] == 2
        assert data["hero"]["trailer_key"] == "zSWdZVtXT7E"
        assert data["hero"]["backdrop"] == "https://image.tmdb.org/t/p/w780/inter_bg.jpg"

        # Segunda chamada deve vir do cache SQLite
        res2 = client.get("/api/v1/streaming/hub/hbo?media_type=series")
        assert res2.status_code == 200
        d2 = res2.json()
        assert d2["cached"] is True
        assert len(d2["shelves"]["movies"]) == 0
        assert len(d2["shelves"]["series"]) == 1


def test_streaming_batch_match_with_client_items_and_legendado(client):
    mock_discover_netflix = {
        "movie": [
            {
                "tmdb_id": 697843,
                "media_type": "movie",
                "title": "Resgate 2",
                "original_title": "Extraction 2",
                "overview": "Tyler Rake retorna.",
                "poster": "https://image.tmdb.org/t/p/w342/ext2.jpg",
                "backdrop": "https://image.tmdb.org/t/p/w780/ext2_bg.jpg",
                "vote_average": 7.5,
                "vote_count": 5000,
                "popularity": 120.0,
                "year": 2023,
                "genre": "Ação",
            }
        ],
        "tv": [],
    }

    with patch("catalog.buscar_discover_provedor", new=AsyncMock(return_value=mock_discover_netflix)):
        payload = {
            "providers": ["netflix", "disney"],
            "use_tmdb_discover": True,
            "items": [
                {"id": "501", "name": "Resgate 2 (2023) [FHD] [LEG]", "media_type": "movie", "category_name": "FILMES | ACAO"},
                {"id": "502", "name": "Battle Star Wars (2020) [HD]", "media_type": "movie", "category_name": "FILMES | FICCAO"},
            ],
        }
        res = client.post("/api/v1/streaming/match", json=payload)
        assert res.status_code == 200
        data = res.json()
        assert data["source_mode"] == "client_items"
        assert "501" in data["streaming_providers"]["netflix"]
        assert "502" not in data["streaming_providers"]["disney"]
        matched_501 = next(x for x in data["matched_items"] if x["id"] == "501")
        assert matched_501["is_legendado"] is True
        assert matched_501["audio"] == "LEGENDADO"


def test_manual_override_crud_and_reflection_in_hub(client):
    from catalog import clear_memory_snapshot
    clear_memory_snapshot()

    override_req = {
        "item_id": "9988",
        "media_type": "movie",
        "title": "Oppenheimer",
        "year": 2023,
        "providers": ["prime"],
        "tmdb_id": 872585,
        "auto_lookup_tmdb": False,
        "poster": "https://image.tmdb.org/t/p/w342/opp.jpg",
        "backdrop": "https://image.tmdb.org/t/p/w780/opp_bg.jpg",
        "overview": "História de J. Robert Oppenheimer.",
    }
    save_res = client.post("/api/v1/streaming/match/manual", json=override_req)
    assert save_res.status_code == 200
    assert save_res.json()["override"]["item_id"] == "9988"

    list_res = client.get("/api/v1/streaming/overrides?provider=prime")
    assert list_res.status_code == 200
    assert any(o["item_id"] == "9988" for o in list_res.json()["overrides"])

    with (
        patch("catalog.fetch_iptv_catalog", new=AsyncMock(return_value=([], [], [], []))),
        patch("catalog.buscar_discover_provedor", new=AsyncMock(return_value={"movie": [], "tv": []})),
        patch("catalog.buscar_trailer_youtube", new=AsyncMock(return_value="uYPbbksJxIg")),
    ):
        hub_res = client.get("/api/v1/streaming/hub/prime?force_refresh=true")
        assert hub_res.status_code == 200
        hub = hub_res.json()
        assert hub["stats"]["movies"] == 1
        assert hub["shelves"]["movies"][0]["id"] == "9988"
        assert hub["shelves"]["movies"][0]["source"] == "manual_override"

    del_res = client.delete("/api/v1/streaming/overrides/movie/9988")
    assert del_res.status_code == 200
    assert del_res.json()["deleted"] is True


def test_warm_hubs_endpoint(client):
    with (
        patch("catalog.fetch_iptv_catalog", new=AsyncMock(return_value=([], [], [], []))),
        patch("catalog.buscar_discover_provedor", new=AsyncMock(return_value={"movie": [], "tv": []})),
    ):
        res = client.post("/api/v1/streaming/hubs/warm?force_refresh=true")
        assert res.status_code == 200
        data = res.json()
        assert data["status"] == "success"
        assert data["providers_warmed"] == 9
        assert "netflix" in data["stats"] and "prime" in data["stats"]


def test_streaming_trending_endpoint(client):
    from catalog import clear_memory_snapshot
    clear_memory_snapshot()

    vod_streams = [
        {"stream_id": 701, "name": "Duna Parte Dois (2024) [4K]", "category_id": "1", "rating": "8.4"}
    ]
    ser_streams = [
        {"series_id": 801, "name": "The Last of Us (2023)", "category_id": "2", "rating": "8.8"}
    ]
    mock_trending = {
        "movie": [
            {
                "tmdb_id": 693134,
                "media_type": "movie",
                "title": "Duna: Parte Dois",
                "original_title": "Dune: Part Two",
                "overview": "Paul Atreides se une aos Fremen.",
                "poster": "https://image.tmdb.org/t/p/w342/d2.jpg",
                "backdrop": "https://image.tmdb.org/t/p/w780/d2_bg.jpg",
                "vote_average": 8.3,
                "vote_count": 5000,
                "popularity": 210.0,
                "year": 2024,
                "genre": "Ficção científica",
            }
        ],
        "tv": [
            {
                "tmdb_id": 100088,
                "media_type": "series",
                "title": "The Last of Us",
                "original_title": "The Last of Us",
                "overview": "Jornada pelos EUA.",
                "poster": "https://image.tmdb.org/t/p/w342/tlou.jpg",
                "backdrop": "https://image.tmdb.org/t/p/w780/tlou_bg.jpg",
                "vote_average": 8.6,
                "vote_count": 4000,
                "popularity": 190.0,
                "year": 2023,
                "genre": "Drama",
            }
        ],
    }

    with (
        patch("catalog.fetch_iptv_catalog", new=AsyncMock(return_value=(vod_streams, [], ser_streams, []))),
        patch("catalog.buscar_trending_semana", new=AsyncMock(return_value=mock_trending)),
    ):
        res = client.get("/api/v1/streaming/trending")
        assert res.status_code == 200
        data = res.json()
        assert data["status"] == "success"
        assert data["counts"]["movies"] == 1
        assert data["counts"]["series"] == 1
        assert data["movies"][0]["id"] == "701"
        assert data["series"][0]["id"] == "801"
