# Sidecar — up to 16 filament slots for Snapmaker U1

Sidecar is a modular material-handling project for the Snapmaker U1. Four
filament lanes per toolhead scale to 16 slots. A Raspberry Pi coordinates
filament selection and G-code preparation; RP2350 controllers operate the
lanes; a local touchscreen provides controls. QuickPurge is a separate design
for preparing a parked toolhead while another toolhead prints.

**See it in action:** [Sidecar development thread](https://forum.snapmaker.com/t/sidecar-16-color-mmu-for-u1/41473)
and [two video demonstrations](docs/DEMOS.md).

This repository is a **beta development preview** of the project and its source.
It is not an installable firmware release. The stock U1 integration still
needs controlled printer testing, and the RP2350 firmware builds need board
verification. [Current status and next steps](docs/STATUS.md) are documented
separately.

## How it fits together

| Part | Role | Source in this preview |
| --- | --- | --- |
| Snapmaker U1 | Four toolheads, heaters, and parked toolhead motion | [Stock 2.0 integration source](firmware/u1/README.md) |
| Raspberry Pi | Tool-to-lane mapping, G-code preparation, lane control, event coordination, touchscreen | [Pi source and configuration](host/pi/README.md) |
| MAIN RP2350 | First four-lane controller; UART connection to the Pi | [Klipper patch and build settings](firmware/rp2350/README.md) |
| AUX RP2350 | Additional four-lane controllers; USB connection to the Pi | [Klipper patch and build settings](firmware/rp2350/README.md) |

Virtual tool `T` selects toolhead `T // 4` and lane `(T % 4) + 1`.
T0–T3 use MAIN; T4–T7, T8–T11, and T12–T15 use AUX units.

The [controller pin map](hardware/rp2350-pinmap.csv) and [QuickPurge STL](hardware/mechanical/quickpurge/)
show part of the hardware design. Sidecar's BoxTurtle-derived printable parts
will be added with their editable modified CAD source and GPL notices.

## What's next

- Validate the U1 integration, Pi handoff, and controller behavior on hardware.
- Publish tested MAIN and AUX builds and installation instructions.
- Add the full mechanical package and electronics documentation after the
  source and attribution review.

The repository has [component-specific licenses and attribution](LICENSE.md).
The original Pi code and touchscreen source are available for review as beta
source; a redistribution license for the original portions has not been
selected yet. The GPL and other third-party notices still apply to their
respective components.
