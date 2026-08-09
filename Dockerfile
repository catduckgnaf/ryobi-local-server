FROM python:3.11-slim

LABEL maintainer="catduckgnaf"
LABEL description="Ryobi GDO local server — emulates tti.tiwiconnect.com on your LAN"

WORKDIR /app

# Install dependencies
COPY pyproject.toml ./
RUN pip install --no-cache-dir -e .

# Copy source
COPY server/ ./server/
COPY config/ ./config/

# State file directory
RUN mkdir -p /data
ENV STATE_FILE=/data/ryobi_state.json

# Expose HTTP port (80 default, but 8080 is safer without root)
EXPOSE 8080

ENV LISTEN_PORT=8080
ENV LOG_LEVEL=INFO

CMD ["python", "-m", "server.main", "--config", "config/config.yaml"]
