"""Binary sensor platform for Quectel QManager.

UNTESTED against real hardware - see README.
"""
from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .coordinator import QManagerConfigEntry, QManagerCoordinator
from .entity import QManagerEntity
from .parser import safe_get

INTERNET_CONNECTED_DESCRIPTION = BinarySensorEntityDescription(
    key="internet_connected",
    translation_key="internet_connected",
    device_class=BinarySensorDeviceClass.CONNECTIVITY,
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: QManagerConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Quectel QManager binary sensors from a config entry."""
    coordinator = entry.runtime_data.main
    async_add_entities([QManagerInternetConnectedBinarySensor(coordinator)])


class QManagerInternetConnectedBinarySensor(QManagerEntity, BinarySensorEntity):
    """Real connectivity check run by the qmanager_ping daemon
    (connectivity.internet_available in the cached status blob) - not an
    inference from RF/registration state. QManager's own probe is
    considerably richer than the sibling integration's single ping: it
    tracks latency/jitter/packet loss and a primary+fallback probe URL
    pair, exposed as extra_state_attributes here.
    """

    entity_description = INTERNET_CONNECTED_DESCRIPTION

    def __init__(self, coordinator: QManagerCoordinator) -> None:
        super().__init__(coordinator, coordinator)
        self._attr_unique_id = f"{coordinator.host}_internet_connected"

    @property
    def is_on(self) -> bool | None:
        return safe_get(self.coordinator.data, "connectivity", "internet_available")

    @property
    def extra_state_attributes(self) -> dict:
        connectivity = safe_get(self.coordinator.data, "connectivity", default={})
        return {
            "status": connectivity.get("status"),
            "latency_ms": connectivity.get("latency_ms"),
            "avg_latency_ms": connectivity.get("avg_latency_ms"),
            "jitter_ms": connectivity.get("jitter_ms"),
            "packet_loss_pct": connectivity.get("packet_loss_pct"),
            "ping_target": connectivity.get("ping_target"),
            "during_recovery": connectivity.get("during_recovery"),
        }
