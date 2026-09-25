"""Diagnostics support for BSK NOTUS."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from homeassistant.components.diagnostics import REDACTED, async_redact_data
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant

from .coordinator import BSKNotusConfigEntry

# Diagnostics are intentionally read-only. Keep cloud/device identifiers and
# account/network metadata out, while retaining device configuration fields
# (including any native weekly-program data returned by BSK Connect).
_TO_REDACT = {
    CONF_USERNAME,
    CONF_PASSWORD,
    "accessToken",
    "token",
    "deviceID",
    "mbDeviceId",
    "_id",
    "userID",
    "userId",
    "ownerID",
    "ownerId",
    "groupID",
    "groupId",
    "email",
    "ssid",
    "wifiSSID",
    "wifiSsid",
    "wifiPassword",
    "password",
    "mac",
    "macAddress",
    "serial",
    "serialNumber",
}


def redact_device_values(values: Mapping[str, Any]) -> dict[str, Any]:
    """Return a recursively redacted copy of a raw BSK device payload."""
    return async_redact_data(dict(values), _TO_REDACT)


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant,
    entry: BSKNotusConfigEntry,
) -> dict[str, Any]:
    """Return redacted config and raw cloud device values for diagnostics."""
    coordinator = entry.runtime_data
    devices: dict[str, Any] = {}

    for index, device in enumerate(coordinator.data.values(), start=1):
        devices[f"device_{index}"] = {
            "name": device.name,
            "model": device.model,
            "device_type": device.device_type,
            "values": redact_device_values(device.values),
        }

    entry_data = async_redact_data(
        entry.as_dict(),
        {CONF_USERNAME, CONF_PASSWORD, "unique_id"},
    )
    # Defensive belt-and-braces: diagnostics must never include login secrets.
    if entry_data.get("data"):
        entry_data["data"][CONF_USERNAME] = REDACTED
        entry_data["data"][CONF_PASSWORD] = REDACTED

    return {
        "config_entry": entry_data,
        "devices": devices,
    }
