"""Response parsing helpers for Quectel QManager.

Most of fetch_data.sh's fields are just real JSON - direct dict access,
no text parsing needed (a real simplification versus the sibling
simpleadmin integration, which had to regex-parse raw AT reply text for
everything). The exceptions are send_command.sh's raw AT text responses
(used only for GPS here, since it has no native QManager feature) and
safe nested-dict access for fields whose presence/nullability isn't
confirmed against a live device.

UNTESTED against real hardware - see README.
"""
from __future__ import annotations

import re
from typing import Any

_ANSI_RE = re.compile(r"\x1b\[[0-9;]*[mG]")
_LINE_RE = re.compile(r"^\+([A-Za-z0-9_]+):\s?(.*)$")


def safe_get(data: dict | None, *path: str, default: Any = None) -> Any:
    """Nested dict.get() that never raises on a missing/wrong-typed key."""
    current: Any = data
    for key in path:
        if not isinstance(current, dict):
            return default
        current = current.get(key)
    return default if current is None else current


def safe_int(value: Any) -> int | None:
    """Best-effort int conversion; returns None instead of raising."""
    if value is None:
        return None
    try:
        return int(value)
    except (ValueError, TypeError):
        return None


def safe_float(value: Any) -> float | None:
    """Best-effort float conversion; returns None instead of raising."""
    if value is None:
        return None
    try:
        return float(value)
    except (ValueError, TypeError):
        return None


def strip_ansi(text: str) -> str:
    """Remove ANSI color escape sequences, if any are present."""
    return _ANSI_RE.sub("", text)


def _strip_echo(lines: list[str]) -> list[str]:
    """Drop a leading echoed-command line, if present.

    send_command.sh's documented example response starts directly with
    the AT reply ("+QENG: ..."), unlike the sibling integration's
    get_atcommand (which always echoes the command first) - so this is
    likely a no-op here. Kept anyway as cheap, harmless insurance in case
    that assumption is wrong: no real AT reply line starts with a bare
    "AT" token, so it's safe to drop the first line if it does.
    """
    if lines and lines[0].strip().upper().startswith("AT"):
        return lines[1:]
    return lines


def parse_at_response(raw: str) -> dict[str, list[str]]:
    """Parse a send_command.sh AT reply into {RESPONSE_KEY: [raw_value, ...]}.

    List-valued per key for consistency with the sibling integration,
    which found real commands (there, +QTEMP/+QMAP/+QCAINFO) can produce
    multiple lines under one key - not confirmed to happen on this
    platform's send_command.sh, but cheap insurance either way.
    """
    result: dict[str, list[str]] = {}
    lines = _strip_echo(strip_ansi(raw).replace("\r", "").splitlines())
    for line in lines:
        line = line.strip()
        if not line or line in ("OK", "ERROR"):
            continue
        match = _LINE_RE.match(line)
        if match:
            key, value = match.groups()
            result.setdefault(key.upper(), []).append(value.strip())
    return result


def first(data: dict[str, list[str]], key: str) -> str | None:
    """Return the first (or only) line's raw value for `key`, if any."""
    values = data.get(key)
    return values[0] if values else None


def split_csv(value: str | None, expected: int | None = None) -> list[str | None]:
    """Split a comma-separated AT field into parts, padding/truncating to `expected`."""
    parts: list[str | None] = [p.strip() for p in value.split(",")] if value else []
    if expected is not None:
        parts = (parts + [None] * expected)[:expected]
    return parts


def unquote(value: str | None) -> str | None:
    """Strip surrounding double quotes from an AT field value, if present."""
    if value is None:
        return None
    value = value.strip()
    if len(value) >= 2 and value[0] == '"' and value[-1] == '"':
        return value[1:-1]
    return value


def parse_nmea_coord(value: str | None, degree_digits: int) -> float | None:
    """Convert a +QGPSLOC-style coordinate into signed decimal degrees.

    Ported from the sibling simpleadmin integration, where this was
    confirmed against a real GPS fix (that integration talks to the same
    module family's GNSS engine via the same AT+QGPSLOC command). Not
    re-verified against this specific backend/platform.
    """
    if not value:
        return None
    value = value.strip()
    hemisphere = value[-1:].upper()
    numeric = value[:-1]
    if "." not in numeric or len(numeric) <= degree_digits:
        return None
    degrees = safe_float(numeric[:degree_digits])
    minutes = safe_float(numeric[degree_digits:])
    if degrees is None or minutes is None:
        return None
    decimal = degrees + minutes / 60
    if hemisphere in ("S", "W"):
        decimal = -decimal
    return round(decimal, 6)
