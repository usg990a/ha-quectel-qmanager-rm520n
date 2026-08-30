"""DataUpdateCoordinators for Quectel QManager.

QManagerCoordinator polls /at_cmd/fetch_data.sh - one cached JSON blob
the QManager poller already refreshes server-side on its own tiered
schedule, so there's no need to replicate that tiering on our side.

QManagerGpsCoordinator is separate and slower: GPS has no native
QManager feature at all, so it issues its own raw AT commands via
send_command.sh, same pattern as the sibling simpleadmin integration.

UNTESTED against real hardware - see README.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import timedelta
import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import QManagerAuthError, QManagerClient, QManagerConnectionError
from .const import (
    AT_CMD_GPS_ENABLE,
    AT_CMD_GPS_LOC,
    DOMAIN,
    FAST_POLL_DURATION_SECONDS,
    FAST_POLL_INTERVAL_SECONDS,
)
from .parser import parse_at_response

_LOGGER = logging.getLogger(__name__)


class QManagerCoordinator(DataUpdateCoordinator[dict]):
    """Polls the cached ModemStatus blob (network/lte/nr/device/connectivity/traffic)."""

    def __init__(
        self,
        hass: HomeAssistant,
        client: QManagerClient,
        host: str,
        update_interval: int,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN}_main",
            update_interval=timedelta(seconds=update_interval),
        )
        self.client = client
        self.host = host

    async def _async_update_data(self) -> dict:
        try:
            return await self.client.fetch_data()
        except QManagerAuthError as err:
            raise UpdateFailed(f"Authentication failed: {err}") from err
        except QManagerConnectionError as err:
            raise UpdateFailed(f"Could not reach modem: {err}") from err

    def async_start_fast_poll(
        self,
        interval: float = FAST_POLL_INTERVAL_SECONDS,
        duration: float = FAST_POLL_DURATION_SECONDS,
    ) -> None:
        """Poll more often for a window after a connection-disrupting action
        (radio cycle, reboot), instead of waiting up to update_interval to
        notice the reconnect. Mirrors the sibling integration's mechanism.
        """
        self.hass.async_create_background_task(
            self._fast_poll(interval, duration),
            name=f"{DOMAIN}_fast_poll",
        )

    async def _fast_poll(self, interval: float, duration: float) -> None:
        elapsed = 0.0
        while elapsed < duration:
            await asyncio.sleep(interval)
            elapsed += interval
            await self.async_request_refresh()


class QManagerGpsCoordinator(DataUpdateCoordinator[dict[str, list[str]]]):
    """Polls GPS location via raw AT (no native QManager feature for this)."""

    def __init__(
        self,
        hass: HomeAssistant,
        client: QManagerClient,
        host: str,
        update_interval: int,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN}_gps",
            update_interval=timedelta(seconds=update_interval),
        )
        self.client = client
        self.host = host

    async def _async_setup(self) -> None:
        """Try enabling GNSS once, if this hardware supports it."""
        try:
            result = await self.client.send_command(AT_CMD_GPS_ENABLE)
            _LOGGER.info("GPS enable result: %s", result)
        except (QManagerAuthError, QManagerConnectionError) as err:
            # Non-fatal: hardware may just not have GNSS wired up, same
            # as on the sibling integration.
            _LOGGER.warning("Could not enable GPS: %s", err)

    async def _async_update_data(self) -> dict[str, list[str]]:
        try:
            raw = await self.client.send_command(AT_CMD_GPS_LOC)
        except QManagerAuthError as err:
            raise UpdateFailed(f"Authentication failed: {err}") from err
        except QManagerConnectionError as err:
            raise UpdateFailed(f"Could not reach modem: {err}") from err
        return parse_at_response(raw)


# Shared type for code that works with either coordinator (e.g. the common
# entity base).
QManagerAnyCoordinator = QManagerCoordinator | QManagerGpsCoordinator


@dataclass
class QManagerRuntimeData:
    """Both coordinators, stored together on the config entry."""

    main: QManagerCoordinator
    gps: QManagerGpsCoordinator


# Typed alias for this integration's config entries. Plain assignment
# rather than PEP 695 `type` syntax to stay safe across Python minor
# versions.
QManagerConfigEntry = ConfigEntry[QManagerRuntimeData]
