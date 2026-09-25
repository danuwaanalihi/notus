"""Diagnostics support for BSK NOTUS."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from homeassistant.components.diagnostics import REDACTED, async_redact_data
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant

from .api import BSKNotusError
from .coordinator import BSKNotusConfigEntry

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

# Read-only protocol discovery only. These names are derived from the BSK
# Connect "Weekly Schedule" UI/resource vocabulary. Diagnostics never write.
_SCHEDULE_READ_CANDIDATES = (
    "/schedule",
    "/schedule-user",
    "/weekly-schedule",
    "/weekly-schedule-user",
    "/program",
    "/program-user",
    "/weekly-program",
    "/weekly-program-user",
    "/device-schedule",
    "/device-program",
)


def redact_payload(value: Any) -> Any:
    """Recursively redact common identity/account/network fields."""
    return async_redact_data(value, _TO_REDACT)


def redact_device_values(values: Mapping[str, Any]) -> dict[str, Any]:
    """Return a recursively redacted copy of a raw BSK device payload."""
    return redact_payload(dict(values))


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant,
    entry: BSKNotusConfigEntry,
) -> dict[str, Any]:
    """Return redacted cloud data plus read-only schedule-route discovery."""
    coordinator = entry.runtime_data
    devices: dict[str, Any] = {}
    schedule_probe: dict[str, Any] = {}

    for index, device in enumerate(coordinator.data.values(), start=1):
        devices[f"device_{index}"] = {
            "name": device.name,
            "model": device.model,
            "device_type": device.device_type,
            "values": redact_device_values(device.values),
        }

        # Probe only the first supported device. Every request is GET-only and
        # uses the same verified deviceID that the app uses for device control.
        if not schedule_probe:
            for path in _SCHEDULE_READ_CANDIDATES:
                try:
                    status, body = await coordinator.client.async_read_path_for_diagnostics(
                        path, params={"deviceID": device.identity}
                    )
                    schedule_probe[path] = {
                        "status": status,
                        "body": redact_payload(body),
                    }
                except BSKNotusError as err:
                    schedule_probe[path] = {
                        "error": type(err).__name__,
                        "detail": str(err)[:200],
                    }

    entry_data = async_redact_data(
        entry.as_dict(),
        {CONF_USERNAME, CONF_PASSWORD, "unique_id"},
    )
    if entry_data.get("data"):
        entry_data["data"][CONF_USERNAME] = REDACTED
        entry_data["data"][CONF_PASSWORD] = REDACTED

    return {
        "config_entry": entry_data,
        "devices": devices,
        "schedule_read_probe": schedule_probe,
    }
