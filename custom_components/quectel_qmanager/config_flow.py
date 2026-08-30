"""Config flow for Quectel QManager.

UNTESTED against real hardware - see README.
"""
from __future__ import annotations

import logging
from typing import Any

import aiohttp
import voluptuous as vol

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_HOST, CONF_PASSWORD
from homeassistant.helpers.aiohttp_client import async_create_clientsession

from .api import QManagerAuthError, QManagerClient, QManagerConnectionError
from .const import DEFAULT_HOST, DOMAIN

_LOGGER = logging.getLogger(__name__)

STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_HOST, default=DEFAULT_HOST): str,
        vol.Required(CONF_PASSWORD): str,
    }
)


class QManagerConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Quectel QManager.

    Assumes QManager's own first-time setup wizard has already been
    completed via its web UI (a password already exists) - this flow
    doesn't perform first-time setup itself, matching the sibling
    integration's assumption that credentials pre-exist.
    """

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}

        if user_input is not None:
            await self.async_set_unique_id(user_input[CONF_HOST])
            self._abort_if_unique_id_configured()

            # A dedicated session (not the shared HA one), same
            # cookie_jar=unsafe=True reasoning as __init__.py (aiohttp
            # drops cookies for bare-IP hosts otherwise). Do NOT close
            # this manually - sessions created via async_create_clientsession
            # are tracked and cleaned up by Home Assistant itself; calling
            # session.close() here trips a HA-level warning (confirmed
            # against real hardware) and fights its own lifecycle
            # management instead of using it.
            session = async_create_clientsession(
                self.hass, verify_ssl=False, cookie_jar=aiohttp.CookieJar(unsafe=True)
            )
            client = QManagerClient(
                session, user_input[CONF_HOST], user_input[CONF_PASSWORD]
            )
            try:
                await client.login()
            except QManagerAuthError:
                errors["base"] = "invalid_auth"
            except QManagerConnectionError:
                errors["base"] = "cannot_connect"
            except Exception:  # noqa: BLE001
                _LOGGER.exception("Unexpected error validating QManager connection")
                errors["base"] = "unknown"
            else:
                return self.async_create_entry(
                    title=f"Quectel Modem ({user_input[CONF_HOST]})",
                    data=user_input,
                )

        return self.async_show_form(
            step_id="user", data_schema=STEP_USER_DATA_SCHEMA, errors=errors
        )
