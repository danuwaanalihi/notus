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
from custom_components.bsk_notus.controls import (
    CONTROLS, FAN_PRESET_FIELDS, FREE_COOLING_CONTROL, fan_preset_values, supports_control,
)
from custom_components.bsk_notus.coordinator import BSKNotusCoordinator, READ_BACK_DELAYS
from custom_components.bsk_notus.number import BSKNotusNumber
from custom_components.bsk_notus.switch import BSKNotusSwitch
from custom_components.bsk_notus.sensor import SENSORS, BSKNotusSensor
from custom_components.bsk_notus.binary_sensor import BINARY_SENSORS
from custom_components.bsk_notus import number, select, switch
from custom_components.bsk_notus.select import BSKNotusFanPreset, BSKNotusFreeCooling

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
    for fields in FAN_PRESET_FIELDS.values():
        values.update(zip(fields.values(), (20, 40, 60, 80, 100)))
    values.update({"freeCoolingSetting": 2, "freeCoolingStatus": 1})
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
                         "setTemperature": 220, "setHumidity": 71,
                         "freeCoolingSetting": 2, "venFanMediumSpeed": 61,
                         "aspFanNightSpeed": 23}.items():
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
                         ("freeCoolingStatus", 1), ("freeCoolingSetting", 3),
                         ("setTemperature", 215), ("venFanLowSpeed", 101),
                         ("setTemperature", 149), ("setTemperature", 301),
                         ("setTemperature", 220.5), ("deviceStatus", True),
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
                await self.client.async_write_control("test-device", "setTemperature", 220)
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
            await self.client.async_write_control("test-device", "setTemperature", 220)
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
    def test_temperature_read_scaling_survives_whole_degree_write_step(self):
        control = CONTROLS["setTemperature"]
        self.assertEqual(control.raw_value(215), 215)
        self.assertFalse(control.valid_write(215))
        self.assertTrue(control.valid_write(220))

    def test_presets_require_cloud_values_and_percentage_mode_without_defaults(self):
        custom = device(venFanNightSpeed=0, venFanLowSpeed=33, venFanMediumSpeed=61)
        self.assertEqual(fan_preset_values(custom, "ventilatorFanSpeed"), {
            "night": 0, "low": 33, "medium": 61, "high": 80, "boost": 100,
        })
        for changes in [{"venFanLowSpeed": None}, {"venFanLowSpeed": True},
                        {"venFanLowSpeed": 101}, {"opMode": "CF"}, {"opMode": None}]:
            self.assertIsNone(fan_preset_values(device(**changes), "ventilatorFanSpeed"))
        self.assertFalse(supports_control(device(opMode="CF"), CONTROLS["venFanLowSpeed"]))

    def test_ranges_scaling_and_invalid_numbers(self):
        temp = CONTROLS["setTemperature"]
        for native, raw in [(15.0, 150), (21.0, 210), (22.0, 220), (30, 300)]:
            self.assertEqual(temp.to_raw(native), raw)
        for invalid in [14.9, 30.1, 21.55, 21.5, 21.1, float("nan"), float("inf"), True, "22.0"]:
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
        self.assertEqual(control.raw_value("220"), 220)


class CoordinatorTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.hass = HomeAssistant("/tmp/bsk-notus-unit-tests")
        self.client = Mock()
        self.client.async_list_notus_devices = AsyncMock(return_value=[device()])
        self.client.async_write_control = AsyncMock()
        self.entry = Mock()
        self.coordinator = BSKNotusCoordinator(self.hass, self.entry, self.client)
        self.coordinator.data = {"test-device": device()}
        self.delay_patch = patch("custom_components.bsk_notus.coordinator.READ_BACK_DELAYS", (0,) * 4)
        self.delay_patch.start()
        self.addCleanup(self.delay_patch.stop)

    async def asyncTearDown(self):
        await self.coordinator.async_shutdown()
        await self.hass.async_stop()

    async def test_temperature_fraction_and_unconfigured_fan_value_never_write(self):
        entity = BSKNotusNumber(self.coordinator, device(), CONTROLS["setTemperature"])
        with self.assertRaises(HomeAssistantError):
            await entity.async_set_native_value(21.5)
        with self.assertRaises(HomeAssistantError):
            await self.coordinator.async_set_control("test-device", "setTemperature", 215)
        with self.assertRaisesRegex(HomeAssistantError, "configured fan percentage"):
            await self.coordinator.async_set_control("test-device", "ventilatorFanSpeed", 41)
        self.client.async_write_control.assert_not_called()

    async def test_preset_uses_fresh_device_configuration_and_confirmed_state(self):
        entity = BSKNotusFanPreset(self.coordinator, device(), "ventilatorFanSpeed")
        self.assertEqual(entity.current_option, "low")
        before = device(venFanMediumSpeed=63)
        after = device(venFanMediumSpeed=63, ventilatorFanSpeed=63)
        self.client.async_list_notus_devices.side_effect = [[before], [after]]
        await entity.async_select_option("medium")
        self.client.async_write_control.assert_awaited_once_with("test-device", "ventilatorFanSpeed", 63)
        self.assertEqual(entity.current_option, "medium")
        self.assertEqual(entity.extra_state_attributes["preset_percentages"]["medium"], 63)

    async def test_queued_preset_waits_for_configuration_write_before_resolving(self):
        values = device().values.copy()
        started, release = asyncio.Event(), asyncio.Event()
        writes = []

        async def read():
            return [device(**values)]

        async def write(identity, key, raw):
            writes.append((key, raw))
            if key == "aspFanMediumSpeed":
                started.set()
                await release.wait()
            values[key] = raw

        self.client.async_list_notus_devices.side_effect = read
        self.client.async_write_control.side_effect = write
        edit = asyncio.create_task(self.coordinator.async_set_control("test-device", "aspFanMediumSpeed", 61))
        await started.wait()
        choose = asyncio.create_task(self.coordinator.async_set_fan_preset("test-device", "aspiratorFanSpeed", "medium"))
        await asyncio.sleep(0)
        self.assertEqual(writes, [("aspFanMediumSpeed", 61)])
        release.set()
        await asyncio.gather(edit, choose)
        self.assertEqual(writes, [("aspFanMediumSpeed", 61), ("aspiratorFanSpeed", 61)])
        self.assertEqual(self.coordinator.data["test-device"].value("ventilatorFanSpeed"), 40)

    async def test_preset_unknown_duplicate_and_missing_values_are_not_guessed(self):
        entity = BSKNotusFanPreset(self.coordinator, device(), "ventilatorFanSpeed")
        for state in [device(ventilatorFanSpeed=41), device(venFanMediumSpeed=40)]:
            self.coordinator.data = {"test-device": state}
            self.assertIsNone(entity.current_option)
        self.client.async_list_notus_devices.return_value = [device(venFanLowSpeed=None)]
        with self.assertRaisesRegex(HomeAssistantError, "unavailable"):
            await entity.async_select_option("low")
        self.assertFalse(entity.available)
        with self.assertRaisesRegex(HomeAssistantError, "Invalid"):
            await entity.async_select_option("turbo")
        self.client.async_write_control.assert_not_called()

    async def test_free_cooling_changes_setting_not_running_status(self):
        entity = BSKNotusFreeCooling(self.coordinator, device())
        self.assertEqual(entity.current_option, "auto")
        for option, raw in [("off", 0), ("on", 1), ("auto", 2)]:
            self.client.async_list_notus_devices.side_effect = [[device()], [device(freeCoolingSetting=raw)]]
            await entity.async_select_option(option)
            self.assertEqual(entity.current_option, option)
            self.assertEqual(self.coordinator.data["test-device"].value("freeCoolingStatus"), 1)
            self.client.async_write_control.assert_awaited_with("test-device", "freeCoolingSetting", raw)
        with self.assertRaisesRegex(HomeAssistantError, "Invalid"):
            await entity.async_select_option("summer")
        self.coordinator.data = {"test-device": device(freeCoolingSetting=None)}
        self.assertFalse(entity.available)

    async def test_late_confirmation_succeeds_without_replaying_write(self):
        before, after = device(), device(ventilatorFanSpeed=60)
        self.client.async_write_control.side_effect = BSKNotusSyncError(GOOGLE_SYNC_ERROR)
        self.client.async_list_notus_devices.side_effect = [[before]] * 11 + [[after]]
        with patch("custom_components.bsk_notus.coordinator.READ_BACK_DELAYS", READ_BACK_DELAYS), \
             patch("custom_components.bsk_notus.coordinator.asyncio.sleep", new_callable=AsyncMock) as pause:
            await self.coordinator.async_set_control("test-device", "ventilatorFanSpeed", 60)
        self.assertGreater(sum(call.args[0] for call in pause.await_args_list), 60)
        self.assertEqual(self.coordinator.data["test-device"].value("ventilatorFanSpeed"), 60)
        self.client.async_write_control.assert_awaited_once()

    async def test_total_confirmation_deadline_marks_unavailable_and_unlocks(self):
        reads = 0

        async def read():
            nonlocal reads
            reads += 1
            if reads == 1:
                return [device()]
            await asyncio.Event().wait()

        self.client.async_list_notus_devices.side_effect = read
        with patch("custom_components.bsk_notus.coordinator.READ_BACK_TIMEOUT", 0.01):
            with self.assertRaisesRegex(HomeAssistantError, "Cannot confirm"):
                await self.coordinator.async_set_control("test-device", "ventilatorFanSpeed", 60)
        self.assertFalse(self.coordinator.last_update_success)
        self.assertFalse(self.coordinator._io_lock.locked())
        self.client.async_write_control.assert_awaited_once()

    async def test_stale_read_back_then_confirmation_updates_all_entities(self):
        before, after = device(), device(setTemperature=220)
        self.client.async_list_notus_devices.side_effect = [[before], [before], [after]]
        entity = BSKNotusNumber(self.coordinator, before, CONTROLS["setTemperature"])
        published = []
        self.coordinator.async_update_listeners = lambda: published.append(entity.native_value)
        await entity.async_set_native_value(22.0)
        self.assertEqual(published, [22.0])
        self.assertEqual(entity.native_value, 22.0)
        self.assertEqual(entity.native_min_value, 15.0)
        self.assertEqual(entity.native_max_value, 30.0)
        self.assertEqual(entity.native_step, 1)
        self.assertEqual(self.coordinator.data["test-device"].value("aspiratorFanSpeed"), 40)
        self.client.async_write_control.assert_awaited_once_with("test-device", "setTemperature", 220)

    async def test_unconfirmed_write_keeps_actual_cloud_value_and_reports_error(self):
        with self.assertRaisesRegex(HomeAssistantError, "did not confirm"):
            await self.coordinator.async_set_control("test-device", "setTemperature", 220)
        self.assertEqual(self.coordinator.data["test-device"].value("setTemperature"), 210)
        self.assertTrue(self.coordinator.last_update_success)
        self.assertEqual(self.client.async_list_notus_devices.await_count, 5)
        self.client.async_write_control.assert_awaited_once()

    async def test_timeout_after_applied_write_reads_actual_state_without_resend(self):
        self.client.async_write_control.side_effect = BSKNotusConnectionError("uncertain")
        self.client.async_list_notus_devices.side_effect = [[device()], [device(setTemperature=220)]]
        with self.assertRaisesRegex(HomeAssistantError, "uncertain"):
            await self.coordinator.async_set_control("test-device", "setTemperature", 220)
        self.assertEqual(self.coordinator.data["test-device"].value("setTemperature"), 220)
        self.client.async_write_control.assert_awaited_once()

    async def test_http_rejection_still_reads_back(self):
        self.client.async_write_control.side_effect = BSKNotusResponseError("HTTP 403")
        with self.assertRaisesRegex(HomeAssistantError, "HTTP 403"):
            await self.coordinator.async_set_control("test-device", "setTemperature", 220)
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
        self.client.async_list_notus_devices.side_effect = [[device()]] + [[device(ventilatorFanSpeed=80)]] * 4
        with self.assertRaisesRegex(HomeAssistantError, "write failed"):
            await self.coordinator.async_set_control("test-device", "ventilatorFanSpeed", 60)
        self.assertEqual(self.coordinator.data["test-device"].value("ventilatorFanSpeed"), 80)
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
            await entity.async_set_native_value(22.0)
        self.assertFalse(entity.available)
        self.assertEqual(entity.native_value, 21.0)
        self.client.async_write_control.assert_awaited_once()

    async def test_missing_device_or_control_during_preflight_never_writes(self):
        for payload in [[], [device(deviceID=None, mbDeviceId="test-device")],
                        [device(setTemperature=None)], [device(deviceModel="other")]]:
            self.client.async_list_notus_devices.return_value = payload
            with self.assertRaisesRegex(HomeAssistantError, "unavailable"):
                await self.coordinator.async_set_control("test-device", "setTemperature", 220)
        self.client.async_write_control.assert_not_called()

    async def test_auth_failure_starts_reauth_and_releases_lock(self):
        self.client.async_list_notus_devices.side_effect = BSKNotusAuthError("expired")
        with self.assertRaises(HomeAssistantError):
            await self.coordinator.async_set_control("test-device", "setTemperature", 220)
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
        first = asyncio.create_task(self.coordinator.async_set_control("test-device", "setTemperature", 220))
        await put_started.wait()
        second = asyncio.create_task(self.coordinator.async_set_control("test-device", "setHumidity", 71))
        poll = asyncio.create_task(self.coordinator.async_refresh())
        await asyncio.sleep(0)
        self.assertEqual(len(events), 2)
        self.assertEqual(self.coordinator.data["test-device"].value("setTemperature"), 210)
        release_put.set()
        await asyncio.gather(first, second, poll)
        self.assertEqual(events, [("read", 210, 70), ("write", "setTemperature", 220),
                                  ("read", 220, 70), ("read", 220, 70),
                                  ("write", "setHumidity", 71), ("read", 220, 71),
                                  ("read", 220, 71)])
        self.assertEqual(self.coordinator.data["test-device"].value("setHumidity"), 71)
        self.assertEqual(self.coordinator.data["test-device"].value("setTemperature"), 220)

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
        task = asyncio.create_task(self.coordinator.async_set_control("test-device", "setTemperature", 220))
        await started.wait()
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertFalse(self.coordinator._io_lock.locked())
        self.assertFalse(self.coordinator.last_update_success)

    async def test_controls_preserve_original_entities_and_read_semantics(self):
        self.entry.runtime_data = self.coordinator
        added = []
        await number.async_setup_entry(self.hass, self.entry, added.extend)
        await switch.async_setup_entry(self.hass, self.entry, added.extend)
        await select.async_setup_entry(self.hass, self.entry, added.extend)
        self.assertEqual(len(added), 19)
        self.assertEqual(len({entity.unique_id for entity in added}), 19)
        old_keys = ("deviceStatus", "manualBoostState", "ventilatorFanSpeed",
                    "aspiratorFanSpeed", "setTemperature", "setHumidity")
        self.assertTrue({f"test-device_control_{key}" for key in old_keys}.issubset(
            entity.unique_id for entity in added
        ))
        self.assertEqual(len(SENSORS) + len(BINARY_SENSORS), 28)
        sensors = {d.translation_key: BSKNotusSensor(self.coordinator, device(), d) for d in SENSORS}
        self.assertEqual(sensors["target_temperature"].native_value, 21.0)
        self.assertFalse(sensors["return_co2"].available)
        self.assertEqual(sensors["operation_mode"].native_value, "CS")
        readonly_ids = {f"test-device_{d.key}" for d in (*SENSORS, *BINARY_SENSORS)}
        self.assertFalse(readonly_ids.intersection(e.unique_id for e in added))


if __name__ == "__main__":
    unittest.main()
