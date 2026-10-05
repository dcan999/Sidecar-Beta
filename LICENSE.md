# Licenses and attribution

This is a development preview with different terms for different components.
There is no project-wide license.

| Material | Terms |
| --- | --- |
| [U1 stock integration source](firmware/u1/stock-port/) | Copyright Eric Nelson; [GPL-3.0-only](LICENSES/GPL-3.0.txt). The patch applies to separately obtained stock Klipper files and keeps upstream notices. |
| [RP2350 Klipper patch](firmware/rp2350/klipper-hx71x.patch) | Klipper-derived GPLv3 material. Obtain the matching upstream source as described in the [build notes](firmware/rp2350/README.md). |
| [QuickPurge STL](hardware/mechanical/quickpurge/) | Copyright Eric Nelson; [CC BY-NC 4.0](https://creativecommons.org/licenses/by-nc/4.0/legalcode) for the original model file. See its [notice](hardware/mechanical/quickpurge/README.md). |
| Original Pi runtime, Klipper extras, macros, service examples, and touchscreen code | Sidecar beta source is available for review. No general copy, modification, or redistribution license has been selected for the original portions yet. The origin and license of Klipper extras and any macros adapted from upstream still need review; existing upstream rights remain in force. |
| Touchscreen dependencies and assets | Their own terms apply. See [UI attributions](host/pi/ui/source/src/Attributions.md), [shadcn/ui MIT notice](LICENSES/shadcn-ui-MIT.txt), and package metadata. |

The Sidecar mechanical parts derived from
[ArmoredTurtle/BoxTurtle](https://github.com/ArmoredTurtle/BoxTurtle) are not
included in this preview. Their GPL-covered exports and editable modified CAD
source will be published together after preparation. Snapmaker's stock U1
source and upstream Klipper are obtained from their own projects; this
repository does not distribute full copies of either.
