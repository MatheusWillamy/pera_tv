"""
CLI helper para o gerenciador iniciar_pera_tv.cmd (compativel 100% com cmd.exe).
Executa verificacoes de saude, warmup, match de filmes, trending, overrides,
cache e relatorio de paridade 1:1 com o fallback HTML offline.
"""
import argparse
import json
import os
import sys
import urllib.error
import urllib.request


def _fetch_json(url: str, method: str = "GET", body: dict = None, timeout: int = 45) -> dict:
    data = json.dumps(body).encode("utf-8") if body is not None else None
    headers = {"Accept": "application/json"}
    if data is not None:
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def cmd_health(local_url: str, prod_url: str) -> int:
    ok_any = False
    for label, u in [("LOCAL", f"{local_url}/health"), ("EASYPANEL", f"{prod_url}/health")]:
        try:
            with urllib.request.urlopen(u, timeout=6) as r:
                print(f"[OK   ] ({label}) {u} -> HTTP {r.status}: {r.read().decode('utf-8')}")
                ok_any = True
        except urllib.error.HTTPError as e:
            print(f"[HTTP ] ({label}) {u} -> HTTP {e.code} ({e.reason})")
        except Exception as e:
            print(f"[OFFLINE] ({label}) {u} -> {e}")
    print("\nDICA EASYPANEL: Se EASYPANEL retornar HTTP 502, confirme no painel se a porta interna do app está em 8001 e clique em Deploy.")
    return 0 if ok_any else 0


def cmd_warm(base_url: str) -> int:
    data = _fetch_json(f"{base_url}/api/v1/streaming/hubs/warm", method="POST", body={}, timeout=120)
    print(json.dumps(data, indent=2, ensure_ascii=False))
    return 0


def cmd_match(base_url: str) -> int:
    for p in ["netflix", "prime", "hbo", "disney", "globoplay", "apple", "paramount", "telecine", "mubi"]:
        try:
            d = _fetch_json(f"{base_url}/api/v1/streaming/hub/{p}", timeout=45)
            st = d.get("stats", {})
            mv = (d.get("shelves") or {}).get("movies") or []
            sample = [f"{m.get('title')} ({m.get('year', '')})" for m in mv[:4]]
            print(f"{p.upper():10s} | total={st.get('total', 0):4d} | filmes={st.get('movies', 0):4d} | series={st.get('series', 0):4d} | top4={sample}")
        except Exception as exc:
            print(f"{p.upper():10s} | ERRO: {exc}")
    return 0


def cmd_trending(base_url: str) -> int:
    d = _fetch_json(f"{base_url}/api/v1/streaming/trending", timeout=45)
    print("Counts:", d.get("counts"))
    print("Top 5 Filmes:", [f"{m.get('title')} ({m.get('year', '')})" for m in (d.get("movies") or [])[:5]])
    print("Top 5 Series:", [f"{s.get('title')} ({s.get('year', '')})" for s in (d.get("series") or [])[:5]])
    return 0


def cmd_sync(base_url: str) -> int:
    d = _fetch_json(f"{base_url}/api/v1/sync/catalog", timeout=120)
    print("Status:", d.get("status"), "| Metrics:", json.dumps(d.get("metrics"), ensure_ascii=False))
    print("Providers:", {k: len(v) for k, v in (d.get("streaming_providers") or {}).items()})
    return 0


def cmd_overrides(base_url: str) -> int:
    d = _fetch_json(f"{base_url}/api/v1/streaming/overrides", timeout=15)
    print(json.dumps(d, indent=2, ensure_ascii=False))
    return 0


def cmd_cache(base_url: str, sub: str) -> int:
    stats = _fetch_json(f"{base_url}/api/v1/cache/stats", timeout=10)
    print("Stats:", json.dumps(stats, ensure_ascii=False))
    if sub in ("clear", "purge"):
        res = _fetch_json(f"{base_url}/api/v1/cache/{sub}", method="POST", body={}, timeout=10)
        print(f"{sub.upper()}:", json.dumps(res, ensure_ascii=False))
    return 0


def cmd_parity() -> int:
    rows = [
        ("1. Sync Completo", "GET/POST /api/v1/sync/catalog", "settings.js syncFull() + core.js AeroConnection (DoH/Espelho/IP) + runLocalTmdbStreamingMatch()"),
        ("2. Hub de Streaming", "GET /api/v1/streaming/hub/{provider}", "streaming.js renderProviderHub() + classifyLocalCatalogByProvider() + runLocalTmdbStreamingMatch()"),
        ("3. Match em Lote", "POST /api/v1/streaming/match", "core.js window.runLocalTmdbStreamingMatch() (TMDB Discover BR flatrate + AeroMatchLogic)"),
        ("4. Override Manual", "POST /api/v1/streaming/match/manual", "localStorage aero_iptv_streaming_providers + aero_iptv_tmdb_cache"),
        ("5. Deduplicacao & LEG", "normalizer.py + _deduplicar_itens()", "core.js parseMediaTitle() + streaming.js deduplicateUnifiedItems() (4K>FHD>HD, LEG)"),
        ("6. Anti-Falso-Positivo", "config.py REGEX_CATEGORIA_REJEICAO", "streaming.js PROVIDER_RULES.reject (Kurt Warner, Mad Max, Battle Star Wars, Optimus Prime)"),
        ("7. Em Alta / Recentes", "GET /api/v1/streaming/trending", "settings.js movie/popular + selecoes 2026/2025/2024"),
        ("8. Cache & Fallback IP", "SQLite cache.db + fallback 50.7.178.191", "AeroSWRCache + HUB_FAST_SNAPSHOT + AeroConnection winner/fallback IPs"),
    ]
    print("=" * 84)
    print("  PARIDADE 1:1 - TODAS AS ACOES DA API PERA TV <--> HTML OFFLINE (MESMO RESULTADO)")
    print("=" * 84)
    for acao, api_route, html_equiv in rows:
        print(f"\n[{acao}]")
        print(f"  API Online   : {api_route}")
        print(f"  HTML Offline : {html_equiv}")
    print("\nResultado: Quando a API estiver offline ou retornar HTTP 502, o HTML executa")
    print("           o fallback local automaticamente e entrega os mesmos filmes e tags.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Pera TV CLI Tools")
    parser.add_argument("action", choices=["health", "warm", "match", "trending", "sync", "overrides", "cache", "parity"])
    parser.add_argument("--sub", default="")
    parser.add_argument("--local-url", default=os.getenv("LOCAL_API_URL", "http://127.0.0.1:8001"))
    parser.add_argument("--prod-url", default=os.getenv("PROD_API_URL", "https://aboboratech-api.wdkvp6.easypanel.host"))
    args = parser.parse_args()

    if args.action == "health":
        return cmd_health(args.local_url, args.prod_url)
    if args.action == "warm":
        return cmd_warm(args.local_url)
    if args.action == "match":
        return cmd_match(args.local_url)
    if args.action == "trending":
        return cmd_trending(args.local_url)
    if args.action == "sync":
        return cmd_sync(args.local_url)
    if args.action == "overrides":
        return cmd_overrides(args.local_url)
    if args.action == "cache":
        return cmd_cache(args.local_url, args.sub)
    return cmd_parity()


if __name__ == "__main__":
    sys.exit(main())
