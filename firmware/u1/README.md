# Stock U1 integration

Sidecar's Pi coordinator expects the U1 to provide `SC_BG_LOAD`,
`SC_BG_UNLOAD`, and `SC_BG_BUSY` for parked toolhead motion. Official stock U1
2.x firmware does not contain these Sidecar commands. The
[stock 2.0 source integration](stock-port/README.md) contains a Klipper
extra and small guards for the matching stock host files.

The integration is supplied as source, without a firmware image or installer.
It has passed offline checks, but it still needs controlled printer validation. An
unmodified U1 cannot run the Pi coordinator's background motion commands.
