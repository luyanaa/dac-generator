# LibreLane flow (replaces the old OpenLane 1.x `make.sh`)

The leaf macros are hardened with **LibreLane 3.0.14** (`librelane`, nix
profile). The legacy `openlane`/`flow.tcl` Docker flow is no longer used.

## TL;DR

```sh
./run.sh <macro> <pdk-spec>
```

- `macro`: `const_gen` · `config_reg_mux` · `audiodac` · `pwmdac` ·
  `tempsense` · `dac_r2r_dig` · `dac_video_dig` · `all`
- results land in `results/<pdk-spec>/<macro>/` (Efabless layout) and the
  run dir in `openlane/<macro>/runs/<pdk-spec>/`

Post-PnR characterization (clock, worst slack, implied f_max, PEX/SPEF,
area/utilization/power, sign-off counters) is regenerated with:

```sh
python3 tools/characterize.py     # -> docs/characterization.{md,csv}
```

## PDK specs

| spec            | PDK name        | root                       | std-cell lib                    |
|-----------------|-----------------|----------------------------|---------------------------------|
| `sky130`        | `sky130A`       | ciel `~/.ciel`             | `sky130_fd_sc_hd`               |
| `sky130-hdll`   | `sky130A`       | ciel                       | `sky130_fd_sc_hdll`             |
| `sky130-ls`     | `sky130A`       | ciel                       | `sky130_fd_sc_ls`               |
| `sky130-osu-t18`| `sky130A`       | ciel                       | `sky130_osu_sc_t18`             |
| `sky130-as-hs`  | `sky130A`       | `./pdks` (view)            | `sky130_as_sc_hs`  (/grid)      |
| `ihp130`        | `ihp-sg13g2`    | `./pdks` (view)            | `sg13g2_stdcell`                |
| `ihp130-hv`     | `ihp-sg13g2`    | ciel                       | `sg13g2_stdcell_hv` (/grid)     |
| `ihp130-cmos5l` | `ihp-sg13cmos5l`| ciel                       | `sg13g2_stdcell`                |
| `gf180`         | `gf180mcuD`     | `./pdks` (view)            | `gf180mcu_fd_sc_mcu9t5v0`       |
| `gf180-7t`      | `gf180mcuD`     | `./pdks` (view)            | `gf180mcu_fd_sc_mcu7t5v0`       |
| `gf180-as-7t3v3`| `gf180mcuD`     | `./pdks` (view)            | `gf180mcu_as_sc_mcu7t3v3` (/grid)|
| `gf180-osu-9t`  | `gf180mcuD`     | `./pdks` (view)            | `gf180mcu_osu_sc_gp9t3v3` (/grid)|
| `ics55`         | `icsprout55-pdk`| `/grid`                    | `ics55_LLSC_H7CL`               |
| `ics55-h7ch`    | `icsprout55-pdk`| `/grid`                    | `ics55_LLSC_H7CH`               |
| `ics55-h7cr`    | `icsprout55-pdk`| `/grid`                    | `ics55_LLSC_H7CR`               |
| `freepdk45`     | `freepdk45`     | ciel `~/.ciel`             | `nangate45`                     |
| `or1`           | `OR1`           | `/grid/OpenRule1um/OR1PDK` | `or1_fd_sc`                     |

`gf180mcu` is run as the **D** flavour (`gf180mcuD`).

`gf180` also has 7-track and 3.3 V flavours. `gf180-as-7t3v3`
(`gf180mcu_as_sc_mcu7t3v3`) cuts audiodac power from 78.3 to 16.1 mW
(-79%) and die from 1.393 to 0.600 mm2 while raising the slow-corner
f_max from 30.3 to 51.9 MHz; `gf180-7t` is the 5 V 7-track drop-in
(58.9 mW, 0.630 mm2, 24.9 MHz). See `docs/gf180_variants.md`.

### PDK "views"

`/grid` standard-cell repos ship only `libs.ref/` + `libs.tech/` fragments
meant to be overlaid on a full PDK. `tools/make_pdk_view.sh` composes a
`<pdkname>/{libs.ref,libs.tech}` tree of symlinks under `./pdks/` so they
become first-class `--scl` choices without touching the shared PDKs.
Some PDKs need a patched SCL `config.tcl` (e.g. expose `LIB`); those live in
`./overrides/` and are merged in by the same script.

