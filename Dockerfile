# Standalone image (Unraid, Synology, any Docker host).
# The Home Assistant add-on is built from ryobi_gdo_local/Dockerfile instead.
FROM python:3.12-slim

LABEL org.opencontainers.image.title="ryobi-local-server" \
      org.opencontainers.image.description="Local TiwiConnect emulator for Ryobi garage door openers" \
      org.opencontainers.image.source="https://github.com/catduckgnaf/ryobi-local-server" \
      org.opencontainers.image.licenses="MIT"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    LISTEN_PORT=8080 \
    CONFIG_FILE=/config/config.yaml \
    STATE_FILE=/data/ryobi_state.json \
    LOG_LEVEL=INFO

RUN apt-get update \
    && apt-get install -y --no-install-recommends openssl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY ryobi_gdo_local/server/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt

COPY ryobi_gdo_local/server/ ./server/
COPY docker/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh \
    && useradd --system --uid 1000 --home /data ryobi \
    && mkdir -p /config /data \
    && chown ryobi /data

USER ryobi
VOLUME ["/data"]
EXPOSE 8080 8443

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import os,urllib.request; urllib.request.urlopen(f'http://127.0.0.1:{os.environ.get(\"LISTEN_PORT\",\"8080\")}/health', timeout=4)"

ENTRYPOINT ["/entrypoint.sh"]
