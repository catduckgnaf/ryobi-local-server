"""Regression fixtures from the sanitized October 21 opener capture."""
import base64
import json

import pytest

from server.models import GarageDoorState
from server.state import StateStore


class Socket:
    closed = False

    def __init__(self):
        self.messages = []

    async def send_str(self, message):
        self.messages.append(json.loads(message))


@pytest.mark.parametrize("value,encoded", [(True, "/wH///8="), (False, "/wD///8=")])
async def test_light_uses_captured_bytes_without_echoing_state(value, encoded):
    store = StateStore()
    device = GarageDoorState(device_id="fixture", light_state=not value)
    store.add_device(device)
    socket = Socket()
    store.register_device_ws("fixture", socket)

    assert await store.apply_command("fixture", "garageLight", "lightState", value)
    assert socket.messages[-1]["params"] == {
        "msgType": 16, "moduleType": 5, "portId": 7,
        "moduleMsg": encoded, "topic": "fixture",
    }
    assert device.light_state is not value  # only telemetry may change state


async def test_captured_light_status_reaches_ha(tmp_path, monkeypatch):
    from server import state
    from server.routes import _handle_opener_message

    monkeypatch.setattr(state, "_STATE_FILE", str(tmp_path / "state.json"))
    store = StateStore()
    device = GarageDoorState(device_id="fixture")
    store.add_device(device)
    ha = Socket()
    store.add_ws_client(ha)
    status = bytearray([0xfe] * 14)
    status[3] = 1
    await _handle_opener_message(Socket(), json.dumps({
        "method": "srvSetModuleStatus", "params": {
            "msgType": 17, "moduleType": 5, "portId": 7,
            "moduleMsg": base64.b64encode(status).decode(),
        },
    }), "fixture", store)
    assert device.light_state is True
    assert ha.messages[-1]["method"] == "wskAttributeUpdateNtfy"
    assert ha.messages[-1]["params"]["garageLight_7.lightState"] == {"value": 1}


@pytest.mark.parametrize("index,value,expected", [
    (5, 1, {"door_state": "1", "door_state_raw": 1, "door_moving": False}),
    (5, 3, {"door_state": "unknown", "door_state_raw": 3, "door_moving": True}),
    (5, 0, {"door_state": "unknown", "door_state_raw": 0, "door_moving": False}),
    (9, 94, {"door_position": 94}),
])
async def test_sparse_door_status_never_infers_unknown_states(index, value, expected, tmp_path, monkeypatch):
    from server import state

    monkeypatch.setattr(state, "_STATE_FILE", str(tmp_path / "state.json"))
    store = StateStore()
    device = GarageDoorState(device_id="fixture", light_state=True)
    store.add_device(device)
    data = bytearray([0xfe] * 14)
    data[index] = value
    await store.handle_device_push("fixture", {
        "msgType": 17, "moduleType": 5, "portId": 7,
        "moduleMsg": base64.b64encode(data).decode(),
    })
    for field, wanted in expected.items():
        assert getattr(device, field, "missing") == wanted
    assert device.light_state is True
    # Building the HA representation must also tolerate unknown direction/state.
    dtm = device.build_device_type_map()
    if expected.get("door_state") == "unknown":
        assert dtm["garageDoor_7"]["at"]["doorState"]["value"] is None


@pytest.mark.parametrize("module_type,port,data,field,expected", [
    (6, 8, b"\x64", "battery_level", 100),
    (1, 3, b"\x01", "park_assist", True),
])
async def test_captured_accessory_status(module_type, port, data, field, expected, tmp_path, monkeypatch):
    from server import state

    monkeypatch.setattr(state, "_STATE_FILE", str(tmp_path / "state.json"))
    store = StateStore()
    device = GarageDoorState(device_id="fixture", battery_level=None)
    store.add_device(device)
    await store.handle_device_push("fixture", {
        "msgType": 17, "moduleType": module_type, "portId": port,
        "moduleMsg": base64.b64encode(data).decode(),
    })
    assert getattr(device, field) == expected


async def test_wifi_push_updates_state(tmp_path, monkeypatch):
    from server import state
    from server.routes import _handle_opener_message

    monkeypatch.setattr(state, "_STATE_FILE", str(tmp_path / "state.json"))
    store = StateStore()
    device = GarageDoorState(device_id="fixture")
    store.add_device(device)
    await _handle_opener_message(Socket(), json.dumps({
        "method": "wifiClientStatusSet", "params": {
            "rssi": -68, "ssid": "fixture-network", "ipAddr": "192.0.2.10",
        },
    }), "fixture", store)
    assert device.wifi_rssi == -68
    assert getattr(device, "wifi_ssid", None) == "fixture-network"


@pytest.mark.parametrize("module,attr,value,encoded", [
    ("garageDoor", "doorState", "1", "////Af8="),
    ("garageDoor", "doorState", "0", None),
    ("garageDoor", "vacationMode", True, None),
    ("fan", "speed", 3, None),
])
async def test_only_captured_commands_are_forwarded(module, attr, value, encoded):
    store = StateStore()
    device = GarageDoorState(device_id="fixture")
    store.add_device(device)
    socket = Socket()
    store.register_device_ws("fixture", socket)
    result = await store.apply_command("fixture", module, attr, value)
    assert result is (encoded is not None)
    assert len(socket.messages) == (1 if encoded else 0)
    if encoded:
        assert socket.messages[0]["params"]["moduleMsg"] == encoded
    assert device.door_state == "0"
    assert device.fan_speed == 0
