"""Data update coordinator for BSK NOTUS."""

import asyncio
from typing import override

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, HomeAssistantError
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import BSKNotusAuthError, BSKNotusClient, BSKNotusError, NotusDevice
from .const import DOMAIN, LOGGER, SCAN_INTERVAL
from .controls import CONTROLS, NotusControl, supports_control

READ_BACK_ATTEMPTS = 4
READ_BACK_DELAY = 2

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
        if control is None or type(raw) is not int or control.raw_value(raw) is None:
            raise HomeAssistantError("Invalid NOTUS control value")

        async with self._io_lock:
            try:
                # Recheck access, identity and capability from a fresh payload.
                devices = await self._async_control_read()
                device = next((d for d in devices if d.identity == identity), None)
                if device is None or not supports_control(device, control):
                    self.async_set_updated_data({d.identity: d for d in devices})
                    raise HomeAssistantError("This NOTUS control is unavailable")

                write_error: BSKNotusError | None = None
                try:
                    await self.client.async_write_control(device.identity, key, raw)
                except BSKNotusError as err:
                    write_error = err

                # Read even after rejection/timeout. Never infer success from
                # the PUT response, nor resend an ambiguous write.
                devices = await self._async_read_back(identity, control, raw)
                self.async_set_updated_data({d.identity: d for d in devices})
                device = self.data.get(identity)
                if write_error is not None:
                    raise HomeAssistantError(
                        f"NOTUS write failed or was uncertain ({write_error}); "
                        "cloud state was refreshed"
                    ) from write_error
                if (
                    device is None
                    or not supports_control(device, control)
                    or control.raw_value(device.value(key)) != raw
                ):
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
        self, identity: str, control: NotusControl, raw: int
    ) -> list[NotusDevice]:
        """Allow bounded cloud propagation without issuing another write."""
        for attempt in range(READ_BACK_ATTEMPTS):
            if attempt:
                await asyncio.sleep(READ_BACK_DELAY)
            try:
                devices = await self._async_control_read()
            except BSKNotusAuthError:
                raise
            except (BSKNotusError, TimeoutError):
                if attempt == READ_BACK_ATTEMPTS - 1:
                    raise
                continue
            device = next((d for d in devices if d.identity == identity), None)
            if (
                device is not None
                and supports_control(device, control)
                and control.raw_value(device.value(control.key)) == raw
            ) or attempt == READ_BACK_ATTEMPTS - 1:
                return devices
        raise AssertionError("Read-back loop exhausted")
