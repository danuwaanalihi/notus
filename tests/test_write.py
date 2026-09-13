"""Safety and HA runtime tests using synthetic payloads; no cloud or hardware."""

import asyncio
from copy import deepcopy
import unittest
from unittest.mock import AsyncMock, Mock, patch

from aiohttp import ClientError
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError

from custom_components.bsk_notus.api import (
    BSKNotusAuthError,
    BSKNotusClient,
    BSKNotusConnectionError,
    BSKNotusResponseError,
    BSKNotusSyncError,
    notus_device_from_payload,
)
from custom_components.bsk_notus.controls import CONTROLS, supports_control
from custom_components.bsk_notus.coordinator import BSKNotusCoordinator
from custom_components.bsk_notus.number import BSKNotusNumber
from custom_components.bsk_notus.switch import BSKNotusSwitch
from custom_components.bsk_notus.sensor import SENSORS, BSKNotusSensor
from custom_components.bsk_notus.binary_sensor import BINARY_SENSORS
from custom_components.bsk_notus import number, switch

GOOGLE_SYNC_ERROR = (
    "Device ID cannot be found. This is usually an indication that the device "
    "may have been removed. Send a Request Sync to re-sync the device in Google."
)


def device(**changes):
    """Synthetic device, deliberately carrying unrelated fields."""
    values = {
        "deviceID": "test-device",
        "deviceModel": "BSK-IGK-LCD-V1.0",
        "__t": "IGKLCDV10Device",
        "deviceStatus": 1,
        "manualBoostState": 0,
        "ventilatorFanSpeed": 40,
        "aspiratorFanSpeed": 40,
        "setTemperature": 210,
        "setHumidity": 70,
        "opMode": "CS",
        "retCo2Ppm": -1,
    }
    values.update(changes)
    return notus_device_from_payload({"title": "Test NOTUS", "device": values})


class Response:
    def __init__(self, status=200, body=None, error=None):
        self.status, self.body, self.error = status, body, error

    async def __aenter__(self):
        if self.error:
            raise self.error
        return self

    async def __aexit__(self, *args):
        pass

    async def json(self, **kwargs):
        return deepcopy(self.body)


class ApiTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.session = Mock()
        self.session.put.return_value = Response()
        self.client = BSKNotusClient(self.session, "test@example.invalid", "test")
        self.client._token = "synthetic-token"

    async def test_exact_endpoint_sparse_integer_payload_and_authorization(self):
        for key, raw in {"deviceStatus": 1, "manualBoostState": 0,
                         "ventilatorFanSpeed": 41, "aspiratorFanSpeed": 41,
                         "setTemperature": 215, "setHumidity": 71}.items():
            await self.client.async_write_control("test-device", key, raw)
            args, kwargs = self.session.put.call_args
            self.assertEqual(args, ("https://connect.bskhvac.com.tr/device",))
            self.assertEqual(kwargs["params"], {"deviceID": "test-device"})
            self.assertEqual(kwargs["json"], {key: raw})
            self.assertEqual(kwargs["headers"], {"Authorization": "synthetic-token"})
            self.assertFalse(kwargs["allow_redirects"])
            self.assertEqual(kwargs["timeout"].total, 20)

    async def test_invalid_or_unconfirmed_fields_never_reach_cloud(self):
        for key, raw in [("opMode", 1), ("freeCooling", 2),
                         ("setTemperature", 149), ("setTemperature", 301),
                         ("setTemperature", 215.5), ("deviceStatus", True),
                         ("manualBoostState", 2), ("setHumidity", -1),
                         ("ventilatorFanSpeed", 101), ("aspiratorFanSpeed", -1)]:
            with self.subTest(key=key, raw=raw), self.assertRaises(BSKNotusResponseError):
                await self.client.async_write_control("test-device", key, raw)
        with self.assertRaises(BSKNotusResponseError):
            await self.client.async_write_control("", "setTemperature", 210)
        self.session.put.assert_not_called()

    async def test_timeout_connection_rejection_and_redirect_are_not_retried(self):
        for response, error in [(Response(error=TimeoutError()), BSKNotusConnectionError),
                                (Response(error=ClientError()), BSKNotusConnectionError),
                                (Response(status=403), BSKNotusResponseError),
                                (Response(status=500), BSKNotusResponseError),
                                (Response(status=302), BSKNotusResponseError),
                                (Response(status=401), BSKNotusAuthError)]:
            self.session.put.reset_mock()
            self.session.put.return_value = response
            with self.assertRaises(error):
                await self.client.async_write_control("test-device", "setTemperature", 215)
            self.session.put.assert_called_once()
        self.assertIsNone(self.client._token)

    async def test_read_layer_still_normalizes_and_refreshes_token(self):
        original = device().values
        self.session.get.side_effect = [Response(401), Response(body=[{"device": original}])]
        self.session.post.return_value = Response(body={"accessToken": "new-token"})
        result = await self.client.async_list_notus_devices()
        self.assertEqual(result[0].values, original)
        self.assertEqual(result[0].value("retCo2Ppm"), -1)
        self.assertEqual(self.session.get.call_count, 2)
        self.assertEqual(self.session.get.call_args.kwargs["headers"], {"Authorization": "new-token"})
        self.session.put.assert_not_called()

    async def test_write_rejection_keeps_status_and_redacts_server_message(self):
        self.session.put.return_value = Response(status=400, body={
            "message": ["setTemperature is invalid", "synthetic-token test-device test@example.invalid"],
            "unrelated": "must not be exposed",
        })
        with self.assertRaises(BSKNotusResponseError) as raised:
            await self.client.async_write_control("test-device", "setTemperature", 215)
        message = str(raised.exception)
        self.assertIn("HTTP 400: setTemperature is invalid", message)
        self.assertNotIn("synthetic-token", message)
        self.assertNotIn("test-device", message)
        self.assertNotIn("test@example.invalid", message)
        self.assertNotIn("must not be exposed", message)

    async def test_only_exact_google_sync_http_400_is_classified(self):
        for status, body, expected in [
            (400, {"message": GOOGLE_SYNC_ERROR}, BSKNotusSyncError),
            (400, {"message": [GOOGLE_SYNC_ERROR]}, BSKNotusSyncError),
            (400, {"error": GOOGLE_SYNC_ERROR}, BSKNotusSyncError),
            (503, {"message": GOOGLE_SYNC_ERROR}, BSKNotusResponseError),
            (403, {"message": GOOGLE_SYNC_ERROR}, BSKNotusResponseError),
            (400, {"message": "Device ID cannot be found."}, BSKNotusResponseError),
            (400, {"message": [GOOGLE_SYNC_ERROR, "invalid value"]}, BSKNotusResponseError),
            (400, {"message": {"detail": GOOGLE_SYNC_ERROR}}, BSKNotusResponseError),
        ]:
            with self.subTest(status=status, body=body):
                self.session.put.reset_mock()
                self.session.put.return_value = Response(status=status, body=body)
                with self.assertRaises(BSKNotusResponseError) as raised:
                    await self.client.async_write_control("test-device", "ventilatorFanSpeed", 60)
                self.assertIs(type(raised.exception), expected)
                self.session.put.assert_called_once()


