"""Base entity for BSK NOTUS."""

from typing import override

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .api import NotusDevice
from .const import DOMAIN
from .coordinator import BSKNotusCoordinator


class BSKNotusEntity(CoordinatorEntity[BSKNotusCoordinator]):
    """Base entity tied to one NOTUS device."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: BSKNotusCoordinator,
        device: NotusDevice,
    ) -> None:
        super().__init__(coordinator)
        self._device_identity = device.identity
        firmware = device.value("version")
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, device.identity)},
            name=device.name,
            manufacturer="BSK",
            model=device.model or "BSK NOTUS",
            serial_number=device.identity,
            sw_version=None if firmware is None else str(firmware),
        )

    @property
    def device(self) -> NotusDevice | None:
        """Return the latest snapshot for this entity's NOTUS device."""
        return self.coordinator.data.get(self._device_identity)

    @property
    @override
    def available(self) -> bool:
        """Return whether the coordinator and device snapshot are available."""
        return super().available and self.device is not None
