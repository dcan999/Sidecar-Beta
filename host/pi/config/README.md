# Pi Klipper configuration example

[`example/printer.cfg`](example/printer.cfg) is a cleaned MAIN unit example.
It contains Sidecar macros, pin assignments, and lane and LED configuration
for a MAIN unit. The generated `SAVE_CONFIG` block
and its load-cell calibration values have been removed. No runtime
`saved_variables.cfg` or credentials are included.

The example includes `sc/savevars.cfg`, `sc/hardware.cfg`,
`sc/aux/aux_units.cfg`, `sc/macros.cfg`, `sc/ledfx.cfg`, and
`sc/bufferfill_units.cfg`. The hardware file in turn includes
`sc/aux/dup_pins.cfg`. `aux_units.cfg` is deliberately empty of AUX devices.
Add reviewed AUX definitions for each controller installed in a particular build.

Supply the required local Mainsail, Moonraker and
Klipper configuration for your host. `sc/savevars.cfg` assumes a `sidecar`
account and the shown printer-data directory; change that path if needed.

The hardware values describe one build, including motor currents, pins, and
automatic sensor-triggered macros. Verify wiring, motor direction, endstops,
heater and motion interlocks, PWM setup, and all calibration on your own
hardware before enabling this configuration. The shared HX711 clock setup
also depends on the matching Klipper HX71x implementation documented under
[`firmware/rp2350/`](../../../firmware/rp2350/). The example has not been booted or
motion-tested with the stock U1 integration.