Rebuild the views with:

```sh
SKY=$(ls -d ~/.ciel/ciel/sky130/versions/*/sky130A | tail -1)
GF=$(ls -d ~/.ciel/ciel/gf180mcu/versions/*/gf180mcuD | tail -1)
IHP=$(ls -d ~/.ciel/ciel/ihp-sg13/versions/*/ihp-sg13g2 | tail -1)
tools/make_pdk_view.sh pdks sky130A   "$SKY" /grid/sky130/sky130_as_sc_hs/pdk
tools/make_pdk_view.sh pdks gf180mcuD "$GF"  "$PWD/overrides/gf180mcuD"
tools/make_pdk_view.sh pdks ihp-sg13g2 "$IHP" "$PWD/overrides/ihp-sg13g2"
```

`overrides/` holds only the small `config.tcl` wrappers that source the ciel
SCL config and expose `::env(LIB)` for LibreLane (found under `~/.ciel`, no
user/version pinned). A 7.9 MB copy of the optional `gf180mcu_as_sc_mcu7t3v3`
SCL (used only by the `gf180-as-7t3v3` spec) is **not** checked in; take it
from `/grid/gf180mcu/gf180mcu_as_sc_mcu7t3v3/pdk` if that spec is needed.

## Hardening matrix

All five leaf macros are hardened on six PDKs — **30 / 30 GDS** delivered
under `results/<pdk>/<macro>/gds/`:

| macro | sky130 | gf180 | ihp130 | ics55 | freepdk45 | or1 |
|---|---|---|---|---|---|---|
| `const_gen`      | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| `config_reg_mux` | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| `audiodac`       | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| `tempsense`      | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| `pwmdac`         | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |

Delivered views are `gds` everywhere plus `lef/def/lib`/`spef` where the
sign-off steps that generate them could run (see the gaps below).
Numbers per combo: `docs/characterization.md`.

### View gaps (deliberate, sign-off steps disabled)

Some foreign-PDK combos do not have every view because the step that
produces it does not converge on that deck; the GDS is still valid:

- **ics55**: `Magic.WriteLEF`/`Magic.SpiceExtraction` are skipped (Magic
  cannot parse the RV/RDL/T4M2 LEF and loops on the 41k-instance netlist) →
  no `lef` for any of the five macros, and no `def` for
  `const_gen`/`config_reg_mux`. Views present: `audiodac` and `pwmdac`
  (`def`+`lib`+`spef`), `tempsense` (`def`+`spef`; no `lib`, MC-STA off),
  `const_gen`/`config_reg_mux` (GDS only).
- **`tempsense` on gf180 / ihp130 / ics55 / freepdk45 / or1**: the `einvp`
  VDAC cell is a black-box stub and the analog sign-off steps plus
  `RUN_MCSTA` are disabled → no `lib`; also no `lef` on ics55 / freepdk45 /
  or1 (`Magic.WriteLEF` disabled).
- **`audiodac`/ihp130**: `Magic.WriteLEF` is skipped (33k cells, does not
  converge) → no `lef` (`def`, `lib`, `spef` are present).
- **`const_gen`/or1**: no `lib` (the OR1 deck has no MCSTA/RCX view);
  `lef`/`def`/`spef` are present.

### Analog-leaf digital halves (`_dig`)

`openlane/dac_*_dig/` are the standard-cell halves of the analog leaves. They
are run explicitly (`./run.sh dac_video_dig sky130`), not from `all`, because
their die area is the analog array's abutment row and their parameters are
PDK-specific.

`dac_video_dig` is the 25 MS/s video current-steering decoder. Its analog
array is 255 cells on a 7.5 um pitch with `d_`/`db_` pads on an exact
3.75 um grid at `x = 2.25 + j*3.75`; the macro is drawn 1912.5 um wide to
match. `openlane/dac_video_dig/gen_pin_template.py` generates:

* `pin_template_<pdk>.def` - the exact abutment row (510 outputs on met2 /
  Metal2 at the analog pad coordinates, control pins on the north edge).
* `pin_order_sky130.cfg` - the same pin order for `IO_PIN_ORDER_CFG`.

