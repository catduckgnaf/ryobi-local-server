#!/bin/sh
# HTTP on 8080 (published as 80) and HTTPS/WSS on 443.
# The opener speaks TLS to tti.tiwiconnect.com:443. Without this listener
# a LAN DNS rewrite sends it to a closed port.
set -e

SSL_DIR="${SSL_DIR:-/data/ssl}"
mkdir -p "${SSL_DIR}"

if [ ! -f "${SSL_DIR}/server.crt" ] || [ ! -f "${SSL_DIR}/server.key" ]; then
    echo "Generating self-signed certificate for tti.tiwiconnect.com"
    openssl req -x509 -newkey rsa:2048 -nodes \
        -keyout "${SSL_DIR}/server.key" \
        -out "${SSL_DIR}/server.crt" \
        -days 3650 \
        -subj "/CN=tti.tiwiconnect.com" \
        -addext "subjectAltName=DNS:tti.tiwiconnect.com,DNS:tti-prod2.thomisidae.com"
fi

exec python -m server.main \
    --config "${CONFIG_FILE:-config/config.yaml}" \
    --host 0.0.0.0 \
    --port "${LISTEN_PORT:-8080}" \
    --ssl-port "${SSL_PORT:-443}" \
    --ssl-cert "${SSL_DIR}/server.crt" \
    --ssl-key "${SSL_DIR}/server.key"
