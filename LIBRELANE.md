# LibreLane flow (replaces the old OpenLane 1.x `make.sh`)

The leaf macros are hardened with **LibreLane 3.0.14** (`librelane`, nix
profile). The legacy `openlane`/`flow.tcl` Docker flow is no longer used.

## TL;DR

```sh
./run.sh <macro> <pdk-spec>
```

- `macro`: `const_gen` · `config_reg_mux` · `audiodac` · `pwmdac` ·
  `tempsense` · `all`
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

- **ics55**: `RUN_MAGIC_WRITE_LEF=false` (Magic cannot parse the RV/RDL/T4M2
  LEF) → no `lef` for any of the five macros, and no `def` for
  `const_gen`, `config_reg_mux`, `pwmdac`. `RUN_MCSTA=false` (plus no SPEF
  for the three smaller macros) → no `lib`/`spef` except on
  `audiodac` (`lib`+`spef`) and `tempsense` (`spef`).
- **`tempsense` on gf180 / ihp130 / ics55 / freepdk45 / or1**: the `einvp`
  VDAC cell is a black-box stub and the analog sign-off steps plus
  `RUN_MCSTA` are disabled → no `lib`; also no `lef` on ics55 / freepdk45 /
  or1 (`Magic.WriteLEF` disabled).
- **`audiodac`/ihp130**: `Magic.WriteLEF` is skipped (33k cells, does not
  converge) → no `lef` (`def`, `lib`, `spef` are present).
- **`const_gen`/or1**: no `lib` (the OR1 deck has no MCSTA/RCX view);
  `lef`/`def`/`spef` are present.

## Characterization

`docs/characterization.md` (`/csv`) is generated from the LibreLane run
results by `tools/characterize.py`. For every combo it reports the clock
period, worst setup/hold slack over all PVT corners, the implied
`f_max = 1/(T_clk - worst_setup_slack)`, whether the post-PnR STA had a
SPEF from `OpenROAD.RCX` (PEX-annotated), die area, utilization, cell count,
total power and DRC/LVS counters.

Highlights (MHz, 50 ns clock unless a combo is timing-violated):

| macro | sky130 | gf180 | ihp130 | ics55 | freepdk45 | or1 |
|---|---|---|---|---|---|---|
| `config_reg_mux` | 41.5 | 35.8 | 44.7 | 39.4 | 48.6 | 46.2 |
| `tempsense` | 78.0 | 52.0 | 90.9 | 91.2 | 97.2 | 90.0 |
| `pwmdac` | 54.0 | 35.5 | 59.5 | 42.6 | 91.6 | 39.7 |
| `audiodac` | 39.3 | 30.3 | 51.8 | 55.8 | 25.4 | 62.9 |

`const_gen` is purely combinational (no timed path). All `audiodac`
variants now meet the 20 MHz clock, including ics55/OR1 (see the timing
closure section below); ics55 `audiodac`/`tempsense` still read ~100%
utilization because that deck counts filler cells as standard cells.

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
| after  | 39.3 | 30.3 | 51.8 | 55.8 | 25.4 | 62.9 |

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

### Residual fast-corner hold

`tempsense` (ihp130, ics55) and `pwmdac` (ics55) still report a small
fast-corner hold violation (-0.07 / -0.17 / -0.19 ns). OpenROAD's
`repair_timing` is single-corner, so LibreLane's resizer only fixes the
default corner and the fast-corner path stays invisible to it; setup closure
and GDS are unaffected. A per-corner resizer pass (or a CTS skew tune) is
needed to remove these.

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
