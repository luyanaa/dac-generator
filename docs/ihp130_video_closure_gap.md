# IHP SG13G2 video DAC: closure status

Status 2026-11-18 (evening).  This is the gap analysis of the IHP130
(`ihp-sg13g2`) video DAC leaf after the 1.2 V re-spin and the digital macro
hardening.  Evidence is in `analog/video_ihp/`, `openlane/dac_video_dig/`,
and the IHP PDK under `pdks/ihp-sg13g2/`.

## Short answer

The **analog row and the IHP digital macro are both signed off separately**,
and the two blocks are **assembled with top-level DRC 0**:

- analog row at **1.2 V series / iref 16.032 uA / Cvcp 470 pF**: all eight
  `signoff.py --stage all` gates pass;
- digital macro (run `ihp_pdn44`): **KLayout DRC 0**, Netgen LVS **0
  device/net/pin differences**, setup **+5.039 ns**, hold **+0.1226 ns**,
  **0.387 mW**, 523 Metal2 pins with the 510 outputs on the exact analog grid;
- assembly `assemble_ihp.py`: **510 independent merged Metal2 islands** and
  **top-level KLayout DRC 0**.

Still open: a reference-CDL analog LVS, the wrapper/bias block, PPA/SFDR,
full-chip LVS/PEX, and one clock-net antenna item (1.14x).  These are listed
below with evidence.

## What closed since the first gap report

| old gap | now | evidence |
|---|---|---|
| P0 voltage domain: 1.8 V row outside `sg13_lv` 1.5 V max Vds | **closed at 1.2 V**, series bias, no layout re-spin | `analog/video/pdk_cell.py` IHP defaults 1.2 V / 16.032 uA / 470 pF; `analog/video_ihp/signoff.py` |
| P0 IHP digital macro had no IHP run | **closed**: `runs/ihp_pdn44` final GDS/DEF/metrics | `runs/ihp_pdn44/final/metrics.json` |
| P0/P1 1.2 V stdcell vs 1.8 V analog gate interface | **closed**: both 1.2 V, no level shifters | `VDD_NETS=[VDD]`, `GND_NETS=[VSS]`, 1.2 V analog row |
| P1 no IHP assembly | **closed**: `assemble_ihp.py`, `y0=-9.5`, Metal2 10/0 | 510 islands, top DRC 0 |
| P1 `signoff.json` only had `pins` | **closed**: `--stage all` restored all 8 stages, all `ok: true` | `analog/video_ihp/build/signoff.json` (git-ignored; values in the README) |
| P2 digital flow details (`VDD_NETS`, CTS, pin-order) | **closed**: VDD/VSS, CTS on, sky130 pin-order moved to `pdk::sky130*` | `openlane/dac_video_dig/config.librelane.json` |

## Verified numbers

### Analog row (1.2 V)

| stage | result |
|---|---|
| build | 255 cells + replica, **1022 devices** (512 pmos / 510 nmos) |
| DRC | PDK `ihp-sg13g2.drc`: **0 items** |
| LVS | `run_lvs.py --net_only` + structural pad-pair walk: **1022 devices, 516 ports**, 255 cell mirrors + replica |
| PEX | Magic hierarchical: **1022 instances, 2.57 pF** |
| DC | extracted, **16.032 uA**: **4.0866 mA (-0.037 %)**, vbp/vcp **0.6316/0.0267 V** |
| MM | PSP103 mismatch, **16 seeds at 1.2 V**: cell sigma **0.704 %**, **DNL 0.1467 / INL 0.0906 LSB**, monotonic |
| tran | carry 127->128, **470 pF on vcp + 100 pF on vbp**: **0.029 LSB** at 40 ns, drift **-0.023/-0.068 mV** |
| pins | **510 Metal2 pads** on the 3.75 um grid, 516 labels (10/25) |

The cell-level full-scale study (0 -> 255) is the reason for **470 pF**, not
330 pF: at 330 pF it lands at 0.549 LSB (over the 0.5 gate); at 470 pF it
settles in **2.81 ns at 0.457 LSB** (`build/pdk_ihp-sg13g2_mos_tt_1.2_series_i16.032_c470.json`).
The 1.2 V **wide-swing** replica is not used: carry -0.783 LSB, full -1.772
LSB, dvcp +82.7 mV.  The existing series replica/layout is unchanged.

### Digital macro (run `ihp_pdn44`, IHP 1.2 V stdcells)

| item | result |
|---|---|
| DRC | **0** (KLayout `ihp-sg13g2.drc`, deep mode, 8 threads) |
| LVS | Netgen: **0** device / net / pin / property differences |
| timing | setup WS **+5.039 ns** at `nom_slow_1p08V_125C`; hold WS **+0.1226 ns** at `nom_fast_1p32V_m40C`; 0 setup/hold violations |
| power | **0.387 mW** |
| area | die **1912.5 x 100 um**, core 129,330 um^2, 1,203 stdcells + 10,167 fill |
| pins | **523**: 510 `dout/dout_n` at `x = 2.25 + 7.5k / 6.0 + 7.5k`, `y = 0..0.6`; 13 control pins at `y = 100` |
| encoding | **8-bit binary**; `dout[2^k-1+i] = code[k]`, matching the row's `b{k}_{i}` tag and the 7.5 um cell pitch |
| antenna | **1 violation**: `clk` -> `clkbuf_0_clk/A`, Metal3, ratio 228.29 vs 200 (1.14x) |

The digital macro's 255 outputs are driven by **8 code registers** (one per
bit) plus output buffers: all cells in a binary group carry the same bit, so
Yosys legally shares the register.  This is still a single-clock-edge launch
and is what the RTL comment intends.

### Assembly

