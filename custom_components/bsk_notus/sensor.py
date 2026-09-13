"""Sensor platform for BSK NOTUS."""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, override

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
    StateType,
)
from homeassistant.const import (
    REVOLUTIONS_PER_MINUTE,
    SIGNAL_STRENGTH_DECIBELS_MILLIWATT,
    UnitOfRatio,
    UnitOfTemperature,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .api import NotusDevice
from .coordinator import BSKNotusConfigEntry, BSKNotusCoordinator
from .entity import BSKNotusEntity


@dataclass(frozen=True, kw_only=True)
class BSKNotusSensorEntityDescription(SensorEntityDescription):
    """Describe a BSK NOTUS sensor."""

    value_fn: Callable[[NotusDevice], StateType]
    unavailable_fn: Callable[[NotusDevice], bool] | None = None


def _number(device: NotusDevice, key: str) -> int | float | None:
    value = device.value(key)
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, (int, float)):
        return value
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return None
    return None


def _raw_state(device: NotusDevice, key: str) -> StateType:
    value = device.value(key)
    if value is None or isinstance(value, (str, int, float)):
        return value
    return str(value)


def _target_temperature(device: NotusDevice) -> float | None:
    value = _number(device, "setTemperature")
    return None if value is None else round(float(value) / 10.0, 1)


def _return_co2(device: NotusDevice) -> int | float | None:
    value = _number(device, "retCo2Ppm")
    if value is None or value < 0:
        return None
    return value


SENSORS: tuple[BSKNotusSensorEntityDescription, ...] = (
    BSKNotusSensorEntityDescription(
        key="return_temperature",
        translation_key="return_temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda device: _number(device, "returnTemperature"),
    ),
    BSKNotusSensorEntityDescription(
        key="return_humidity",
        translation_key="return_humidity",
        device_class=SensorDeviceClass.HUMIDITY,
        native_unit_of_measurement=UnitOfRatio.PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda device: _number(device, "returnHumidity"),
    ),
    BSKNotusSensorEntityDescription(
        key="external_temperature",
        translation_key="external_temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda device: _number(device, "externalTemperature"),
    ),
    BSKNotusSensorEntityDescription(
        key="external_humidity",
        translation_key="external_humidity",
        device_class=SensorDeviceClass.HUMIDITY,
        native_unit_of_measurement=UnitOfRatio.PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda device: _number(device, "externalHumidity"),
    ),
    BSKNotusSensorEntityDescription(
        key="supply_temperature",
        translation_key="supply_temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda device: _number(device, "supplyTemperature"),
    ),
    BSKNotusSensorEntityDescription(
        key="supply_humidity",
        translation_key="supply_humidity",
        device_class=SensorDeviceClass.HUMIDITY,
        native_unit_of_measurement=UnitOfRatio.PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda device: _number(device, "supplyHumidity"),
    ),
    BSKNotusSensorEntityDescription(
        key="exhaust_temperature",
        translation_key="exhaust_temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda device: _number(device, "exhaustTemperature"),
    ),
    BSKNotusSensorEntityDescription(
        key="exhaust_humidity",
        translation_key="exhaust_humidity",
        device_class=SensorDeviceClass.HUMIDITY,
        native_unit_of_measurement=UnitOfRatio.PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda device: _number(device, "exhaustHumidity"),
    ),
    BSKNotusSensorEntityDescription(
        key="supply_fan_speed",
        translation_key="supply_fan_speed",
        native_unit_of_measurement=UnitOfRatio.PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda device: _number(device, "ventilatorFanSpeed"),
    ),
    BSKNotusSensorEntityDescription(
        key="extract_fan_speed",
        translation_key="extract_fan_speed",
        native_unit_of_measurement=UnitOfRatio.PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda device: _number(device, "aspiratorFanSpeed"),
    ),
    BSKNotusSensorEntityDescription(
        key="supply_fan_rpm",
        translation_key="supply_fan_rpm",
        native_unit_of_measurement=REVOLUTIONS_PER_MINUTE,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda device: _number(device, "vntFanRpm"),
    ),
    BSKNotusSensorEntityDescription(
        key="extract_fan_rpm",
        translation_key="extract_fan_rpm",
        native_unit_of_measurement=REVOLUTIONS_PER_MINUTE,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda device: _number(device, "aspFanRpm"),
    ),
    BSKNotusSensorEntityDescription(
        key="target_temperature",
        translation_key="target_temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=_target_temperature,
    ),
    BSKNotusSensorEntityDescription(
        key="target_humidity",
        translation_key="target_humidity",
        device_class=SensorDeviceClass.HUMIDITY,
        native_unit_of_measurement=UnitOfRatio.PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda device: _number(device, "setHumidity"),
    ),
    BSKNotusSensorEntityDescription(
        key="wifi_rssi",
        translation_key="wifi_rssi",
        device_class=SensorDeviceClass.SIGNAL_STRENGTH,
        native_unit_of_measurement=SIGNAL_STRENGTH_DECIBELS_MILLIWATT,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda device: _number(device, "WifiRSSI"),
    ),
    BSKNotusSensorEntityDescription(
        key="return_co2",
        translation_key="return_co2",
        device_class=SensorDeviceClass.CO2,
        native_unit_of_measurement=UnitOfRatio.PARTS_PER_MILLION,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=_return_co2,
        unavailable_fn=lambda device: _return_co2(device) is None,
    ),
    BSKNotusSensorEntityDescription(
        key="operation_mode",
        translation_key="operation_mode",
        value_fn=lambda device: _raw_state(device, "opMode"),
    ),
    BSKNotusSensorEntityDescription(
        key="firmware",
        translation_key="firmware",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda device: _raw_state(device, "version"),
    ),
    BSKNotusSensorEntityDescription(
        key="mainboard_firmware",
        translation_key="mainboard_firmware",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda device: _raw_state(device, "mbVersion"),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: BSKNotusConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up BSK NOTUS sensors."""
    coordinator = entry.runtime_data
    async_add_entities(
        BSKNotusSensor(coordinator, device, description)
        for device in coordinator.data.values()
        for description in SENSORS
    )


class BSKNotusSensor(BSKNotusEntity, SensorEntity):
    """Read-only BSK NOTUS sensor."""

    entity_description: BSKNotusSensorEntityDescription

    def __init__(
        self,
        coordinator: BSKNotusCoordinator,
        device: NotusDevice,
        description: BSKNotusSensorEntityDescription,
    ) -> None:
        super().__init__(coordinator, device)
        self.entity_description = description
        self._attr_unique_id = f"{device.identity}_{description.key}"

    @property
    @override
    def native_value(self) -> StateType:
        """Return the current sensor value."""
        device = self.device
        if device is None:
            return None
        return self.entity_description.value_fn(device)

    @property
    @override
    def available(self) -> bool:
        """Return whether this specific sensor has a usable value."""
        if not super().available:
            return False
        device = self.device
        if device is None:
            return False
        if self.entity_description.unavailable_fn is None:
            return True
        return not self.entity_description.unavailable_fn(device)
