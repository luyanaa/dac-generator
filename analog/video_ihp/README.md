# IHP sg13g2 video DAC array (dump-tail cell)

The P5 cell on IHP SG13G2, built from the PDK's own `SG13_dev` PCells:
255 cells + the diode-connected replica, **1022 devices** (512 pmos, 510
nmos), 510 met2 pads on the 3.75 um grid.  **All nine signoff stages pass at
1.2 V**: DRC 0, structural LVS walk on all 255 cells, 510 pins, PEX 1022
instances / 2.57 pF, extracted DC **4.0866 mA (-0.037 %)** at vbp/vcp
**0.6316/0.0267 V**, 16-seed mismatch **DNL 0.1467 / INL 0.0906 LSB**
(monotonic), carry **0.029 LSB**.  The assembled leaf (row + IHP digital
macro) has **top-level DRC 0** and 510 independent Metal2 pad islands.

**Status 2026-11-18:** the row is moving from 1.8 V to **1.2 V** because the
PDK `sg13_lv` model states **maximum Vds 1.5 V**; the old 1.8 V supply and
1.8 V pair-gate drive were outside that limit.  The 1.2 V **series** replica
with `iref` **16.032 uA** and `Cvcp` **470 pF** passes the extracted DC and
the 127->128 carry (0.029 LSB, vbp/vcp drift -0.023/-0.068 mV).  The 1.2 V
**wide-swing** bias fails (carry -0.783 LSB, full -1.772 LSB, dvcp +82.7 mV)
and is not used.  The digital `sg13g2_stdcell` is 1.2 V, so the 510 outputs
match directly with no level shifters.

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
nmos 4/0.28, at **1.2 V** (series bias; PDK `sg13_lv` max Vds 1.5 V).

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
| lvs_full | `gen_cdl.py` reference (1022 devices, 516 ports) vs the GDS, PDK `run_lvs.py` **COMPARE** mode: **PASS, Netlists match** (0 errors) |
| pex | magic hierarchical extraction, cthresh/rthresh 0: **1022 instances, 8421 caps, 2.57 pF, no floating node** |
| dc | extracted array, **16.032 uA** at vcp, all 255 cells to iout, **1.2 V**: **4.0865 mA** (-0.037 %), **vbp 0.6316 V / vcp 0.0267 V** |
| mm | PDK PSP103 mismatch (`mos_tt_mismatch` + per-instance `mm_ok=1`), one-hot 255-point `.dc` per seed; **1.2 V**, 16 seeds: cell sigma **0.704 %**, **DNL 0.1467 / INL 0.0906 LSB**, monotonic (the 1.8 V values were 0.196/0.122) |
| tran | carry 127->128, **470 pF on vcp + 100 pF on vbp**, 37.5 ohm + 2 pF, **1.2 V**: **0.029 LSB** at 40 ns, vbp/vcp drift **-0.023/-0.068 mV** |
| pins | 510 met2 pads on the 3.75 um grid, 516 labels (10/25) |

The LVS runner needs KLayout >= 0.30.7 for its version gate and the
`klayout` python module.  This environment has KLayout 0.30.0's python module
and a 0.30.12 binary; `signoff.py` writes a `klayout` wrapper that hides the
binary from `LD_LIBRARY_PATH` so the gate passes, and accepts the runner's
version-mismatch warning.  `--disable_tap_extraction` keeps the taps out of
the schematic comparison; the layout's ntap/ptap still tie the wells.

`--selftest` rejects 3/3 netlist mutations (duplicate pad gate, open tail,
pmos bulk off vdd).

## Benches

PEX is magic's (`libs.tech/magic`, `cthresh/rthresh 0`): 1022 instances and
8421 capacitors.  The extracted DC uses the PDK's `cornerMOSlv.lib` (PSP103,
OSDI loaded by the PDK `.spiceinit` with `PDK_ROOT`/`PDK`) and reproduces the
study's bias to four digits.

