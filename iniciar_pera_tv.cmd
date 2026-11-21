@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"

echo ============================================================
echo   PERA TV - API BFF IPTV + TMDB Streaming Hubs (Porta 8001)
echo ============================================================
echo.

if "%IPTV_URL%"=="" set IPTV_URL=http://dg25.me
if "%IPTV_FALLBACK_IP%"=="" set IPTV_FALLBACK_IP=http://50.7.178.191
if "%PORT%"=="" set PORT=8001

echo [1/3] Verificando dependencias Python...
python -c "import fastapi, uvicorn, httpx, pydantic" >nul 2>&1
if errorlevel 1 (
    echo Instalando dependencias de requirements.txt...
    python -m pip install -r requirements.txt
)

if /I "%1"=="test" (
    echo.
    echo [2/3] Executando suite de testes pytest...
    python -m pytest tests -q
    exit /b %errorlevel%
)

echo [2/3] Servidor IPTV padrao: %IPTV_URL% (fallback %IPTV_FALLBACK_IP%)
echo [3/3] Iniciando API Pera TV em http://127.0.0.1:%PORT%
echo       Swagger Docs  : http://127.0.0.1:%PORT%/docs
echo       Streaming Hubs: http://127.0.0.1:%PORT%/api/v1/streaming/hubs
echo       Exemplo HBO   : http://127.0.0.1:%PORT%/api/v1/streaming/hub/hbo
echo.
python -m uvicorn main:app --host 0.0.0.0 --port %PORT%
