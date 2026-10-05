# RP2350 controller source

Sidecar uses Klipper MCU firmware on RP2350 controllers. MAIN uses UART0 on
GPIO0/GPIO1 at 115200 baud; AUX controllers use USB. The two saved build
configurations and the Sidecar HX71x changes are here as source. This preview
does not include UF2 images or a flash procedure.

The [patch](klipper-hx71x.patch) applies to upstream Klipper commit
[`8dd798ebb8ad37dcfd6d6d825ff7a7482f3ddafe`](https://github.com/Klipper3d/klipper/commit/8dd798ebb8ad37dcfd6d6d825ff7a7482f3ddafe).
It modifies `klippy/extras/hx71x.py` for the Pi host and
`src/sensor_hx71x.c` for the MCU. Keep both sides at the matching revision.

On a Linux host with Klipper's RP2350 toolchain installed, from this
directory:

```sh
git clone https://github.com/Klipper3d/klipper.git klipper-source
git -C klipper-source checkout --detach 8dd798ebb8ad37dcfd6d6d825ff7a7482f3ddafe
git -C klipper-source apply "$(pwd)/klipper-hx71x.patch"
cp uart/config.txt klipper-source/.config
make -C klipper-source clean
make -C klipper-source -j2
cp klipper-source/out/klipper.uf2 ./main-rebuilt.uf2
cp usb/config.txt klipper-source/.config
make -C klipper-source clean
make -C klipper-source -j2
cp klipper-source/out/klipper.uf2 ./aux-rebuilt.uf2
```

The builds still need comparison with the flashed boards and controlled
hardware validation. The [pin map](../../hardware/rp2350-pinmap.csv) records
the intended controller connections. The patch retains the upstream Klipper
license terms; see [licensing](../../LICENSE.md).
