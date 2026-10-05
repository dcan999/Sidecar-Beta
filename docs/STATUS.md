# Development status

| Component | Available here | Next step |
| --- | --- | --- |
| U1 | Source extra and a small patch against official stock U1 2.0.0.205 host files | Validate parked motion, heat control, and tool handoff on a printer |
| Pi | Coordinator, preprocessing, watcher, Klipper extras, macros, service examples, and React touchscreen source | Check the full handoff on hardware and complete the origin/license review for extras and macros |
| RP2350 MAIN/AUX | Klipper HX71x source patch, UART/USB settings, pin map | Rebuild and compare firmware with controllers; validate boards before distributing UF2 images |
| Mechanical | Original QuickPurge STL | Add the BoxTurtle-derived Sidecar parts with editable modified CAD and GPL notices; document assembly and fit |
| Electronics | Controller signal map | Review schematic, PCB, power, and fabrication documentation for publication |

Offline tests for the U1 motion command contract and Pi watcher/health-check
are in [`tests/`](../tests/). Run them from the repository root with
`python3 -m unittest discover -s tests -v`. These tests do not establish
printer or board safety. The [U1 notes](../firmware/u1/stock-port/README.md)
record the exact stock host file hashes for its patch. The
[RP2350 notes](../firmware/rp2350/README.md) pin the upstream Klipper revision
used for its source changes.

The touchscreen source can be built from `host/pi/ui/source` with `npm ci`
and `npm run build`. The Pi source and configuration are beta examples that
require matching printer hardware and calibration, not an automatic install
path.
