"""Data models for the Ryobi GDO local server emulator."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class GarageDoorState:
    """Current state of a single garage door / GDO device."""

    device_id: str
    device_name: str = "Ryobi GDO"

    # Core door state: "0"=closed, "1"=open, "2"=closing, "3"=opening, "4"=fault
    door_state: str = "0"

    # Accessory states
    light_state: bool = False
    battery_level: int | None = None   # percentage, None if no backup charger
    wifi_rssi: int | None = None        # dBm, None if unknown
    safety: bool = False                # safety sensor blocked
    motion: bool = False                # motion sensor
    vacation_mode: bool = False
    park_assist: bool = False
    bt_speaker: bool = False
    mic_status: bool = False
    inflator: bool = False

    # Modules present on this device (module_name -> key_in_deviceTypeMap)
    modules: dict[str, str] = field(default_factory=dict)

    def to_ha_data(self) -> dict[str, Any]:
        """Return flat dict matching what the HA integration reads from coordinator.data."""
        return {
            "door_state": self.door_state,
            "light_state": self.light_state,
            "battery_level": self.battery_level,
            "wifi_rssi": self.wifi_rssi,
            "safety": self.safety,
            "motion": self.motion,
            "vacationMode": self.vacation_mode,
            "park_assist": self.park_assist,
            "bt_speaker": self.bt_speaker,
            "micStatus": self.mic_status,
            "inflator": self.inflator,
            "device_name": self.device_name,
        }

    def build_device_type_map(self) -> dict[str, Any]:
        """
        Build the deviceTypeMap structure that the HA integration parses.

        The integration indexes modules by scanning deviceTypeMap keys for known
        module names (garageDoor, garageLight, etc.). Keys look like:
        "garageDoor_7": {"at": {"doorState": {"value": 0}, ...}}
        """
        dtm: dict[str, Any] = {}

        # --- garageDoor module ---
        door_key = self.modules.get("garageDoor", "garageDoor_7")
        dtm[door_key] = {
            "at": {
                "doorState": {"value": int(self.door_state)},
                "sensorFlag": {"value": 1 if self.safety else 0},
                "vacationMode": {"value": 1 if self.vacation_mode else 0},
                "motionSensor": {"value": 1 if self.motion else 0},
            }
        }

        # --- garageLight module ---
        if "garageLight" in self.modules or self.light_state is not None:
            light_key = self.modules.get("garageLight", "garageLight_7")
            dtm[light_key] = {
                "at": {
                    "lightState": {"value": 1 if self.light_state else 0},
                }
            }

        # --- backupCharger (battery) ---
        if self.battery_level is not None:
            charger_key = self.modules.get("backupCharger", "backupCharger_6")
            dtm[charger_key] = {
                "at": {
                    "chargeLevel": {"value": self.battery_level},
                }
            }

        # --- wifiModule ---
        if self.wifi_rssi is not None:
            wifi_key = self.modules.get("wifiModule", "wifiModule_7")
            dtm[wifi_key] = {
                "at": {
                    "rssi": {"value": self.wifi_rssi},
                }
            }

        # --- parkAssistLaser ---
        if "parkAssistLaser" in self.modules or self.park_assist:
            laser_key = self.modules.get("parkAssistLaser", "parkAssistLaser_1")
            dtm[laser_key] = {
                "at": {
                    "moduleState": {"value": 1 if self.park_assist else 0},
                }
            }

        # --- inflator ---
        if "inflator" in self.modules or self.inflator:
            inf_key = self.modules.get("inflator", "inflator_4")
            dtm[inf_key] = {
                "at": {
                    "moduleState": {"value": 1 if self.inflator else 0},
                }
            }

        # --- btSpeaker ---
        if "btSpeaker" in self.modules or self.bt_speaker:
            spk_key = self.modules.get("btSpeaker", "btSpeaker_2")
            dtm[spk_key] = {
                "at": {
                    "moduleState": {"value": 1 if self.bt_speaker else 0},
                    "micEnable": {"value": 1 if self.mic_status else 0},
                }
            }

        return dtm

    def build_device_result(self) -> dict[str, Any]:
        """Return a full device result entry as returned by GET /api/devices/<id>."""
        return {
            "varName": self.device_id,
            "metaData": {
                "name": self.device_name,
                "sys": {"productName": "GD200"},
            },
            "deviceTypeMap": self.build_device_type_map(),
        }

    def build_list_entry(self) -> dict[str, Any]:
        """Return a minimal list entry as returned by GET /api/devices."""
        return {
            "varName": self.device_id,
            "metaData": {
                "name": self.device_name,
                "sys": {"productName": "GD200"},
            },
        }
