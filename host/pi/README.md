# Pi coordinator and touchscreen

[`runtime/`](runtime/) contains Sidecar's G-code preparation, coordinator,
watcher, autostart, scan, and read-only U1 health-check source.
[`klipper-extras/`](klipper-extras/) contains lane and LED control modules.
[`config/example/`](config/example/) contains the MAIN unit pin map, macros,
and settings. [`services/`](services/) contains optional systemd examples.
[`ui/source/`](ui/source/) contains the React/Vite touchscreen and API client.
The block-of-four mapping sends virtual tools T0–T15 to four U1 toolheads and
up to four lanes per toolhead.

The coordinator's private-link default is `10.42.0.10:7125`; change `U1_HTTP`
and `U1_WS` for another setup. The watcher defaults to automatic print start
and raw-file deletion disabled. `sc_u1_healthcheck.py` queries Moonraker for
state and the `SC_BG_*` command names without moving or heating a toolhead.
The `sc_autostart.py` source has an active print-start path; use it only after
testing the complete printer handoff.

Build the touchscreen locally from `ui/source/` with `npm ci` and
`npm run build`. `requirements.txt` records a Python WebSocket dependency.
The Klipper extras, macros, and Pi service configuration are beta source. An
origin and license review of the extras and any upstream-derived macros is
still in progress; retain third-party notices and terms. This preview is
not a standalone Pi image or installation guide; it expects the matching U1
integration and board-specific setup.
