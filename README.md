<p align="center">
  <img src="docs/logo.png" alt="TerraMaster" width="360">
</p>

<h1 align="center">TerraMaster NAS for Home Assistant</h1>

<p align="center">
  <a href="https://github.com/r0-prod/terramaster-hass/releases"><img src="https://img.shields.io/github/v/release/r0-prod/terramaster-hass?style=flat-square" alt="Release"></a>
  <a href="LICENSE"><img src="https://img.shields.io/github/license/r0-prod/terramaster-hass?style=flat-square" alt="License"></a>
  <a href="https://hacs.xyz"><img src="https://img.shields.io/badge/HACS-custom-41BDF5?style=flat-square" alt="HACS"></a>
</p>

Monitor drive temperatures and storage on a TerraMaster NAS, and control its fan —
locally, with no cloud account.

## Features

- Per-drive temperature, power-on hours and health, for every bay
- CPU and system temperature, plus a "hottest disk" sensor for automations
- Fan speed in RPM and a fan mode control (Automatic / Low / Medium / Full)
- Volume and storage pool capacity and usage
- Overheat protection: restores automatic fan control if the drives get too hot
- Local polling over HTTP — no TerraMaster account, nothing leaves your network

## Supported models

Developed and tested on an **F4-425** running **TOS 6**. The integration talks to the
TOS web API rather than anything model-specific, so other TOS 6 units should work and
the number of drive entities follows the number of bays. Reports welcome.

TOS 5 and earlier are not supported.

## Installation

### HACS

1. HACS → ⋮ → **Custom repositories**
2. Add `https://github.com/r0-prod/terramaster-hass`, category **Integration**
3. Install **TerraMaster NAS**, then restart Home Assistant

### Manual

Copy `custom_components/terramaster/` into your `config/custom_components/` directory
and restart Home Assistant.

## Setup

**Settings → Devices & Services → Add Integration → TerraMaster NAS**

| Field | Value |
|---|---|
| Host | IP address or hostname of the NAS |
| Port | TOS web interface port, default `8181` |
| Username / Password | Any TOS account reads every sensor; **administrator** is only needed to change the fan mode |

Credentials are required — TOS has no anonymous read access, and every data
endpoint rejects unauthenticated requests. If you only want monitoring, use a
non-administrator TOS account: all sensors work, and the fan mode control reports
that it is not permitted rather than failing obscurely.

Options (⚙ on the integration) cover the polling interval and overheat protection.
Reading temperatures runs SMART queries on the NAS and takes a few seconds, so the
default interval is 60 seconds.

## Entities

| Entity | Notes |
|---|---|
| `sensor` HDD*n* temperature | One per bay, with model, serial and capacity as attributes |
| `sensor` HDD*n* power-on hours | Diagnostic |
| `sensor` CPU / System temperature | |
| `sensor` Hottest disk | Highest drive temperature — the one to automate on |
| `sensor` Fan speed | RPM |
| `sensor` Volume / Pool total, used, free, usage | Per volume and per pool |
| `binary_sensor` HDD*n* problem | On when TOS reports a fault |
| `select` Fan mode | Automatic, Low, Medium, Full |

### Fan control

`Automatic` hands the fan to the NAS firmware, which ramps with temperature. The three
fixed modes disable that ramp, so a fixed mode chosen in winter can run too slow in
summer. Overheat protection guards against this: if the hottest drive reaches the
threshold (default 55 °C, TerraMaster's own warning point) while a fixed mode is
active, the integration switches the fan back to Automatic and logs a warning. It can
be turned off in the options.

## Troubleshooting

Confirm the TOS web interface is reachable from Home Assistant at
`http://<host>:8181`. Then enable debug logging:

```yaml
logger:
  logs:
    custom_components.terramaster: debug
```

After a TOS firmware update, the API may change — see
[docs/TOS_API.md](docs/TOS_API.md) and run `tools/probe_tos.py` to compare.

## Development

See [AGENTS.md](AGENTS.md) for the repository layout and workflow, and
[docs/TOS_API.md](docs/TOS_API.md) for the reverse-engineered protocol.

## License

[MIT](LICENSE)

## Disclaimer

Not affiliated with, endorsed by, or supported by TerraMaster. The TerraMaster name and
logo are trademarks of their respective owner and are used here only to identify the
supported hardware.
