"""Data update coordinator for BSK NOTUS."""

from typing import override

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import BSKNotusAuthError, BSKNotusClient, BSKNotusError, NotusDevice
from .const import DOMAIN, LOGGER, SCAN_INTERVAL

type BSKNotusConfigEntry = ConfigEntry[BSKNotusCoordinator]


class BSKNotusCoordinator(DataUpdateCoordinator[dict[str, NotusDevice]]):
    """Poll the BSK Connect cloud for read-only NOTUS state."""

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

    @override
    async def _async_update_data(self) -> dict[str, NotusDevice]:
        """Fetch current NOTUS device snapshots."""
        try:
            devices = await self.client.async_list_notus_devices()
        except BSKNotusAuthError as err:
            raise ConfigEntryAuthFailed("Authentication with BSK Connect failed") from err
        except BSKNotusError as err:
            raise UpdateFailed(str(err)) from err

        return {device.identity: device for device in devices}
