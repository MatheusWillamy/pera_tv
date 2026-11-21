@echo off
chcp 65001 >nul
setlocal EnableDelayedExpansion
cd /d "%~dp0"

if "%IPTV_URL%"=="" set IPTV_URL=http://dg25.me
if "%IPTV_FALLBACK_IP%"=="" set IPTV_FALLBACK_IP=http://50.7.178.191
if "%PORT%"=="" set PORT=8001
if "%LOCAL_API_URL%"=="" set LOCAL_API_URL=http://127.0.0.1:%PORT%
if "%PROD_API_URL%"=="" set PROD_API_URL=https://aboboratech-api.wdkvp6.easypanel.host

if not "%~1"=="" goto :CLI_DISPATCH

:MENU
cls
echo ============================================================================
echo   PERA TV - Gerenciador BFF ^& Paridade 1:1 ^(API Python ^<--^> HTML Offline^)
echo ============================================================================
echo   API Local    : %LOCAL_API_URL%
echo   API Easypanel: %PROD_API_URL%
echo   IPTV Oficial : %IPTV_URL%  ^(Contingencia: %IPTV_FALLBACK_IP%^)
echo ============================================================================
echo.
echo   [1]  Iniciar API Pera TV ^(Uvicorn Porta %PORT% + Warmup IPTV em Background^)
echo   [2]  Diagnostico de Saude ^(Testa Local 127.0.0.1:%PORT% e Easypanel^)
echo   [3]  Aquecer Todos os 9 Hubs de Streaming ^(POST /api/v1/streaming/hubs/warm^)
echo   [4]  Testar Match Real de Filmes ^(Netflix, Prime Video, HBO Max, Disney+^)
echo   [5]  Testar Trending da Semana TMDB x IPTV ^(GET /api/v1/streaming/trending^)
echo   [6]  Consultar Overrides Manuais Salvos ^(GET /api/v1/streaming/overrides^)
echo   [7]  Ver Estatisticas / Expurgar Cache SQLite ^(stats / purge / clear^)
echo   [8]  Executar Suite de Testes Automatizados ^(python -m pytest tests -v^)
echo   [9]  Exibir Tabela de Paridade Completa: API Online == HTML Offline
echo   [10] Commit ^& Push para GitHub ^(origin/main^) para Redeploy no Easypanel
echo   [0]  Sair
echo.
set /p "OPT=Escolha uma opcao [0-10]: "

if "%OPT%"=="1" goto :CMD_START
if "%OPT%"=="2" goto :CMD_HEALTH
if "%OPT%"=="3" goto :CMD_WARM
if "%OPT%"=="4" goto :CMD_MATCH
if "%OPT%"=="5" goto :CMD_TRENDING
if "%OPT%"=="6" goto :CMD_OVERRIDES
if "%OPT%"=="7" goto :CMD_CACHE
if "%OPT%"=="8" goto :CMD_TEST
if "%OPT%"=="9" goto :CMD_PARITY
if "%OPT%"=="10" goto :CMD_PUSH
if "%OPT%"=="0" exit /b 0
goto :MENU

:CLI_DISPATCH
set "ACTION=%~1"
if /I "%ACTION%"=="start" goto :CMD_START
if /I "%ACTION%"=="health" goto :CMD_HEALTH
if /I "%ACTION%"=="warm" goto :CMD_WARM
if /I "%ACTION%"=="match" goto :CMD_MATCH
if /I "%ACTION%"=="trending" goto :CMD_TRENDING
if /I "%ACTION%"=="sync" goto :CMD_SYNC
if /I "%ACTION%"=="overrides" goto :CMD_OVERRIDES
if /I "%ACTION%"=="cache" goto :CMD_CACHE
if /I "%ACTION%"=="test" goto :CMD_TEST
if /I "%ACTION%"=="parity" goto :CMD_PARITY
if /I "%ACTION%"=="push" goto :CMD_PUSH
echo Uso: %~nx0 [start^|health^|warm^|match^|trending^|sync^|overrides^|cache^|test^|parity^|push]
exit /b 1

:ENSURE_DEPS
python -c "import fastapi, uvicorn, httpx, pydantic" >nul 2>&1
if errorlevel 1 (
    echo [Deps] Instalando dependencias de requirements.txt...
    python -m pip install -r requirements.txt
)
goto :EOF

:CMD_START
call :ENSURE_DEPS
echo.
echo [1/2] IPTV Oficial: %IPTV_URL% ^(Fallback IP: %IPTV_FALLBACK_IP%^)
echo [2/2] Subindo Pera TV BFF v2.3.0 em %LOCAL_API_URL% ...
echo       Docs Swagger : %LOCAL_API_URL%/docs
echo       Healthcheck  : %LOCAL_API_URL%/health
echo       Hub Prime    : %LOCAL_API_URL%/api/v1/streaming/hub/prime
echo       Trending     : %LOCAL_API_URL%/api/v1/streaming/trending
echo.
python -m uvicorn main:app --host 0.0.0.0 --port %PORT%
if "%~1"=="" pause & goto :MENU
exit /b %errorlevel%

:CMD_HEALTH
echo.
python cli_tools.py health --local-url "%LOCAL_API_URL%" --prod-url "%PROD_API_URL%"
if "%~1"=="" pause & goto :MENU
exit /b %errorlevel%

:CMD_WARM
echo.
python cli_tools.py warm --local-url "%LOCAL_API_URL%"
if "%~1"=="" pause & goto :MENU
exit /b %errorlevel%

:CMD_MATCH
echo.
python cli_tools.py match --local-url "%LOCAL_API_URL%"
if "%~1"=="" pause & goto :MENU
exit /b %errorlevel%

:CMD_TRENDING
echo.
python cli_tools.py trending --local-url "%LOCAL_API_URL%"
if "%~1"=="" pause & goto :MENU
exit /b %errorlevel%

:CMD_SYNC
echo.
python cli_tools.py sync --local-url "%LOCAL_API_URL%"
if "%~1"=="" pause & goto :MENU
exit /b %errorlevel%

:CMD_OVERRIDES
echo.
python cli_tools.py overrides --local-url "%LOCAL_API_URL%"
if "%~1"=="" pause & goto :MENU
exit /b %errorlevel%

:CMD_CACHE
echo.
python cli_tools.py cache --local-url "%LOCAL_API_URL%" --sub "%~2"
if "%~1"=="" pause & goto :MENU
exit /b %errorlevel%

:CMD_TEST
call :ENSURE_DEPS
echo.
echo === EXECUTANDO SUITE DE TESTES PYTEST ===
python -m pytest tests -v
if "%~1"=="" pause & goto :MENU
exit /b %errorlevel%

:CMD_PARITY
echo.
python cli_tools.py parity
if "%~1"=="" pause & goto :MENU
exit /b %errorlevel%

:CMD_PUSH
echo.
echo === GIT STATUS / COMMIT / PUSH PARA GITHUB ===
git status -s
set /p "MSG=Mensagem do commit (Enter para padrao): "
if "%MSG%"=="" set "MSG=feat(api): flatrate discover br, startup warmup, trending match e gerenciador cmd"
git add -A
git commit -m "%MSG%"
git push origin main
if "%~1"=="" pause & goto :MENU
exit /b %errorlevel%
