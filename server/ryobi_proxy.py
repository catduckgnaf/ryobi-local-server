"""
Optional background task that polls the real Ryobi cloud for device state
and mirrors it into the local StateStore.

Set RYOBI_CLOUD_POLL=false (or cloud_poll: false in config) to disable.
This is useful as a "best of both worlds" approach: local server stays current
even without a reed switch or other local sensor.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

import aiohttp

from .state import StateStore

LOGGER = logging.getLogger(__name__)

HOST_URI = "tti.tiwiconnect.com"
LOGIN_ENDPOINT = "api/login"
DEVICE_GET_ENDPOINT = "api/devices"
REQUEST_TIMEOUT = 10

DOOR_STATE_MAP = {
    "0": "0",  # closed
    "1": "1",  # open
    "2": "2",  # closing
    "3": "3",  # opening
    "4": "4",  # fault
}


class RyobiCloudProxy:
    """Polls the real Ryobi cloud and syncs state into the local store."""

    def __init__(
        self,
        store: StateStore,
        username: str,
        password: str,
        poll_interval: int = 30,
    ) -> None:
        """Initialize the cloud proxy."""
        self.store = store
        self.username = username
        self.password = password
        self.poll_interval = poll_interval
        self._api_key: str | None = None
        self._session: aiohttp.ClientSession | None = None
        self._running = False
        self._task: asyncio.Task | None = None

    async def start(self) -> None:
        """Start the background polling loop."""
        self._running = True
        connector = aiohttp.TCPConnector(ssl=True)
        self._session = aiohttp.ClientSession(connector=connector)
        self._task = asyncio.create_task(self._loop())
        LOGGER.info("Cloud proxy started (poll interval: %ds)", self.poll_interval)

    async def stop(self) -> None:
        """Stop the background polling loop."""
        self._running = False
        if self._task:
            self._task.cancel()
        if self._session:
            await self._session.close()
        LOGGER.info("Cloud proxy stopped")

    async def _loop(self) -> None:
        """Main polling loop."""
        while self._running:
            try:
                await self._poll()
            except asyncio.CancelledError:
                break
            except Exception as err:  # pylint: disable=broad-except
                LOGGER.warning("Cloud poll error: %s", err)
            await asyncio.sleep(self.poll_interval)

    async def _poll(self) -> None:
        """Poll once: get API key if needed, then fetch each device's state."""
        if self._api_key is None:
            self._api_key = await self._get_api_key()
            if self._api_key is None:
                LOGGER.error("Cloud proxy: failed to get API key, will retry")
                return

        for device in self.store.list_devices():
            await self._fetch_device(device.device_id)

    async def _get_api_key(self) -> str | None:
        """Authenticate with Ryobi and return API key."""
        url = f"https://{HOST_URI}/{LOGIN_ENDPOINT}"
        data = {"username": self.username, "password": self.password}
        resp = await self._http_post(url, data)
        if resp is None:
            return None
        try:
            return resp["result"]["metaData"]["wskAuthAttempts"][0]["apiKey"]
        except (KeyError, IndexError, TypeError) as err:
            LOGGER.error("Cloud proxy: failed to parse API key: %s", err)
            return None

    async def _fetch_device(self, device_id: str) -> None:
        """Fetch and apply state for one device."""
        url = f"https://{HOST_URI}/{DEVICE_GET_ENDPOINT}/{device_id}"
        data = {"username": self.username, "password": self.password}
        resp = await self._http_get(url, data)
        if resp is None:
            return

        try:
            result_list = resp.get("result", [])
            if not result_list:
                return
            first = result_list[0]
            dtm: dict[str, Any] = first.get("deviceTypeMap", {})
            updates: dict[str, Any] = {}

            for key, module_data in dtm.items():
                at = module_data.get("at", {})
                if "garageDoor" in key:
                    if "doorState" in at:
                        updates["door_state"] = str(at["doorState"].get("value", "0"))
                    if "sensorFlag" in at:
                        updates["safety"] = bool(at["sensorFlag"].get("value", 0))
                    if "vacationMode" in at:
                        updates["vacation_mode"] = bool(at["vacationMode"].get("value", 0))
                    if "motionSensor" in at:
                        updates["motion"] = bool(at["motionSensor"].get("value", 0))
                elif "garageLight" in key:
                    if "lightState" in at:
                        updates["light_state"] = bool(at["lightState"].get("value", 0))
                elif "backupCharger" in key:
                    if "chargeLevel" in at:
                        updates["battery_level"] = at["chargeLevel"].get("value")
                elif "wifiModule" in key:
                    if "rssi" in at:
                        updates["wifi_rssi"] = at["rssi"].get("value")
                elif "parkAssistLaser" in key:
                    if "moduleState" in at:
                        updates["park_assist"] = bool(at["moduleState"].get("value", 0))
                elif "inflator" in key:
                    if "moduleState" in at:
                        updates["inflator"] = bool(at["moduleState"].get("value", 0))
                elif "btSpeaker" in key:
                    if "moduleState" in at:
                        updates["bt_speaker"] = bool(at["moduleState"].get("value", 0))
                    if "micEnable" in at:
                        updates["mic_status"] = bool(at["micEnable"].get("value", 0))

            if updates:
                await self.store.update_state(device_id, updates)
                LOGGER.debug("Cloud sync applied %d updates for %s", len(updates), device_id)

        except Exception as err:  # pylint: disable=broad-except
            LOGGER.warning("Cloud proxy: failed to parse device %s: %s", device_id, err)

    async def _http_get(self, url: str, params: dict) -> dict | None:
        """HTTP GET with timeout."""
        if not self._session:
            return None
        try:
            async with asyncio.timeout(REQUEST_TIMEOUT):
                async with self._session.get(url, params=params) as resp:
                    text = await resp.text()
                    return json.loads(text)
        except Exception as err:  # pylint: disable=broad-except
            LOGGER.warning("HTTP GET %s failed: %s", url, err)
            return None

    async def _http_post(self, url: str, data: dict) -> dict | None:
        """HTTP POST with timeout."""
        if not self._session:
            return None
        try:
            async with asyncio.timeout(REQUEST_TIMEOUT):
                async with self._session.post(url, data=data) as resp:
                    text = await resp.text()
                    return json.loads(text)
        except Exception as err:  # pylint: disable=broad-except
            LOGGER.warning("HTTP POST %s failed: %s", url, err)
            return None
