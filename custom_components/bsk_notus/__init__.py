"""BSK NOTUS Home Assistant integration."""

from homeassistant.const import CONF_PASSWORD, CONF_USERNAME, Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import BSKNotusClient
from .coordinator import BSKNotusConfigEntry, BSKNotusCoordinator

PLATFORMS: tuple[Platform, ...] = (
    Platform.SENSOR,
    Platform.BINARY_SENSOR,
    Platform.SWITCH,
    Platform.NUMBER,
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: BSKNotusConfigEntry,
) -> bool:
    """Set up BSK NOTUS from a config entry."""
    client = BSKNotusClient(
        async_get_clientsession(hass),
        entry.data[CONF_USERNAME],
        entry.data[CONF_PASSWORD],
    )
    coordinator = BSKNotusCoordinator(hass, entry, client)
    await coordinator.async_config_entry_first_refresh()

    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(
    hass: HomeAssistant,
    entry: BSKNotusConfigEntry,
) -> bool:
    """Unload a BSK NOTUS config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
