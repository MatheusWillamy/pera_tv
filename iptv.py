"""
Módulo de Integração com Servidores IPTV (Protocolo Xtream Codes API).
Suporta autenticação, download de categorias e listas de filmes (VOD) e séries.
"""
import logging
from typing import Any, Dict, List, Tuple
import httpx
from config import IPTV_REQUEST_TIMEOUT

logger = logging.getLogger(__name__)


class IPTVError(Exception):
    """Exceção base para erros de IPTV"""
    pass


class IPTVAuthError(IPTVError):
    """Credenciais incorretas ou acesso negado no servidor IPTV"""
    pass


class IPTVConnectionError(IPTVError):
    """Falha de conexão de rede ou timeout com o servidor IPTV"""
    pass


async def fetch_iptv_catalog(
    client: httpx.AsyncClient,
    iptv_url: str,
    username: str,
    password: str,
    include_series: bool = True,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], List[Dict[str, Any]], List[Dict[str, Any]]]:
    """
    Autentica e baixa o catálogo completo de VODs e Séries do servidor IPTV.
    Retorna: (vod_streams, vod_categories, series_streams, series_categories)
    """
    clean_url = iptv_url.rstrip("/")
    login_url = f"{clean_url}/player_api.php?username={username}&password={password}"

    # 1. Autenticação e validação
    try:
        auth_res = await client.get(login_url, timeout=IPTV_REQUEST_TIMEOUT)
    except httpx.TimeoutException as exc:
        raise IPTVConnectionError(
            f"Tempo esgotado ao conectar no servidor IPTV ({clean_url}). Servidor offline ou porta inacessível."
        ) from exc
    except httpx.RequestError as exc:
        raise IPTVConnectionError(
            f"Erro ao conectar ao servidor IPTV ({clean_url}): {str(exc)}"
        ) from exc

    if auth_res.status_code != 200:
        raise IPTVConnectionError(
            f"Servidor IPTV retornou status HTTP {auth_res.status_code}"
        )

    try:
        auth_data = auth_res.json()
    except Exception as exc:
        raise IPTVConnectionError("Resposta inválida do servidor IPTV (não é JSON).") from exc

    user_info = auth_data.get("user_info", {})
    if str(user_info.get("auth")) not in ("1", 1):
        msg = user_info.get("message") or "Usuário ou senha do IPTV incorretos."
        raise IPTVAuthError(msg)

    # 2. Requisições concorrentes de VOD e Séries
    vods_url = f"{login_url}&action=get_vod_streams"
    vod_cats_url = f"{login_url}&action=get_vod_categories"

    requests_to_gather = [
        client.get(vods_url, timeout=IPTV_REQUEST_TIMEOUT),
        client.get(vod_cats_url, timeout=IPTV_REQUEST_TIMEOUT),
    ]

    if include_series:
        series_url = f"{login_url}&action=get_series"
        series_cats_url = f"{login_url}&action=get_series_categories"
        requests_to_gather.extend([
            client.get(series_url, timeout=IPTV_REQUEST_TIMEOUT),
            client.get(series_cats_url, timeout=IPTV_REQUEST_TIMEOUT),
        ])

    import asyncio

    try:
        responses = await asyncio.gather(*requests_to_gather)
    except httpx.TimeoutException as exc:
        raise IPTVConnectionError("Tempo limite esgotado ao baixar catálogos do IPTV.") from exc
    except httpx.RequestError as exc:
        raise IPTVConnectionError(f"Erro ao baixar catálogos do IPTV: {exc}") from exc

    vods_res = responses[0]
    cats_res = responses[1]
    series_res = responses[2] if include_series and len(responses) > 2 else None
    s_cats_res = responses[3] if include_series and len(responses) > 3 else None

    vod_streams = vods_res.json() if vods_res.status_code == 200 else []
    vod_categories = cats_res.json() if cats_res.status_code == 200 else []
    series_streams = series_res.json() if series_res and series_res.status_code == 200 else []
    series_categories = s_cats_res.json() if s_cats_res and s_cats_res.status_code == 200 else []

    return vod_streams, vod_categories, series_streams, series_categories

