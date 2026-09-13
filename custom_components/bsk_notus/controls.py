"""Verified NOTUS user controls and configurable fan presets, in cloud units.

Protocol evidence is recorded in docs/write-protocol.md. Keep this allowlist
separate from discovery: a readable device is not necessarily safe to control.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .api import NotusDevice


@dataclass(frozen=True, slots=True)
class NotusControl:
    """One sparse cloud field and its validated raw range."""

    key: str
    translation_key: str
    minimum: int
    maximum: int
    scale: int = 1
    is_switch: bool = False
    step: int = 1
    is_config: bool = False
    percentage_mode: bool = False

    def raw_value(self, value: Any) -> int | None:
        """Parse a cloud value without rounding, clamping or assuming zero."""
        if isinstance(value, bool):
            return int(value) if self.is_switch else None
        if not isinstance(value, (int, float, str)):
            return None
        try:
            number = float(value)
        except (ValueError, OverflowError):
            return None
        if not isfinite(number) or not number.is_integer():
            return None
        raw = int(number)
        return raw if self.minimum <= raw <= self.maximum else None

    def valid_write(self, raw: Any) -> bool:
        """Enforce write steps separately from parsing existing cloud state."""
        return (
            type(raw) is int
            and self.raw_value(raw) is not None
            and (raw - self.minimum) % self.step == 0
        )

    def to_raw(self, value: float) -> int:
        """Convert HA units to raw units, rejecting invalid service input."""
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError("A numeric control value is required")
        scaled = value * self.scale
        if not isfinite(scaled) or abs(scaled - round(scaled)) > 1e-7:
            raise ValueError("Value does not match the control step")
        raw = round(scaled)
        if not self.minimum <= raw <= self.maximum:
            raise ValueError("Control value is outside the supported range")
        if not self.valid_write(raw):
            raise ValueError("Value does not match the control step")
        return raw


FAN_PRESET_FIELDS = {
    "ventilatorFanSpeed": {
        "night": "venFanNightSpeed",
        "low": "venFanLowSpeed",
        "medium": "venFanMediumSpeed",
        "high": "venFanHighSpeed",
        "boost": "venFanBoostSpeed",
    },
    "aspiratorFanSpeed": {
        "night": "aspFanNightSpeed",
        "low": "aspFanLowSpeed",
        "medium": "aspFanMediumSpeed",
        "high": "aspFanHighSpeed",
        "boost": "aspFanBoostSpeed",
    },
}
FAN_NAMES = {"ventilatorFanSpeed": "supply", "aspiratorFanSpeed": "extract"}
FREE_COOLING_OPTIONS = {"off": 0, "on": 1, "auto": 2}
FREE_COOLING_CONTROL = NotusControl("freeCoolingSetting", "free_cooling_mode", 0, 2)
PRESET_NUMBER_CONTROLS = tuple(
    NotusControl(
        field, f"{FAN_NAMES[fan]}_{preset}_speed", 0, 100,
        is_config=True, percentage_mode=True,
    )
    for fan, fields in FAN_PRESET_FIELDS.items()
    for preset, field in fields.items()
)

SWITCH_CONTROLS = (
    NotusControl("deviceStatus", "power", 0, 1, is_switch=True),
    NotusControl("manualBoostState", "manual_boost", 0, 1, is_switch=True),
)
NUMBER_CONTROLS = (
    NotusControl("ventilatorFanSpeed", "supply_fan_speed", 0, 100, percentage_mode=True),
    NotusControl("aspiratorFanSpeed", "extract_fan_speed", 0, 100, percentage_mode=True),
    NotusControl("setTemperature", "target_temperature", 150, 300, scale=10, step=10),
    NotusControl("setHumidity", "target_humidity", 0, 100),
    *PRESET_NUMBER_CONTROLS,
)
CONTROLS = {
    control.key: control
    for control in (*SWITCH_CONTROLS, *NUMBER_CONTROLS, FREE_COOLING_CONTROL)
}


def supports_control(device: NotusDevice, control: NotusControl) -> bool:
    """Require the verified model, actual deviceID and a valid existing field."""
    device_id = device.value("deviceID")
    return (
        device.model == "BSK-IGK-LCD-V1.0"
        and device.device_type == "IGKLCDV10Device"
        and isinstance(device_id, str)
        and bool(device_id.strip())
        and device_id == device.identity
        and (not control.percentage_mode or device.value("opMode") == "CS")
        and control.raw_value(device.value(control.key)) is not None
    )


def fan_preset_values(device: NotusDevice, fan_key: str) -> dict[str, int] | None:
    """Read all five percentages; never substitute default or cached values."""
    fields = FAN_PRESET_FIELDS.get(fan_key)
    if fields is None or not supports_control(device, CONTROLS[fan_key]):
        return None
    values: dict[str, int] = {}
    for preset, field in fields.items():
        control = CONTROLS[field]
        if not supports_control(device, control):
            return None
        raw = control.raw_value(device.value(field))
        assert raw is not None
        values[preset] = raw
    return values
