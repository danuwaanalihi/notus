"""Diagnostics tests; no cloud or hardware."""

from homeassistant.components.diagnostics import REDACTED

from custom_components.bsk_notus.diagnostics import redact_device_values


def test_diagnostics_redact_identity_but_keep_weekly_program():
    values = {
        "deviceID": "production-device-id",
        "mbDeviceId": "bridge-id",
        "_id": "db-id",
        "email": "owner@example.invalid",
        "wifiSSID": "private-network",
        "accessToken": "secret-token",
        "weeklyProgram": {
            "monday": [
                {"time": "06:30", "mode": "medium"},
                {"time": "23:00", "mode": "night"},
            ]
        },
        "programEnabled": True,
        "ventilatorFanSpeed": 60,
    }

    redacted = redact_device_values(values)

    for key in ("deviceID", "mbDeviceId", "_id", "email", "wifiSSID", "accessToken"):
        assert redacted[key] == REDACTED
    assert redacted["weeklyProgram"] == values["weeklyProgram"]
    assert redacted["programEnabled"] is True
    assert redacted["ventilatorFanSpeed"] == 60
