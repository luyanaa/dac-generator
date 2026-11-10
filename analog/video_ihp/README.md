# IHP sg13g2 video DAC cell core

Status: the **device source and the cell core are solved**; the array routing
is the remaining work.  This directory holds the proof, not yet a leaf
signoff.

## Device source: the PDK PCells *are* usable headless

The earlier note ("`sg13g2_pr.gds` holds only PCM cells, the pycell library
needs a PCell host") was too pessimistic.  The PDK's `SG13_dev` PCells work
in batch KLayout with three load-bearing details:

1. **Import the library yourself.**  Add the PDK python tree to `sys.path`
   and `import sg13g2_pycell_lib`; KLayout's autorun macro does not run in
   `-b`.  Without the import `create_cell("nmos", "SG13_dev", ...)` returns
   nil and the first instance dies with an internal error.
2. **Set the technology.**  `layout.technology_name = "sg13g2"` and run with
   `KLAYOUT_PATH=<pdk>/libs.tech/klayout`.  Without it the SG13_dev library
   cannot resolve.
3. **Parameters are unit strings** (`"8u"`, `"0.5u"`), not metres.  The
   `cni` wrapper calls `Numeric("8.0u")`; a float raises
   `could not convert string to float: '8.0u'`.
4. **Flatten before writing.**  The PCell cells are dynamic; the geometry is
   materialised by `layout.flatten(top)` (or a cell instance in a flattened
   top), not by `Layout.write` alone.

`gen_gds.py` does all four, and also flattens because our own generator needs
to draw on the same cell.

## Cell core

`gen_gds.py` places the dump-tail cell:

| device | PCell | W/L |
|---|---|---|
| mirror | `pmos` | 8/1 |
| cascode | `pmos` | 8/0.5 |
| pair | `nmos` | 4/0.28 |

The PCell draws source/drain on Metal1 and the gate as a bare GatPoly stripe
(no gate contact, no bulk tap).  The core adds:

* **gate lands**: a GatPoly pad at each gate end with the contact.  The
  0.28 um nmos gate cannot hold a 0.16 um contact plus the 0.07 um GatPoly
  enclosure (Cnt.d), so the land is wider than the gate and its outward
  finger is >= 0.13 um (Gat.a/Gat.b) - a narrower land makes a 0.02 um poly
  finger and fails;
* **bulk taps**: `ntap1` in the merged pfet nwell, `ptap1` below the nmos
  pair (LU.a/LU.b want a tie within 20 um; NBL.e wants the ntap's nBuLay
  enclosed by nwell by 1.0 um, which sets the nwell bar's extent);
* one nwell bar across the pfet row (NW.b 0.62 um spacing/notch would flag
  the 0.01 um sliver at the device nwell edges if they were separate).

Verified with the PDK's own deck (`tech/drc/ihp-sg13g2.drc`, KLayout, no
`run_drc.py` - that script imports the `klayout` pip module, which this
environment does not have):

| layout | DRC |
|---|---|
| 1 cell (`build/core1.gds`) | **0 items** |
| 2 cells on the 7.5 um pitch (`build/core2.gds`) | **0 items** |

Command:

```bash
KLAYOUT_PATH=<pdk>/libs.tech/klayout klayout -b -r gen_gds.py \
    -rd out=build/core2.gds -rd dbg_cells=2
KLAYOUT_PATH=<pdk>/libs.tech/klayout klayout -b -r \
    <pdk>/libs.tech/klayout/tech/drc/ihp-sg13g2.drc \
    -rd input=$PWD/build/core2.gds -rd report=$PWD/build/core2.lyrdb \
    -rd topcell=dac_video_ihp
```

## Remaining work (the actual leaf)

* cell routing: md (mirror drain -> cascode source), cd (cascode drain -> the
  pair's shared source), vbp/vcp buses (the gate lands are at the *bottom* of
  the pmos gates; the vcp riser cannot cross the vbp bus on the same metal -
  the sky130 solution of separate met2 buses at different y does not map
  directly, the gate lands must go over the top or the buses must be split
  by cell), iout/idump, vdd/vss;
* the 510 met2 pads on the 3.75 um row, the replica, then magic/LVS/PEX:
  the LVS deck (`tech/lvs/run_lvs.py`, `sg13g2.lvs`) needs the `klayout`
  python module or a direct `.lvs` run + netgen compare; the ngspice models
  are present (`libs.tech/ngspice`), so the benches are a model-port, not a
  blocker;
* the ideal device sizes from `../video/pdk_cell.py` (mirror 8/1, cascode
  8/0.5, pair 4/0.28 at 1.8 V) are the ones placed here.