The config uses `IO_PIN_ORDER_CFG` because LibreLane 3.0.14 cannot ingest the
DEF template: `Odb.ApplyDEFTemplate` raises
`KeyError: 'design__die__bbox'` (the string metric from
`apply_def_template.py` is dropped by the metrics parser). The resulting row
is therefore on the routing track grid: met2 pitch 0.46 um gives 3.68 um per
pin instead of 3.75, i.e. the row spans 18.63..1891.75 um against the analog
2.25..1911.0 um (max ~19 um misalignment at the ends). Pin *order* is exact
(`d0, db0, d1, db1, ...`), so a wrapper can route the 510 nets; true
abutment needs the DEF-template step fixed.

The sky130 config synthesizes `RESOLUTION=7, ENCODING=1` (7-bit thermometer:
127 of the 255 cells, the rest held off so their dump-tail pair still steers
to idump); gf180 and ihp130 use `RESOLUTION=8, ENCODING=0`.

## Characterization

`docs/characterization.md` (`/csv`) is generated from the LibreLane run
results by `tools/characterize.py`. For every combo it reports the clock
period, worst setup/hold slack over all PVT corners, the implied
`f_max = 1/(T_clk - worst_setup_slack)`, whether the post-PnR STA had a
SPEF from `OpenROAD.RCX` (PEX-annotated), die area, utilization, cell count,
total power and DRC/LVS counters.

Rows whose source is `post-GRT, default corner` come from decks with
`RUN_MCSTA=false` (the `tempsense` black-box VDAC): only `DEFAULT_CORNER`
is re-evaluated after global routing, the other corners in `metrics.json`
are stale pre-PnR values and are ignored.

Highlights (MHz, 50 ns clock unless a combo is timing-violated):

| macro | sky130 | gf180 | ihp130 | ics55 | freepdk45 | or1 |
|---|---|---|---|---|---|---|
| `config_reg_mux` | 41.5 | 35.8 | 44.7 | 39.4 | 48.6 | 46.2 |
| `tempsense` | 78.0 | 59.1 | 91.1 | 91.2 | 97.2 | 90.0 |
| `pwmdac` | 54.0 | 35.5 | 59.5 | 40.1 | 91.6 | 39.7 |
| `audiodac` | 39.3 | 30.3 | 51.8 | 55.8 | 90.3 | 62.9 |

`const_gen` is purely combinational (no timed path). All `audiodac`
variants now meet the 20 MHz clock, including ics55/OR1 (see the timing
closure section below); ics55 `audiodac`/`tempsense` still read ~100%
utilization because that deck counts filler cells as standard cells.

### PPA optimization

`docs/ppa_optimization.md` records a dense-die pass on `audiodac`:
sky130/gf180/ihp130 shrink the die by ~43% at `FP_CORE_UTIL=45` (DRT 0;
sky130/gf180 DRC 0; timing still 2-3x the 20 MHz target), and OR1 goes
6600² -> 6200² with a +0.05 ns hold margin, cutting 17.5% of the cells.
freepdk45 is pin-access limited and ics55 is filler/deck limited; both are
unchanged. The OR1 3-corner flow currently OOMs in
`OpenROAD.FillInsertion`; see the caveat in that document.

## Timing closure

### audiodac

`sinegen` reads a 128-entry LUT with a variable part-select, so each
`read_ptr` bit fans out to ~600 mux selects. With the post-GPL repair pass
disabled (it used to runaway to ~22k buffers) that single net was ~25 ns on
sky130 and >430 ns on ics55, dominating the macro's f_max.

The audiodac configs now run `OpenROAD.RepairDesignPostGPL` with
`MAX_FANOUT_CONSTRAINT=80` and I/O buffering disabled. It inserts ~390
buffers (sky130) to ~920 (OR1) in ~300 nets, then the post-CTS / post-GRT
resizers optimize the remaining paths. Result:

| f_max (MHz) | sky130 | gf180 | ihp130 | ics55 | freepdk45 | or1 |
|---|---|---|---|---|---|---|
| before | 16.7 | 18.6 | 15.3 | 2.3 | 25.4 | 4.8 |
| after  | 39.3 | 30.3 | 51.8 | 55.8 | 90.3 | 62.9 |

