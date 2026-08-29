"""
HTTP and WebSocket route handlers for the Ryobi local server emulator.

Implements the four Ryobi TiwiConnect endpoints:
  POST /api/login           - credential auth → API key
  GET  /api/devices         - list all devices
  GET  /api/devices/{id}    - device detail with deviceTypeMap
  GET  /api/wsrpc           - WebSocket upgrade for real-time push/commands

Plus two management endpoints:
  POST /state               - webhook: push real device state in
  GET  /state               - debug: view current in-memory state as JSON
  GET  /health              - health check
"""

from __future__ import annotations

import asyncio
import json
import logging
import secrets
import time
from typing import Any

import aiohttp
from aiohttp import WSMsgType, web

from .state import StateStore

LOGGER = logging.getLogger(__name__)

# Simple in-process token store: token -> {"username": ..., "expires": ...}
_TOKENS: dict[str, dict] = {}
TOKEN_TTL = 86400  # 24 hours


def _issue_token(username: str) -> str:
    """Issue a new API key token."""
    token = secrets.token_hex(32)
    _TOKENS[token] = {"username": username, "expires": time.time() + TOKEN_TTL}
    return token


def _validate_token(token: str) -> bool:
    """Return True if token is valid and not expired."""
    entry = _TOKENS.get(token)
    if entry is None:
        return False
    if time.time() > entry["expires"]:
        del _TOKENS[token]
        return False
    return True


# ---------------------------------------------------------------------------
# Route factories — each takes the store as a closure
# ---------------------------------------------------------------------------

def make_login_handler(store: StateStore, config: dict):
    """POST /api/login — accepts username+password, returns fake API key."""

    async def handle_login(request: web.Request) -> web.Response:
        try:
            data = await request.post()
        except Exception:
            data = {}

        username = data.get("username", "")
        password = data.get("password", "")

        # If credentials are configured, enforce them; otherwise accept anything
        expected_user = config.get("username", "")
        expected_pass = config.get("password", "")

        if expected_user and (username != expected_user or password != expected_pass):
            LOGGER.warning("Login rejected for user: %s", username)
            return web.json_response({"result": None, "error": "Unauthorized"}, status=401)

        token = _issue_token(username)
        LOGGER.info("Login successful for user: %s", username)

        # Mimic the Ryobi login response shape with local server metadata
        response = {
            "result": {
                "metaData": {
                    "wskAuthAttempts": [{"apiKey": token}],
                    "username": username,
                },
                "status": "OK",
                "server_type": "local",
                "local_server": True,
            }
        }
        return web.json_response(response, headers={"X-Server": "Ryobi-Local-Server"})

    return handle_login


def make_devices_handler(store: StateStore):
    """GET /api/devices — list all registered devices."""

    async def handle_devices(request: web.Request) -> web.Response:
        devices = store.list_devices()
        result = [d.build_list_entry() for d in devices]
        return web.json_response(
            {"result": result, "server_type": "local", "local_server": True},
            headers={"X-Server": "Ryobi-Local-Server"},
        )

    return handle_devices


def make_device_detail_handler(store: StateStore):
    """GET /api/devices/{device_id} — return full device detail."""

    async def handle_device_detail(request: web.Request) -> web.Response:
        device_id = request.match_info.get("device_id", "")
        device = store.get_device(device_id)
        if device is None:
            LOGGER.warning("Device not found: %s", device_id)
            return web.json_response(
                {"result": [], "error": "Device not found"},
                headers={"X-Server": "Ryobi-Local-Server"},
            )
        return web.json_response(
            {"result": [device.build_device_result()], "server_type": "local", "local_server": True},
            headers={"X-Server": "Ryobi-Local-Server"},
        )

    return handle_device_detail


def make_wsrpc_handler(store: StateStore, config: dict):
    """
    GET /api/wsrpc — WebSocket upgrade handler.

    Implements:
    - srvWebSocketAuth: authenticate the WS session
    - wskSubscribe: subscribe to device updates (no-op; we push to all)
    - gdoModuleCommand: dispatch command to local state
    """

    async def handle_wsrpc(request: web.Request) -> web.WebSocketResponse:
        ws = web.WebSocketResponse(heartbeat=30)
        await ws.prepare(request)

        store.add_ws_client(ws)
        LOGGER.info("WebSocket client connected from %s", request.remote)

        try:
            async for msg in ws:
                if msg.type == WSMsgType.TEXT:
                    await _handle_ws_message(ws, msg.data, store, config)
                elif msg.type in (WSMsgType.CLOSED, WSMsgType.ERROR):
                    break
        finally:
            store.unregister_device_ws(ws)
            store.remove_ws_client(ws)
            LOGGER.info("WebSocket client disconnected from %s", request.remote)

        return ws

    return handle_wsrpc


