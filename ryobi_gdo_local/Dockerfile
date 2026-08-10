ARG BUILD_FROM=ghcr.io/home-assistant/amd64-base-python:3.12-alpine3.20
FROM $BUILD_FROM

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

# Copy the ryobi server source into /app/server
COPY server/ /app/server/

# Copy the main entrypoint
COPY run.sh /run.sh
RUN chmod a+x /run.sh

WORKDIR /app

CMD ["/run.sh"]