All decks close 20 MHz with positive hold slack (worst: ics55 +0.063 ns at
the fast corner). `freepdk45` was already timing-clean before this change
and was left as-is.

**OR1 caveat.** The OR1 column is not signoff-grade: the deck exposes a
single `TT_5.0 V / 25 °C` corner (no slow/fast corners or derates), its
liberty header states the DFF setup/hold tables are *not characterised yet*,
and the audiodac worst path is I/O-dominated (10 ns of the 15.9 ns path is
the external input delay). The PDK's own reference counter (31 cells,
20 ns clock) shows +15 ns slack, so the deck is simply fast at TT — the
62.9 MHz is an optimistic TT estimate, not a silicon speed. See
`docs/or1_characterization.md` for the I/O (62.9 MHz) vs register-to-register
(72.7 MHz) split and the hold numbers.

### Hold closure

All 30 macro/PDK combinations now have **positive setup and hold** on the
corner that is actually evaluated. The last two ics55 cases needed the
post-CTS resizer re-enabled with a relaxed target:

- `tempsense`/ics55: +0.24 ns at `nom_tt` (post-GRT estimate; the deck has
  `RUN_MCSTA=false`, so only the default corner is re-evaluated).
- `pwmdac`/ics55: +0.06 ns at `nom_ff` (post-route STA). Fixing the -0.19 ns
  fast-corner hold costs ~1.3k hold buffers; setup still closes with +25 ns
  and DRT is clean, but the extra small cells trip ~1.3k ics55
  min-area/implant deck rules, kept non-fatal like the other ics55 signoff
  checks (no routing DRC).

OpenROAD's `repair_timing` is single-corner, so the resizer fixes the
default corner only; these two were the only cases where that corner was
also the worst one.

### Reproducible skips

`run.sh` encodes the per-deck skips that cannot converge:
`*/ics55` skips `Magic.WriteLEF` + `Magic.SpiceExtraction` +
`Odb.CheckDesignAntennaProperties`; `*/or1` skips `Odb.SetPowerConnections` +
the antenna checker; `audiodac/ihp130` and `tempsense/freepdk45` skip the
missing-LEF antenna checker.

## Notes / caveats

- **LibreLane 3.0.14 `io_place.py` pin-length bug** (worked around): when
  `IO_PIN_V_LENGTH`/`IO_PIN_H_LENGTH` are unset it derives the pin length
  from `layer.getArea()`, but that value is already in dbu² so a
  67600-dbu² met2 pin becomes a ~241000µm-tall port and I/O placement
  scatters pins off-die (`GRT-0036 "outside die area"` → `GRT-0080`).
  Every macro using `IO_PIN_ORDER_CFG` sets both to `2` (µm) to bypass the
  broken default. Worth reporting upstream.
- `config_reg_mux`/`audiodac` set `RUN_REPAIR_DESIGN=false`: the post-GPL
  `repair_design` ran away inserting ~20–35k repeater buffers into the
  high-fanout select/data nets, pushing the die to 170%+ utilization
  (`DPL-0038`/`DPL-0036`). The bounded post-CTS `resizer_timing` pass
  handles the real repair; `MAX_FANOUT_CONSTRAINT=80` keeps the SDC
  fanout cap from re-triggering a tree.
- `ALL_PROXY`/`all_proxy` is unset inside `run.sh`: a socks proxy breaks
  ciel/httpx (needs `httpx[socks]`).
- ciel PDKs are used **offline**: `run.sh` points `--pdk-root` at the
  already-installed `~/.ciel/ciel/<fam>/versions/<hash>` dir with
  `--manual-pdk`, so no network fetch happens.
- `tempsense` directly instantiates `sky130_fd_sc_hd__einvp_1` in its VDAC.
  On non-sky130 PDKs a black-box model (`verilog/models/analog_cells.v`)
  lets the netlist elaborate; the analog VDAC is **not functional** there —
  a per-PDK equivalent enable-inverter cell is required for real silicon.
- `user_project_wrapper` is still caravel-shaped (fixed DEF template,
  caravel power domains, `adc_top` macro) and only hardens on `sky130*`.
