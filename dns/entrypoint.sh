#!/bin/sh
# Answers tti.tiwiconnect.com with ADVERTISE_IP and forwards everything else.
set -e

if [ -z "${ADVERTISE_IP:-}" ]; then
    echo "ADVERTISE_IP is required (the LAN IP of the Docker host)" >&2
    exit 1
fi

{
    echo "no-resolv"
    echo "no-hosts"
    for s in ${UPSTREAM_DNS:-1.1.1.1 8.8.8.8}; do echo "server=$s"; done
    echo "address=/tti.tiwiconnect.com/${ADVERTISE_IP}"
    echo "port=${DNS_PORT:-53}"
    echo "listen-address=${ADVERTISE_IP}"
    echo "bind-dynamic"
    echo "local-ttl=10"
    [ "${LOG_QUERIES:-false}" = "true" ] && echo "log-queries"
} > /etc/dnsmasq.conf

echo "dnsmasq: tti.tiwiconnect.com -> ${ADVERTISE_IP}"
exec dnsmasq --keep-in-foreground --log-facility=-
