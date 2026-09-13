"""The six verified NOTUS user controls, in cloud units.

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
        return raw


SWITCH_CONTROLS = (
    NotusControl("deviceStatus", "power", 0, 1, is_switch=True),
    NotusControl("manualBoostState", "manual_boost", 0, 1, is_switch=True),
)
NUMBER_CONTROLS = (
    NotusControl("ventilatorFanSpeed", "supply_fan_speed", 0, 100),
    NotusControl("aspiratorFanSpeed", "extract_fan_speed", 0, 100),
    NotusControl("setTemperature", "target_temperature", 150, 300, scale=10),
    NotusControl("setHumidity", "target_humidity", 0, 100),
)
CONTROLS = {control.key: control for control in (*SWITCH_CONTROLS, *NUMBER_CONTROLS)}


def supports_control(device: NotusDevice, control: NotusControl) -> bool:
    """Require the verified model, actual deviceID and a valid existing field."""
    device_id = device.value("deviceID")
    return (
        device.model == "BSK-IGK-LCD-V1.0"
        and device.device_type == "IGKLCDV10Device"
        and isinstance(device_id, str)
        and bool(device_id.strip())
        and device_id == device.identity
        and control.raw_value(device.value(control.key)) is not None
    )
