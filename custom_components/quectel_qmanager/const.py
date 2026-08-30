"""Constants for the Quectel QManager (RM520N-GL) integration.

UNTESTED against real hardware. Every path/field/command name here comes
from dr-dolomite/QManager-RM520N's docs/API-REFERENCE.md and
docs/ARCHITECTURE.md (reviewed, not run against a live device) - see
this integration's README for the full caveat and what to check first
when testing against real hardware.
"""
from __future__ import annotations

DOMAIN = "quectel_qmanager"

DEFAULT_HOST = "192.168.225.1"

# fetch_data.sh just reads a cache the QManager poller already refreshes
# server-side on its own tiered schedule (~2s hot fields, ~30s warm
# fields, once at boot for identity) - polling faster than the poller's
# own hot tier doesn't get us fresher data, just re-reads the same cache.
DEFAULT_SCAN_INTERVAL = 5  # seconds

# GPS has no native QManager feature (confirmed: no gps/gnss/location
# endpoint anywhere in API-REFERENCE.md's ~80 endpoints), so it's polled
# separately via raw AT, same as the sibling simpleadmin integration -
# and same reasoning for keeping it on a slower interval (location for a
# parked RV doesn't change often).
DEFAULT_GPS_SCAN_INTERVAL = 60  # seconds

API_BASE = "/cgi-bin/quecmanager"
LOGIN_PATH = f"{API_BASE}/auth/login.sh"
FETCH_DATA_PATH = f"{API_BASE}/at_cmd/fetch_data.sh"
SEND_COMMAND_PATH = f"{API_BASE}/at_cmd/send_command.sh"
REBOOT_PATH = f"{API_BASE}/system/reboot.sh"

# GNSS - same raw-AT approach as the sibling integration, just via
# send_command.sh instead of get_atcommand.
AT_CMD_GPS_ENABLE = "AT+QGPS=1"
AT_CMD_GPS_LOC = "AT+QGPSLOC?"

# Cycle Radio - no native endpoint for this specific action either; raw
# AT via send_command.sh. QManager's own docs/cfun-0-fix-analysis.md
# confirms CFUN=0/1 semantics match what we already rely on, and flags
# that any raw AT write on this platform must go through their qcmd/
# atcli_smd11 wrapper (which send_command.sh does) to respect
# /tmp/qmanager_at.lock and not collide with the poller.
AT_CMD_RADIO_OFF = "AT+CFUN=0"
AT_CMD_RADIO_ON = "AT+CFUN=1"
# The sibling simpleadmin integration found 0s worked fine on that
# hardware after testing 3s/1s/0s live. This is a different backend on
# the same module family, not the same confirmation - starting
# conservative until verified on this platform.
CYCLE_RADIO_DELAY_SECONDS = 3

# Reboot/Cycle Radio disrupt the connection; poll this often for this
# long afterward instead of waiting up to DEFAULT_SCAN_INTERVAL to notice
# the reconnect. Mirrors the sibling integration's fast-poll mechanism.
FAST_POLL_INTERVAL_SECONDS = 5
FAST_POLL_DURATION_SECONDS = 90
