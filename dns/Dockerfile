# Optional DNS sidecar for the standalone Docker setup.
# Only needed for the experimental "redirect the opener itself" mode.
FROM alpine:3.20
RUN apk add --no-cache dnsmasq
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh
ENTRYPOINT ["/entrypoint.sh"]
