"""Diagnostics tests; no cloud or hardware."""

import unittest

from homeassistant.components.diagnostics import REDACTED

from custom_components.bsk_notus.diagnostics import redact_device_values


class DiagnosticsTests(unittest.TestCase):
    def test_redacts_identity_but_keeps_weekly_program(self):
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
            self.assertEqual(redacted[key], REDACTED)
        self.assertEqual(redacted["weeklyProgram"], values["weeklyProgram"])
        self.assertIs(redacted["programEnabled"], True)
        self.assertEqual(redacted["ventilatorFanSpeed"], 60)


if __name__ == "__main__":
    unittest.main()
