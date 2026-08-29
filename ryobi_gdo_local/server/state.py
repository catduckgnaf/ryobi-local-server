"""
In-memory state store for the Ryobi GDO local server.

Manages device state and broadcasts WebSocket updates to connected HA clients.
State is persisted to a JSON file so it survives restarts.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from typing import Any

import aiofiles

from .models import GarageDoorState

LOGGER = logging.getLogger(__name__)

_STATE_FILE = os.environ.get("STATE_FILE", "ryobi_state.json")


class StateStore:
    """Thread-safe async state store with WebSocket broadcast support."""

    def __init__(self) -> None:
        """Initialize an empty state store."""
        # device_id -> GarageDoorState
        self._devices: dict[str, GarageDoorState] = {}
        # Set of active WebSocket responses (aiohttp WebSocketResponse)
        self._ws_clients: set[Any] = set()
        # Physical hardware WebSocket connections (device_id -> ws)
        self._device_sockets: dict[str, Any] = {}
        self._lock = asyncio.Lock()

    # ------------------------------------------------------------------
    # Device management
    # ------------------------------------------------------------------

    def add_device(self, device: GarageDoorState) -> None:
        """Register a device (called at startup from config)."""
        self._devices[device.device_id] = device
        LOGGER.info("Device registered: %s (%s)", device.device_id, device.device_name)

    def get_device(self, device_id: str) -> GarageDoorState | None:
        """Return device state or None if unknown."""
        return self._devices.get(device_id)

    def list_devices(self) -> list[GarageDoorState]:
        """Return all registered devices."""
        return list(self._devices.values())

    def register_device_ws(self, device_id: str, ws: Any) -> None:
        """Register a physical hardware WebSocket connection."""
        self._device_sockets[device_id] = ws
        LOGGER.info("Physical hardware WebSocket connected for device %s", device_id)

    def unregister_device_ws(self, ws: Any) -> None:
        """Remove physical hardware WebSocket if disconnected."""
        for dev_id, dev_ws in list(self._device_sockets.items()):
            if dev_ws == ws:
                del self._device_sockets[dev_id]
                LOGGER.info("Physical hardware WebSocket disconnected for device %s", dev_id)

    def is_device_ws(self, ws: Any) -> bool:
        """Return True if the websocket belongs to physical hardware."""
        return ws in self._device_sockets.values()

    # ------------------------------------------------------------------
    # State updates
    # ------------------------------------------------------------------

    async def handle_device_push(self, device_id: str, raw_params: dict[str, Any]) -> None:
        """Parse incoming push notifications from the physical hardware opener."""
        updates: dict[str, Any] = {}
        for key, val_obj in raw_params.items():
            if key in ("varName", "topic", "id") or not isinstance(val_obj, dict):
                continue
            val = val_obj.get("value")
            if val is None:
                continue

            parts = key.split(".")
            attr = parts[1] if len(parts) > 1 else key

            if "garageDoor" in key:
                if attr == "doorState":
                    updates["door_state"] = str(val)
                elif attr == "doorPosition":
                    updates["door_position"] = int(val)
                elif attr == "maxDoorPosition":
                    updates["max_door_position"] = int(val)
                elif attr == "motorStatus":
                    updates["motor_status"] = int(val)
                elif attr == "motionSensor":
                    updates["motion"] = bool(val)
                elif attr == "sensorFlag":
                    updates["safety"] = bool(val)
                elif attr == "vacationMode":
                    updates["vacation_mode"] = bool(val)

            elif "garageLight" in key:
                if attr == "lightState":
                    updates["light_state"] = bool(val)

            elif "backupCharger" in key:
                if attr in ("chargeLevel", "batteryLevel"):
                    updates["battery_level"] = int(val)

            elif "wifiModule" in key:
                if attr == "rssi":
                    updates["wifi_rssi"] = int(val)

            elif "parkAssistLaser" in key:
                if attr == "moduleState":
                    updates["park_assist"] = bool(val)

            elif "inflator" in key:
                if attr == "moduleState":
                    updates["inflator"] = bool(val)

            elif "btSpeaker" in key:
                if attr == "moduleState":
                    updates["bt_speaker"] = bool(val)
                elif attr in ("micEnable", "micEnabled"):
                    updates["mic_status"] = bool(val)

            elif "fan" in key:
                if attr == "speed":
                    updates["fan_speed"] = int(val)
                    updates["fan"] = bool(val > 0)
                elif attr == "moduleState":
                    updates["fan"] = bool(val)

        if updates:
            LOGGER.info("Physical device [%s] pushed updates: %s", device_id, updates)
            await self.update_state(device_id, updates)

    async def update_state(self, device_id: str, updates: dict[str, Any]) -> bool:
        """
        Apply a partial state update to a device and broadcast via WebSocket.

        ``updates`` is a flat dict of field names matching GarageDoorState attributes,
        e.g. {"door_state": "1", "light_state": True}.

        Returns True if the device was found and updated.
        """
        async with self._lock:
            device = self._devices.get(device_id)
            if device is None:
                LOGGER.warning("update_state: unknown device %s", device_id)
                return False

            changed = False
            for key, value in updates.items():
                if hasattr(device, key):
                    old = getattr(device, key)
                    if old != value:
                        setattr(device, key, value)
                        changed = True
                        LOGGER.debug("State change [%s] %s: %s -> %s", device_id, key, old, value)
                else:
                    LOGGER.warning("Unknown state field '%s' for device %s", key, device_id)

            if changed:
                await self._persist()
                await self._broadcast(device)

        return True

    async def apply_command(self, device_id: str, module: str, attr: str, value: Any) -> bool:
        """
        Apply a command (from WebSocket gdoModuleCommand) to local state and forward to hardware.

        Maps module + attr pairs to GarageDoorState fields.
        """
        field_map = {
            ("garageLight", "lightState"): "light_state",
            ("garageDoor", "lightState"): "light_state",
            ("garageDoor", "doorState"): "door_state",
            ("garageDoor", "doorCommand"): "door_state",
            ("garageDoor", "vacationMode"): "vacation_mode",
            ("parkAssistLaser", "moduleState"): "park_assist",
            ("inflator", "moduleState"): "inflator",
            ("btSpeaker", "moduleState"): "bt_speaker",
            ("btSpeaker", "micEnable"): "mic_status",
            ("fan", "moduleState"): "fan",
            ("fan", "speed"): "fan_speed",
        }
        field = field_map.get((module, attr))
        if field is None:
            LOGGER.warning("No field mapping for module=%s attr=%s", module, attr)
            return False

        # Normalize bool-like values
        if field == "fan_speed":
            try:
                norm_value = int(value)
            except (ValueError, TypeError):
                norm_value = 0
        elif field == "door_state":
            norm_value = str(value)
        elif isinstance(value, str):
            norm_value = value.lower() in ("1", "true", "on", "open")
        elif isinstance(value, int):
            norm_value = bool(value)
        else:
            norm_value = value

        # Forward command down to physical opener if connected
        device_ws = self._device_sockets.get(device_id)
        if device_ws and not device_ws.closed:
            module_info = {
                "garageDoor": (5, 7, {"doorCommand": 1 if str(value) in ("1", "true", "open") else 0}),
                "garageLight": (5, 7, {"lightState": 1 if norm_value else 0}),
                "parkAssistLaser": (1, 3, {"moduleState": 1 if norm_value else 0}),
                "inflator": (4, 0, {"moduleState": 1 if norm_value else 0}),
                "btSpeaker": (2, 6, {"moduleState": 1 if norm_value else 0} if attr != "micEnable" else {"micEnable": 1 if norm_value else 0}),
                "fan": (3, 3, {"speed": norm_value} if attr == "speed" else {"moduleState": 1 if norm_value else 0}),
            }
            if module in module_info:
                mod_type, port_id, mod_msg = module_info[module]
                cmd_payload = {
                    "jsonrpc": "2.0",
                    "id": int(asyncio.get_event_loop().time() * 1000),
                    "method": "gdoModuleCommand",
                    "params": {
                        "msgType": 16,
                        "moduleType": mod_type,
                        "portId": port_id,
                        "moduleMsg": mod_msg,
                        "topic": device_id,
                    },
                }
                try:
                    await device_ws.send_str(json.dumps(cmd_payload))
                    LOGGER.info("Forwarded command to physical device %s: %s", device_id, cmd_payload)
                except Exception as err:
                    LOGGER.warning("Failed to forward command to physical device %s: %s", device_id, err)

        return await self.update_state(device_id, {field: norm_value})

    # ------------------------------------------------------------------
    # WebSocket client management
    # ------------------------------------------------------------------

    def add_ws_client(self, ws: Any) -> None:
        """Register a connected WebSocket client."""
        self._ws_clients.add(ws)
        LOGGER.debug("WS client connected (total: %d)", len(self._ws_clients))

    def remove_ws_client(self, ws: Any) -> None:
        """Unregister a disconnected WebSocket client."""
        self._ws_clients.discard(ws)
        LOGGER.debug("WS client disconnected (total: %d)", len(self._ws_clients))

    async def _broadcast(self, device: GarageDoorState) -> None:
        """Push a wskAttributeUpdateNtfy message to all connected WS clients."""
        if not self._ws_clients:
            return

        # Build the attributes-changed payload matching the real Ryobi push format
        state = device.to_ha_data()
        payload: dict[str, Any] = {
            "method": "wskAttributeUpdateNtfy",
            "params": {
                "varName": device.device_id,
                "topic": f"{device.device_id}.wskAttributeUpdateNtfy",
            },
        }

        # Add each changed attribute as a dotted key entry
        dtm = device.build_device_type_map()
        for module_key, module_data in dtm.items():
            for attr_key, attr_data in module_data.get("at", {}).items():
                param_key = f"{module_key}.{attr_key}"
                payload["params"][param_key] = attr_data

        msg = json.dumps(payload)
        dead: set[Any] = set()
        for ws in list(self._ws_clients):
            try:
                await ws.send_str(msg)
            except Exception:  # pylint: disable=broad-except
                dead.add(ws)

        for ws in dead:
            self.remove_ws_client(ws)

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    async def _persist(self) -> None:
        """Save current state to JSON file."""
        try:
            data: dict[str, Any] = {}
            for device_id, dev in self._devices.items():
                data[device_id] = {
                    "device_name": dev.device_name,
                    "door_state": dev.door_state,
                    "door_position": dev.door_position,
                    "max_door_position": dev.max_door_position,
                    "motor_status": dev.motor_status,
                    "light_state": dev.light_state,
                    "battery_level": dev.battery_level,
                    "wifi_rssi": dev.wifi_rssi,
                    "safety": dev.safety,
                    "motion": dev.motion,
                    "vacation_mode": dev.vacation_mode,
                    "park_assist": dev.park_assist,
                    "bt_speaker": dev.bt_speaker,
                    "mic_status": dev.mic_status,
                    "inflator": dev.inflator,
                    "ext_cord": dev.ext_cord,
                    "modules": dev.modules,
                }
            async with aiofiles.open(_STATE_FILE, "w") as f:
                await f.write(json.dumps(data, indent=2))
        except Exception as err:  # pylint: disable=broad-except
            LOGGER.warning("Failed to persist state: %s", err)

    async def load_persisted(self) -> None:
        """Load state from JSON file into existing devices (updates known fields)."""
        if not os.path.exists(_STATE_FILE):
            return
        try:
            async with aiofiles.open(_STATE_FILE) as f:
                raw = await f.read()
            data: dict[str, Any] = json.loads(raw)
            for device_id, saved in data.items():
                dev = self._devices.get(device_id)
                if dev is None:
                    LOGGER.warning("Persisted state has unknown device %s, skipping", device_id)
                    continue
                for field_name, value in saved.items():
                    if field_name == "modules" and isinstance(value, dict) and value:
                        dev.modules.update(value)
                    elif hasattr(dev, field_name) and field_name not in ("device_id", "modules"):
                        setattr(dev, field_name, value)
            LOGGER.info("Loaded persisted state from %s", _STATE_FILE)
        except Exception as err:  # pylint: disable=broad-except
            LOGGER.warning("Failed to load persisted state: %s", err)
