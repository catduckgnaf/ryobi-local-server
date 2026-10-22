"""Release safety regressions, without opening listeners or using real DNS."""
import json
import logging
import subprocess
import tomllib
from pathlib import Path

import pytest

from server.main import _load_config

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("address", ["", "not-an-ip", "127.0.0.1", "192.168.250.26", "::1"])
def test_cloud_mode_rejects_invalid_upstream(address, tmp_path, monkeypatch):
    monkeypatch.setenv("OPENER_MODE", "cloud")
    monkeypatch.setenv("TTI_CLOUD_IP", address)
    monkeypatch.delenv("OPENER_CLOUD_RELAY_IP", raising=False)
    with pytest.raises(ValueError, match="public IPv4"):
        _load_config(str(tmp_path / "absent.yaml"))


def test_empty_relay_environment_never_selects_local(tmp_path, monkeypatch):
    monkeypatch.delenv("OPENER_MODE", raising=False)
    monkeypatch.setenv("OPENER_CLOUD_RELAY_IP", "")
    monkeypatch.setenv("TTI_CLOUD_IP", "")
    with pytest.raises(ValueError, match="public IPv4"):
        _load_config(str(tmp_path / "absent.yaml"))


def test_addon_dns_failure_stops_before_python_launch():
    source = (ROOT / "ryobi_gdo_local/run.sh").read_text()
    section = source[source.index('TTI_CLOUD_IP="$('):source.index('MAIN_PID=$!')]
    harness = '''
set -e
nslookup() { return 1; }
bashio::config() { printf auto; }
bashio::config.true() { return 0; }
bashio::log.warning() { :; }
bashio::log.fatal() { :; }
python3() { printf PYTHON_STARTED; }
''' + section
    result = subprocess.run(["bash", "-c", harness], capture_output=True, text=True)
    assert result.returncode != 0
    assert "PYTHON_STARTED" not in result.stdout


async def test_wifi_info_logs_exclude_network_identifiers(tmp_path, monkeypatch, caplog):
    from server import state
    from server.models import GarageDoorState
    from server.routes import _handle_opener_message
    from server.state import StateStore

    monkeypatch.setattr(state, "_STATE_FILE", str(tmp_path / "state.json"))
    store = StateStore()
    store.add_device(GarageDoorState(device_id="fixture"))
    payload = json.dumps({"method": "wifiClientStatusSet", "params": {
        "ssid": "private-fixture-network", "ipAddr": "192.168.250.99", "rssi": -68}})
    with caplog.at_level(logging.INFO):
        await _handle_opener_message(None, payload, "fixture", store)
    assert "private-fixture-network" not in caplog.text
    assert "192.168.250.99" not in caplog.text
    assert store.get_device("fixture").wifi_ssid == "private-fixture-network"


def test_package_declares_tls_bridge_dependency():
    config = tomllib.loads((ROOT / "pyproject.toml").read_text())
    assert "tlslite-ng>=0.8.2" in config["project"]["dependencies"]
