# Quectel QManager (RM520N-GL) — Home Assistant integration

Home Assistant integration for a Quectel RM520N-GL modem running
[dr-dolomite/QManager-RM520N](https://github.com/dr-dolomite/QManager-RM520N),
the successor to `iamromulan/quectel-rgmii-toolkit`'s `simpleadmin` (see
the sibling repo, [ha-quectel-simpleadmin](https://github.com/usg990a/ha-quectel-simpleadmin),
for that toolkit). QManager is a full rewrite with a different transport
entirely — cookie-session JSON API instead of Basic-Auth AT-text-over-CGI
— so this is a separate integration, not a variant of the sibling one.
See that repo's history for why they're kept apart rather than unified.

## ⚠️ UNTESTED against real hardware

Every endpoint path, field name, JSON shape, and behavioral assumption in
this codebase comes from reading QManager's own `docs/API-REFERENCE.md`
and `docs/ARCHITECTURE.md` — **none of it has been run against a live
device.** Treat this as a well-reasoned first draft, not a verified
integration. Expect real mismatches on first contact: a field that's
`null` instead of absent, a nesting level that's not quite what the docs
example showed, a response wrapper that isn't exactly `{"success":
true, ...}` for every endpoint, session/cookie behavior that doesn't
match the documented flow, etc.

**When you do get hardware access, work through this in order** (same
methodology used to build and debug the sibling integration — verify
against real output before trusting any parsing, don't guess a second
time when a first guess turns out wrong):

1. **Auth first.** Confirm `POST /auth/login.sh` with `{"password":
   "..."}` actually sets `qm_session`/`qm_logged_in` cookies and that
   `aiohttp`'s cookie jar carries them on the next request without extra
   code. If this doesn't just work, it's the whole integration blocked,
   not one sensor — debug this before anything else.
2. **`GET /at_cmd/fetch_data.sh` raw output.** Compare the real JSON
   against the shape `sensor.py`'s `_network`/`_lte`/`_nr`/`_device`/
   `_connectivity`/`_traffic` helpers assume. This is where the most
   mismatches are likely, since the doc's example is illustrative, not a
   schema dump.
3. **`POST /at_cmd/send_command.sh`** with something harmless like `{"command":
   "AT+CGMR"}` — confirm the response shape and whether `response`
   includes an echoed command line the way the sibling integration's
   `get_atcommand` does (this integration's `_strip_echo()` assumes it
   probably doesn't, but is written to no-op safely either way).
4. **GPS** (`AT+QGPS=1` / `AT+QGPSLOC?` via `send_command.sh`) — confirms
   whether raw AT passthrough for commands outside QManager's own
   feature set behaves the same as the sibling integration found on
   simpleadmin's `get_atcommand`.
5. **Cycle Radio** (`AT+CFUN=0` then `AT+CFUN=1`) — start with the
   conservative `CYCLE_RADIO_DELAY_SECONDS = 3` default in `const.py`
   and only lower it after confirming it cycles cleanly, the way the
   sibling integration tested 3s → 1s → 0s live before settling on 0.
6. **Reboot** — confirm `POST /system/reboot.sh` actually drops the
   connection the way the docs describe, and that the fast-poll burst
   afterward correctly catches the reconnect.

## Requirements

- A Quectel RM520N-GL modem running QManager, with its first-time setup
  wizard already completed (a password already set) — this integration's
  config flow doesn't perform first-time setup itself
- The QManager password (host defaults to `192.168.225.1`, same as the
  sibling toolkit's default — not independently confirmed for QManager)
- Home Assistant with `custom_components/` writable

## Installing

Same pattern as the sibling integration — copy or bind-mount
`custom_components/quectel_qmanager/` into Home Assistant's
`custom_components/` directory, then restart Home Assistant.

## Configuring

**Settings → Devices & Services → Add Integration → "Quectel QManager
(RM520N-GL)"**, enter the modem's host and password. The connection is
verified with a real login attempt before the entry is created — note
QManager rate-limits failed logins (5 attempts / 5 min → 5 min lockout
per its docs), so don't hammer this if it's failing; check the password
rather than retrying repeatedly.

## Architecture

Two coordinators, for a different reason than the sibling integration's
fast/slow split:

- **`QManagerCoordinator`** (`DEFAULT_SCAN_INTERVAL`, 5s default) polls
  `GET /at_cmd/fetch_data.sh` — one cached JSON blob that QManager's own
  `qmanager_poller` daemon already refreshes server-side on its own
  tiered schedule (~2s hot fields like signal, ~30s warm fields like
  temperature/SIM, once at boot for identity). Polling faster than the
  poller's own hot tier doesn't get fresher data, just re-reads the same
  cache — so unlike the sibling integration, there's no need for us to
  split *this* data into fast/slow tiers ourselves; the server already
  did that.
- **`QManagerGpsCoordinator`** (`DEFAULT_GPS_SCAN_INTERVAL`, 60s default)
  polls GPS via raw AT, since GPS has no native QManager feature at all
  (confirmed: nothing GPS/GNSS/location-related anywhere in the ~80
  documented endpoints). Same reasoning as the sibling integration's
  slow coordinator: location for a parked vehicle doesn't need frequent
  polling.

Identity (manufacturer/model/firmware/IMEI/etc.) is part of
`fetch_data.sh`'s regular payload, not a separate one-time fetch like
the sibling integration needed — `entity.py` always reads it from the
main coordinator regardless of which coordinator a given entity
otherwise subscribes to for live updates.

## What it creates

One device, with manufacturer/model/firmware/IMEI from `fetch_data.sh`'s
`device` block, and:

**Sensors**: Network Type, Carrier, Service Status, APN, WAN IPv4/IPv6,
Carrier Aggregation (disabled by default); LTE band/RSRP/RSRQ/SINR/Cell
ID/PCI/TAC; NR (5G) band/RSRP/RSRQ/SINR/PCI; Temperature, CPU Usage,
Memory Used, Last Restart; Manufacturer/Model/Firmware/IMEI always
enabled, IMSI/ICCID/Phone Number disabled by default; Latency, Packet
Loss; Download/Upload Rate, Data Received/Sent.

**Binary sensor**: Internet Connection — QManager's own `qmanager_ping`
daemon result (`connectivity.internet_available`), a real connectivity
probe with a primary+fallback target URL, not an AT/RF-state inference.
Notably richer than the sibling integration's single ping: latency,
average latency, jitter, and packet loss are all available as
attributes here already, without needing our own history tracking.

**Device tracker**: GPS Location — raw AT, same caveats as the sibling
integration (not every board has GNSS wired up; fails soft to unset
location rather than erroring).

**Buttons**: Reboot (QManager's native `POST /system/reboot.sh` — a real
endpoint exists here, so it's used instead of raw `AT+CFUN=1,1`), Cycle
Radio (`AT+CFUN=0` then `AT+CFUN=1` — no native endpoint for this
specific action, raw AT via `send_command.sh`, same as the sibling
integration). Both trigger a fast-poll burst afterward
(`FAST_POLL_INTERVAL_SECONDS`/`FAST_POLL_DURATION_SECONDS` in
`const.py`) to catch the reconnect quickly.

## Deliberately out of scope for this first pass

- **Cell/neighbor scan results.** QManager actually has proper async
  start/status endpoints for both (`/at_cmd/cell_scan_start.sh` +
  `cell_scan_status.sh`), which the sibling integration's simpleadmin
  backend never had (only fire-and-log). This is a genuine opportunity
  — a real results sensor, not just a button — worth building once the
  basics here are validated against real hardware.
- **QManager's native `watchcat` feature** (`/monitoring/watchdog.sh`) —
  a built-in, tiered auto-recovery watchdog running on the modem itself,
  independent of Home Assistant. This overlaps with the "Cycle Radio on
  Sustained Disconnect" automation built for the sibling integration
  (kept in that project's own HA config, not committed to either repo).
  Worth deciding whether to use QManager's native watchdog instead of —
  or carefully coordinated with, to avoid double-intervention — an
  HA-side automation, once this integration is actually running.
- Band locking, network mode, APN control, tower/frequency locking, SIM
  profiles, DPI/video optimizer, VPN/Tailscale settings — QManager has
  native endpoints for all of these (see its own `docs/API-REFERENCE.md`),
  well beyond what the sibling integration ever attempted. Real
  expansion potential once the foundation here is confirmed working.

## Known unknowns (not just "untested" — genuinely unconfirmed from the docs alone)

- **TLS/cert setup.** `ssl=False` is assumed (matching the sibling
  integration's self-signed-cert handling), but QManager's own docs
  didn't explicitly confirm a self-signed cert on this platform.
- **Exact JSON nullability/absence behavior** for `lte`/`nr` sections
  when the modem isn't actively using that RAT (idle state fields vs.
  the whole section being absent) — `safe_get()` throughout `sensor.py`
  handles either gracefully, but which one actually happens is unverified.
- **Login rate-limit window and lockout duration** — the 60s cooldown in
  `api.py` between our own retry attempts is a defensive guess, not a
  value confirmed against the documented "5 attempts / 5 min → 5 min
  lockout."
- **`CYCLE_RADIO_DELAY_SECONDS` default (3s)** — the sibling integration
  found 0s worked fine after live testing, but that was a different
  backend on the same module family, not the same confirmation.
