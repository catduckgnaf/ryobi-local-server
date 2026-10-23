"""
Entrypoint for the Ryobi local server emulator.

Usage:
  python -m server.main --config config/config.yaml --host 0.0.0.0 --port 80
  ryobi-server  (after pip install -e .)
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import ipaddress
import os
import sys

import yaml
from aiohttp import web

from .app import create_app

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)

LOGGER = logging.getLogger(__name__)


def _log_tls_handshake_failures() -> None:
    """Record opener connections that die during TLS.

    ssl.SSLError is an OSError, and asyncio only logs those when the loop
    is in debug mode. Without this, a garage door that connects to port 443
    and rejects the certificate leaves no line in the add-on log.
    """
    import ssl
    from asyncio.sslproto import SSLProtocol

    original = SSLProtocol._fatal_error

    def _fatal_error(self, exc, message="Fatal error on transport"):  # type: ignore[no-untyped-def]
        if isinstance(exc, ssl.SSLError):
            peer = None
            transport = getattr(self, "_transport", None)
            extra = getattr(transport, "_extra", None) if transport is not None else None
            if isinstance(extra, dict):
                peer = extra.get("peername")
            LOGGER.warning(
                "TLS handshake failed from %s: %s.",
                peer or "unknown",
                exc,
            )
        return original(self, exc, message)

    SSLProtocol._fatal_error = _fatal_error  # type: ignore[method-assign]


def _server_ssl_context(certfile: str, keyfile: str):
    """TLS the opener can finish.

    tti.tiwiconnect.com still accepts TLS 1.0 with ECDHE-RSA-AES128-SHA.
    OpenSSL 3's default is TLS 1.2 at security level 2, which answered the
    door with NO_SHARED_SIGNATURE_ALGORITHMS and then NO_SHARED_CIPHER.
    """
    import ssl
    import warnings

    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        ctx.minimum_version = ssl.TLSVersion.TLSv1
    # ALL, not DEFAULT: the door's list is the old SHA-1 and CBC suites.
    ctx.set_ciphers("ALL:@SECLEVEL=0")
    ctx.load_cert_chain(certfile=certfile, keyfile=keyfile)
    LOGGER.info(
        "TLS for the opener: %d ciphers, minimum %s",
        len(ctx.get_ciphers()),
        getattr(ctx.minimum_version, "name", ctx.minimum_version),
    )
    return ctx


def opener_mode(config: dict) -> str:
    """Legacy capture flag wins; auto preserves existing local/cloud selection."""
    mode = os.environ.get("OPENER_MODE", config.get("opener_mode", "auto"))
    if mode not in ("auto", "cloud", "takeover", "local"):
        raise ValueError("opener_mode must be auto, cloud, takeover or local")
    if config.get("cloud_relay") or "OPENER_CLOUD_RELAY_IP" in os.environ:
        return "cloud"
    return "local" if mode == "auto" else mode


def _load_config(config_path: str) -> dict:
    """Load YAML config file, merging with environment variable overrides."""
    config: dict = {}
    if config_path and os.path.exists(config_path):
        with open(config_path) as f:
            config = yaml.safe_load(f) or {}
        LOGGER.info("Loaded config from %s", config_path)
    else:
        LOGGER.warning("Config file not found: %s — using defaults", config_path)

    # Environment variable overrides (useful for Docker)
    if os.environ.get("RYOBI_USERNAME"):
        config["username"] = os.environ["RYOBI_USERNAME"]
    if os.environ.get("RYOBI_PASSWORD"):
        config["password"] = os.environ["RYOBI_PASSWORD"]
    if os.environ.get("RYOBI_DEVICE_ID"):
        # Allow specifying a single device via env var
        config.setdefault("devices", [])
        existing_ids = [d["device_id"] for d in config["devices"]]
        if os.environ["RYOBI_DEVICE_ID"] not in existing_ids:
            config["devices"].append({
                "device_id": os.environ["RYOBI_DEVICE_ID"],
                "name": os.environ.get("RYOBI_DEVICE_NAME", "Ryobi GDO"),
            })
    if os.environ.get("RYOBI_CLOUD_POLL"):
        config["cloud_poll"] = os.environ["RYOBI_CLOUD_POLL"].lower() not in ("false", "0", "no")
    if os.environ.get("RYOBI_POLL_INTERVAL"):
        config["poll_interval"] = int(os.environ["RYOBI_POLL_INTERVAL"])

    config["opener_mode"] = opener_mode(config)
    config["cloud_ip"] = os.environ.get("TTI_CLOUD_IP", config.get("cloud_ip", ""))
    if config["opener_mode"] in ("cloud", "takeover"):
        try:
            address = ipaddress.IPv4Address(config["cloud_ip"])
        except ipaddress.AddressValueError as err:
            raise ValueError("Cloud mode requires a public IPv4 address") from err
        if not address.is_global or address.is_multicast:
            raise ValueError("Cloud mode requires a public IPv4 address")
    return config


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Ryobi GDO local server — emulates tti.tiwiconnect.com on your LAN"
    )
    parser.add_argument(
        "--config",
        default=os.environ.get("CONFIG_FILE", "config/config.yaml"),
        help="Path to YAML config file (default: config/config.yaml)",
    )
    parser.add_argument(
        "--host",
        default=os.environ.get("LISTEN_HOST", "0.0.0.0"),
        help="Bind host (default: 0.0.0.0)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=int(os.environ.get("LISTEN_PORT", "80")),
        help="Bind port (default: 80; use 8080 if not running as root)",
    )
    parser.add_argument(
        "--ssl-port",
        type=int,
        default=int(os.environ.get("SSL_PORT", "443")),
        help="SSL bind port for HTTPS/WSS (default: 443)",
    )
    parser.add_argument(
        "--ssl-cert",
        default=os.environ.get("SSL_CERT", ""),
        help="Path to SSL certificate file (PEM format)",
    )
    parser.add_argument(
        "--ssl-key",
        default=os.environ.get("SSL_KEY", ""),
        help="Path to SSL private key file",
    )
    parser.add_argument(
        "--ingress-port",
        type=int,
        default=int(os.environ.get("INGRESS_PORT", "0")),
        help="Home Assistant Ingress port (e.g. 8099)",
    )
    parser.add_argument(
        "--log-level",
        default=os.environ.get("LOG_LEVEL", "INFO"),
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Log level (default: INFO)",
    )
    return parser.parse_args(argv)


async def _async_main(args: argparse.Namespace) -> None:
    logging.getLogger().setLevel(getattr(logging, args.log_level.upper()))
    _log_tls_handshake_failures()
    config = _load_config(args.config)

    if not config.get("devices"):
        LOGGER.error(
            "No devices configured. Add at least one device to config.yaml "
            "or set RYOBI_DEVICE_ID environment variable."
        )
        sys.exit(1)

    app = await create_app(config)
    runner = web.AppRunner(app)
    await runner.setup()

    # 1. Main HTTP Site (port 80)
    site_http = web.TCPSite(runner, host=args.host, port=args.port)
    await site_http.start()
    LOGGER.info("HTTP Server running on %s:%d (%d device(s))", args.host, args.port, len(config["devices"]))

    # 2. Main HTTPS / WSS Site (port 443) with TLS for physical GDO hardware
    if args.ssl_cert and os.path.exists(args.ssl_cert) and args.ssl_key and os.path.exists(args.ssl_key):
        try:
            if os.environ.get("TLS_ENGINE", "tlslite") == "tlslite":
                # OpenSSL cannot answer the opener's ClientHello; see tls_bridge.py.
                from .tls_bridge import OpenerTLSBridge

                OpenerTLSBridge(
                    args.host, args.ssl_port, args.ssl_cert, args.ssl_key, args.port,
                    cloud_relay_ip=(config["cloud_ip"] if config["opener_mode"] == "cloud" else ""),
                ).start()
                LOGGER.info("HTTPS/WSS Server running on %s:%d (tlslite-ng bridge)", args.host, args.ssl_port)
            else:
                ssl_ctx = _server_ssl_context(args.ssl_cert, args.ssl_key)
                site_https = web.TCPSite(runner, host=args.host, port=args.ssl_port, ssl_context=ssl_ctx)
                await site_https.start()
                LOGGER.info("HTTPS/WSS Server running on %s:%d (TLS active)", args.host, args.ssl_port)
        except Exception as err:
            LOGGER.error("Failed to start HTTPS listener on port %d with %s: %s", args.ssl_port, args.ssl_cert, err)
            fallback_cert = os.path.join(os.path.dirname(args.ssl_cert), "server.crt")
            fallback_key = os.path.join(os.path.dirname(args.ssl_key), "server.key")
            if os.path.exists(fallback_cert) and os.path.exists(fallback_key) and fallback_cert != args.ssl_cert:
                LOGGER.info("Attempting fallback HTTPS listener with %s", fallback_cert)
                try:
                    if os.environ.get("TLS_ENGINE", "tlslite") == "tlslite":
                        from .tls_bridge import OpenerTLSBridge
                        OpenerTLSBridge(
                            args.host, args.ssl_port, fallback_cert, fallback_key, args.port,
                            cloud_relay_ip=(config["cloud_ip"] if config["opener_mode"] == "cloud" else ""),
                        ).start()
                        LOGGER.info("HTTPS/WSS Server running on %s:%d (tlslite-ng fallback bridge)", args.host, args.ssl_port)
                    else:
                        ssl_ctx = _server_ssl_context(fallback_cert, fallback_key)
                        site_https = web.TCPSite(runner, host=args.host, port=args.ssl_port, ssl_context=ssl_ctx)
                        await site_https.start()
                        LOGGER.info("HTTPS/WSS Server running on %s:%d (TLS fallback active)", args.host, args.ssl_port)
                except Exception as fb_err:
                    LOGGER.error("Fallback HTTPS listener also failed: %s", fb_err)

    # 3. Ingress Site (HA sidebar dashboard on 8099)
    if args.ingress_port and args.ingress_port not in (args.port, args.ssl_port):
        try:
            site_ingress = web.TCPSite(runner, host=args.host, port=args.ingress_port)
            await site_ingress.start()
            LOGGER.info("Ingress Server running on %s:%d", args.host, args.ingress_port)
        except Exception as err:
            LOGGER.error("Failed to start Ingress listener on port %d: %s", args.ingress_port, err)

    LOGGER.info("Ryobi Local Server is fully initialized.")

    try:
        await asyncio.Event().wait()  # run forever
    except asyncio.CancelledError:
        pass
    finally:
        await runner.cleanup()


def run() -> None:
    """Entry point (called by ryobi-server console script)."""
    args = _parse_args()
    try:
        asyncio.run(_async_main(args))
    except KeyboardInterrupt:
        LOGGER.info("Shutting down.")


if __name__ == "__main__":
    run()