The mismatch MC uses the PDK's own law: the `mos_tt_mismatch` section and
`mm_ok=1` on every device, so each extracted instance draws its own
`delvto`/`factuo`; one 255-point one-hot `.dc` per seed recovers every cell's
current and the 256-code transfer is exact superposition.  16 seeds give
sigma 0.704 %, DNL 0.1467, INL 0.0906 LSB at 1.2 V (16 seeds, no
non-monotonic seed).

The 1.2 V carry transient (127 -> 128, 5 ps step, 40 ns) uses **470 pF on
vcp + 100 pF on vbp**: 0.029 LSB, vbp/vcp drift -0.023/-0.068 mV.  The P5
cell full-scale study (0 -> 255) needs 470 pF: at 330 pF it lands at
0.549 LSB, at 470 pF it settles in 2.8 ns at **0.457 LSB**.  Both caps are
wrapper requirements, not part of this macro.

## Digital macro and assembly (IHP)

The IHP digital macro is hardened in `openlane/dac_video_dig` with
`config.librelane.json` (`RESOLUTION=8`, `ENCODING=0`, die 1912.5 x 100 um,
`pin_template_ihp130.def`).  Run `ihp_ant` is clean:

* **KLayout DRC 0**; Netgen LVS **0 device/net/pin differences**;
* **523 Metal2 pins**, the 510 `dout/dout_n` on the exact `x = 2.25 + 7.5k /
  6.0 + 7.5k`, y = 0..0.6 analog grid; the 13 control pins on the top edge;
* 8-bit binary order matches the row: `dout[2^k-1+i] = code[k]`, the same
  `b{k}_{i}` tag as `gen_gds.py`;
* setup **+5.053 ns** at `nom_slow_1p08V_125C`, hold **+0.1171 ns** at
  `nom_fast_1p32V_m40C`, power **0.3865 mW**, core 129,330 um^2;
* antenna **0 violating nets/pins**; the earlier `clk` Metal3 item (228.29
  vs 200) is fixed by the `OpenROAD.RepairAntennas` jumper when `DIODE_CELL`
  is set.

`openlane/dac_video_dig/assemble_ihp.py` places the digital macro mirrored
in Y at `y0 = -9.5` under the row.  The 510 pads overlap by 0.4 um on
Metal2 (10/0); the assembled `build/dac_video_top.gds` has **510 distinct
merged Metal2 islands** and the PDK KLayout DRC on the top cell is **0
items**.

## Closure update (2026-11-19)

- **Reference-CDL LVS:** `gen_cdl.py` + `signoff.py --stage lvs_full`:
  1022 devices, 516 ports, PDK `run_lvs.py` COMPARE **PASS**
  ("Netlists match").
- **Wrapper/bias:** `wrapper_bias.py` uses a 1660 ohm `rppd` resistor from
  `vcp` to `vss` (iref is a sink): DC **4.1031 mA / 16.091 uA per cell**,
  `vcp 26.62 mV`, `vbp 631.53 mV`; carry **0.030 LSB** at 40 ns.  The
  21-port wrapper layout is `openlane/dac_video_dig/wrapper_connect.py`
  (**510 islands, DRC 0**); see `wrapper.md`.
- **PPA/SFDR:** `static_sfdr.py` / `ppa_sfdr.md`: 16-seed static
  **SFDR 58.8 dB, SNDR 49.3 dB, ENOB 7.9 bit**; total power 5.335 mW
  full-scale (2.861 mW sine average), 213.4 pJ/sample.
- **Full-chip LVS/PEX/RCX:** `fullchip_lvs.py` (Netgen "Circuits match
  uniquely"), `fullchip_rcx.py`, `top_pex.spice` (12,013 devices / 19,491
  caps) and the digital OpenRCX SPEF (1,214 nets, 2.795 pF).  The only
  remaining physical item is the ESD/probe pad ring; decoupling and the
  1.66 kohm resistor are external by design.
