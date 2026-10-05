# Pi systemd examples

These units assume a `sidecar`
service account, `/opt/sidecar` checkout, Python virtual environment at
`/opt/sidecar/venv`, a built UI under `host/pi/ui/source/build`, and a local
Pi Moonraker at port 7125. Adjust these paths to your installation. Build the
UI from `host/pi/ui/source` with `npm ci` and `npm run build`.

The coordinator listens on loopback at port 8090 for the local kiosk, and the
UI server listens on loopback at port 8088. The U1 address shown is the
observed private link (`10.42.0.10:7125`); configure it for your network.
The coordinator accepts browser requests from local UI origins on ports 8088
and 3000. If the UI runs at another origin, set `SC_ALLOWED_ORIGINS` to an
explicit comma-separated list of trusted origins. Requests from other browser
origins are rejected. Keep the API bound to loopback; browser origin checks
do not authenticate local programs that can connect directly.
The watcher starts with `DELETE_RAW=0`, `FIREWALL_RAW=0`, and `AUTO_START=0`.
The active print-start service is intentionally not included as an example.

Review service permissions, the Moonraker authorization model, Pi PWM access,
and the handoff from processed upload to printing before enabling anything.
The PWM preparation helper is not part of these examples, so servo control
needs its own setup and verification. The health check queries command
availability only. These examples have not been used to bring up hardware.
