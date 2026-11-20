# Etapa 1 — trava de build: JavaScript com erro de sintaxe derruba a tela inteira.
# Se o app.js não passar no `node --check`, o build falha aqui e o EasyPanel mantém a
# versão anterior no ar, em vez de publicar a página quebrada.
FROM node:22-alpine AS checagem
WORKDIR /chk
COPY public/*.js ./
RUN for f in *.js; do node --check "$f" || exit 1; done && touch /chk/ok

# Etapa 2 — o app
FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# depende da etapa 1: sem isto o Docker pularia a checagem
COPY --from=checagem /chk/ok /tmp/js-ok

COPY app ./app
COPY public ./public
COPY scripts ./scripts
COPY sql ./sql

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=4).status == 200 else 1)"

# 2 workers: o estado vive todo no Postgres, então mais de um processo é seguro
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2", "--proxy-headers", "--forwarded-allow-ips", "*"]
