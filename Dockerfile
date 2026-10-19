FROM python:3.11-slim

LABEL maintainer="catduckgnaf"
LABEL description="Ryobi GDO local server — emulates tti.tiwiconnect.com on your LAN"

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends openssl \
    && rm -rf /var/lib/apt/lists/*

# Install dependencies
COPY pyproject.toml ./
RUN pip install --no-cache-dir -e .

# Copy source
COPY server/ ./server/
COPY config/ ./config/

COPY docker/server-entrypoint.sh /server-entrypoint.sh
RUN chmod a+x /server-entrypoint.sh

# State file directory
RUN mkdir -p /data
ENV STATE_FILE=/data/ryobi_state.json

EXPOSE 8080 443

ENV LISTEN_PORT=8080
ENV SSL_PORT=443
ENV LOG_LEVEL=INFO

CMD ["/server-entrypoint.sh"]
