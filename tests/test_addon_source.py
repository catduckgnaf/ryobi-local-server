"""The add-on build context must ship the source exercised by tests."""
from pathlib import Path


def test_addon_ships_identical_server_source():
    root = Path(__file__).resolve().parents[1]
    source = root / "server"
    bundled = root / "ryobi_gdo_local" / "server"
    for path in source.glob("*.py"):
        assert (bundled / path.name).read_bytes() == path.read_bytes(), path.name
