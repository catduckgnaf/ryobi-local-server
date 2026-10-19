#!/bin/sh
# Standalone container entrypoint.
#
# HTTP is always served on LISTEN_PORT (default 8080). Point the ryobi_gdo
# integration's Server field at http://<docker-host-ip>:<published port>.
#
# HTTPS is optional and only needed for the experimental DNS redirect setup.
# Set SSL_ENABLED=true to serve it on SSL_PORT (default 8443). If SSL_CERT and
# SSL_KEY are not provided, a self-signed certificate is generated in /data.
set -e

if ! touch /data/.write-test 2>/dev/null; then
    echo "WARNING: /data is not writable by uid $(id -u). State will not survive restarts." >&2
    echo "         Fix the volume owner, or set 'user:' in compose (Unraid: \"99:100\")." >&2
else
    rm -f /data/.write-test
fi

if [ "${SSL_ENABLED:-false}" = "true" ]; then
    SSL_PORT="${SSL_PORT:-8443}"
    if [ -z "${SSL_CERT:-}" ] || [ -z "${SSL_KEY:-}" ]; then
        SSL_CERT=/data/ssl/server.crt
        SSL_KEY=/data/ssl/server.key
        if [ ! -f "$SSL_CERT" ] || [ ! -f "$SSL_KEY" ]; then
            echo "Generating self-signed certificate for tti.tiwiconnect.com"
            mkdir -p /data/ssl
            openssl req -x509 -newkey rsa:2048 -nodes -days 3650 \
                -keyout "$SSL_KEY" -out "$SSL_CERT" \
                -subj "/CN=tti.tiwiconnect.com" \
                -addext "subjectAltName=DNS:tti.tiwiconnect.com,DNS:tti-prod2.thomisidae.com" \
                2>/dev/null
        fi
    fi
    export SSL_PORT SSL_CERT SSL_KEY
else
    # main.py only starts HTTPS when both files exist, so blank them out.
    export SSL_CERT="" SSL_KEY=""
fi

exec python -m server.main "$@"
