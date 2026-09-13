"""Binary sensor platform for BSK NOTUS."""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, override

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .api import NotusDevice
from .coordinator import BSKNotusConfigEntry, BSKNotusCoordinator
from .entity import BSKNotusEntity


@dataclass(frozen=True, kw_only=True)
class BSKNotusBinarySensorEntityDescription(BinarySensorEntityDescription):
    """Describe a BSK NOTUS binary sensor."""

    value_fn: Callable[[NotusDevice], bool | None]


def _as_bool(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        if value < 0:
            return None
        return value != 0
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {
            "1",
            "true",
            "on",
            "enabled",
            "active",
            "running",
            "online",
            "yes",
        }:
            return True
        if normalized in {
            "0",
            "false",
            "off",
            "disabled",
            "inactive",
            "stopped",
            "offline",
            "no",
        }:
            return False
    return None


def _binary_value(device: NotusDevice, key: str) -> bool | None:
    return _as_bool(device.value(key))


BINARY_SENSORS: tuple[BSKNotusBinarySensorEntityDescription, ...] = (
    BSKNotusBinarySensorEntityDescription(
        key="power",
        translation_key="power",
        device_class=BinarySensorDeviceClass.POWER,
        value_fn=lambda device: _binary_value(device, "deviceStatus"),
    ),
    BSKNotusBinarySensorEntityDescription(
        key="filter_warning",
        translation_key="filter_warning",
        device_class=BinarySensorDeviceClass.PROBLEM,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda device: _binary_value(device, "FilterWarning"),
    ),
    BSKNotusBinarySensorEntityDescription(
        key="low_fan_speed_warning",
        translation_key="low_fan_speed_warning",
        device_class=BinarySensorDeviceClass.PROBLEM,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda device: _binary_value(device, "LowFanSpeedWarning"),
    ),
    BSKNotusBinarySensorEntityDescription(
        key="manual_boost",
        translation_key="manual_boost",
        device_class=BinarySensorDeviceClass.RUNNING,
        value_fn=lambda device: _binary_value(device, "manualBoostState"),
    ),
    BSKNotusBinarySensorEntityDescription(
        key="humidity_boost",
        translation_key="humidity_boost",
        device_class=BinarySensorDeviceClass.RUNNING,
        value_fn=lambda device: _binary_value(device, "humidityBoost"),
    ),
    BSKNotusBinarySensorEntityDescription(
        key="external_boost",
        translation_key="external_boost",
        device_class=BinarySensorDeviceClass.RUNNING,
        value_fn=lambda device: _binary_value(device, "externalBoostState"),
    ),
    BSKNotusBinarySensorEntityDescription(
        key="free_cooling",
        translation_key="free_cooling",
        device_class=BinarySensorDeviceClass.RUNNING,
        value_fn=lambda device: _binary_value(device, "freeCoolingStatus"),
    ),
    BSKNotusBinarySensorEntityDescription(
        key="preheater_attached",
        translation_key="preheater_attached",
        device_class=BinarySensorDeviceClass.PLUG,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda device: _binary_value(device, "preHeaterAttached"),
    ),
    BSKNotusBinarySensorEntityDescription(
        key="preheater_status",
        translation_key="preheater_status",
        device_class=BinarySensorDeviceClass.POWER,
        value_fn=lambda device: _binary_value(device, "preHeaterStatus"),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: BSKNotusConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up BSK NOTUS binary sensors."""
    coordinator = entry.runtime_data
    async_add_entities(
        BSKNotusBinarySensor(coordinator, device, description)
        for device in coordinator.data.values()
        for description in BINARY_SENSORS
    )


class BSKNotusBinarySensor(BSKNotusEntity, BinarySensorEntity):
    """Read-only BSK NOTUS binary sensor."""

    entity_description: BSKNotusBinarySensorEntityDescription

    def __init__(
        self,
        coordinator: BSKNotusCoordinator,
        device: NotusDevice,
        description: BSKNotusBinarySensorEntityDescription,
    ) -> None:
        super().__init__(coordinator, device)
        self.entity_description = description
        self._attr_unique_id = f"{device.identity}_{description.key}"

    @property
    @override
    def is_on(self) -> bool | None:
        """Return the current binary state."""
        device = self.device
        if device is None:
            return None
        return self.entity_description.value_fn(device)
