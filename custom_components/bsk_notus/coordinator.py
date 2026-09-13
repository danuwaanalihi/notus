"""Data update coordinator for BSK NOTUS."""

import asyncio
from typing import override

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, HomeAssistantError
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import (
    BSKNotusAuthError,
    BSKNotusClient,
    BSKNotusError,
    BSKNotusSyncError,
    NotusDevice,
)
from .const import DOMAIN, LOGGER, SCAN_INTERVAL
from .controls import (
    CONTROLS,
    FAN_PRESET_FIELDS,
    NotusControl,
    fan_preset_values,
    supports_control,
)

# Fast confirmation first, then allow a device reporting cycle to catch up.
# Bound the entire confirmation phase, including request time, to 90 seconds.
READ_BACK_DELAYS = (0, 2, 2, 2, 5, 10, 10, 10, 10, 10, 10, 10)
READ_BACK_TIMEOUT = 90

type BSKNotusConfigEntry = ConfigEntry[BSKNotusCoordinator]


class BSKNotusCoordinator(DataUpdateCoordinator[dict[str, NotusDevice]]):
    """Poll cloud state and serialize writes through their confirmed read-back."""

    config_entry: BSKNotusConfigEntry

    def __init__(
        self,
        hass: HomeAssistant,
        config_entry: BSKNotusConfigEntry,
        client: BSKNotusClient,
    ) -> None:
        super().__init__(
            hass,
            LOGGER,
            config_entry=config_entry,
            name=DOMAIN,
            update_interval=SCAN_INTERVAL,
        )
        self.client = client
        self._io_lock = asyncio.Lock()

    @override
    async def _async_update_data(self) -> dict[str, NotusDevice]:
        """Fetch current NOTUS device snapshots."""
        try:
            async with self._io_lock:
                devices = await self.client.async_list_notus_devices()
        except BSKNotusAuthError as err:
            raise ConfigEntryAuthFailed("Authentication with BSK Connect failed") from err
        except BSKNotusError as err:
            raise UpdateFailed(str(err)) from err

        return {device.identity: device for device in devices}

    async def async_set_control(self, identity: str, key: str, raw: int) -> None:
        """Serialize preflight, sparse PUT, read-back and state publication."""
        control = CONTROLS.get(key)
        if control is None or not control.valid_write(raw):
            raise HomeAssistantError("Invalid NOTUS control value")
        await self._async_set_control(identity, control, raw)

    async def async_set_fan_preset(self, identity: str, key: str, preset: str) -> None:
        """Select a name; resolve its percentage only after acquiring the lock."""
        if key not in FAN_PRESET_FIELDS or preset not in FAN_PRESET_FIELDS[key]:
            raise HomeAssistantError("Invalid NOTUS fan preset")
        await self._async_set_control(identity, CONTROLS[key], None, preset)

    async def _async_set_control(
        self, identity: str, control: NotusControl, raw: int | None, preset: str | None = None
    ) -> None:
        key = control.key
        async with self._io_lock:
            try:
                # Recheck access, identity and capability from a fresh payload.
                devices = await self._async_control_read()
                device = next((d for d in devices if d.identity == identity), None)
                if device is None or not supports_control(device, control):
                    self.async_set_updated_data({d.identity: d for d in devices})
                    raise HomeAssistantError("This NOTUS control is unavailable")

                if key in FAN_PRESET_FIELDS:
                    values = fan_preset_values(device, key)
                    if values is None:
                        self.async_set_updated_data({d.identity: d for d in devices})
                        raise HomeAssistantError("NOTUS fan preset percentages are unavailable")
                    if preset is not None:
                        raw = values[preset]
                    if raw != 0 and raw not in values.values():
                        self.async_set_updated_data({d.identity: d for d in devices})
                        raise HomeAssistantError(
                            "Choose a configured fan percentage or edit the preset first"
                        )
                assert raw is not None and control.valid_write(raw)

                write_error: BSKNotusError | None = None
                try:
                    await self.client.async_write_control(device.identity, key, raw)
                except BSKNotusError as err:
                    write_error = err

                # Read even after rejection/timeout. Never infer success from
                # the PUT response, nor resend an ambiguous write.
                devices = await self._async_read_back(
                    identity, control, raw,
                    extended=write_error is None or isinstance(write_error, BSKNotusSyncError),
                )
                self.async_set_updated_data({d.identity: d for d in devices})
                device = self.data.get(identity)
                confirmed = (
                    device is not None
                    and supports_control(device, control)
                    and control.raw_value(device.value(key)) == raw
                )
                # This exact Google sync error has followed applied writes.
                # A fresh, matching device/field is still required; all other
                # errors and mismatched values retain their failure status.
                if isinstance(write_error, BSKNotusSyncError) and confirmed:
                    LOGGER.debug("NOTUS cloud confirmed the write despite Google sync failure")
                elif write_error is not None:
                    raise HomeAssistantError(
                        f"NOTUS write failed or was uncertain ({write_error}); "
                        "cloud state was refreshed"
                    ) from write_error
                if not confirmed:
                    raise HomeAssistantError(
                        "BSK Connect did not confirm the requested value; "
                        "Home Assistant shows the latest cloud state"
                    )
            except (BSKNotusError, TimeoutError) as err:
                self.async_set_update_error(UpdateFailed("Cannot confirm NOTUS cloud state"))
                if isinstance(err, BSKNotusAuthError):
                    self.config_entry.async_start_reauth_if_available(self.hass)
                raise HomeAssistantError("Cannot confirm NOTUS cloud state") from err
            except asyncio.CancelledError:
                self.async_set_update_error(UpdateFailed("NOTUS write confirmation interrupted"))
                raise

    async def _async_control_read(self) -> list[NotusDevice]:
        """Bound reads performed while a control service holds the lock."""
        async with asyncio.timeout(20):
            return await self.client.async_list_notus_devices()

    async def _async_read_back(
        self, identity: str, control: NotusControl, raw: int, *, extended: bool = True
    ) -> list[NotusDevice]:
        """Allow bounded cloud propagation without issuing another write."""
        delays = READ_BACK_DELAYS if extended else READ_BACK_DELAYS[:4]
        async with asyncio.timeout(READ_BACK_TIMEOUT):
            for attempt, delay in enumerate(delays):
                if delay:
                    await asyncio.sleep(delay)
                try:
                    devices = await self._async_control_read()
                except BSKNotusAuthError:
                    raise
                except (BSKNotusError, TimeoutError):
                    if attempt == len(delays) - 1:
                        raise
                    continue
                device = next((d for d in devices if d.identity == identity), None)
                if (
                    device is not None
                    and supports_control(device, control)
                    and control.raw_value(device.value(control.key)) == raw
                ) or attempt == len(delays) - 1:
                    return devices
        raise AssertionError("Read-back loop exhausted")