`openlane/dac_video_dig/assemble_ihp.py` places the digital macro mirrored
in Y at `y0 = -9.5` below the analog row:

- digital pins become -10.1..-9.5; analog pads are -10.0..-9.6 -> **0.4 um
  overlap** on Metal2 (10/0), no jog and no via;
- **510 distinct merged Metal2 islands**, no shared island, all 510 centres
  covered;
- top-cell bbox -1.0,-109.8 .. 1918.5,12.0 um;
- **PDK KLayout DRC on `dac_video_top`: 0 items**.

```sh
cd openlane/dac_video_dig
DIG_GDS=runs/ihp_pdn44/final/gds/dac_video_dig.gds \
  /usr/bin/klayout -b -r assemble_ihp.py -z
/usr/bin/klayout -b -zz -r \
  /grid/dac-generator/pdks/ihp-sg13g2/libs.tech/klayout/tech/drc/ihp-sg13g2.drc \
  -rd input=build/dac_video_top.gds -rd topcell=dac_video_top \
  -rd report=build/top_drc.lyrdb -rd no_recommended=true \
  -rd run_mode=deep -rd thr=8
```

## Remaining gaps

1. **Reference-CDL analog LVS (P1).**  The row signoff is still the PDK
   `run_lvs.py --net_only` extraction plus a structural pad-pair walk.  There
   is no `gen_cdl.py` for the IHP row yet (unlike `video_ics55`), so a full
   schematic-vs-layout compare with the extracted 1022-device netlist is still
   missing.
2. **Wrapper and bias (P1).**  The wrapper must provide:
   - **iref 16.032 uA** (resistor/current mirror with startup);
   - **470 pF on vcp**, **100 pF on vbp** (both are external components);
   - 1.2 V analog and 1.2 V digital rails (can be the same domain, but keep
     the 510 gate nets and the row's `vdd`/`vbp`/`vcp`/`iout`/`idump` rails
     separate from the digital PDN);
   - control/status pads: `clk`, `code[0..7]`, `stb`, `rst_n`, `valid`,
     `ready`; the digital `dout/dout_n` are already on the row's pad row;
   - no on-chip reference, startup or decap exists in either block.
3. **PPA/SFDR (P2).**  Analog: 51,032 um^2, ~4.9 mW at 1.2 V, 25 MS/s, LSB
   0.601 mV into 37.5 ohm.  Digital: 0.387 mW, 129,330 um^2 core, setup/hold
   above.  Static SFDR can be computed from the 16-seed 1.2 V transfer (DNL
   0.1467 / INL 0.0906 LSB) with `video_ics55/static_sfdr.py`; dynamic carry
   0.029 LSB.  No full-chip SFDR yet.
4. **Full-chip LVS/PEX (P2).**  The blocks are signed off separately and the
   assembly is DRC-clean with isolated pad islands, but there is no top-level
   netlist, combined LVS, or full-chip RCX/SFDR.  The digital macro has SPEF
   and post-PnR STA; the analog row has Magic PEX; a top-level extraction is
   still missing.
5. **Antenna (P2).**  One clock net is 1.14x over the cumulative Metal3
   antenna limit (`clk` -> `clkbuf_0_clk/A`).  Fixes: shorten the M3 clock
   route, move the clock to Metal2 (`RT_CLOCK_MAX_LAYER`), widen the first
   buffer's input gate, or insert an antenna diode.  It is the only remaining
   digital DRC/LVS-adjacent item.
6. **RF/MOM:** not a gap.  The DAC uses neither.

## Digital flow notes (reproducible)

```sh
cd openlane/dac_video_dig
PYTHONPATH=$PWD/librelane_patch \
librelane config.librelane.json \
  --pdk ihp-sg13g2 --pdk-root /grid/dac-generator/pdks \
  --manual-pdk --run-tag <tag>
```

The IHP section sets `VDD_NETS=[VDD]`, `GND_NETS=[VSS]`, `RUN_CTS=true`,
`FP_DEF_TEMPLATE=pin_template_ihp130.def`, `PDN_RAIL_WIDTH=0.44`, and
`RUN_MAGIC_DRC=false` (Magic DRC OOM-killed the 28k-instance 1912x100 macro;
the PDK KLayout deck is the golden check).  Three details matter:

- **PDN rail width 0.44 um.**  The `sg13g2` cell power pin is 0.44 um tall
  (3.56..4.00 in a 3.78 um row).  The default 1.0 um rail leaves a 0.10 um
  notch to the cell internal M1: 3,924 `M1.b` + 33 `M1.e` violations.  0.44
  matches the pin and clears both; 0.6 leaves 74 `M1.b`/`M1.e` items.
- **`FP_DEF_TEMPLATE` and `IO_PIN_ORDER_CFG` live in `pdk::sky130*`.**  A
  top-level key after the `pdk::` sections overrides them, so the IHP run
  was reading the sky130 template and failing at ApplyDEFTemplate with
  `met2`/`code[7]` errors.  The IHP section's `FP_DEF_TEMPLATE` is
  authoritative.
- **`--last-run` only selects a run directory; it does not resume.**  Add
  `--from <Step.Id>` to continue (for example `--from Odb.RemovePDNObstructions`).
  Regenerating PDN on top of an existing PDN with a different rail width can
  report "grid does not contain any shapes"; start the PDN from a fresh run.

The previous 1.8 V row also needed `Cvcp=220 pF`; at 1.2 V the cell
full-scale study sets **470 pF**.  The row signoff tran uses 470 pF and the
same 100 pF on vbp.

The critical path is now **wrapper/bias -> reference-CDL LVS -> full-chip
LVS/PEX -> PPA/SFDR -> antenna fix.**