- Deprecated/removed config keys were dropped: `RUN_CVC` (unsupported),
  `DESIGN_IS_CORE`→`PDN_MULTILAYER`, `PL_TARGET_DENSITY`→`PL_TARGET_DENSITY_PCT`,
  `MAGIC_WRITE_FULL_LEF`, `PL_OPENPHYSYN_OPTIMIZATIONS`.

### audiodac sine LUT (found via FPGA synthesis)

`audiodac_sinegen` used a flat `[0:BW*2**LUT_SIZE-1]` vector and a variable
part-select (`SINE_CONST[read_ptr*BW +: BW]`). Icarus and Yosys disagree on
the bit order of that construct, so the yosys/ASIC netlist evaluated a
different table from RTL simulation (with `LUT_SIZE=7`/`SINE_AMPL=0.5` the
netlist starts at -9152 instead of +571). It is now a 2-D array indexed by
`read_ptr`, verified by comparing pre/post-synthesis simulation.

Impact: the six delivered `audiodac` GDS were synthesized before this fix,
so their `tst_sinegen_en_i=1` test-sine mode is wrong; the normal
FIFO -> delta-sigma path is unaffected. Re-run `audiodac` on all PDKs when
LibreLane is available. The fix does not change the mux structure or the
`read_ptr` fanout that the timing closure was built around.

An FPGA smoke-test flow (yosys + nextpnr, OSS CAD Suite) lives in `fpga/`
(see `fpga/README.md`): `audiodac` fits an iCE40 UP5K (39/39 I/O, 18 MHz)
and closes 52 MHz on an ECP5-25k.

### OR1 (`/grid/OpenRule1um/OR1PDK/OR1`)

- The updated OR1 deck has async-reset FFs, so `const_gen`/`config_reg_mux`/
  `tempsense`/`audiodac` harden like the other PDKs. OR1 needs a **single
  self-contained YAML** (`openlane/<macro>/config.or1.yaml`): step-scoped
  `Path` variables and `MACROS`/`MACRO_PLACEMENT_CFG` do not survive
  LibreLane's multi-file JSON merge, so they must live in one file.
- `PL_MAX_DISPLACEMENT_X/Y = 2000` (µm): the default ±3-row limit cannot
  spread the 84 µm `DFFRX1` cells (`DPL-0036`).
- `GRT_ALLOW_CONGESTION = true`, `DRT_OPT_ITERS = 10`; the PDN pitches are
  reset to 120/200 µm (the inherited 12/24 µm stripes block every wide cell),
  and `Odb.SetPowerConnections` / `Odb.CheckDesignAntennaProperties` are
  skipped (escaped hierarchical names → 0 connections).
- OR1 ML2 DRC reports ~85 width/space violations on this deck; they are
  recorded in the run dir and kept non-fatal (`ERROR_ON_KLAYOUT_DRC=false`).
  Timing-checker corners are `[""]` for the same reason.
- OR1 `einvp` is a black-box stub (`openlane/tempsense/einvp_or1.*`,
  `verilog/models/or1_analog_cells.v`) — the analog VDAC is not functional.

### Foreign-PDK sign-off

To get GDS out of the foreign decks, a few sign-off checks are disabled
per-combo rather than left failing; each one is annotated in the relevant
`config.librelane.json` with the reason:

- ihp130 `audiodac`/`pwmdac`: `sg13g2_decap_8` fillers produce ~11k M1.b
  (0.18 µm metal1 space) errors; Magic full DRC/SPICE on 33k cells never
  finishes, so `RUN_MAGIC_DRC`/`RUN_LVS`/`RUN_KLAYOUT_DRC` are off for
  `audiodac`.
- ics55 `audiodac`: `RUN_LVS=false` (Magic SPICE extraction hangs on 33k
  cells).
- freepdk45 `audiodac`: DRT is pin-access limited; `FP_CORE_UTIL=20`,
  `PL_TARGET_DENSITY_PCT=15`, `GRT_ADJUSTMENT=0.5`. One residual KLayout DRC
  error is kept non-fatal.
- The `lib` views that would come from `RUN_MCSTA` are also disabled on the
  combos listed under "View gaps"; those macros must be re-run with the
  deck's analog cells replaced before hierarchical integration.
