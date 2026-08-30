"""Base entity for Quectel QManager, tying every entity to one device.

UNTESTED against real hardware - device_info fields are read from
fetch_data.sh's documented "device" block, not confirmed live.
"""
from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import QManagerAnyCoordinator, QManagerCoordinator
from .parser import safe_get


class QManagerEntity(CoordinatorEntity[QManagerAnyCoordinator]):
    """Common base: every entity belongs to the device registry entry for the modem.

    Identity (manufacturer/model/firmware/IMEI) lives inside
    fetch_data.sh's regular "device" block, not a separate one-time
    fetch like the sibling simpleadmin integration needed - so this
    always reads it from `main_coordinator` specifically, regardless of
    which coordinator the entity itself subscribes to for live updates
    (the GPS coordinator's own .data has no "device" key at all).
    """

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: QManagerAnyCoordinator,
        main_coordinator: QManagerCoordinator,
    ) -> None:
        super().__init__(coordinator)
        device = safe_get(main_coordinator.data, "device", default={})
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, main_coordinator.host)},
            manufacturer=device.get("manufacturer") or "Quectel",
            model=device.get("model") or "RM520N-GL",
            sw_version=device.get("firmware"),
            serial_number=device.get("imei"),
            name=f"Quectel Modem ({main_coordinator.host})",
            configuration_url=f"https://{main_coordinator.host}",
        )