async def _handle_ws_message(
    ws: web.WebSocketResponse, raw: str, store: StateStore, config: dict
) -> None:
    """Dispatch a single incoming JSON-RPC WebSocket message."""
    try:
        msg: dict[str, Any] = json.loads(raw)
    except (ValueError, TypeError):
        LOGGER.warning("Received non-JSON WS message: %s", raw)
        return

    method = msg.get("method", "")
    params = msg.get("params", {})
    msg_id = msg.get("id", 1)

    LOGGER.debug("WS message: method=%s params=%s", method, params)

    if method == "srvWebSocketAuth":
        # Validate API key (or accept any if not enforced)
        api_key = params.get("apiKey", "")
        var_name = params.get("varName", "")
        authorized = _validate_token(api_key) or not config.get("enforce_token", False)

        # Send authorizedWebSocket event
        await ws.send_str(
            json.dumps({
                "jsonrpc": "2.0",
                "method": "authorizedWebSocket",
                "params": {"authorized": authorized, "socketId": f"local_{var_name or 'client'}"},
            })
        )

        # Send method response
        await ws.send_str(
            json.dumps({
                "jsonrpc": "2.0",
                "id": msg_id,
                "result": {"authorized": authorized, "varName": var_name, "aCnt": 0},
            })
        )

        if authorized and var_name and store.get_device(var_name):
            store.register_device_ws(var_name, ws)

        if not authorized:
            LOGGER.warning("WS auth rejected: invalid API key for %s", var_name)

    elif method in ("wskAttributeUpdateNtfy", "gdoModuleMsg", "gdoModuleState"):
        # Real-time state push from physical opener hardware
        var_name = params.get("varName") or params.get("topic")
        if var_name:
            # Strip topic suffix if present (e.g. c4be84734c7b.wskAttributeUpdateNtfy)
            dev_id = var_name.split(".")[0]
            await store.handle_device_push(dev_id, params)

        await ws.send_str(
            json.dumps({
                "jsonrpc": "2.0",
                "id": msg_id,
                "result": {"result": "OK"},
            })
        )

    elif method == "wskSubscribe":
        # Subscribe acknowledgement — we push to all clients anyway
        topic = params.get("topic", "")
        LOGGER.debug("WS subscribe for topic: %s", topic)
        await ws.send_str(
            json.dumps({
                "jsonrpc": "2.0",
                "id": msg_id,
                "result": {"result": "OK", "topic": topic},
            })
        )

    elif method == "gdoModuleCommand":
        # Command from HA to control the device
        device_id = params.get("topic", "")
        module_type = params.get("moduleType")
        module_msg: dict[str, Any] = params.get("moduleMsg", {})

        # Resolve module name from moduleType or message attribute
        module_type_map = {
            5: "garageDoor",
            6: "backupCharger",
            7: "wifiModule",
            1: "parkAssistLaser",
            4: "inflator",
            2: "btSpeaker",
            3: "fan",
        }
        module_name = module_type_map.get(module_type, "garageDoor")

        # module_msg is like {"lightState": 1} or {"doorCommand": 1}
        for attr, value in module_msg.items():
            # Attribute-level module resolution override
            if attr == "lightState":
                module_name = "garageLight"
            elif attr in ("doorCommand", "doorState", "vacationMode", "sensorFlag"):
                module_name = "garageDoor"
            elif attr in ("micEnable", "micEnabled"):
                module_name = "btSpeaker"

            # Map doorCommand (open=1, close=0) to door_state ("1" / "0")
            if attr == "doorCommand":
                attr = "doorState"
                value = "1" if str(value) in ("1", "true", "open") else "0"

            await store.apply_command(device_id, module_name, attr, value)

            # Fire outgoing command webhook if configured
            webhook_url = config.get("command_webhook_url", "")
            if webhook_url:
                await _fire_command_webhook(
                    webhook_url=webhook_url,
                    timeout=int(config.get("command_webhook_timeout", 3)),
                    device_id=device_id,
                    module=module_name,
                    attr=attr,
                    value=value,
                )

        # Send command ACK
        await ws.send_str(
            json.dumps({
                "id": msg_id,
                "result": {"result": "OK"},
            })
        )

    else:
        # Unknown method — send generic OK
        LOGGER.debug("Unknown WS method: %s", method)
        await ws.send_str(
            json.dumps({
                "id": msg_id,
                "result": {"result": "OK"},
            })
        )


