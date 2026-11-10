# sky130 video DAC array (dump-tail cell)

The P5 cell on sky130A.  It exists because the device study showed the 1.8 V
logic PMOS cannot stack two diodes at 16 uA inside 1.8 V (the replica's `vcp`
is driven negative), so the array runs the **5 V `g5v0d10v5` devices at
3.3 V**, mirror/cascode/pair all W/L 8/0.5, exactly as `../video/pdk_cell.py`
sized them.

## Devices

`./gen_devices.py` generates them with **magic's** `gencell` - the KLayout
paths cannot supply this device (`sky130_fd_pr.gds` has no 5 V pfet and
`pya_draw` at W=8 is not DRC-clean).  The invocation details are load-bearing:

* options are **space-separated pairs** (`l 0.5 w 8 nf 1 guard 1`); `k=v`
  makes `dict create` see keys like `l=0.5` and silently uses the defaults;
* the instance name must be non-empty - an empty name opens the GUI parameter
  dialog, which dies headless;
* one gencell per magic process (a second call hits the dialog callback).

`guard 1` is not cosmetic: it draws the bulk tap ring and the `B` port.  The
ring is contacted on its **side walls** (li1 + licon only - the gencell does
not put mcon on it), so the array adds the li1->m1 mcon squares itself.  A
guard-0 device has no tap at all: magic then extracts a floating nwell per
pfet, which is what the first LVS run showed.

The device is a 3.08 x 11 um cell.  Its met1 terminals, relative to the
device origin:

| terminal | met1 / li1 |
|---|---|
| drain rail | x -0.51 .. -0.28, y -4.0 .. 4.0 |
| source rail | x 0.28 .. 0.51, y -4.0 .. 4.0 |
| gate pads | x -0.23 .. 0.23, y 4.21 .. 4.44 and -4.44 .. -4.21 |
| bulk ring | x -1.15 .. -0.98 and 0.98 .. 1.15, y -4.82 .. 4.82 |

## Array

`./gen_gds.py` places 255 cells + the 2-device replica, straps the terminals,
and draws the rails:

* **7.5 um cell pitch**, because the pin contract is two met2 pads per cell
  on a 3.75 um grid (2.25 / 6.0 um inside the cell); the same pitch keeps the
  nwell edges out of the 1.27 um spacing rule once the wells are merged;
* cell: pfet mirror (source vdd, gate vbp), pfet cascode (gate vcp), nfet pair
  whose shared source is the cascode drain, drains iout/idump, gates on the
  two pads; the tail always flows (dump-tail);
* routing: md is a met2 bar, cd a met2 column, the pair source a met2 bar;
  vbp/vcp are met2 buses at y 4.38..4.76 / 5.08..5.50, vdd/iout/idump met3
  buses, vss a met1 rail at the bottom;
* the pfet nwells and the 5 V hvi markers are continuous **bars** across the
  row (7.5 um is below the 1.27 um nwell spacing), and the pfet/nfet bulk
  rings are tied by met1 bars: pfet -> met1 -> via1 -> met2 -> via2 -> met3
  vdd at y 6.0; nfet -> met1 down to the vss rail;
* the replica (right end) is the mirror+cascode, diode-connected, no switch;
  its cascode source leaves the device **under the guard ring** (the ring's
  bottom wall has no mcon) before going up to the vbp bus, and its vcp climbs
  on the far right, clear of the vdd stack.

## Signoff

`./signoff.py` is the fail-closed entry point:

| stage | gate |
|---|---|
| build | devices + array, generator short check |
| drc | KLayout `sky130A_mr.drc`, feol+beol, top `dac_video_ana`, **0 items** |
| lvs | magic flat extraction, pad-pair walk (1022 devices, 512 pfet / 510 nfet, all bulks vdd/vss) |
| pins | the 510 met2 pads measured on the drawn GDS on the 3.75 um grid |
| pex | magic hierarchical extraction, cthresh/rthresh 0: **1022 instances, 7150 caps, 7.94 pF, no floating node** |
| dc | extracted array, 16 uA at vcp, all 255 cells to iout: **4.0996 mA** full scale (+0.479 %), **vbp 2.1916 V / vcp 0.8427 V** - the study's 2.192/0.843 V |

The 100 pF on vcp is a **wrapper** requirement (the benches model it with
`--vcp-cap-pf`); it is not part of this macro.
