"""Tests for HTTP route handlers."""

from __future__ import annotations

import json
import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from server.app import create_app


DEVICE_ID = "GDO_TEST00001"

BASE_CONFIG = {
    "username": "test@example.com",
    "password": "testpass",
    "enforce_token": False,
    "cloud_poll": False,
    "devices": [
        {
            "device_id": DEVICE_ID,
            "name": "Test Garage",
        }
    ],
}


@pytest.fixture
async def client(aiohttp_client):
    app = await create_app(BASE_CONFIG)
    return await aiohttp_client(app)


# ---------------------------------------------------------------------------
# Login
# ---------------------------------------------------------------------------

async def test_login_success(client):
    resp = await client.post("/api/login", data={"username": "test@example.com", "password": "testpass"})
    assert resp.status == 200
    data = await resp.json()
    assert "result" in data
    assert "wskAuthAttempts" in data["result"]["metaData"]
    api_key = data["result"]["metaData"]["wskAuthAttempts"][0]["apiKey"]
    assert len(api_key) == 64  # 32 bytes hex


async def test_login_no_credentials(client):
    """With enforce_token=False and no expected credentials, any login succeeds."""
    resp = await client.post("/api/login", data={"username": "anyone", "password": "anything"})
    assert resp.status == 200


# ---------------------------------------------------------------------------
# Device list
# ---------------------------------------------------------------------------

async def test_get_devices(client):
    resp = await client.get("/api/devices")
    assert resp.status == 200
    data = await resp.json()
    result = data["result"]
    assert isinstance(result, list)
    assert len(result) == 1
    assert result[0]["varName"] == DEVICE_ID


# ---------------------------------------------------------------------------
# Device detail
# ---------------------------------------------------------------------------

async def test_get_device_detail(client):
    resp = await client.get(f"/api/devices/{DEVICE_ID}")
    assert resp.status == 200
    data = await resp.json()
    result = data["result"]
    assert len(result) == 1
    assert result[0]["varName"] == DEVICE_ID
    dtm = result[0]["deviceTypeMap"]
    # Should have at least garageDoor module
    assert any("garageDoor" in k for k in dtm)


async def test_get_device_detail_unknown(client):
    resp = await client.get("/api/devices/GDO_UNKNOWN")
    assert resp.status == 200
    data = await resp.json()
    assert data["result"] == []


# ---------------------------------------------------------------------------
# State webhook
# ---------------------------------------------------------------------------

async def test_state_get(client):
    resp = await client.get("/state")
    assert resp.status == 200
    data = await resp.json()
    assert DEVICE_ID in data
    assert "door_state" in data[DEVICE_ID]


async def test_state_post_update(client):
    payload = {"device_id": DEVICE_ID, "door_state": "1", "light_state": True}
    resp = await client.post("/state", json=payload)
    assert resp.status == 200
    data = await resp.json()
    assert data["result"] == "OK"

    # Verify state changed
    resp2 = await client.get("/state")
    state = (await resp2.json())[DEVICE_ID]
    assert state["door_state"] == "1"
    assert state["light_state"] is True


async def test_state_post_unknown_device(client):
    payload = {"device_id": "GDO_DOESNOTEXIST", "door_state": "1"}
    resp = await client.post("/state", json=payload)
    assert resp.status == 404


async def test_state_post_missing_device_id(client):
    payload = {"door_state": "1"}
    resp = await client.post("/state", json=payload)
    assert resp.status == 400


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------

async def test_health(client):
    resp = await client.get("/health")
    assert resp.status == 200
    data = await resp.json()
    assert data["status"] == "ok"
