"""Opt-in authenticated takeover; aiohttp owns framing, control and limits."""
from __future__ import annotations

import asyncio
import json
import logging
import socket
from contextlib import asynccontextmanager

import aiohttp

from aiohttp import WSMsgType
from aiohttp.abc import AbstractResolver

from .state import StateStore

LOGGER = logging.getLogger(__name__)
MAX_MESSAGE = 65536
CLOUD_HOST = "tti.tiwiconnect.com"


class CloudResolver(AbstractResolver):
    """Connect to the externally resolved IP without losing TLS host checking."""

    def __init__(self, ip):
        self.ip = ip

    async def resolve(self, host, port=0, family=socket.AF_INET):
        if host != CLOUD_HOST:
            raise OSError("unexpected upstream host")
        return [{"hostname": host, "host": self.ip, "port": port,
                 "family": socket.AF_INET, "proto": 0, "flags": 0}]

    async def close(self):
        pass


@asynccontextmanager
async def connect_cloud(headers: dict, cloud_ip: str):
    """Use the real cloud with verified TLS, bounded frames, no proxy or redirect."""
    import ipaddress

    address = ipaddress.IPv4Address(cloud_ip)
    if not address.is_global:
        raise ValueError("cloud IP must be a public IPv4 address")
    connector = aiohttp.TCPConnector(resolver=CloudResolver(str(address)), limit=1)
    async with aiohttp.ClientSession(
        connector=connector, trust_env=False,
        timeout=aiohttp.ClientTimeout(total=None, sock_connect=10),
    ) as session:
        async with session.ws_connect(
            f"wss://{CLOUD_HOST}/api/wsrpc", headers=headers,
            heartbeat=20, max_msg_size=MAX_MESSAGE, compress=0,
        ) as cloud:
            yield cloud


async def run_takeover(opener, cloud, device_id: str, store: StateStore, *, timeout: float = 10) -> None:
    """Relay registration, retain the opener only after explicit cloud approval.

    No unbounded queues: each receive is forwarded before reading the next.
    The cloud socket belongs exclusively to this session. Reconnection performs
    a new cloud authentication; an authentication failure never enables control.
    """
    registered = asyncio.Event()
    authenticated = asyncio.Event()
    tasks = []
    initial = []
    initial_bytes = 0

    async def from_opener():
        from .routes import _handle_opener_message

        nonlocal initial_bytes

        while True:
            message = await opener.receive()
            if message.type != WSMsgType.TEXT:
                return
            if len(message.data.encode("utf-8")) > MAX_MESSAGE:
                raise ValueError("opener message too large")
            payload = json.loads(message.data)
            if not isinstance(payload, dict):
                raise ValueError("invalid opener message")
            if not authenticated.is_set():
                initial_bytes += len(message.data.encode("utf-8"))
                if len(initial) >= 64 or initial_bytes > MAX_MESSAGE:
                    raise ValueError("opener registration limit exceeded")
                initial.append(message.data)
                await cloud.send_str(message.data)
                if payload.get("method") == "wskServerRegister":
                    registered.set()
            else:
                # Do not generate a second authorization event after takeover.
                if payload.get("method") != "wskServerRegister":
                    await _handle_opener_message(opener, message.data, device_id, store)

    async def from_cloud():
        count = 0
        while True:
            message = await cloud.receive()
            if message.type != WSMsgType.TEXT:
                raise ValueError("cloud closed before authorization")
            count += 1
            if count > 64 or len(message.data.encode("utf-8")) > MAX_MESSAGE:
                raise ValueError("cloud registration limit exceeded")
            payload = json.loads(message.data)
            if not isinstance(payload, dict):
                raise ValueError("invalid cloud message")
            if payload.get("method") == "authorizedWebSocket":
                params = payload.get("params")
                if not isinstance(params, dict) or params.get("authorized") is not True:
                    raise ValueError("cloud authorization rejected")
                if not isinstance(params.get("socketId"), str) or not params["socketId"]:
                    raise ValueError("cloud authorization missing socket ID")
                if not registered.is_set():
                    raise ValueError("cloud authorization preceded opener registration")
                await opener.send_str(message.data)
                authenticated.set()
                return
            await opener.send_str(message.data)

    try:
        if store.get_device(device_id) is None or device_id in store._device_sockets:
            return
        reader = asyncio.create_task(from_opener())
        auth = asyncio.create_task(from_cloud())
        tasks = [reader, auth]
        done, _ = await asyncio.wait(tasks, timeout=timeout, return_when=asyncio.FIRST_COMPLETED)
        if auth not in done or reader in done:
            return
        await auth  # Propagate malformed/denied registration.
        await cloud.close()
        from .routes import _handle_opener_message

        for raw in initial:
            if json.loads(raw).get("method") != "wskServerRegister":
                await _handle_opener_message(opener, raw, device_id, store)
        initial.clear()
        store.register_device_ws(device_id, opener)
        await reader
    except (ValueError, TypeError, OSError) as error:
        LOGGER.warning("Takeover ended for %s: %s", device_id, error)
    finally:
        store.unregister_device_ws(opener)
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await cloud.close()
        await opener.close()
