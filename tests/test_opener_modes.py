"""Mode selection preserves legacy relay behavior without activating services."""
import pytest

from server.main import _load_config


@pytest.mark.parametrize("mode,relay,expected", [
    (None, False, "local"), (None, True, "cloud"),
    ("auto", True, "cloud"), ("auto", False, "local"),
    ("takeover", False, "takeover"), ("takeover", True, "cloud"),
    ("cloud", False, "cloud"), ("local", False, "local"),
])
def test_mode_selection_preserves_capture_override(mode, relay, expected, tmp_path, monkeypatch):
    from server.main import opener_mode

    monkeypatch.delenv("OPENER_MODE", raising=False)
    monkeypatch.delenv("OPENER_CLOUD_RELAY_IP", raising=False)
    config = {"cloud_relay": relay}
    if mode:
        config["opener_mode"] = mode
    assert opener_mode(config) == expected


def test_environment_mode_reaches_app_config(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENER_MODE", "takeover")
    monkeypatch.setenv("TTI_CLOUD_IP", "52.202.193.108")
    monkeypatch.delenv("OPENER_CLOUD_RELAY_IP", raising=False)
    config = _load_config(str(tmp_path / "absent.yaml"))
    assert config["opener_mode"] == "takeover"
    assert config["cloud_ip"] == "52.202.193.108"


def test_invalid_mode_fails_closed(monkeypatch):
    from server.main import opener_mode

    monkeypatch.delenv("OPENER_MODE", raising=False)
    monkeypatch.delenv("OPENER_CLOUD_RELAY_IP", raising=False)
    with pytest.raises(ValueError):
        opener_mode({"opener_mode": "typo"})
