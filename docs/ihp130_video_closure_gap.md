# IHP SG13G2 video DAC: what is still missing for closure

Status 2026-11-18.  This is a gap analysis of the IHP130 (`ihp-sg13g2`) video
DAC leaf, not a new signoff result.  Evidence is from the current workspace:
`analog/video_ihp/`, `openlane/dac_video_dig/`, and the IHP PDK under
`pdks/ihp-sg13g2/`.

## Short answer

The **analog row is the mature block** (DRC 0, structural LVS walk, PEX, DC,
16-seed mismatch, carry transient).  The following are not closed:

1. **Voltage domain (P0).** The row runs at **1.8 V** (`pdk_cell.py` IHP
   config, `dc_bench.py`, `tran` decks), but the PDK `cornerMOSlv.lib` states
   **maximum drain-source voltage 1.5 V** for `sg13_lv`.  The pair gate is
   driven at 1.8 V with its drain near 0 V in the DC bench, i.e. Vgd ~1.8 V.
   This is outside the model's stated maximum; DRC/LVS do not check it.  A
   1.8 V row needs a reliability waiver, a 1.2 V re-spin (series replica, trimmed iref), or
   `sg13_hv` 3.3 V devices.
2. **IHP digital macro (P0).** `openlane/dac_video_dig` has an
   `pdk::ihp-sg13g2` config (1912.5 x 100 um, `RESOLUTION=8`, `ENCODING=0`,
   `pin_template_ihp130.def`), but `runs/` contains only `sky130` and
   `sky130_pins`; there is no IHP synthesis/place/route/GDS, no DRC/LVS, no
   timing/power/PEX, no 510-pin grid check.
3. **Digital-analog interface (P0/P1).** The IHP stdcell library is **1.2 V**;
   the analog row's gate drive is **1.8 V**.  If the row stays at 1.8 V, the
   510 digital outputs need a 1.8 V driver/level shifter (the `sg13g2_io`
   library is 3.3 V).  If the row moves to 1.2 V (the `sg13_lv` nominal), the
   digital and analog supplies match and no shifter is needed.
4. **Assembly (P1).** `openlane/dac_video_dig/assemble.py` is sky130-only
   (hard-coded `analog/video_sky130`, met2 69/20, `DIG_Y=-17.7`).  The IHP row
   pads are `PAD_Y=(-10.00,-9.60)` on met2 (10/0); the digital template pins
   are at y=0..0.6.  A mirror + `y0=-9.5` gives the same 0.4 um overlap, but
   the script, 510-island check and top-level DRC are missing.
5. **True analog-row LVS (P1).** `analog/video_ihp/signoff.py` runs the PDK
   `run_lvs.py --net_only --disable_tap_extraction` and a **structural pad-pair
   walk** (1022 devices, 512 pmos/510 nmos, bulks, 255 mirrors).  It does not
   compare against a reference CDL.  The IHP row has no `gen_cdl.py` (unlike
   `video_ics55`); a full schematic-vs-layout LVS is still missing.
6. **Signoff bookkeeping (P1).** `analog/video_ihp/build/signoff.json` contains
   only the `pins` stage (it was overwritten by a later `--stage pins` run at
   22:42; the DRC/LVS/PEX/DC/MM/tran logs are from 00:13-00:14).
   `./signoff.py --stage all` should be re-run to restore the fail-closed
   aggregate.  The `signoff.py` docstring still says "Not claimed: PEX and the
   benches", which the README contradicts.
7. **Bias / wrapper (P1).** The row's replica plus an external **16 uA** on
   `vcp`; the README requires **220 pF on vcp and 100 pF on vbp** as wrapper
   components.  There is no on-chip reference/startup or decap; the wrapper
   must also supply the 510 gate nets, `iref`, `vdd`, `vbp`, `vcp`, `iout`,
   `idump`, and the digital control pins.
8. **PPA / SFDR (P2).** No IHP PPA/SFDR table.  The analog row DC is
   4.0815 mA (7.35 mW at 1.8 V; ~4.9 mW at 1.2 V), area 1918.5 x 26.6 =
   51,032 um^2; mismatch DNL 0.196 / INL 0.122 LSB; carry 0.062 LSB.  The
   digital macro power/timing and the full-chip SFDR are unknown.
9. **Full-chip LVS/PEX (P2).** Same gap as sky130: the two blocks are signed
   off separately and the pad islands are checked, but there is no top-level
   netlist, combined LVS, or full-chip RCX/SFDR.
