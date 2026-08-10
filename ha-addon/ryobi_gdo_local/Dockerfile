ARG BUILD_FROM=ghcr.io/home-assistant/amd64-base-python:3.12-alpine3.20
FROM $BUILD_FROM

# Labels for HA addon build system
ARG BUILD_ARCH
ARG BUILD_DATE
ARG BUILD_DESCRIPTION
ARG BUILD_NAME
ARG BUILD_REF
ARG BUILD_REPOSITORY
ARG BUILD_VERSION

LABEL \
    io.hass.name="${BUILD_NAME}" \
    io.hass.description="${BUILD_DESCRIPTION}" \
    io.hass.arch="${BUILD_ARCH}" \
    io.hass.type="addon" \
    io.hass.version="${BUILD_VERSION}" \
    maintainer="catduckgnaf <https://github.com/catduckgnaf>"

# Install system dependencies:
# - dnsmasq: lightweight DNS server for redirecting tti.tiwiconnect.com
# - bash, curl, jq: for run.sh helpers
RUN apk add --no-cache \
    dnsmasq \
    bash \
    curl \
    jq

# Install Python dependencies
COPY server/requirements.txt /tmp/requirements.txt
RUN pip3 install --no-cache-dir -r /tmp/requirements.txt

# Copy the ryobi server source
COPY server/ /app/server/

# Copy s6-overlay service scripts (startup/process management)
COPY ha-addon/ryobi_gdo_local/rootfs/ /

# Copy the main entrypoint
COPY ha-addon/ryobi_gdo_local/run.sh /run.sh
RUN chmod +x /run.sh

WORKDIR /app

CMD ["/run.sh"]
