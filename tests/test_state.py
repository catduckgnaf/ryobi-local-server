"""Tests for the in-memory StateStore."""

from __future__ import annotations

import asyncio
import pytest

from server.models import GarageDoorState
from server.state import StateStore


@pytest.fixture
def store():
    s = StateStore()
    s.add_device(GarageDoorState(device_id="GDO_TEST001", device_name="Test Door"))
    s.add_device(GarageDoorState(device_id="GDO_TEST002", device_name="Test Door 2"))
    return s


# ---------------------------------------------------------------------------
# Basic state management
# ---------------------------------------------------------------------------

async def test_get_device_exists(store: StateStore):
    dev = store.get_device("GDO_TEST001")
    assert dev is not None
    assert dev.device_name == "Test Door"


async def test_get_device_missing(store: StateStore):
    assert store.get_device("GDO_MISSING") is None


async def test_list_devices(store: StateStore):
    devices = store.list_devices()
    assert len(devices) == 2


async def test_update_state_known_field(store: StateStore):
    result = await store.update_state("GDO_TEST001", {"door_state": "1"})
    assert result is True
    dev = store.get_device("GDO_TEST001")
    assert dev.door_state == "1"


async def test_update_state_multiple_fields(store: StateStore):
    result = await store.update_state("GDO_TEST001", {
        "door_state": "1",
        "light_state": True,
        "battery_level": 75,
    })
    assert result is True
    dev = store.get_device("GDO_TEST001")
    assert dev.door_state == "1"
    assert dev.light_state is True
    assert dev.battery_level == 75


async def test_update_state_unknown_device(store: StateStore):
    result = await store.update_state("GDO_MISSING", {"door_state": "1"})
    assert result is False


async def test_update_state_unknown_field(store: StateStore):
    # Should warn but not crash
    result = await store.update_state("GDO_TEST001", {"nonexistent_field": "value"})
    assert result is True  # device exists, update attempted


# ---------------------------------------------------------------------------
# apply_command
# ---------------------------------------------------------------------------

async def test_apply_command_light(store: StateStore):
    result = await store.apply_command("GDO_TEST001", "garageLight", "lightState", True)
    assert result is True
    dev = store.get_device("GDO_TEST001")
    assert dev.light_state is True


async def test_apply_command_light_off(store: StateStore):
    await store.update_state("GDO_TEST001", {"light_state": True})
    result = await store.apply_command("GDO_TEST001", "garageLight", "lightState", 0)
    assert result is True
    dev = store.get_device("GDO_TEST001")
    assert dev.light_state is False


async def test_apply_command_door_state(store: StateStore):
    result = await store.apply_command("GDO_TEST001", "garageDoor", "doorState", "1")
    assert result is True


async def test_apply_command_unknown_module(store: StateStore):
    result = await store.apply_command("GDO_TEST001", "unknown_module", "someAttr", True)
    assert result is False


async def test_two_fan_ports_stay_separate():
    """fan1/fan2 config keys are two ports, and a command names one of them."""
    store = StateStore()
    store.add_device(GarageDoorState(
        device_id="GDO_FANS",
        modules={"fan1": "fan_2", "fan2": "fan_5"},
    ))

    dev = store.get_device("GDO_FANS")
    dtm = dev.build_device_type_map()
    assert set(dtm) >= {"fan_2", "fan_5"}
    assert "fan1" not in dtm

    await store.apply_command("GDO_FANS", "fan", "speed", 3, port_id=5)
    dev = store.get_device("GDO_FANS")
    dtm = dev.build_device_type_map()
    assert dtm["fan_5"]["at"]["speed"]["value"] == 3
    assert dtm["fan_5"]["at"]["moduleState"]["value"] == 1
    assert dtm["fan_2"]["at"]["speed"]["value"] == 0

    await store.apply_command("GDO_FANS", "fan", "moduleState", 1, port_id=2)
    dev = store.get_device("GDO_FANS")
    dtm = dev.build_device_type_map()
    assert dtm["fan_2"]["at"]["moduleState"]["value"] == 1
    assert dtm["fan_2"]["at"]["speed"]["value"] == 1
    assert dtm["fan_5"]["at"]["speed"]["value"] == 3


# ---------------------------------------------------------------------------
# WebSocket client tracking
# ---------------------------------------------------------------------------

async def test_ws_client_add_remove(store: StateStore):
    # Use a simple mock object as "ws"
    class FakeWS:
        pass

    ws = FakeWS()
    store.add_ws_client(ws)
    assert ws in store._ws_clients

    store.remove_ws_client(ws)
    assert ws not in store._ws_clients


async def test_ws_remove_nonexistent(store: StateStore):
    # Should not raise
    store.remove_ws_client("not_a_real_client")


# ---------------------------------------------------------------------------
# Model: deviceTypeMap generation
# ---------------------------------------------------------------------------

async def test_build_device_type_map_defaults(store: StateStore):
    dev = store.get_device("GDO_TEST001")
    dtm = dev.build_device_type_map()
    # Should have garageDoor module
    assert any("garageDoor" in k for k in dtm)
    # doorState should be 0 (closed) by default
    door_key = next(k for k in dtm if "garageDoor" in k)
    assert dtm[door_key]["at"]["doorState"]["value"] == 0


async def test_build_device_type_map_with_light(store: StateStore):
    await store.update_state("GDO_TEST001", {"light_state": True})
    dev = store.get_device("GDO_TEST001")
    dtm = dev.build_device_type_map()
    light_key = next(k for k in dtm if "garageLight" in k)
    assert dtm[light_key]["at"]["lightState"]["value"] == 1


async def test_build_device_type_map_with_battery(store: StateStore):
    await store.update_state("GDO_TEST001", {"battery_level": 85})
    dev = store.get_device("GDO_TEST001")
    dtm = dev.build_device_type_map()
    charger_key = next(k for k in dtm if "backupCharger" in k)
    assert dtm[charger_key]["at"]["chargeLevel"]["value"] == 85
