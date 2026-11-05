# PPA optimization (audiodac)

Baseline is the 30-combo run in `docs/characterization.*`; the optimized
runs used the same RTL and the same PDK decks, with only the die-utilisation
and (for OR1) hold-margin settings changed.

## Results

| PDK | die before | die after | Δ area | cells before → after | power before → after | setup (slow) | f_max (slow) |
|---|---|---|---|---|---|---|---|
| sky130 | 0.406 mm² | **0.233 mm²** | **−42.7%** | 15,494 → 12,937 (−16.5%) | 4.344 → 4.015 mW (−7.6%) | +24.53 → +23.37 ns | 39.3 → 37.5 MHz |
| gf180 | 1.393 mm² | **0.792 mm²** | **−43.2%** | 16,809 → 13,688 (−18.6%) | 78.29 → 75.45 mW (−3.6%) | +17.04 → +19.66 ns | 30.3 → 33.0 MHz |
| ihp130 | 0.815 mm² | **0.462 mm²** | **−43.4%** | 17,865 → 18,133 (+1.5%) | 3.985 → 3.748 mW (−6.0%) | +30.71 → +31.19 ns | 51.8 → 53.1 MHz |
| OR1 | 43.56 mm² | **38.44 mm²** | **−11.7%** | 24,239 → 20,007 (−17.5%) | 46.44 → 40.71 mW (TT, −12.3%) | TT 34.11 → 33.93 ns; SS +33.00 ns | TT 62.9 → 62.1 MHz; SS 58.8 MHz |
| freepdk45 | 0.096 mm² | unchanged | — | 9,034 | 0.927 mW | +38.93 ns | 90.3 MHz |
| ics55 | 0.104 mm² | unchanged | — | 41,536 | 1.488 mW | +32.09 ns | 55.8 MHz |

All optimized runs keep **DRT 0** and positive hold. `sky130` and `gf180`
also keep **KLayout DRC 0**; `ihp130` has its DRC/LVS steps disabled in the
audiodac config (same as the baseline). The headline f_max is still an
I/O-dominated `1/(T_clk - slack)` number (10 ns external delay on a 50 ns
clock), so the small decreases are expected and irrelevant to the 20 MHz
target.

## What changed

### sky130 / gf180 / ihp130: die utilisation

The flow was sizing these dies at `FP_CORE_UTIL=25` (ihp130 also had
`PL_TARGET_DENSITY_PCT=22`), which left the core at 34-39% utilisation.
Setting `FP_CORE_UTIL=45` and `PL_TARGET_DENSITY_PCT=40` in
`openlane/audiodac/config.librelane.json` shrinks the die by ~43% while
still routing and closing timing. The final placement lands at 62-71%
utilisation because the post-synthesis cell area is smaller than the final
(resized) area.

- `sky130`: die 631.9×642.6 → 477.0×487.8 µm, util 34.4% → 62.3%.
- `gf180`: 1167×1194 → 876.5×903.4 µm, util 39.4% → 70.8%.
- `ihp130`: 893.7×912.4 → 670.3×689.0 µm, util 35.9% → 68.2%.

`gf180`'s slow-corner setup actually improves (+17.0 → +19.7 ns) because the
shorter wires more than offset the higher density.

### OR1: 3 corners, fewer hold buffers, smaller die

The 3-corner SS/FF libs expose a fast FF corner. With the old
`PL_RESIZER_HOLD_SLACK_MARGIN=0.3`, the post-CTS resizer inserted **8,559
hold buffers** and detailed placement failed. The FF lib is estimated (its
DFF setup/hold tables are not characterised), so fixing to +0.05 ns is the
right trade: it inserted 2 hold buffers at post-CTS, the final TT hold is
+0.067 ns (FF +0.029, SS +0.116), and the cell count drops from 24,239 to
20,007. The die goes 6600² → 6200² because 6000² ends with 16 DRT
violations on the 2-layer metal2/metal3 stack.

## Not changed

- **freepdk45**: the baseline is already pin-access limited at 20%
  utilisation. Runs at 33% and 28% produced 8k-12k DRT violations; the
  existing 20/15 setting is kept. A 22-23% attempt would gain only ~10%
  area.
- **ics55**: the `util 100%` in the table is filler-inflated (the deck
  classifies fillers as `other`), and the 3,351 KLayout DRC errors are the
  known RV/RDL deck/streamout mismatch. Not a die-size problem.
- **gf180 power**: 75-78 mW is dominated by the 5 V `mcu9t5v0` cell library.
  Moving to the 3.3 V `mcu7t3v3` view would cut it substantially but is a
  different PDK variant, not an in-place optimisation.

## Caveats

- The OR1 3-corner flow currently **OOMs in `OpenROAD.FillInsertion`**
  (~426k fill cells × 3 corners). The PPA metrics were measured with
  `-S OpenROAD.FillInsertion`; the GDS from `runs/exp-or1-6200` therefore
  lacks fill. Re-run fill (or wait for the LibreLane fix) before delivering
  that GDS.
- Multi-corner `power__total` is the worst corner (FF). The OR1 after-run's
  metric is 49.26 mW at FF; the same-corner TT value is 40.71 mW, which is
  the −12.3% figure above. The baseline OR1 run was TT-only.
- `freepdk45` and `ics55` are unchanged; the other macros (`pwmdac`,
  `tempsense`, `config_reg_mux`) were not re-tuned in this pass.

## Reproduce

```sh
# dense dies (sky130 / gf180 / ihp130)
librelane openlane/common.json openlane/audiodac/config.librelane.json \
  --manual-pdk --pdk-root <pdk-root> --pdk <pdk> --scl <scl> \
  --run-tag exp-<pdk>-dense

# OR1: 3 corners + 6200 um die + 0.05 ns hold margin
librelane openlane/audiodac/config.or1.yaml \
  --manual-pdk --pdk-root /grid/OpenRule1um/OR1PDK --pdk OR1 --scl or1_fd_sc \
  --run-tag exp-or1-6200 -S OpenROAD.FillInsertion \
  -S Odb.SetPowerConnections -S Odb.CheckDesignAntennaProperties
```

The baselines are in `openlane/audiodac/runs/<pdk>/final/metrics.json`; the
optimized runs are in `runs/exp-sky130-dense`, `runs/exp-gf180-dense`,
`runs/exp-ihp130-dense`, `runs/exp-or1-6200` (all gitignored).