class ControlTests(unittest.TestCase):
    def test_ranges_scaling_and_invalid_numbers(self):
        temp = CONTROLS["setTemperature"]
        for native, raw in [(15.0, 150), (21.0, 210), (21.5, 215), (21.1, 211), (30, 300)]:
            self.assertEqual(temp.to_raw(native), raw)
        for invalid in [14.9, 30.1, 21.55, float("nan"), float("inf"), True, "21.5"]:
            with self.subTest(value=invalid), self.assertRaises(ValueError):
                temp.to_raw(invalid)
        for key in ["ventilatorFanSpeed", "aspiratorFanSpeed", "setHumidity"]:
            for raw in [0, 100]:
                self.assertEqual(CONTROLS[key].to_raw(raw), raw)
            with self.assertRaises(ValueError):
                CONTROLS[key].to_raw(40.5)

    def test_missing_invalid_field_wrong_model_and_fallback_id_disable_control(self):
        control = CONTROLS["setTemperature"]
        self.assertTrue(supports_control(device(), control))
        for changes in [{"setTemperature": None}, {"setTemperature": "nan"},
                        {"setTemperature": True}, {"setTemperature": 210.2},
                        {"deviceModel": "BSK-IGK-LCD-V2.0"}, {"__t": "OtherDevice"},
                        {"deviceID": None, "mbDeviceId": "fallback-id"}]:
            self.assertFalse(supports_control(device(**changes), control))
        self.assertEqual(control.raw_value("215"), 215)


class CoordinatorTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.hass = HomeAssistant("/tmp/bsk-notus-unit-tests")
        self.client = Mock()
        self.client.async_list_notus_devices = AsyncMock(return_value=[device()])
        self.client.async_write_control = AsyncMock()
        self.entry = Mock()
        self.coordinator = BSKNotusCoordinator(self.hass, self.entry, self.client)
        self.coordinator.data = {"test-device": device()}
        self.delay_patch = patch("custom_components.bsk_notus.coordinator.READ_BACK_DELAY", 0)
        self.delay_patch.start()
        self.addCleanup(self.delay_patch.stop)

    async def asyncTearDown(self):
        await self.coordinator.async_shutdown()
        await self.hass.async_stop()

    async def test_stale_read_back_then_confirmation_updates_all_entities(self):
        before, after = device(), device(setTemperature=215)
        self.client.async_list_notus_devices.side_effect = [[before], [before], [after]]
        entity = BSKNotusNumber(self.coordinator, before, CONTROLS["setTemperature"])
        published = []
        self.coordinator.async_update_listeners = lambda: published.append(entity.native_value)
        await entity.async_set_native_value(21.5)
        self.assertEqual(published, [21.5])
        self.assertEqual(entity.native_value, 21.5)
        self.assertEqual(entity.native_min_value, 15.0)
        self.assertEqual(entity.native_max_value, 30.0)
        self.assertEqual(entity.native_step, 0.1)
        self.assertEqual(self.coordinator.data["test-device"].value("aspiratorFanSpeed"), 40)
        self.client.async_write_control.assert_awaited_once_with("test-device", "setTemperature", 215)

    async def test_unconfirmed_write_keeps_actual_cloud_value_and_reports_error(self):
        with self.assertRaisesRegex(HomeAssistantError, "did not confirm"):
            await self.coordinator.async_set_control("test-device", "setTemperature", 215)
        self.assertEqual(self.coordinator.data["test-device"].value("setTemperature"), 210)
        self.assertTrue(self.coordinator.last_update_success)
        self.assertEqual(self.client.async_list_notus_devices.await_count, 5)
        self.client.async_write_control.assert_awaited_once()

    async def test_timeout_after_applied_write_reads_actual_state_without_resend(self):
        self.client.async_write_control.side_effect = BSKNotusConnectionError("uncertain")
        self.client.async_list_notus_devices.side_effect = [[device()], [device(setTemperature=215)]]
        with self.assertRaisesRegex(HomeAssistantError, "uncertain"):
            await self.coordinator.async_set_control("test-device", "setTemperature", 215)
        self.assertEqual(self.coordinator.data["test-device"].value("setTemperature"), 215)
        self.client.async_write_control.assert_awaited_once()

    async def test_http_rejection_still_reads_back(self):
        self.client.async_write_control.side_effect = BSKNotusResponseError("HTTP 403")
        with self.assertRaisesRegex(HomeAssistantError, "HTTP 403"):
            await self.coordinator.async_set_control("test-device", "setTemperature", 215)
        self.assertEqual(self.client.async_list_notus_devices.await_count, 5)
        self.assertEqual(self.coordinator.data["test-device"].value("setTemperature"), 210)

    async def test_google_sync_error_with_exact_read_back_confirms_without_resend(self):
        before, after = device(), device(ventilatorFanSpeed=60)
        self.client.async_write_control.side_effect = BSKNotusSyncError(GOOGLE_SYNC_ERROR)
        self.client.async_list_notus_devices.side_effect = [[before], [before], [after]]
        entity = BSKNotusNumber(self.coordinator, before, CONTROLS["ventilatorFanSpeed"])
        published = []
        self.coordinator.async_update_listeners = lambda: published.append(entity.native_value)
        await entity.async_set_native_value(60)
        self.assertEqual(published, [60])
        self.assertTrue(entity.available)
        self.assertEqual(self.coordinator.data["test-device"].value("aspiratorFanSpeed"), 40)
        self.client.async_write_control.assert_awaited_once_with("test-device", "ventilatorFanSpeed", 60)

    async def test_google_sync_error_with_different_value_still_fails(self):
        self.client.async_write_control.side_effect = BSKNotusSyncError(GOOGLE_SYNC_ERROR)
        self.client.async_list_notus_devices.side_effect = [[device()]] + [[device(ventilatorFanSpeed=60)]] * 4
        with self.assertRaisesRegex(HomeAssistantError, "write failed"):
            await self.coordinator.async_set_control("test-device", "ventilatorFanSpeed", 41)
        self.assertEqual(self.coordinator.data["test-device"].value("ventilatorFanSpeed"), 60)
        self.assertTrue(self.coordinator.last_update_success)
        self.assertEqual(self.client.async_list_notus_devices.await_count, 5)
        self.client.async_write_control.assert_awaited_once()

    async def test_unknown_http_error_with_matching_read_back_still_fails(self):
        self.client.async_write_control.side_effect = BSKNotusResponseError("HTTP 400: invalid value")
        self.client.async_list_notus_devices.side_effect = [[device()], [device(ventilatorFanSpeed=60)]]
        with self.assertRaisesRegex(HomeAssistantError, "HTTP 400: invalid value"):
            await self.coordinator.async_set_control("test-device", "ventilatorFanSpeed", 60)
        self.assertEqual(self.coordinator.data["test-device"].value("ventilatorFanSpeed"), 60)
        self.client.async_write_control.assert_awaited_once()

    async def test_failed_read_back_marks_state_unavailable(self):
        self.client.async_write_control.side_effect = BSKNotusSyncError(GOOGLE_SYNC_ERROR)
        self.client.async_list_notus_devices.side_effect = [[device()]] + [BSKNotusConnectionError("offline")] * 4
        entity = BSKNotusNumber(self.coordinator, device(), CONTROLS["setTemperature"])
        with self.assertRaisesRegex(HomeAssistantError, "Cannot confirm"):
            await entity.async_set_native_value(21.5)
        self.assertFalse(entity.available)
        self.assertEqual(entity.native_value, 21.0)
        self.client.async_write_control.assert_awaited_once()

    async def test_missing_device_or_control_during_preflight_never_writes(self):
        for payload in [[], [device(deviceID=None, mbDeviceId="test-device")],
                        [device(setTemperature=None)], [device(deviceModel="other")]]:
            self.client.async_list_notus_devices.return_value = payload
            with self.assertRaisesRegex(HomeAssistantError, "unavailable"):
                await self.coordinator.async_set_control("test-device", "setTemperature", 215)
        self.client.async_write_control.assert_not_called()

    async def test_auth_failure_starts_reauth_and_releases_lock(self):
        self.client.async_list_notus_devices.side_effect = BSKNotusAuthError("expired")
        with self.assertRaises(HomeAssistantError):
            await self.coordinator.async_set_control("test-device", "setTemperature", 215)
        self.entry.async_start_reauth_if_available.assert_called_once_with(self.hass)
        self.assertFalse(self.coordinator._io_lock.locked())
        self.client.async_write_control.assert_not_called()

    async def test_parallel_writes_and_poll_wait_for_read_back(self):
        current = device().values.copy()
        events = []
        put_started, release_put = asyncio.Event(), asyncio.Event()

        async def read():
            events.append(("read", current["setTemperature"], current["setHumidity"]))
            return [device(**current)]

        async def write(identity, key, raw):
            events.append(("write", key, raw))
            if key == "setTemperature":
                put_started.set()
                await release_put.wait()
            current[key] = raw

        self.client.async_list_notus_devices.side_effect = read
        self.client.async_write_control.side_effect = write
        first = asyncio.create_task(self.coordinator.async_set_control("test-device", "setTemperature", 215))
        await put_started.wait()
        second = asyncio.create_task(self.coordinator.async_set_control("test-device", "setHumidity", 71))
        poll = asyncio.create_task(self.coordinator.async_refresh())
        await asyncio.sleep(0)
        self.assertEqual(len(events), 2)
        self.assertEqual(self.coordinator.data["test-device"].value("setTemperature"), 210)
        release_put.set()
        await asyncio.gather(first, second, poll)
        self.assertEqual(events, [("read", 210, 70), ("write", "setTemperature", 215),
                                  ("read", 215, 70), ("read", 215, 70),
                                  ("write", "setHumidity", 71), ("read", 215, 71),
                                  ("read", 215, 71)])
        self.assertEqual(self.coordinator.data["test-device"].value("setHumidity"), 71)
        self.assertEqual(self.coordinator.data["test-device"].value("setTemperature"), 215)

    async def test_switch_uses_integer_bool_and_confirmed_state(self):
        entity = BSKNotusSwitch(self.coordinator, device(), CONTROLS["manualBoostState"])
        self.assertFalse(entity.is_on)
        self.client.async_list_notus_devices.side_effect = [[device()], [device(manualBoostState=1)]]
        await entity.async_turn_on()
        self.assertTrue(entity.is_on)
        self.client.async_write_control.assert_awaited_once_with("test-device", "manualBoostState", 1)
        self.client.async_list_notus_devices.side_effect = [[device(manualBoostState=1)], [device()]]
        await entity.async_turn_off()
        self.assertFalse(entity.is_on)

    async def test_cancellation_releases_lock_and_disables_unconfirmed_state(self):
        started = asyncio.Event()

        async def write(*args):
            started.set()
            await asyncio.Event().wait()

        self.client.async_write_control.side_effect = write
        task = asyncio.create_task(self.coordinator.async_set_control("test-device", "setTemperature", 215))
        await started.wait()
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertFalse(self.coordinator._io_lock.locked())
        self.assertFalse(self.coordinator.last_update_success)

    async def test_six_controls_and_original_read_semantics(self):
        self.entry.runtime_data = self.coordinator
        added = []
        await number.async_setup_entry(self.hass, self.entry, added.extend)
        await switch.async_setup_entry(self.hass, self.entry, added.extend)
        self.assertEqual(len(added), 6)
        self.assertEqual(len({entity.unique_id for entity in added}), 6)
        self.assertEqual(len(SENSORS) + len(BINARY_SENSORS), 28)
        sensors = {d.translation_key: BSKNotusSensor(self.coordinator, device(), d) for d in SENSORS}
        self.assertEqual(sensors["target_temperature"].native_value, 21.0)
        self.assertFalse(sensors["return_co2"].available)
        self.assertEqual(sensors["operation_mode"].native_value, "CS")
        readonly_ids = {f"test-device_{d.key}" for d in (*SENSORS, *BINARY_SENSORS)}
        self.assertFalse(readonly_ids.intersection(e.unique_id for e in added))


if __name__ == "__main__":
    unittest.main()
