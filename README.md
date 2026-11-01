# EVAKOOL Bluetooth Fridge for Home Assistant

Unofficial custom integration that connects Home Assistant directly to an
**EVAKOOL Down Under / CoolRide** dual-zone fridge over Bluetooth Low Energy.
It is not affiliated with or supported by EVAKOOL.

## Requirements

- Home Assistant **2026.10** or newer.
- A **connectable** Bluetooth path within range of the fridge: a local Bluetooth
  adapter configured in Home Assistant, or an
  [ESPHome Bluetooth proxy](https://esphome.io/components/bluetooth_proxy.html) with
  `active: true`. Passive-only scanners can discover the fridge but cannot control it.
- The fridge accepts **one** Bluetooth connection at a time. Close the phone app (or
  turn off the phone's Bluetooth) while Home Assistant is connected.

## Install

### HACS (custom repository)

1. HACS → ⋮ → **Custom repositories** → add `https://github.com/DJS91/HA-EvakoolFridge`
   with category **Integration**.
2. Install **EVAKOOL Bluetooth Fridge** and restart Home Assistant.

### Manual

Copy `custom_components/evakool` into your Home Assistant `config/custom_components/`
directory and restart Home Assistant.

## Set up

Power the fridge on near a Bluetooth adapter/proxy. Home Assistant discovers fridges
advertising the EVAKOOL service or a `DownUnder_*` / `CoolRide` name and shows a
**Discovered** card under **Settings → Devices & services**. You can also choose
**Add integration → EVAKOOL Bluetooth Fridge** and select it from the list.

Setup completes even if the fridge is out of range. Its data entities stay
unavailable, and the integration keeps searching for the fridge on every poll.

## Entities

| Entity | Type | Notes |
| --- | --- | --- |
| Left temperature | Sensor | Current compartment temperature |
| Right temperature | Sensor | Current compartment temperature |
| Supply voltage | Sensor | Volts. Integer protocol values are tenths of a volt (`138` → 13.8 V) |
| Compressor mode | Sensor | `Eco` / `Max` |
| Left target temperature | Number | Setpoint control |
| Right target temperature | Number | Setpoint control |
| Compressor mode | Select | Switch between Eco and Max |
| Power | Switch | Fridge on/off |
| Bluetooth connection | Switch (config) | Search and connect (on) or release the fridge (off) |
| Connected | Binary sensor (diagnostic) | Whether Home Assistant currently holds the Bluetooth link |

Temperatures are reported in the fridge's configured unit (°C or °F), and Home
Assistant converts them to your display unit. Targets are limited to
**-25..20 °C (-13..68 °F)**, the same conservative guard used by Open-DiKey; this is not
your model's rating.

### How controls behave

- Each change is written **once**, then the fridge is re-queried until it reports the
  new value (up to 10 seconds). Entities only show values reported by the fridge.
- If the fridge does not confirm in time, the action fails with an error and the
  command is **not** resent.
- Fault frames (`/SEE/…`, `/SCE/…`) or lost connections make the entities
  unavailable until the next successful status update.

### Sharing the fridge with another app

The fridge accepts only **one** Bluetooth client at a time. To use the phone app, turn **Bluetooth connection** off. Home Assistant then disconnects
immediately, cancelling any connection attempt in progress, and stops polling. The
other entities show as unavailable until you reconnect.

Turn it back on to search for the fridge through any connectable adapter or proxy and
reconnect straight away. The switch state survives restarts, and the **Connected**
sensor shows whether the link is actually up. You can automate the switch, for
example to release the fridge when your phone arrives nearby.

## Options

**Settings → Devices & services → EVAKOOL Bluetooth Fridge → Configure**:

- **Poll interval** (default 30 s, 5–600 s): how often status is requested. Status
  frames received between polls are published immediately.
- **Keep Bluetooth connected between polls** (default on): faster updates and
  controls. Turn off to release the connection after each poll/command so the phone
  app can connect in between (each poll then has to reconnect, which takes longer and
  can fail more often through proxies).

## Troubleshooting

Enable debug logging to see each transmitted command and received frame:

```yaml
logger:
  logs:
    custom_components.evakool: debug
```

If your firmware sends a frame the parser rejects, open an issue with the logged
`RX` frame.

## Development

```powershell
uv sync --python 3.14 --all-groups
uv run ruff check .
uv run pytest
```

The protocol and client tests need no Home Assistant install. The `homeassistant-test`
group installs Home Assistant 2026.10.4 plus the requirements of its `bluetooth`
component for the HA-level tests. CI also runs `hassfest` and HACS validation.

Hardware validation is still required: these tests use a simulated fridge, not a
real radio.
