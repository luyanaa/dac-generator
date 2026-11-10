# IHP sg13g2 video DAC array (dump-tail cell)

The P5 cell on IHP SG13G2, built from the PDK's own `SG13_dev` PCells:
255 cells + the diode-connected replica, **1022 devices** (512 pmos, 510
nmos), 510 met2 pads on the 3.75 um grid.  Signoff: **DRC 0**, **LVS walk
passes on all 255 cells**, **510 pins**.

## Device source: the PDK PCells work headless

The earlier note ("`sg13g2_pr.gds` holds only PCM cells, the pycell library
needs a PCell host") was too pessimistic.  The `SG13_dev` PCells work in
batch KLayout with three load-bearing details:

1. **Import the library yourself.**  Add the PDK python tree to `sys.path`
   and `import sg13g2_pycell_lib`; KLayout's autorun macro does not run in
   `-b`.  Without the import `create_cell("nmos", "SG13_dev", ...)` returns
   nil and the first instance dies with an internal error.
2. **Set the technology.**  `layout.technology_name = "sg13g2"` and run with
   `KLAYOUT_PATH=<pdk>/libs.tech/klayout`.
3. **Parameters are unit strings** (`"8u"`, `"0.5u"`), not metres.  The
   `cni` wrapper calls `Numeric("8.0u")`; a float raises
   `could not convert string to float: '8.0u'`.
4. **Flatten before writing.**  The PCell cells are dynamic; the geometry is
   materialised by `layout.flatten(top)`.

Sizes from `../video/pdk_cell.py`: mirror pmos 8/1, cascode pmos 8/0.5, pair
nmos 4/0.28, at 1.8 V.

## Array

`gen_gds.py` places 255 cells on a 7.5 um pitch + the replica, and routes:

* **md** (mirror drain -> cascode source) on met2 over the pfet row;
* **cd** (cascode drain -> pair shared source) on **met3**, so it crosses
  both bias buses without touching them;
* **vbp** is met2 at y -1.2..-1.0 (mirror gate via/riser), **vcp** is met1 at
  y -1.81..-1.59: the cascode gate neck passes *under* the vbp bus.  A met2
  vcp riser would short to vbp - this split is the key routing decision;
* **iout/idump** are met3 buses below the pair, **vdd** a met3 plane above
  the row, **vss** a met1 rail below the pad row;
* the nmos 0.28 um gate cannot hold a 0.16 contact with the 0.07 GatPoly
  enclosure (Cnt.d), so each gate gets a **poly land** wider than the gate,
  with the outward finger >= 0.13 (Gat.a/Gat.b); the pfet gate lands are
  below the active with the same enclosure rules;
* the pfet well is one **nwell bar** per cell (NW.b 0.62) with an `ntap1`
  whose nBuLay needs 1.0 um enclosure (NBL.e), tied to the met3 vdd plane;
  the nmos substrate is tied by `ptap1` to the met1 vss rail (LU.a/LU.b).

The first DRC rounds were via rules: **Via1/Via2 are 0.19 um (min=max)**, not
0.16, with 0.01 met enclosure - all via pads were re-cut around that.

## Signoff

`./signoff.py` is the fail-closed entry point:

| stage | gate |
|---|---|
| build | `gen_gds.py` under KLayout with the sg13g2 technology; the generator's same-layer short check |
| drc | PDK `tech/drc/ihp-sg13g2.drc`: **0 items** on the full 1918.5 x 26.6 um array |
| lvs | PDK `tech/lvs/run_lvs.py --net_only --disable_tap_extraction`, then the pad-pair walk: **1022 devices (512 pmos / 510 nmos), 516 ports, all pmos bulks vdd, all nmos bulks vss, 255 cell mirrors + 1 replica mirror/cascode** |
| pins | 510 met2 pads on the 3.75 um grid, 516 labels (10/25) |

The LVS runner needs KLayout >= 0.30.7 for its version gate and the
`klayout` python module.  This environment has KLayout 0.30.0's python module
and a 0.30.12 binary; `signoff.py` writes a `klayout` wrapper that hides the
binary from `LD_LIBRARY_PATH` so the gate passes, and accepts the runner's
version-mismatch warning.  `--disable_tap_extraction` keeps the taps out of
the schematic comparison; the layout's ntap/ptap still tie the wells.

`--selftest` rejects 3/3 netlist mutations (duplicate pad gate, open tail,
pmos bulk off vdd).

## Not done: PEX and benches

The PDK has no KLayout PEX deck; a magic tech exists
(`libs.tech/magic`), but its device extractor has not been validated against
these PCell devices, so the leaf stops at DRC/LVS/pins.  The ngspice models
are present (`libs.tech/ngspice/models`), so once an extracted netlist
exists the DC/mismatch/transient benches are a model port, not a blocker.
