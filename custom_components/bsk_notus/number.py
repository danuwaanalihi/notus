"""Verified NOTUS fan, temperature and humidity controls."""

from typing import override

from homeassistant.components.number import NumberDeviceClass, NumberEntity, NumberMode
from homeassistant.const import PERCENTAGE, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .api import NotusDevice
from .controls import (
    FAN_PRESET_FIELDS,
    NUMBER_CONTROLS,
    NotusControl,
    fan_preset_values,
    supports_control,
)
from .coordinator import BSKNotusConfigEntry, BSKNotusCoordinator
from .entity import BSKNotusEntity


async def async_setup_entry(
    hass: HomeAssistant, entry: BSKNotusConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Add only controls present in a verified device payload."""
    coordinator = entry.runtime_data
    async_add_entities(
        BSKNotusNumber(coordinator, device, control)
        for device in coordinator.data.values()
        for control in NUMBER_CONTROLS
        if supports_control(device, control)
    )


class BSKNotusNumber(BSKNotusEntity, NumberEntity):
    """A bounded number with confirmed cloud state, never optimistic state."""

    _attr_mode = NumberMode.BOX

    def __init__(
        self, coordinator: BSKNotusCoordinator, device: NotusDevice, control: NotusControl
    ) -> None:
        super().__init__(coordinator, device)
        self.control = control
        self._attr_unique_id = f"{device.identity}_control_{control.key}"
        self._attr_translation_key = control.translation_key
        self._attr_native_min_value = control.minimum / control.scale
        self._attr_native_max_value = control.maximum / control.scale
        self._attr_native_step = control.step / control.scale
        if control.is_config:
            self._attr_entity_category = EntityCategory.CONFIG
        if control.key == "setTemperature":
            self._attr_device_class = NumberDeviceClass.TEMPERATURE
            self._attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
        else:
            self._attr_native_unit_of_measurement = PERCENTAGE
            self._attr_icon = "mdi:water-percent" if control.key == "setHumidity" else "mdi:fan"
            if control.key == "setHumidity":
                self._attr_device_class = NumberDeviceClass.HUMIDITY

    @property
    @override
    def available(self) -> bool:
        return super().available and self.device is not None and supports_control(
            self.device, self.control
        )

    @property
    @override
    def native_value(self) -> float | None:
        if self.device is None:
            return None
        raw = self.control.raw_value(self.device.value(self.control.key))
        return None if raw is None else raw / self.control.scale

    @property
    @override
    def extra_state_attributes(self) -> dict | None:
        if self.device is None or self.control.key not in FAN_PRESET_FIELDS:
            return None
        values = fan_preset_values(self.device, self.control.key)
        return {
            "preset_percentages": values,
            "valid_values": sorted({0, *values.values()}) if values else [],
        }

    @override
    async def async_set_native_value(self, value: float) -> None:
        try:
            raw = self.control.to_raw(value)
        except ValueError as err:
            raise HomeAssistantError(str(err)) from err
        await self.coordinator.async_set_control(self._device_identity, self.control.key, raw)
