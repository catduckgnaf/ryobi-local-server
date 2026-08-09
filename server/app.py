"""
aiohttp Application factory for the Ryobi local server.

Wires together the state store, route handlers, and optional cloud proxy.
"""

from __future__ import annotations

import logging
from typing import Any

from aiohttp import web

from .models import GarageDoorState
from .routes import (
    make_devices_handler,
    make_device_detail_handler,
    make_health_handler,
    make_login_handler,
    make_state_get_handler,
    make_state_post_handler,
    make_wsrpc_handler,
)
from .state import StateStore

LOGGER = logging.getLogger(__name__)


async def create_app(config: dict[str, Any]) -> web.Application:
    """
    Create and configure the aiohttp Application.

    config keys:
      username: str               - Ryobi account username (for proxy + auth enforcement)
      password: str               - Ryobi account password
      enforce_token: bool         - If True, reject WS connections with invalid tokens
      cloud_poll: bool            - If True, poll real Ryobi cloud for state
      poll_interval: int          - Cloud poll interval in seconds (default 30)
      devices: list[dict]         - List of device definitions (see config.yaml.example)
    """
    store = StateStore()

    # Register devices from config
    for dev_cfg in config.get("devices", []):
        device = GarageDoorState(
            device_id=dev_cfg["device_id"],
            device_name=dev_cfg.get("name", "Ryobi GDO"),
            battery_level=dev_cfg.get("battery_level"),
            wifi_rssi=dev_cfg.get("wifi_rssi"),
            modules=dev_cfg.get("modules", {}),
        )
        store.add_device(device)

    # Load any persisted state (overrides defaults above)
    await store.load_persisted()

    app = web.Application()

    # Attach store + config to app for use in startup/cleanup
    app["store"] = store
    app["config"] = config

    # Register routes
    app.router.add_post("/api/login", make_login_handler(store, config))
    app.router.add_get("/api/devices", make_devices_handler(store))
    app.router.add_get("/api/devices/{device_id}", make_device_detail_handler(store))
    app.router.add_get("/api/wsrpc", make_wsrpc_handler(store, config))

    # Management / webhook routes
    app.router.add_get("/state", make_state_get_handler(store))
    app.router.add_post("/state", make_state_post_handler(store))
    app.router.add_get("/health", make_health_handler())

    # Startup / cleanup hooks
    app.on_startup.append(_on_startup)
    app.on_cleanup.append(_on_cleanup)

    return app


async def _on_startup(app: web.Application) -> None:
    """Start background tasks (cloud proxy, etc.)."""
    config = app["config"]
    store = app["store"]

    if config.get("cloud_poll", False):
        username = config.get("username", "")
        password = config.get("password", "")
        if username and password:
            from .ryobi_proxy import RyobiCloudProxy  # noqa: PLC0415
            proxy = RyobiCloudProxy(
                store=store,
                username=username,
                password=password,
                poll_interval=config.get("poll_interval", 30),
            )
            await proxy.start()
            app["cloud_proxy"] = proxy
            LOGGER.info("Cloud proxy started")
        else:
            LOGGER.warning("cloud_poll enabled but no username/password configured")


async def _on_cleanup(app: web.Application) -> None:
    """Stop background tasks."""
    proxy = app.get("cloud_proxy")
    if proxy is not None:
        await proxy.stop()
        LOGGER.info("Cloud proxy stopped")
