#!/usr/bin/with-contenv bashio
# ==============================================================================
# Ryobi GDO Local Server — Home Assistant add-on entrypoint
#
#  1. Read options from the add-on UI
#  2. Work out the LAN IP other devices use to reach this host
#  3. Optionally start dnsmasq (experimental DNS redirect mode)
#  4. Optionally create a self-signed cert (experimental HTTPS mode)
#  5. Write the server config and run the Python server in the foreground
# ==============================================================================
set -e

DEVICE_ID="$(bashio::config 'device_id')"
DEVICE_NAME="$(bashio::config 'device_name' 'Garage Door')"
LOG_LEVEL="$(bashio::config 'log_level' 'info')"
SERVER_PORT="$(bashio::config 'server_port' '80')"
HTTPS_ENABLED="$(bashio::config 'https_enabled' 'false')"
HTTPS_PORT="$(bashio::config 'https_port' '443')"
DNS_ENABLED="$(bashio::config 'dns_enabled' 'false')"
DNS_PORT="$(bashio::config 'dns_port' '53')"
INGRESS_PORT="$(bashio::addon.ingress_port)"

if bashio::var.is_empty "${DEVICE_ID}"; then
    bashio::exit.nok "device_id is required. Set it on the Configuration tab (see the Documentation tab for how to find it)."
fi

# ---------------------------------------------------------------------------
# LAN IP: explicit override, else the source address of the default route
# ---------------------------------------------------------------------------
if bashio::config.has_value 'advertise_ip'; then
    HOST_IP="$(bashio::config 'advertise_ip')"
else
    HOST_IP="$(ip route get 1.1.1.1 2>/dev/null | awk '{for(i=1;i<=NF;i++) if ($i=="src") {print $(i+1); exit}}')"
fi
if bashio::var.is_empty "${HOST_IP}"; then
    bashio::exit.nok "Could not detect this host's LAN IP. Set advertise_ip in the add-on configuration."
fi

if [ "${SERVER_PORT}" = "80" ]; then
    INTEGRATION_HOST="http://${HOST_IP}"
else
    INTEGRATION_HOST="http://${HOST_IP}:${SERVER_PORT}"
fi

# ---------------------------------------------------------------------------
# Experimental: DNS redirect for tti.tiwiconnect.com
# ---------------------------------------------------------------------------
if bashio::var.true "${DNS_ENABLED}"; then
    bashio::log.warning "Built-in DNS is enabled (experimental). It only affects devices that use ${HOST_IP} as their DNS server."

    # Bind only to the LAN IP so we don't fight systemd-resolved, the
    # Supervisor DNS plugin, or anything else listening on loopback.
    cat > /etc/dnsmasq.conf <<EOF
port=${DNS_PORT}
no-resolv
no-hosts
no-poll
server=1.1.1.1
server=8.8.8.8
address=/tti.tiwiconnect.com/${HOST_IP}
listen-address=${HOST_IP}
bind-dynamic
local-ttl=10
EOF
    if [ "${LOG_LEVEL}" = "debug" ]; then
        echo "log-queries" >> /etc/dnsmasq.conf
    fi

    dnsmasq --keep-in-foreground --log-facility=- &
    DNSMASQ_PID=$!
    sleep 1
    if ! kill -0 "${DNSMASQ_PID}" 2>/dev/null; then
        bashio::log.error "dnsmasq failed to start. Port ${DNS_PORT} on ${HOST_IP} is probably taken (AdGuard Home or Pi-hole?)."
        bashio::log.error "Turn off dns_enabled and add the tti.tiwiconnect.com rewrite in that DNS server instead."
        unset DNSMASQ_PID
    else
        bashio::log.info "DNS: tti.tiwiconnect.com -> ${HOST_IP} (port ${DNS_PORT})"
    fi
fi

