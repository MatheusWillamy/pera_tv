"""
Script de Inicialização Direta do Servidor Pera TV BFF.
Permite executar via `python server.py`.
"""
import uvicorn
from config import DEFAULT_IPTV_URL, DEFAULT_USERNAME, PORT, TMDB_API_KEY
from main import app

if __name__ == "__main__":
    print("\n" + "=" * 65)
    print(" 🚀 PERA TV - SERVIDOR BFF INICIADO COM SUCESSO!")
    print("=" * 65)
    print(f" • PORTA ATIVA: {PORT}")
    print(f" • IPTV URL:    {DEFAULT_IPTV_URL}")
    print(f" • USUÁRIO:     {DEFAULT_USERNAME}")
    print(f" • TMDB KEY:    {TMDB_API_KEY[:8]}... (Configurada)")
    print(f" • SWAGGER DOC: http://localhost:{PORT}/docs")
    print(f" • HEALTHCHECK: http://localhost:{PORT}/health")
    print(f" • SYNC API:    http://localhost:{PORT}/api/v1/sync/catalog")
    print("=" * 65 + "\n")

    uvicorn.run(app, host="0.0.0.0", port=PORT)