async def _fire_command_webhook(
    webhook_url: str,
    timeout: int,
    device_id: str,
    module: str,
    attr: str,
    value: Any,
) -> None:
    """
    POST a command to the configured outgoing webhook URL.

    This is how HA commands reach your Pi/ESP to fire a physical relay.
    The Pi/ESP should:
    1. Fire the relay (toggles the door button)
    2. Wait for the reed switch to confirm new state
    3. POST the confirmed new state back to /state

    Payload:
      {
        "device_id": "GDO_XXXXXXXXXX",
        "module":    "garageDoor",
        "attr":      "doorState",
        "value":     "1",
        "command":   "open"   # human-readable helper
      }
    """
    # Build a human-readable command name
    command_name_map = {
        ("garageDoor", "doorState", "1"): "open",
        ("garageDoor", "doorState", "0"): "close",
        ("garageLight", "lightState", True): "light_on",
        ("garageLight", "lightState", False): "light_off",
    }
    command_name = command_name_map.get((module, attr, value), f"{module}.{attr}={value}")

    payload = {
        "device_id": device_id,
        "module": module,
        "attr": attr,
        "value": value,
        "command": command_name,
    }

    LOGGER.info(
        "Firing command webhook: %s -> %s (module=%s attr=%s value=%s)",
        webhook_url, command_name, module, attr, value,
    )

    try:
        async with asyncio.timeout(timeout):
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    webhook_url,
                    json=payload,
                    headers={"Content-Type": "application/json"},
                ) as resp:
                    LOGGER.debug("Command webhook response: %s", resp.status)
    except asyncio.TimeoutError:
        LOGGER.warning("Command webhook timed out after %ds: %s", timeout, webhook_url)
    except Exception as err:  # pylint: disable=broad-except
        LOGGER.warning("Command webhook error: %s", err)


# ---------------------------------------------------------------------------
# Management endpoints
# ---------------------------------------------------------------------------

def make_state_get_handler(store: StateStore):
    """GET /state — debug view of all device states."""

    async def handle_state_get(request: web.Request) -> web.Response:
        data: dict[str, Any] = {}
        for dev in store.list_devices():
            data[dev.device_id] = dev.to_ha_data()
        return web.json_response(data)

    return handle_state_get


def make_state_post_handler(store: StateStore):
    """
    POST /state — webhook for external sensors to push real state in.

    Body (JSON):
    {
      "device_id": "GDO_XXXXXXXXXX",
      "door_state": "0",        // "0"=closed "1"=open "2"=closing "3"=opening
      "light_state": false,
      "battery_level": 85,
      "wifi_rssi": -65,
      "safety": false
    }
    """

    async def handle_state_post(request: web.Request) -> web.Response:
        try:
            body = await request.json()
        except Exception:
            return web.json_response({"error": "Invalid JSON"}, status=400)

        device_id = body.get("device_id")
        if not device_id:
            return web.json_response({"error": "Missing device_id"}, status=400)

        # Extract allowed fields (everything except device_id)
        updates = {k: v for k, v in body.items() if k != "device_id"}

        success = await store.update_state(device_id, updates)
        if not success:
            return web.json_response({"error": f"Unknown device: {device_id}"}, status=404)

        LOGGER.info("Webhook state update for %s: %s", device_id, updates)
        return web.json_response({"result": "OK", "device_id": device_id, "updates": updates})

    return handle_state_post


def make_health_handler():
    """GET /health — simple liveness check."""

    async def handle_health(request: web.Request) -> web.Response:
        return web.json_response({"status": "ok"})

    return handle_health
