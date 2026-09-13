"""Fan presets and the verified free cooling setting."""

from typing import override

from homeassistant.components.select import SelectEntity
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .api import NotusDevice
from .controls import (
    CONTROLS,
    FAN_NAMES,
    FAN_PRESET_FIELDS,
    FREE_COOLING_CONTROL,
    FREE_COOLING_OPTIONS,
    fan_preset_values,
    supports_control,
)
from .coordinator import BSKNotusConfigEntry, BSKNotusCoordinator
from .entity import BSKNotusEntity


async def async_setup_entry(
    hass: HomeAssistant, entry: BSKNotusConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator = entry.runtime_data
    entities: list[SelectEntity] = []
    for device in coordinator.data.values():
        for fan_key in FAN_PRESET_FIELDS:
            if fan_preset_values(device, fan_key) is not None:
                entities.append(BSKNotusFanPreset(coordinator, device, fan_key))
        if supports_control(device, FREE_COOLING_CONTROL):
            entities.append(BSKNotusFreeCooling(coordinator, device))
    async_add_entities(entities)


class BSKNotusFanPreset(BSKNotusEntity, SelectEntity):
    """Resolve a named speed from the current device's configuration."""

    _attr_icon = "mdi:fan"

    def __init__(
        self, coordinator: BSKNotusCoordinator, device: NotusDevice, fan_key: str
    ) -> None:
        super().__init__(coordinator, device)
        self.fan_key = fan_key
        self._attr_unique_id = f"{device.identity}_control_{fan_key}_preset"
        self._attr_translation_key = f"{FAN_NAMES[fan_key]}_fan_preset"
        self._attr_options = list(FAN_PRESET_FIELDS[fan_key])

    @property
    @override
    def available(self) -> bool:
        return (
            super().available
            and self.device is not None
            and fan_preset_values(self.device, self.fan_key) is not None
        )

    @property
    @override
    def current_option(self) -> str | None:
        if self.device is None:
            return None
        values = fan_preset_values(self.device, self.fan_key)
        if values is None:
            return None
        raw = CONTROLS[self.fan_key].raw_value(self.device.value(self.fan_key))
        matches = [option for option, value in values.items() if value == raw]
        # Equal percentages cannot identify which named preset was selected.
        return matches[0] if len(matches) == 1 else None

    @property
    @override
    def extra_state_attributes(self) -> dict:
        if self.device is None:
            return {}
        return {
            "preset_percentages": fan_preset_values(self.device, self.fan_key),
            "percentage": CONTROLS[self.fan_key].raw_value(self.device.value(self.fan_key)),
        }

    @override
    async def async_select_option(self, option: str) -> None:
        await self.coordinator.async_set_fan_preset(
            self._device_identity, self.fan_key, option
        )


class BSKNotusFreeCooling(BSKNotusEntity, SelectEntity):
    """Control the setting, independently of the existing running sensor."""

    _attr_icon = "mdi:snowflake"
    _attr_translation_key = "free_cooling_mode"
    _attr_options = list(FREE_COOLING_OPTIONS)

    def __init__(self, coordinator: BSKNotusCoordinator, device: NotusDevice) -> None:
        super().__init__(coordinator, device)
        self._attr_unique_id = f"{device.identity}_control_freeCoolingSetting"

    @property
    @override
    def available(self) -> bool:
        return (
            super().available
            and self.device is not None
            and supports_control(self.device, FREE_COOLING_CONTROL)
        )

    @property
    @override
    def current_option(self) -> str | None:
        if self.device is None:
            return None
        raw = FREE_COOLING_CONTROL.raw_value(self.device.value(FREE_COOLING_CONTROL.key))
        return next((option for option, value in FREE_COOLING_OPTIONS.items() if value == raw), None)

    @override
    async def async_select_option(self, option: str) -> None:
        if option not in FREE_COOLING_OPTIONS:
            raise HomeAssistantError("Invalid free cooling option")
        await self.coordinator.async_set_control(
            self._device_identity, FREE_COOLING_CONTROL.key, FREE_COOLING_OPTIONS[option]
        )
