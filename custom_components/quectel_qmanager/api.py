"""Async client for QManager's cookie-session JSON API.

UNTESTED against real hardware - built from QManager-RM520N's
docs/API-REFERENCE.md and docs/ARCHITECTURE.md, not verified against a
live device. See this integration's README.
"""
from __future__ import annotations

import logging
import time

import aiohttp

from .const import FETCH_DATA_PATH, LOGIN_PATH, REBOOT_PATH, SEND_COMMAND_PATH

_LOGGER = logging.getLogger(__name__)

# Docs: 5 failed login attempts / 5-minute window triggers a 5-minute
# lockout. This cooldown is a defensive guess at a safe retry cadence to
# avoid ever tripping that lockout from a re-auth loop - the exact
# lockout window itself hasn't been independently confirmed.
_LOGIN_RETRY_COOLDOWN_SECONDS = 60


class QManagerError(Exception):
    """Base error for the QManager client."""


class QManagerAuthError(QManagerError):
    """Raised when login fails or a session can't be re-established."""


class QManagerConnectionError(QManagerError):
    """Raised when the modem can't be reached or errors out."""


class QManagerClient:
    """Thin async wrapper around QManager's cookie-session JSON API.

    Uses its own dedicated aiohttp.ClientSession (not Home Assistant's
    shared one) so this integration has explicit control over the
    session's cookie jar and lifecycle - qm_session/qm_logged_in cookies
    are stored and resent automatically by aiohttp as long as the same
    ClientSession instance is reused across requests, which is exactly
    what async_setup_entry/async_unload_entry manage.
    """

    def __init__(self, session: aiohttp.ClientSession, host: str, password: str) -> None:
        self._session = session
        self._host = host
        self._password = password
        self._last_login_failure: float | None = None

    def _url(self, path: str) -> str:
        return f"https://{self._host}{path}"

    async def login(self) -> None:
        """POST the configured password to /auth/login.sh."""
        now = time.monotonic()
        if (
            self._last_login_failure is not None
            and now - self._last_login_failure < _LOGIN_RETRY_COOLDOWN_SECONDS
        ):
            raise QManagerAuthError(
                "Not retrying login yet - backing off after a recent "
                "failure rather than risk tripping QManager's rate limit "
                "(5 attempts / 5 min -> 5 min lockout, per its docs)"
            )
        try:
            async with self._session.post(
                self._url(LOGIN_PATH),
                json={"password": self._password},
                ssl=False,
                timeout=aiohttp.ClientTimeout(total=15.0),
            ) as resp:
                body = await resp.json(content_type=None)
        except aiohttp.ClientError as err:
            raise QManagerConnectionError(str(err)) from err
        except TimeoutError as err:
            raise QManagerConnectionError("Timed out logging in") from err

        if not body.get("success"):
            self._last_login_failure = now
            raise QManagerAuthError(body.get("detail", "Login failed"))
        self._last_login_failure = None

    async def _request(
        self,
        method: str,
        path: str,
        json_body: dict | None = None,
        timeout: float = 15.0,
        _retried: bool = False,
    ) -> dict:
        try:
            async with self._session.request(
                method,
                self._url(path),
                json=json_body,
                ssl=False,  # matches the sibling integration's self-signed cert assumption
                timeout=aiohttp.ClientTimeout(total=timeout),
            ) as resp:
                if resp.status == 401:
                    if _retried:
                        raise QManagerAuthError("Still unauthorized after re-login")
                    _LOGGER.debug("Session expired or missing, re-authenticating")
                    await self.login()
                    return await self._request(
                        method, path, json_body, timeout, _retried=True
                    )
                resp.raise_for_status()
                # content_type=None: defensive against the CGI scripts not
                # setting an exact "application/json" header, unconfirmed
                # either way without a live device to check.
                return await resp.json(content_type=None)
        except aiohttp.ClientError as err:
            raise QManagerConnectionError(str(err)) from err
        except TimeoutError as err:
            raise QManagerConnectionError(f"Timed out waiting for {path}") from err

    async def fetch_data(self) -> dict:
        """GET the cached ModemStatus blob (/at_cmd/fetch_data.sh)."""
        return await self._request("GET", FETCH_DATA_PATH)

    async def send_command(self, command: str, timeout: float = 15.0) -> str:
        """POST a raw AT command (/at_cmd/send_command.sh); return its response text."""
        body = await self._request(
            "POST", SEND_COMMAND_PATH, json_body={"command": command}, timeout=timeout
        )
        if not body.get("success"):
            raise QManagerConnectionError(
                body.get("detail", f"send_command failed for: {command}")
            )
        return body.get("response", "")

    async def reboot(self) -> None:
        """POST /system/reboot.sh. No request body."""
        try:
            await self._request("POST", REBOOT_PATH)
        except QManagerConnectionError:
            # Docs: the response is flushed before the device reboots
            # asynchronously - a dropped connection right after this call
            # is the expected/successful case, not necessarily a failure.
            _LOGGER.debug("Connection dropped after reboot request (expected)")
