"""Button platform for Quectel QManager.

Cell/neighbor scan are deliberately out of scope for this initial
scaffold - QManager actually has proper async start/status endpoints for
both (/at_cmd/cell_scan_start.sh + cell_scan_status.sh), which would let
this integration do something the sibling simpleadmin one couldn't
(a real results sensor instead of fire-and-log) - worth adding once this
has been validated against real hardware.

UNTESTED against real hardware - see README.
"""
from __future__ import annotations

import asyncio
import logging

from homeassistant.components.button import ButtonEntity, ButtonEntityDescription
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import AT_CMD_RADIO_OFF, AT_CMD_RADIO_ON, CYCLE_RADIO_DELAY_SECONDS
from .coordinator import QManagerConfigEntry, QManagerCoordinator
from .entity import QManagerEntity

_LOGGER = logging.getLogger(__name__)

REBOOT_DESCRIPTION = ButtonEntityDescription(
    key="reboot",
    translation_key="reboot",
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: QManagerConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Quectel QManager buttons from a config entry."""
    coordinator = entry.runtime_data.main
    async_add_entities(
        [
            QManagerRebootButton(coordinator),
            QManagerCycleRadioButton(coordinator),
        ]
    )


class QManagerRebootButton(QManagerEntity, ButtonEntity):
    """Reboot via QManager's native endpoint (POST /system/reboot.sh),
    rather than the raw AT+CFUN=1,1 the sibling integration uses - a
    real feature exists here, so prefer it over reimplementing via AT.
    """

    entity_description = REBOOT_DESCRIPTION

    def __init__(self, coordinator: QManagerCoordinator) -> None:
        super().__init__(coordinator, coordinator)
        self._attr_unique_id = f"{coordinator.host}_reboot"

    async def async_press(self) -> None:
        _LOGGER.info("Rebooting modem")
        await self.coordinator.client.reboot()
        self.coordinator.async_start_fast_poll()


class QManagerCycleRadioButton(QManagerEntity, ButtonEntity):
    """Radio-only reset (AT+CFUN=0, then AT+CFUN=1) - lighter than a full
    reboot, for when the modem still reports good signal but the actual
    connection is dead. No native QManager endpoint for this specific
    action, so it's raw AT via send_command.sh, same as the sibling
    integration. CYCLE_RADIO_DELAY_SECONDS defaults conservatively here
    (3s) since the sibling's confirmed-safe 0s was tested on a different
    backend, not this one.
    """

    _attr_translation_key = "cycle_radio"

    def __init__(self, coordinator: QManagerCoordinator) -> None:
        super().__init__(coordinator, coordinator)
        self._attr_unique_id = f"{coordinator.host}_cycle_radio"

    async def async_press(self) -> None:
        _LOGGER.debug("Cycling radio: %s", AT_CMD_RADIO_OFF)
        off_result = await self.coordinator.client.send_command(AT_CMD_RADIO_OFF)
        _LOGGER.info("Cycle radio (off) result:\n%s", off_result)

        await asyncio.sleep(CYCLE_RADIO_DELAY_SECONDS)

        _LOGGER.debug("Cycling radio: %s", AT_CMD_RADIO_ON)
        on_result = await self.coordinator.client.send_command(AT_CMD_RADIO_ON)
        _LOGGER.info("Cycle radio (on) result:\n%s", on_result)

        await self.coordinator.async_request_refresh()
        self.coordinator.async_start_fast_poll()
