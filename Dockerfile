FROM python:3.12-slim

# 1. Impede escrita de .pyc e força flush imediato de logs (stdout/stderr)
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PORT=8000

WORKDIR /app

# 2. Copia e instala requirements primeiro (Camada com Cache isolado)
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# 3. Copia o código da aplicação
COPY . /app

# 4. Declara a porta exposta
EXPOSE 8000

# 5. Healthcheck nativo em Python (dispensa curl/wget no slim)
HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')" || exit 1

# 6. Inicialização do Uvicorn escutando em 0.0.0.0 (obrigatório em contêineres)
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