10. **Digital flow details (P2).** `config.librelane.json` inherits
    `VDD_NETS=[vccd1]`, `GND_NETS=[vssd1]` from `openlane/common.json`; the IHP
    stdcell pins are `VDD/VSS`.  `RUN_CTS` is `false`; 28k flops at 100 MHz
    should either enable CTS or justify the clock tree.  The sky130
    `IO_PIN_ORDER_CFG`/`pin_order_sky130.cfg` fallback is not IHP-specific
    (the strict DEF template is authoritative, but it should be made explicit).
11. **RF/MOM:** not a gap.  The IHP PDK is mature and this DAC uses no RF/MOM
    devices.

## Evidence

| item | evidence |
|---|---|
| analog row signoff | `analog/video_ihp/README.md`: DRC 0, LVS walk 1022 devices, PEX 2.57 pF, DC 4.0815 mA, DNL/INL 0.196/0.122, carry 0.062 LSB |
| analog 1.8 V | `analog/video/pdk_cell.py` `"ihp-sg13g2": {"vdd": 1.8, ... "sg13_lv_*"}`, `build/dc_bench.py` `Vdd vdd 0 1.8`, `Vd_* ... 1.8` |
| `sg13_lv` max | `pdks/ihp-sg13g2/libs.tech/ngspice/models/cornerMOSlv.lib` line 63: "Maximum drain-source voltage: 1.5" |
| structural LVS | `analog/video_ihp/signoff.py` `run_lvs.py ... --net_only`, then `check()`; no reference CDL |
| signoff JSON | `analog/video_ihp/build/signoff.json` has only `pins`; logs `drc.log`, `lvs.log`, `dc_transfer.log`, `pex.spice` exist |
| digital config | `openlane/dac_video_dig/config.librelane.json` `pdk::ihp-sg13g2` (8-bit binary, 100 um die, pin template) |
| no IHP run | `openlane/dac_video_dig/runs/` = `sky130`, `sky130_pins` only |
| pin template | `pin_template_ihp130.def`: 523 pins, 510 `dout/dout_n` on `x=2.25+3.75k`, y=0..0.6; 13 control pins at y=100 |
| assembly | `openlane/dac_video_dig/assemble.py` hard-codes sky130 met2 69/20 and `analog/video_sky130` |
| IHP row pads | `analog/video_ihp/gen_gds.py` `PAD_Y=(-10.00,-9.60)`, `PITCH=7.5`, met2 (10/0), met2 label (10/25) |
| IHP LibreLane | `pdks/ihp-sg13g2/libs.tech/librelane/config.tcl` (sg13g2_stdcell, KLayout DRC/LVS, Magic, OpenRCX) |

## Recommended closure path

### 1. Decide the analog voltage domain first (P0)

**Decision (2026-11-18): 1.2 V.**  The 1.2 V P5 cell study was run with both
bias topologies.  The **series** bias is the better path; it uses the existing
row replica (no layout re-spin):

| 1.2 V bias | 127->128 | 0->255 | dvcp | verdict |
|---|---|---|---|---|
| series | **-0.062 LSB, 2.26 ns** | -0.698 LSB | +0.72 mV | FAIL only by the 0.5 LSB / 0.7 mV thresholds |
| wide-swing (nbias 0.5/1.0) | -0.783 LSB, settle inf | -1.772 LSB | +82.7 mV | FAIL |

The wide-swing `vcp` is only 0.027 V and the 220 pF `vcp` node is kicked by
82 mV at the carry; the triode bias cannot hold it.  The **series** carry is
already good.  The 0->255 `settle inf` is not a topology failure: the final
value is 0.698 LSB off, so it can never enter the 0.5 LSB window.  A ~0.2 %
`iref` trim (16.032 uA instead of 16 uA) balances carry/full at about
+/-0.19 LSB, and `Cvcp` 220 -> 330 pF reduces the full-scale kick to about
0.48 mV.  Re-run `pdk_cell.py ihp-sg13g2 --vdd 1.2 --bias series` with those
two values; if it passes, keep the existing row GDS and only change the
benches/wrapper.

Option A (selected): **1.2 V row, series replica, trimmed iref + Cvcp.**
- No row layout change; `gen_gds.py` replica stays as-is.
- `signoff.py`/`dc_bench.py`/`_tran_decks` at 1.2 V and gates at 1.2 V.
- The digital 1.2 V stdcell outputs then match directly; no level shifters,
  and the `sg13_lv` 1.5 V maximum is respected.
- The iout full-scale/gain trim lives in the wrapper's `iref` reference
  (16.032 uA) and the `Cvcp` is 330 pF (240 pF at the vcp node plus margin).

Option B (fallback): **1.8 V with `sg13_hv` 3.3 V devices.**

