"""Data models for the Ryobi GDO local server emulator."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


def fan_module_keys(modules: dict[str, Any] | None) -> list[str]:
    """Return one deviceTypeMap key per configured fan.

    ``fan: fan_3`` is one fan. ``fan1: fan_2`` and ``fan2: fan_5`` are two.
    The name only has to start with ``fan``. The value is the port key the
    integration reads, and the number after the underscore is the port.
    """
    found: list[str] = []
    for name, raw in (modules or {}).items():
        if not isinstance(name, str) or not name.lower().startswith("fan"):
            continue
        key = str(raw).strip()
        if not key:
            continue
        if not key.lower().startswith("fan"):
            key = f"fan_{key}"
        if key not in found:
            found.append(key)
    return found


@dataclass
class GarageDoorState:
    """Current state of a single garage door / GDO device."""

    device_id: str
    device_name: str = "Ryobi GDO"

    # Core door state: "0"=closed, "1"=open, "2"=closing, "3"=opening, "4"=fault
    door_state: str = "0"
    door_state_raw: int | None = None
    door_moving: bool = False
    door_position: int = 1
    max_door_position: int = 93
    motor_status: int = 1

    # Accessory states
    light_state: bool = False
    battery_level: int | None = 100    # percentage, default 100 for backup charger
    wifi_ssid: str | None = None
    wifi_rssi: int | None = -55        # dBm, default strong signal
    safety: bool = False                # safety sensor blocked
    motion: bool = False                # motion sensor
    vacation_mode: bool = False
    park_assist: bool = False
    bt_speaker: bool = False
    mic_status: bool = False
    inflator: bool = False
    ext_cord: bool = True
    fan: bool = False
    fan_speed: int = 0
    # One entry per fan port, keyed by the deviceTypeMap name (fan_2, fan_5).
    fans: dict[str, dict[str, int]] = field(default_factory=dict)
    camera_state: bool = True
    camera_recording: bool = False
    camera_image_url: str = ""

    # Modules present on this device (module_name -> key_in_deviceTypeMap)
    modules: dict[str, str] = field(default_factory=dict)

    def to_ha_data(self) -> dict[str, Any]:
        """Return flat dict matching what the HA integration reads from coordinator.data."""
        return {
            "door_state": self.door_state,
            "door_position": self.door_position,
            "max_door_position": self.max_door_position,
            "motor_status": self.motor_status,
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
            "ext_cord": self.ext_cord,
            "fan": self.fan,
            "fan_speed": self.fan_speed,
            "camera_state": self.camera_state,
            "camera_recording": self.camera_recording,
            "camera_image_url": self.camera_image_url,
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
        door_key = (self.modules or {}).get("garageDoor", "garageDoor_7")
        dtm[door_key] = {
            "at": {
                "doorState": {"value": int(self.door_state) if self.door_state in ("0", "1", "2", "3", "4") else None},
                "doorPosition": {"value": self.door_position},
                "maxDoorPosition": {"value": self.max_door_position},
                "motorStatus": {"value": self.motor_status},
                "sensorFlag": {"value": 1 if self.safety else 0},
                "vacationMode": {"value": 1 if self.vacation_mode else 0},
                "motionSensor": {"value": 1 if self.motion else 0},
            }
        }

        # --- garageLight module ---
        light_key = (self.modules or {}).get("garageLight", "garageLight_7")
        dtm[light_key] = {
            "at": {
                "lightState": {"value": 1 if self.light_state else 0},
            }
        }

        # --- backupCharger (battery) ---
        charger_key = (self.modules or {}).get("backupCharger", "backupCharger_8")
        dtm[charger_key] = {
            "at": {
                "chargeLevel": {"value": self.battery_level if self.battery_level is not None else 100},
            }
        }

        # --- wifiModule ---
        wifi_key = (self.modules or {}).get("wifiModule", "wifiModule_9")
        dtm[wifi_key] = {
            "at": {
                "rssi": {"value": self.wifi_rssi if self.wifi_rssi is not None else -55},
            }
        }

        # --- extCord ---
        ext_key = (self.modules or {}).get("extCord", "extCord_4")
        dtm[ext_key] = {
            "at": {},
            "metaData": {
                "name": "Extension Cord",
                "description": "Extension Cord Module",
                "icon": "/img/profiles/extension_cord.png",
            },
        }

        # --- parkAssistLaser ---
        laser_key = (self.modules or {}).get("parkAssistLaser", "parkAssistLaser_1")
        dtm[laser_key] = {
            "at": {
                "moduleState": {"value": 1 if self.park_assist else 0},
            }
        }

        # --- inflator ---
        inf_key = (self.modules or {}).get("inflator", "inflator_4")
        dtm[inf_key] = {
            "at": {
                "moduleState": {"value": 1 if self.inflator else 0},
            }
        }

        # --- btSpeaker ---
        spk_key = (self.modules or {}).get("btSpeaker", "btSpeaker_2")
        dtm[spk_key] = {
            "at": {
                "moduleState": {"value": 1 if self.bt_speaker else 0},
                "micEnable": {"value": 1 if self.mic_status else 0},
            }
        }

        # --- fans (one entry per configured port) ---
        fan_keys = fan_module_keys(self.modules)
        for index, fan_key in enumerate(fan_keys):
            stored = self.fans.get(fan_key) or {}
            if stored:
                state = int(stored.get("moduleState", 0) or 0)
                speed = int(stored.get("speed", 0) or 0)
            elif index == 0:
                state = 1 if self.fan else 0
                speed = int(self.fan_speed or 0)
            else:
                state = 0
                speed = 0
            dtm[fan_key] = {
                "at": {
                    "moduleState": {"value": state},
                    "speed": {"value": speed if state else 0},
                }
            }

        # --- camera ---
        cam_key = (self.modules or {}).get("camera", "securityCamera_1")
        if "camera" in (self.modules or {}) or "securityCamera" in (self.modules or {}):
            dtm[cam_key] = {
                "at": {
                    "moduleState": {"value": 1 if self.camera_state else 0},
                    "recordingState": {"value": 1 if self.camera_recording else 0},
                    "streamUrl": {"value": f"/api/camera/{self.device_id}/live"},
                },
                "metaData": {
                    "moduleId": 9,
                    "name": "Security Camera",
                    "icon": "/img/profiles/camera.png",
                },
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
