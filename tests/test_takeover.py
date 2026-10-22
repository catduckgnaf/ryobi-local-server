"""Offline cloud/opener lifecycle fixtures. No external services are used."""
import asyncio
import json
from collections import deque
from contextlib import asynccontextmanager

import pytest
from aiohttp import WSMessage, WSMsgType

from server.models import GarageDoorState
from server.state import StateStore


class Socket:
    def __init__(self, messages=()):
        self.messages = deque(messages)
        self.sent = []
        self.closed = False

    async def receive(self):
        if self.messages:
            return self.messages.popleft()
        await asyncio.Event().wait()

    async def send_str(self, text):
        self.sent.append(json.loads(text))

    async def close(self, **kwargs):
        self.closed = True


def text(method, params=None):
    return WSMessage(WSMsgType.TEXT, json.dumps({"method": method, "params": params}), "")


def closed():
    return WSMessage(WSMsgType.CLOSE, None, "")


async def test_authorized_takeover_keeps_opener_and_uses_captured_command(tmp_path, monkeypatch):
    from server import state
    from server.takeover import run_takeover

    monkeypatch.setattr(state, "_STATE_FILE", str(tmp_path / "state.json"))
    store = StateStore()
    store.add_device(GarageDoorState(device_id="fixture"))
    opener = Socket([text("wskServerRegister")])
    cloud = Socket([text("authorizedWebSocket", {"authorized": True, "socketId": "cloud-fixture"})])
    task = asyncio.create_task(run_takeover(opener, cloud, "fixture", store, timeout=0.2))
    for _ in range(50):
        if store.is_device_ws(opener):
            break
        await asyncio.sleep(0)
    assert store.is_device_ws(opener)
    assert cloud.closed
    assert not opener.closed
    assert cloud.sent == [{"method": "wskServerRegister", "params": None}]
    assert opener.sent[0]["method"] == "authorizedWebSocket"
    assert await store.apply_command("fixture", "garageLight", "lightState", True)
    assert opener.sent[-1]["params"]["moduleMsg"] == "/wH///8="
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert opener.closed
    assert not store.is_device_ws(opener)


@pytest.mark.parametrize("messages", [
    [text("authorizedWebSocket", {"authorized": False})],
    [WSMessage(WSMsgType.TEXT, "not-json", "")],
    [text("authorizedWebSocket", {"authorized": "true"})],
    [text("authorizedWebSocket", {"authorized": True}), closed()],
    [closed()],
    [],
])
async def test_failed_registration_never_enables_control(messages):
    from server.takeover import run_takeover

    store = StateStore()
    store.add_device(GarageDoorState(device_id="fixture"))
    opener = Socket([text("wskServerRegister")])
    cloud = Socket(messages)
    await run_takeover(opener, cloud, "fixture", store, timeout=0.005)
    assert not store.is_device_ws(opener)
    assert opener.closed and cloud.closed


async def test_takeover_route_connects_expected_identity(aiohttp_client, monkeypatch, tmp_path):
    from server import state, takeover
    from server.app import create_app

    monkeypatch.setattr(state, "_STATE_FILE", str(tmp_path / "state.json"))
    cloud = Socket()
    seen = {}

    class Cloud(Socket):
        async def receive(self):
            while not self.sent:
                await asyncio.sleep(0)
            return text("authorizedWebSocket", {"authorized": True, "socketId": "fixture"})

    cloud = Cloud()

    @asynccontextmanager
    async def connect(headers, cloud_ip):
        seen.update(headers)
        assert cloud_ip == "192.0.2.20"
        yield cloud

    monkeypatch.setattr(takeover, "connect_cloud", connect)
    app = await create_app({"opener_mode": "takeover", "cloud_ip": "192.0.2.20",
                            "devices": [{"device_id": "fixture"}]})
    client = await aiohttp_client(app)
    ws = await client.ws_connect("/api/wsrpc", headers={
        "x-tc-varname": "fixture", "x-tc-apikey": "fixture-key",
        "x-tc-transform": "tti-gdo-rpc",
    })
    await ws.send_json({"method": "wskServerRegister", "params": None})
    assert (await ws.receive_json())["params"]["authorized"] is True
    for _ in range(50):
        if app["store"].is_device_ws(next(iter(app["store"]._device_sockets.values()), None)):
            break
        await asyncio.sleep(0)
    assert seen["x-tc-varname"] == "fixture"
    assert seen["x-tc-apikey"] == "fixture-key"
    assert cloud.closed
    assert await app["store"].apply_command("fixture", "garageLight", "lightState", True)
    assert (await ws.receive_json())["params"]["moduleMsg"] == "/wH///8="
    await ws.close()


async def test_initial_telemetry_is_retained_after_authorization(tmp_path, monkeypatch):
    from server import state
    from server.takeover import run_takeover

    monkeypatch.setattr(state, "_STATE_FILE", str(tmp_path / "state.json"))
    store = StateStore()
    device = GarageDoorState(device_id="fixture")
    store.add_device(device)
    opener = Socket([text("wifiClientStatusSet", {"rssi": -68, "ssid": "fixture-net"}),
                     text("wskServerRegister")])
    cloud = Socket([text("authorizedWebSocket", {"authorized": True, "socketId": "fixture"})])
    task = asyncio.create_task(run_takeover(opener, cloud, "fixture", store, timeout=0.2))
    for _ in range(100):
        if store.is_device_ws(opener):
            break
        await asyncio.sleep(0.001)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert device.wifi_rssi == -68
    assert device.wifi_ssid == "fixture-net"


