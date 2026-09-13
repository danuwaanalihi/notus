"""Verified NOTUS power and manual boost controls."""

from typing import Any, override

from homeassistant.components.switch import SwitchEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .api import NotusDevice
from .controls import SWITCH_CONTROLS, NotusControl, supports_control
from .coordinator import BSKNotusConfigEntry, BSKNotusCoordinator
from .entity import BSKNotusEntity


async def async_setup_entry(
    hass: HomeAssistant, entry: BSKNotusConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Add only controls present in a verified device payload."""
    coordinator = entry.runtime_data
    async_add_entities(
        BSKNotusSwitch(coordinator, device, control)
        for device in coordinator.data.values()
        for control in SWITCH_CONTROLS
        if supports_control(device, control)
    )


class BSKNotusSwitch(BSKNotusEntity, SwitchEntity):
    """A switch whose state comes exclusively from cloud reads."""

    def __init__(
        self, coordinator: BSKNotusCoordinator, device: NotusDevice, control: NotusControl
    ) -> None:
        super().__init__(coordinator, device)
        self.control = control
        self._attr_unique_id = f"{device.identity}_control_{control.key}"
        self._attr_translation_key = control.translation_key
        self._attr_icon = "mdi:power" if control.key == "deviceStatus" else "mdi:fan-plus"

    @property
    @override
    def available(self) -> bool:
        return super().available and self.device is not None and supports_control(
            self.device, self.control
        )

    @property
    @override
    def is_on(self) -> bool | None:
        if self.device is None:
            return None
        raw = self.control.raw_value(self.device.value(self.control.key))
        return None if raw is None else bool(raw)

    @override
    async def async_turn_on(self, **kwargs: Any) -> None:
        await self.coordinator.async_set_control(self._device_identity, self.control.key, 1)

    @override
    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.coordinator.async_set_control(self._device_identity, self.control.key, 0)
