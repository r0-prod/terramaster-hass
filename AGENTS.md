# AGENTS.md

Working notes for anyone — human or agent — developing this integration.

## Layout

```
custom_components/terramaster/
  tos/            standalone async TOS 6 client — NO Home Assistant imports
    crypto.py     request-envelope crypto (see docs/TOS_API.md)
    client.py     session, login, GET/POST wrappers, endpoint methods
    models.py     payload parsing -> dataclasses
  coordinator.py  one DataUpdateCoordinator; also the overheat watchdog
  entity.py       TerraMasterEntity + TerraMasterDiskEntity bases
  sensor.py binary_sensor.py select.py
  config_flow.py  setup, reauth and options flows
  icons.json      icon translations (do NOT use _attr_icon)
  strings.json    + translations/en.json — keep the two identical
  brand/          icon/logo PNGs served by HA >= 2026.3
tools/            probe_tos.py (dump the API), ha.py (drive HA over REST)
docs/TOS_API.md   the reverse-engineered protocol
```

**`tos/` must stay free of Home Assistant imports.** That is what lets you drive a real
NAS from a shell without booting HA, which is how nearly all of this was developed.

## Setup

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
cp .env.local.example .env.local   # gitignored; fill in host + credentials
.venv/bin/python -m pytest tests/ -q
```

`.env.local` holds `TOS_HOST`, `TOS_PORT`, `TOS_USER`, `TOS_PASS`, `HA_URL`, `HA_TOKEN`.
It is gitignored and must never be committed.

## Working against a real NAS

```bash
.venv/bin/python tools/probe_tos.py         # dump every endpoint -> tools/captures/
.venv/bin/python tools/ha.py states --filter terramaster
```

`tools/captures/` is gitignored. `tests/test_captures.py` parses whatever is there and
skips when it is absent, so it doubles as a firmware-drift check: after a TOS upgrade,
re-run `probe_tos.py` and then the tests.

## Invariants — break these and things fail subtly

1. **`POST /v2/hardware/set` takes the whole hardware object, not a delta.** Always
   read `/v2/hardware/` first and merge. `coordinator.async_set_hardware()` does this.
2. **Trust `fan.is_auto` before `fan.level`.** In automatic mode TOS reports the level
   it is currently driving, not `-1`.
3. **The CSRF token goes on every request, GETs included.** Without it TOS answers 403
   even with a valid session cookie.
4. **The client needs `aiohttp.CookieJar(unsafe=True)`** — the default jar silently
   drops cookies set by a bare IP address.
5. **The AES salt and `X-Security-Code` must derive from the same `Date` header**, or
   the server cannot reconstruct the key.
6. Only request *bodies* are encrypted. GETs and all responses are plaintext JSON.
7. **Errors arrive as HTTP 200 with `code: false`.** Check the body, not the status.
   `code_num` 117/41/14/27/28/97 mean the session is gone and must trigger a
   re-login; 90 means the account lacks rights and re-logging in will not help.

## Entity conventions

- Every entity has a `translation_key`; icons live in `icons.json`. `_attr_icon` is
  discouraged by Home Assistant — do not reintroduce it.
- Entities named after a drive/volume/pool use `_attr_translation_placeholders`
  (`{disk_name}`, `{volume_name}`, `{pool_name}`), never a hand-written `name` property.
- Unique IDs are `{entry_id}_{key}`; drive keys use the **serial**, so an entity follows
  its drive across bays. Drives are looked up by slot at read time.
- Set `PARALLEL_UPDATES = 0` in every platform — all data comes from one refresh.
- User-facing failures raise `HomeAssistantError` with a `translation_key` that exists
  under `exceptions` in `strings.json`.

### Adding a sensor

1. Add the endpoint to `tos/client.py` and parse it in `tos/models.py` into `NasData`.
2. Fetch it in `TerraMasterCoordinator._async_update_data` and map it in `_assemble`.
3. Add a `TerraMasterSensorDescription` (or a class, if per-drive) in `sensor.py`.
4. Add the name to `strings.json`, copy to `translations/en.json`, add an icon to
   `icons.json`.
5. Cover it in `tests/test_integration.py`, which loads the component in a real HA.

## Quality scale

Bronze and Silver rules are met: `config-flow`, `entity-unique-id`, `has-entity-name`,
`runtime-data`, `test-before-configure`, `unique-config-entry`,
`config-flow-test-coverage`, `config-entry-unloading`, `reauthentication-flow`,
`parallel-updates`, `action-exceptions`.

## Brand assets

`custom_components/terramaster/brand/` holds `icon`/`dark_icon`/`logo`/`dark_logo` as
`.png` and `@2x.png`. Icons are 256²/512², logos are 256/512 tall. Dark variants are the
**white** mark, for dark backgrounds. All are RGBA with a transparent background.

## Releasing

Bump `version` in `custom_components/terramaster/manifest.json`, tag `vX.Y.Z`, and
publish a **GitHub Release** — HACS reads the Releases API, and a bare tag is not a
release.