Option C: keep 1.8 V `sg13_lv` with a written PDK/process waiver.
- The model states 1.5 V max; a waiver is required before tapeout.  The
  current `dc`/`tran` benches at 1.8 V are outside the stated model range.

### 2. Harden the IHP digital macro (P0)

```sh
cd openlane/dac_video_dig
PYTHONPATH=$PWD/librelane_patch \
librelane config.librelane.json \
  --pdk ihp-sg13g2 --pdk-root /grid/dac-generator/pdks/ihp-sg13g2 \
  --run-tag ihp_pins
```

Before the run:
- set `VDD_NETS: [VDD]`, `GND_NETS: [VSS]` (or confirm the `vccd1/vssd1`
  mapping) in the `pdk::ihp-sg13g2` section;
- decide `RUN_CTS` (enable CTS for the 28k-flop 100 MHz clock, or document
  why the ideal clock is acceptable);
- make the IHP pin order explicit (disable/override the sky130
  `IO_PIN_ORDER_CFG` fallback; the strict `pin_template_ihp130.def` is the
  contract).

After the run check: 510 outputs on `x=2.25+3.75k`, y=0..0.6; 523 LEF pins;
DRC 0; LVS 0 against the standard-cell CDL; setup/hold at ss/tt/ff; power;
antenna; PEX; the 8-bit binary cell order against the row's `b*` tags.

### 3. Assemble the IHP blocks (P1)

Write an IHP `assemble.py` (met2 10/0):
- analog row at the origin (`PAD_Y=(-10.00,-9.60)`);
- digital macro mirrored in Y, `y0=-9.5` (digital pads become -10.1..-9.5,
  overlapping the analog -10.0..-9.6 by 0.4 um);
- check 510 merged-met2 pad islands, no shared island, top-cell bbox;
- run the IHP KLayout DRC on the assembled `dac_video_top` (the sky130
  assembly reached 0 items with the same 0.4 um overlap).

### 4. Close the analog LVS and signoff bookkeeping (P1)

- Generate an IHP row reference CDL (port `video_ics55/gen_cdl.py` to the
  `sg13_lv` devices; or emit it from `pdk_cell.py`/`gen_gds.py`).
- Run the PDK `run_lvs.py` with the reference (not `--net_only`) plus the
  pad-pair walk; resolve the tap/well handling (currently
  `--disable_tap_extraction`).
- Re-run `./signoff.py --stage all`, or merge the existing stage logs into
  `signoff.json`; update the stale "Not claimed: PEX" docstring.

### 5. Wrapper and bias (P1)

- 16 uA `iref` reference (resistor/current mirror) with startup;
- 220 pF on `vcp` and 100 pF on `vbp` (both are wrapper requirements);
- 1.2 V digital and 1.2 V (or 1.8 V) analog rails, separated;
- control/status pads for `clk`, `code[0..7]`, `stb`, `rst_n`, `valid`,
  `ready`; digital `dout[0..254]`/`dout_n[0..254]` to the 510 row pads;
- if the row stays 1.8 V, 510 level shifters / 1.8 V drivers between the
  digital and analog pads.

### 6. PPA/SFDR (P2)

- Analog PPA: 51,032 um^2; 7.35 mW at 1.8 V (or ~4.9 mW at 1.2 V);
  25 MS/s; LSB 0.6 mV into 37.5 ohm (16 uA/cell).
- Digital PPA from the IHP LibreLane metrics (area, power, setup/hold).
- Static SFDR from the 16-seed mismatch transfer (same method as
  `video_ics55/static_sfdr.py`; the 8-bit binary DNL/INL 0.196/0.122 LSB is
  the input); dynamic carry 0.062 LSB.
- Full-chip SFDR/PEX after assembly and the wrapper.

## What is already closed

- Analog row generator and layout: 255 cells + replica, 1022 devices,
  510 met2 pads on the 3.75 um grid, DRC 0, PEX 1022 instances / 2.57 pF,
  DC 4.0815 mA, 16-seed DNL/INL 0.196/0.122, carry 0.062 LSB.
- Digital pin contract: `pin_template_ihp130.def`, 523 pins, 510 outputs on
  the exact analog grid, 8-bit binary, 100 um die.
- IHP PDK LibreLane support: `sg13g2_stdcell`, KLayout DRC/LVS, Magic,
  OpenRCX; the `librelane_patch` for the DEF template step.

The critical path is **voltage-domain decision -> IHP row re-spin (if 1.2 V)
-> digital macro hardening -> assembly -> wrapper -> full-chip LVS/PEX/SFDR.**