async def test_takeover_disconnected_commands_never_echo(aiohttp_client, monkeypatch, tmp_path):
    from server import state
    from server.app import create_app

    monkeypatch.setattr(state, "_STATE_FILE", str(tmp_path / "state.json"))
    app = await create_app({"opener_mode": "takeover", "devices": [{"device_id": "fixture"}]})
    client = await aiohttp_client(app)
    ws = await client.ws_connect("/api/wsrpc")
    await ws.send_json({"method": "srvWebSocketAuth", "params": {
        "apiKey": "fixture-key", "varName": "fixture"}})
    await ws.receive_json()
    await ws.receive_json()
    assert not app["store"].is_device_ws(ws)
    assert not await app["store"].apply_command("fixture", "garageLight", "lightState", True)
    assert app["store"].get_device("fixture").light_state is False
    await ws.close()


async def test_opener_disconnect_finishes_takeover_and_unregisters(tmp_path, monkeypatch):
    from server import state
    from server.takeover import run_takeover

    monkeypatch.setattr(state, "_STATE_FILE", str(tmp_path / "state.json"))
    store = StateStore()
    store.add_device(GarageDoorState(device_id="fixture"))
    disconnected = asyncio.Event()

    class Opener(Socket):
        async def receive(self):
            if self.messages:
                return self.messages.popleft()
            await disconnected.wait()
            return closed()

    opener = Opener([text("wskServerRegister")])
    cloud = Socket([text("authorizedWebSocket", {"authorized": True, "socketId": "fixture"})])
    task = asyncio.create_task(run_takeover(opener, cloud, "fixture", store, timeout=0.2))
    for _ in range(100):
        if store.is_device_ws(opener):
            break
        await asyncio.sleep(0)
    assert store.is_device_ws(opener)
    disconnected.set()
    await asyncio.wait_for(task, timeout=0.2)
    assert not store.is_device_ws(opener)
    assert opener.closed and cloud.closed


@pytest.mark.parametrize("method", ["wskAttributeUpdateNtfy", "gdoModuleMsg", "gdoModuleState"])
async def test_ha_client_cannot_push_hardware_telemetry(aiohttp_client, monkeypatch, tmp_path, method):
    from server import state
    from server.app import create_app

    monkeypatch.setattr(state, "_STATE_FILE", str(tmp_path / "state.json"))
    app = await create_app({"opener_mode": "takeover", "devices": [{"device_id": "fixture"}]})
    client = await aiohttp_client(app)
    ws = await client.ws_connect("/api/wsrpc")
    await ws.send_json({"id": 1, "method": method, "params": {
        "varName": "fixture", "garageLight_7.lightState": {"value": 1}}})
    response = await ws.receive_json()
    assert "error" in response
    assert app["store"].get_device("fixture").light_state is False
    await ws.close()


async def test_unknown_identity_is_rejected():
    from server.takeover import run_takeover

    opener, cloud = Socket(), Socket()
    await run_takeover(opener, cloud, "unknown", StateStore(), timeout=0.005)
    assert opener.closed and cloud.closed
    assert not opener.sent and not cloud.sent


@pytest.mark.parametrize("headers", [
    {"x-tc-apikey": "fixture-key", "x-tc-transform": "tti-gdo-rpc"},
    {"x-tc-varname": "", "x-tc-apikey": "fixture-key", "x-tc-transform": "tti-gdo-rpc"},
    {"x-tc-varname": "fixture"},
    {"x-tc-varname": "fixture", "x-tc-transform": "tti-gdo-rpc"},
    {"x-tc-varname": "fixture", "x-tc-apikey": "fixture-key"},
])
async def test_partial_opener_headers_rejected_before_upgrade(aiohttp_client, monkeypatch, tmp_path, headers):
    from server import state
    from server.app import create_app

    monkeypatch.setattr(state, "_STATE_FILE", str(tmp_path / "state.json"))
    app = await create_app({"opener_mode": "takeover", "devices": [{"device_id": "fixture"}]})
    client = await aiohttp_client(app)
    with pytest.raises(Exception) as exc:
        await client.ws_connect("/api/wsrpc", headers=headers)
    assert getattr(exc.value, "status", None) == 403
    assert not app["store"]._takeover_sessions


async def test_header_free_ha_client_auth_preserved_without_physical_registration(aiohttp_client, monkeypatch, tmp_path):
    from server import state
    from server.app import create_app

    monkeypatch.setattr(state, "_STATE_FILE", str(tmp_path / "state.json"))
    app = await create_app({"opener_mode": "takeover", "devices": [{"device_id": "fixture"}]})
    client = await aiohttp_client(app)
    ws = await client.ws_connect("/api/wsrpc")
    await ws.send_json({"method": "srvWebSocketAuth", "params": {"apiKey": "fixture-key", "varName": "fixture"}})
    assert (await ws.receive_json())["params"]["authorized"] is True
    assert not app["store"].is_device_ws(ws)
    assert not await app["store"].apply_command("fixture", "garageLight", "lightState", True)
    await ws.close()
