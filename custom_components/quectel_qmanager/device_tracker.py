"""Device tracker platform for Quectel QManager (GPS).

No native QManager feature for this (confirmed: no gps/gnss/location
endpoint anywhere in the ~80-endpoint API reference) - raw AT via
send_command.sh, same approach as the sibling simpleadmin integration.

UNTESTED against real hardware - see README.
"""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.device_tracker import SourceType, TrackerEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .coordinator import QManagerConfigEntry, QManagerCoordinator, QManagerGpsCoordinator
from .entity import QManagerEntity
from .parser import first, parse_nmea_coord, safe_float, safe_int, split_csv

_LOGGER = logging.getLogger(__name__)

# +QGPSLOC: <utc>,<lat>,<lon>,<hdop>,<altitude>,<fix>,<cog>,<spkm>,<spkn>,<date>,<nsat>
# Ported from the sibling integration, where this layout was confirmed
# against a real fix - not re-verified against this backend.
_FIELDS = (
    "utc", "lat", "lon", "hdop", "altitude", "fix", "cog", "spkm", "spkn",
    "date", "nsat",
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: QManagerConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Quectel QManager GPS device tracker from a config entry."""
    async_add_entities(
        [QManagerGpsTracker(entry.runtime_data.gps, entry.runtime_data.main)]
    )


class QManagerGpsTracker(QManagerEntity, TrackerEntity):
    """GPS location from the modem's own GNSS receiver (+QGPSLOC).

    Not every board has a GPS antenna wired up - if this hardware
    doesn't support it, +QGPSLOC just returns an AT ERROR and this
    entity's location stays unset (unknown) rather than erroring.
    """

    _attr_translation_key = "gps"
    _attr_source_type = SourceType.GPS

    def __init__(
        self,
        coordinator: QManagerGpsCoordinator,
        main_coordinator: QManagerCoordinator,
    ) -> None:
        super().__init__(coordinator, main_coordinator)
        self._attr_unique_id = f"{coordinator.host}_gps"

    def _fields(self) -> dict[str, str | None]:
        parts = split_csv(first(self.coordinator.data, "QGPSLOC"), len(_FIELDS))
        return dict(zip(_FIELDS, parts))

    @property
    def latitude(self) -> float | None:
        return parse_nmea_coord(self._fields().get("lat"), degree_digits=2)

    @property
    def longitude(self) -> float | None:
        return parse_nmea_coord(self._fields().get("lon"), degree_digits=3)

    @property
    def location_accuracy(self) -> int:
        # Rough heuristic (HDOP * ~5m typical GPS user range error) - not
        # an officially documented Quectel conversion.
        hdop = safe_float(self._fields().get("hdop"))
        return round(hdop * 5) if hdop is not None else 0

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        f = self._fields()
        return {
            "hdop": safe_float(f.get("hdop")),
            "altitude_m": safe_float(f.get("altitude")),
            "fix_type": safe_int(f.get("fix")),
            "satellites": safe_int(f.get("nsat")),
            "speed_kmh": safe_float(f.get("spkm")),
            "utc_time": f.get("utc"),
            "fix_date": f.get("date"),
        }
