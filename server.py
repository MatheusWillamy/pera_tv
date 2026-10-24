"""
Script de Inicialização Direta do Servidor Pera TV BFF.
Permite executar via `python server.py`.
"""
import uvicorn
from config import DEFAULT_IPTV_URL, DEFAULT_USERNAME, TMDB_API_KEY
from main import app

if __name__ == "__main__":
    print("\n" + "=" * 65)
    print(" 🚀 PERA TV - SERVIDOR BFF INICIADO COM SUCESSO!")
    print("=" * 65)
    print(f" • IPTV URL:    {DEFAULT_IPTV_URL}")
    print(f" • USUÁRIO:     {DEFAULT_USERNAME}")
    print(f" • TMDB KEY:    {TMDB_API_KEY[:8]}... (Configurada)")
    print(f" • SWAGGER DOC: http://localhost:8000/docs")
    print(f" • HEALTHCHECK: http://localhost:8000/health")
    print(f" • SYNC API:    http://localhost:8000/api/v1/sync/catalog")
    print("=" * 65 + "\n")

    uvicorn.run(app, host="0.0.0.0", port=8000)
