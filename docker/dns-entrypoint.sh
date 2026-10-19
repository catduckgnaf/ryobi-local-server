#!/bin/sh
# Same DNS the Home Assistant add-on starts: one name, tti.tiwiconnect.com,
# answered with this machine's LAN IP. Everything else goes upstream.
set -e

if [ -z "${RYOBI_HOST_IP}" ]; then
    echo "RYOBI_HOST_IP is required (the LAN address of this machine)." >&2
    exit 1
fi

apk add --no-cache dnsmasq

cat > /etc/dnsmasq.conf <<EOF
port=53
no-resolv
no-poll
server=1.1.1.1
server=8.8.8.8
address=/tti.tiwiconnect.com/${RYOBI_HOST_IP}
listen-address=0.0.0.0
bind-interfaces
local-ttl=10
EOF

echo "ryobi-dns: tti.tiwiconnect.com -> ${RYOBI_HOST_IP}"
echo "Point the router's LAN DNS server at ${RYOBI_HOST_IP}"
exec dnsmasq -k --log-queries --log-facility=-
