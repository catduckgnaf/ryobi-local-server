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
            import ssl
            ssl_ctx = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
            ssl_ctx.load_cert_chain(certfile=args.ssl_cert, keyfile=args.ssl_key)
            site_https = web.TCPSite(runner, host=args.host, port=args.ssl_port, ssl_context=ssl_ctx)
            await site_https.start()
            LOGGER.info("HTTPS/WSS Server running on %s:%d (TLS active)", args.host, args.ssl_port)
        except Exception as err:
            LOGGER.error("Failed to start HTTPS listener on port %d: %s", args.ssl_port, err)

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
