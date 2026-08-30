"""Sensor platform for Quectel QManager.

Nearly everything here is direct JSON field access into fetch_data.sh's
cached ModemStatus blob - no AT-reply text parsing needed, unlike the
sibling simpleadmin integration. Field names/nesting/nullability are
taken from docs/API-REFERENCE.md's example payload, not confirmed
against a live device - see README.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import timedelta
import logging
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import (
    EntityCategory,
    UnitOfInformation,
    UnitOfTemperature,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
import homeassistant.util.dt as dt_util

from .coordinator import QManagerConfigEntry, QManagerCoordinator
from .entity import QManagerEntity
from .parser import safe_float, safe_get, safe_int

_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, kw_only=True)
class QManagerSensorEntityDescription(SensorEntityDescription):
    """Describes a Quectel QManager sensor and how to compute it."""

    value_fn: Callable[[QManagerCoordinator], Any]
    attrs_fn: Callable[[QManagerCoordinator], dict[str, Any]] | None = None


# --- section getters ---------------------------------------------------


def _network(c: QManagerCoordinator) -> dict:
    return safe_get(c.data, "network", default={})


def _lte(c: QManagerCoordinator) -> dict:
    return safe_get(c.data, "lte", default={})


def _nr(c: QManagerCoordinator) -> dict:
    return safe_get(c.data, "nr", default={})


def _device(c: QManagerCoordinator) -> dict:
    return safe_get(c.data, "device", default={})


def _connectivity(c: QManagerCoordinator) -> dict:
    return safe_get(c.data, "connectivity", default={})


def _data_used(c: QManagerCoordinator) -> dict:
    # Confirmed against real output: the doc's "traffic" section (with
    # rx_bytes_per_sec/total_rx_bytes etc.) doesn't exist. The real section
    # is "data_used", with only cumulative counters
    # (accumulated_rx_bytes/accumulated_tx_bytes) - no per-second rate
    # field at all, so there's nothing to build a rate sensor from
    # natively (would need our own delta-over-time tracking to derive one).
    return safe_get(c.data, "data_used", default={})


# --- value/attr extractors ----------------------------------------------


def _last_restart(c: QManagerCoordinator):
    seconds = safe_int(_device(c).get("uptime_seconds"))
    if seconds is None:
        return None
    boot = dt_util.utcnow() - timedelta(seconds=seconds)
    # device.uptime_seconds is presumably whole-second precision (not
    # confirmed) - round to the minute regardless so this doesn't jitter
    # every poll even if the source has more precision than that.
    return boot.replace(second=0, microsecond=0)


def _carrier_aggregation_summary(c: QManagerCoordinator) -> str | None:
    # Confirmed against real output: network.ca_count is LTE-specific (0 on
    # an NR-CA-only device even while carrier_components lists 2 active
    # component carriers) - counting carrier_components directly reflects
    # reality regardless of which RAT's CA counter is nonzero.
    components = _network(c).get("carrier_components") or []
    count = len(components)
    if not count:
        return "Inactive"
    return f"{count} component carrier{'s' if count != 1 else ''}"


def _carrier_aggregation_attrs(c: QManagerCoordinator) -> dict[str, Any]:
    network = _network(c)
    return {
        "ca_active": network.get("ca_active"),
        "nr_ca_active": network.get("nr_ca_active"),
        "nr_ca_count": safe_int(network.get("nr_ca_count")),
        "total_bandwidth_mhz": safe_int(network.get("total_bandwidth_mhz")),
        "bandwidth_details": network.get("bandwidth_details"),
        "carrier_components": network.get("carrier_components"),
    }


def _memory_percent(c: QManagerCoordinator) -> float | None:
    device = _device(c)
    used = safe_float(device.get("memory_used_mb"))
    total = safe_float(device.get("memory_total_mb"))
    if not used or not total:
        return None
    return round((used / total) * 100, 1)


# --- descriptions ---------------------------------------------------------

SENSOR_DESCRIPTIONS: tuple[QManagerSensorEntityDescription, ...] = (
    # Network
    QManagerSensorEntityDescription(
        key="network_type",
        translation_key="network_type",
        value_fn=lambda c: _network(c).get("type"),
    ),
    QManagerSensorEntityDescription(
        key="carrier",
        translation_key="carrier",
        value_fn=lambda c: _network(c).get("carrier"),
    ),
    QManagerSensorEntityDescription(
        key="service_status",
        translation_key="service_status",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda c: _network(c).get("service_status"),
    ),
    QManagerSensorEntityDescription(
        key="apn",
        translation_key="apn",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda c: _network(c).get("apn"),
    ),
    QManagerSensorEntityDescription(
        key="wan_ipv4",
        translation_key="wan_ipv4",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda c: _network(c).get("wan_ipv4"),
    ),
    QManagerSensorEntityDescription(
        key="wan_ipv6",
        translation_key="wan_ipv6",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda c: _network(c).get("wan_ipv6"),
    ),
    QManagerSensorEntityDescription(
        key="carrier_aggregation",
        translation_key="carrier_aggregation",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=_carrier_aggregation_summary,
        attrs_fn=_carrier_aggregation_attrs,
    ),
    # LTE
    QManagerSensorEntityDescription(
        key="lte_band",
        translation_key="lte_band",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda c: _lte(c).get("band"),
    ),
    QManagerSensorEntityDescription(
        key="lte_rsrp",
        translation_key="lte_rsrp",
        device_class=SensorDeviceClass.SIGNAL_STRENGTH,
        native_unit_of_measurement="dBm",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda c: safe_int(_lte(c).get("rsrp")),
    ),
    QManagerSensorEntityDescription(
        key="lte_rsrq",
        translation_key="lte_rsrq",
        native_unit_of_measurement="dB",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda c: safe_int(_lte(c).get("rsrq")),
    ),
    QManagerSensorEntityDescription(
        key="lte_sinr",
        translation_key="lte_sinr",
        native_unit_of_measurement="dB",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda c: safe_int(_lte(c).get("sinr")),
    ),
    QManagerSensorEntityDescription(
        key="lte_cell_id",
        translation_key="lte_cell_id",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda c: _lte(c).get("cell_id"),
    ),
    QManagerSensorEntityDescription(
        key="lte_pci",
        translation_key="lte_pci",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda c: _lte(c).get("pci"),
    ),
    QManagerSensorEntityDescription(
        key="lte_tac",
        translation_key="lte_tac",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda c: _lte(c).get("tac"),
    ),
    # NR (5G)
    QManagerSensorEntityDescription(
        key="nr_band",
        translation_key="nr_band",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda c: _nr(c).get("band"),
    ),
    QManagerSensorEntityDescription(
        key="nr_rsrp",
        translation_key="nr_rsrp",
        device_class=SensorDeviceClass.SIGNAL_STRENGTH,
        native_unit_of_measurement="dBm",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda c: safe_int(_nr(c).get("rsrp")),
    ),
    QManagerSensorEntityDescription(
        key="nr_rsrq",
        translation_key="nr_rsrq",
        native_unit_of_measurement="dB",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda c: safe_int(_nr(c).get("rsrq")),
    ),
    QManagerSensorEntityDescription(
        key="nr_sinr",
        translation_key="nr_sinr",
        native_unit_of_measurement="dB",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda c: safe_int(_nr(c).get("sinr")),
    ),
    QManagerSensorEntityDescription(
        key="nr_pci",
        translation_key="nr_pci",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda c: _nr(c).get("pci"),
    ),
    # Device
    QManagerSensorEntityDescription(
        key="modem_temperature",
        translation_key="modem_temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda c: safe_float(_device(c).get("temperature")),
    ),
    QManagerSensorEntityDescription(
        key="cpu_usage",
        translation_key="cpu_usage",
        native_unit_of_measurement="%",
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda c: safe_float(_device(c).get("cpu_usage")),
    ),
    QManagerSensorEntityDescription(
        key="memory_used",
        translation_key="memory_used",
        native_unit_of_measurement="%",
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=_memory_percent,
        attrs_fn=lambda c: {
            "used_mb": safe_float(_device(c).get("memory_used_mb")),
            "total_mb": safe_float(_device(c).get("memory_total_mb")),
        },
    ),
    QManagerSensorEntityDescription(
        key="last_restart",
        translation_key="last_restart",
        device_class=SensorDeviceClass.TIMESTAMP,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=_last_restart,
    ),
    QManagerSensorEntityDescription(
        key="manufacturer",
        translation_key="manufacturer",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda c: _device(c).get("manufacturer"),
    ),
    QManagerSensorEntityDescription(
        key="model",
        translation_key="model",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda c: _device(c).get("model"),
    ),
    QManagerSensorEntityDescription(
        key="firmware_version",
        translation_key="firmware_version",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda c: _device(c).get("firmware"),
    ),
    QManagerSensorEntityDescription(
        key="imei",
        translation_key="imei",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda c: _device(c).get("imei"),
    ),
    QManagerSensorEntityDescription(
        key="imsi",
        translation_key="imsi",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda c: _device(c).get("imsi"),
    ),
    QManagerSensorEntityDescription(
        key="iccid",
        translation_key="iccid",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda c: _device(c).get("iccid"),
    ),
    QManagerSensorEntityDescription(
        key="phone_number",
        translation_key="phone_number",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda c: _device(c).get("phone_number"),
    ),
    # Connectivity (internet_available itself is the binary_sensor, not here)
    QManagerSensorEntityDescription(
        key="latency",
        translation_key="latency",
        native_unit_of_measurement="ms",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda c: safe_float(_connectivity(c).get("latency_ms")),
    ),
    QManagerSensorEntityDescription(
        key="packet_loss",
        translation_key="packet_loss",
        native_unit_of_measurement="%",
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda c: safe_float(_connectivity(c).get("packet_loss_pct")),
    ),
    # Data usage - cumulative counters only (data_used.*); no per-second
    # rate field exists natively, confirmed against real output, so there
    # are no rate sensors here (a derived rate would need our own
    # delta-over-time tracking - not implemented).
    QManagerSensorEntityDescription(
        key="data_received",
        translation_key="data_received",
        device_class=SensorDeviceClass.DATA_SIZE,
        native_unit_of_measurement=UnitOfInformation.BYTES,
        state_class=SensorStateClass.TOTAL_INCREASING,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda c: safe_int(_data_used(c).get("accumulated_rx_bytes")),
    ),
    QManagerSensorEntityDescription(
        key="data_sent",
        translation_key="data_sent",
        device_class=SensorDeviceClass.DATA_SIZE,
        native_unit_of_measurement=UnitOfInformation.BYTES,
        state_class=SensorStateClass.TOTAL_INCREASING,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda c: safe_int(_data_used(c).get("accumulated_tx_bytes")),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: QManagerConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Quectel QManager sensors from a config entry."""
    coordinator = entry.runtime_data.main
    async_add_entities(
        QManagerSensor(coordinator, coordinator, description)
        for description in SENSOR_DESCRIPTIONS
    )


class QManagerSensor(QManagerEntity, SensorEntity):
    """A sensor computed from the main coordinator's latest cached data."""

    entity_description: QManagerSensorEntityDescription

    def __init__(
        self,
        coordinator: QManagerCoordinator,
        main_coordinator: QManagerCoordinator,
        description: QManagerSensorEntityDescription,
    ) -> None:
        super().__init__(coordinator, main_coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{coordinator.host}_{description.key}"

    @property
    def native_value(self) -> Any:
        try:
            return self.entity_description.value_fn(self.coordinator)
        except Exception:  # noqa: BLE001
            _LOGGER.debug(
                "Failed to compute value for %s", self.entity_description.key,
                exc_info=True,
            )
            return None

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        if self.entity_description.attrs_fn is None:
            return None
        try:
            return self.entity_description.attrs_fn(self.coordinator)
        except Exception:  # noqa: BLE001
            return None
