# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A Home Assistant `custom_components` integration (domain `quectel_qmanager`) for a
Quectel RM520N-GL modem running [dr-dolomite/QManager-RM520N](https://github.com/dr-dolomite/QManager-RM520N).
QManager is the successor to `iamromulan/quectel-rgmii-toolkit`'s `simpleadmin`,
which has a sibling integration at [ha-quectel-simpleadmin](https://github.com/usg990a/ha-quectel-simpleadmin).
These are deliberately **separate** integrations, not variants of one codebase —
the two backends are mutually exclusive per device, use fundamentally different
auth models (cookie session here vs. Basic Auth there), and most of the sibling's
AT-reply-text parsing logic doesn't apply to QManager's JSON API at all. When in
doubt about a design choice here, check whether the sibling repo already solved
the same problem differently for a *reason* (documented in its own commit
history) before assuming this repo should match it.

## ⚠️ UNTESTED against real hardware — the most important thing to know

Every endpoint path, JSON field name/shape, and behavioral assumption in this
codebase was derived from reading QManager's own `docs/API-REFERENCE.md` and
`docs/ARCHITECTURE.md` — **none of it has been run against a live device.**
This has direct consequences for how to work on this repo:

- Do not add comments claiming something is "confirmed against real output" —
  that phrasing is reserved (and used extensively in the sibling repo) for
  things actually verified against live device responses. Here, say what the
  assumption is and where it came from (which doc, which example payload).
- Write parsing defensively (`safe_get`/`safe_int`/`safe_float` in `parser.py`)
  rather than assuming a field's presence, type, or nullability.
- The README's "When you do get hardware access, work through this in order"
  checklist is the actual test plan — auth first, then `fetch_data.sh` shape,
  then `send_command.sh`, then GPS, then Cycle Radio delay, then reboot. Follow
  that order when real hardware becomes available rather than validating
  randomly; each step's config depends on the previous one actually working.
- The README's "Known unknowns" section lists specific unconfirmed assumptions
  (TLS/cert setup, LTE/NR section nullability, login rate-limit window,
  `CYCLE_RADIO_DELAY_SECONDS` default) — update it as each gets resolved
  instead of just deleting the caveat.

## Validating changes

There's no test suite and no build step (this is a set of Python modules HA
loads directly, plus static JSON). What actually gets run during development:

```bash
# Syntax-check every module
python3 -m py_compile custom_components/quectel_qmanager/*.py

# Validate all JSON files
for f in custom_components/quectel_qmanager/manifest.json \
         custom_components/quectel_qmanager/strings.json \
         custom_components/quectel_qmanager/translations/en.json \
         hacs.json; do
  python3 -c "import json; json.load(open('$f')); print('OK: $f')"
done

# strings.json and translations/en.json must stay identical
diff custom_components/quectel_qmanager/strings.json \
     custom_components/quectel_qmanager/translations/en.json && echo identical
```

**Every `translation_key` used in code must have a matching entry in both
`strings.json` and `translations/en.json`**, under `entity.<platform>.<key>`.
Entity descriptions set it via the `translation_key=` dataclass field;
one-off entity classes (`QManagerCycleRadioButton`, `QManagerGpsTracker`) set
it via `_attr_translation_key = "..."` instead — check both styles when
cross-referencing:

```bash
cd custom_components/quectel_qmanager
grep -oE 'translation_key="[a-z_0-9]+"' *.py | sed -E 's/.*"(.*)"/\1/' | sort -u
grep -oE '_attr_translation_key = "[a-z_0-9]+"' *.py | sed -E 's/.*"(.*)"/\1/' | sort -u
```

After `strings.json` changes, re-sync: `cp strings.json translations/en.json`.

There's no live Home Assistant instance available in this environment to test
against — changes get compiled/validated here, then the actual load-and-run
test happens on the user's HA instance (outside this repo).

## Architecture

**Two `DataUpdateCoordinator`s, for different reasons than you might expect:**

- `QManagerCoordinator` (`coordinator.py`) polls `GET /at_cmd/fetch_data.sh` —
  one cached JSON blob that QManager's own `qmanager_poller` daemon already
  refreshes server-side on its own tiered schedule (~2s hot fields like signal,
  ~30s warm fields like temperature, once at boot for identity). Because the
  *server* already tiers the data, this integration doesn't need to replicate
  that tiering with multiple coordinators the way the sibling integration does
  for its raw-AT polling — one coordinator at `DEFAULT_SCAN_INTERVAL` covers
  network/LTE/NR/device/connectivity/traffic all at once.
- `QManagerGpsCoordinator` is separate and slower (`DEFAULT_GPS_SCAN_INTERVAL`)
  because GPS has no native QManager feature at all — confirmed absent from
  the ~80 documented endpoints — so it's the one thing still done via raw AT
  (`AT+QGPS=1` / `AT+QGPSLOC?`) through `send_command.sh`.

Both coordinators are bundled into `QManagerRuntimeData` (a small dataclass)
and stored on `entry.runtime_data`; platforms pull `entry.runtime_data.main`
or `.gps` depending which coordinator they need.

**Identity lives inside the regular poll, not a separate fetch.** Unlike the
sibling integration (which has to fetch device identity once at startup
because simpleadmin has no equivalent to `fetch_data.sh`), here
manufacturer/model/firmware/IMEI are just part of the same cached blob. So
`QManagerEntity.__init__` (`entity.py`) always takes *two* coordinator
arguments — `coordinator` (whatever this specific entity subscribes to for
live updates) and `main_coordinator` (always the main one, used only to read
`.data["device"]` for `DeviceInfo`) — because a GPS entity's own coordinator
has no `"device"` key in its data at all. Every entity constructor across
`sensor.py`/`button.py`/`binary_sensor.py`/`device_tracker.py` follows this
same two-argument call pattern; when adding a new entity, match it even if
the entity happens to live on the main coordinator (pass it twice, as the
existing sensors/buttons do), not just for GPS.

**Auth is real session state, not a stateless header.** `api.py`'s
`QManagerClient` holds its own dedicated `aiohttp.ClientSession` (created in
`__init__.py`/`config_flow.py`, not Home Assistant's shared session) so its
cookie jar (`qm_session`/`qm_logged_in`) persists correctly across requests.
`_request()` auto-retries once through `login()` on a `401`, then raises
`QManagerAuthError` rather than looping. `login()` itself has a
60s-since-last-failure cooldown before it will retry at all, specifically to
avoid tripping QManager's documented login rate limit (5 attempts / 5 min →
5 min lockout) from an unattended retry loop — don't remove this cooldown
without addressing the same risk another way.

**Entity description pattern**: `sensor.py` uses a frozen dataclass
(`QManagerSensorEntityDescription`) extending `SensorEntityDescription` with
a `value_fn`/optional `attrs_fn`, evaluated defensively in
`QManagerSensor.native_value`/`extra_state_attributes` (broad
`except Exception` around each, logged at debug, never raised) — so a bad
assumption about one field's shape degrades that one entity to `unknown`
rather than breaking the whole platform. `button.py` and `binary_sensor.py`
mix this pattern (for `Reboot`, which uses a plain
`ButtonEntityDescription`) with hand-written entity classes (for
`CycleRadioButton`, which needs a multi-step `async_press` with a delay
between two AT calls, and `GpsTracker`, which needs `TrackerEntity`'s
`latitude`/`longitude`/`location_accuracy` properties rather than a single
`native_value`). Follow whichever pattern fits — don't force a two-step
action or a multi-property entity into the single-`value_fn` shape.

**Fast-poll-after-action**: both `Reboot` and `CycleRadio` buttons call
`coordinator.async_start_fast_poll()` afterward (defined on
`QManagerCoordinator` only, not the GPS one) to catch the reconnect within
`FAST_POLL_INTERVAL_SECONDS` instead of waiting up to a full
`DEFAULT_SCAN_INTERVAL` cycle. This is a background `asyncio` task, not a
change to `update_interval` — the coordinator's normal schedule is untouched,
this just adds extra `async_request_refresh()` calls on top for a limited
window.
