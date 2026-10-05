# Stock U1 background motion source

This integration targets the **official U1 2.0.0.205** Klipper
host. It provides the three background extruder commands used by the Pi
coordinator. It has passed offline checks against the matching stock host
files, but **has not been run on a printer**. Do not install it for printing
without controlled hardware validation.

The host files used for the patch have these SHA-256 hashes:

| Stock file | SHA-256 |
| --- | --- |
| `klippy/kinematics/extruder.py` | `2085de67fb9a7d6c799a958c2a2ece639cc8f136f9dec792fa68eb2c359ce8f5` |
| `klippy/toolhead.py` | `f28887bb85dcfd1ac530b4381bc3bf0b6103af247027870ab1a98024038f5188` |

The module lives at `klippy/extras/sc_bg.py`; `[sc_bg]` loads it in a stock
Klipper configuration. `stock-hooks.patch` adds guards before extruder
selection, stepper queue changes, and calibration changes. The patch targets
the paths above, with `-p1` from the Klipper checkout root. It is intentionally
a small patch rather than a replacement copy of vendor files. Verify both
hashes before applying it. This directory contains no firmware image, installer,
or modified stock tree.

## Command contract

| Command | Purpose |
| --- | --- |
| `SC_BG_BUSY EXTRUDER=extruder1` | Replies `SC_BG_BUSY busy=0 remaining=0.000` or reports time remaining. |
| `SC_BG_LOAD EXTRUDER=... TEMP=... MIN_TEMP=... HEAT_TIMEOUT=... FAST_DIST=... FAST_V=... SLOW_DIST=... SLOW_V=...` | Heats and queues a two-stage forward profile. Optional `FAST_A`, `SLOW_A`, `FAST_LINE`, `SLOW_LINE`, `SYNC`. |
| `SC_BG_UNLOAD EXTRUDER=... TEMP=... MIN_TEMP=... HEAT_TIMEOUT=... PRE_DIST=... PRE_V=... R1_DIST=... R1_V=... R2_DIST=... R2_V=... DWELL_S=... R3_DIST=... R3_V=... ACCEL=...` | Heats and queues a forward pre-move and three reverse stages. Optional `SYNC`. |

`SYNC=0` is the default. A background command only accepts one of the U1's
four named extruders when its park detector confirms `PARKED`, its stepper
still belongs to its own queue, and no other Sidecar background profile is
pending. It enforces positive heat targets, at least the stock minimum
extrusion temperature and 170 °C, motion limits, and a heat timeout. It
rejects activation and queue reassignment until the MCU time has passed the
scheduled end. A low-level queue failure requires a Klipper restart.

The Pi coordinator separately enables the selected motor with stock
`SET_STEPPER_ENABLE`. The stock heater manager's concurrency limit remains
in force. Printer testing must check the park detector, motor enable,
temperature behavior, step generation, command responses, and handoff during
an actual tool change before this can become an installation guide.

Run the offline unit checks from the repository root with
`python -m unittest tests/test_stock_bg.py -v`. The U1 source integration is
licensed under GPL-3.0-only; see [`../../../LICENSES/GPL-3.0.txt`](../../../LICENSES/GPL-3.0.txt).
