"""The Quectel QManager integration.

UNTESTED against real hardware - see README.
"""
from __future__ import annotations

from homeassistant.const import CONF_HOST, CONF_PASSWORD, Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_create_clientsession

from .api import QManagerClient
from .const import DEFAULT_GPS_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL
from .coordinator import (
    QManagerConfigEntry,
    QManagerCoordinator,
    QManagerGpsCoordinator,
    QManagerRuntimeData,
)

PLATFORMS: list[Platform] = [
    Platform.SENSOR,
    Platform.BUTTON,
    Platform.BINARY_SENSOR,
    Platform.DEVICE_TRACKER,
]


async def async_setup_entry(hass: HomeAssistant, entry: QManagerConfigEntry) -> bool:
    """Set up Quectel QManager from a config entry."""
    # A dedicated session (not Home Assistant's shared one) so this
    # integration has explicit control over its own cookie jar/lifecycle
    # - QManager's session auth needs that state managed deliberately,
    # unlike the sibling integration's stateless Basic Auth.
    session = async_create_clientsession(hass, verify_ssl=False)
    client = QManagerClient(session, entry.data[CONF_HOST], entry.data[CONF_PASSWORD])

    main_coordinator = QManagerCoordinator(
        hass, client, entry.data[CONF_HOST], DEFAULT_SCAN_INTERVAL
    )
    gps_coordinator = QManagerGpsCoordinator(
        hass, client, entry.data[CONF_HOST], DEFAULT_GPS_SCAN_INTERVAL
    )
    await main_coordinator.async_config_entry_first_refresh()
    await gps_coordinator.async_config_entry_first_refresh()

    entry.runtime_data = QManagerRuntimeData(main=main_coordinator, gps=gps_coordinator)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: QManagerConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