# ---------------------------------------------------------------------------
# Experimental: HTTPS/WSS listener with a self-signed certificate
# ---------------------------------------------------------------------------
SSL_ARGS=()
if bashio::var.true "${HTTPS_ENABLED}"; then
    SSL_DIR="/data/ssl"
    mkdir -p "${SSL_DIR}"
    # Regenerate if the cert is missing or was issued for a different IP
    if [ ! -f "${SSL_DIR}/server.crt" ] || [ ! -f "${SSL_DIR}/server.key" ] \
        || [ "$(cat "${SSL_DIR}/ip" 2>/dev/null)" != "${HOST_IP}" ]; then
        bashio::log.info "Generating self-signed certificate for tti.tiwiconnect.com..."
        openssl req -x509 -newkey rsa:2048 -nodes -days 3650 \
            -keyout "${SSL_DIR}/server.key" \
            -out "${SSL_DIR}/server.crt" \
            -subj "/CN=tti.tiwiconnect.com" \
            -addext "subjectAltName=DNS:tti.tiwiconnect.com,DNS:tti-prod2.thomisidae.com,IP:${HOST_IP}" \
            2>/dev/null
        echo "${HOST_IP}" > "${SSL_DIR}/ip"
    fi
    SSL_ARGS=(--ssl-port "${HTTPS_PORT}" --ssl-cert "${SSL_DIR}/server.crt" --ssl-key "${SSL_DIR}/server.key")
fi

# ---------------------------------------------------------------------------
# Server config. Built with jq (JSON is valid YAML) so odd characters in the
# device name can't break the file.
# ---------------------------------------------------------------------------
CONFIG_FILE="/data/ryobi_server_config.yaml"
jq -n \
    --arg id "${DEVICE_ID}" \
    --arg name "${DEVICE_NAME}" \
    --arg webhook "$(bashio::config 'command_webhook_url' '')" \
    --argjson timeout "$(bashio::config 'command_webhook_timeout' '3')" \
    '{
        devices: [{
            device_id: $id,
            name: $name,
            modules: {
                garageDoor: "garageDoor_7",
                garageLight: "garageLight_7",
                backupCharger: "backupCharger_6",
                wifiModule: "wifiModule_7",
                parkAssistLaser: "parkAssistLaser_1",
                inflator: "inflator_4",
                btSpeaker: "btSpeaker_2",
                fan: "fan_3"
            }
        }],
        cloud_poll: false,
        enforce_token: false
    }
    + (if $webhook != "" then {command_webhook_url: $webhook, command_webhook_timeout: $timeout} else {} end)' \
    > "${CONFIG_FILE}"

bashio::log.info "------------------------------------------------------------"
bashio::log.info " Device:  ${DEVICE_NAME} (${DEVICE_ID})"
bashio::log.info " In the Ryobi integration, set Server to:  ${INTEGRATION_HOST}"
bashio::log.info " Health check: ${INTEGRATION_HOST}/health"
bashio::log.info "------------------------------------------------------------"

LOG_LEVEL_UPPER="$(echo "${LOG_LEVEL}" | tr '[:lower:]' '[:upper:]')"

python3 -m server.main \
    --config "${CONFIG_FILE}" \
    --host 0.0.0.0 \
    --port "${SERVER_PORT}" \
    --ingress-port "${INGRESS_PORT}" \
    --log-level "${LOG_LEVEL_UPPER}" \
    "${SSL_ARGS[@]}" &
MAIN_PID=$!

# Stop children cleanly when Supervisor stops the add-on
trap 'kill ${MAIN_PID} ${DNSMASQ_PID:-} 2>/dev/null' TERM INT

set +e
wait "${MAIN_PID}"
EXIT_CODE=$?
[ -n "${DNSMASQ_PID:-}" ] && kill "${DNSMASQ_PID}" 2>/dev/null
bashio::log.warning "Ryobi server exited with code ${EXIT_CODE}"
exit "${EXIT_CODE}"
