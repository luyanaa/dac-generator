# R-2R DAC leaf

First analog leaf in the generator (roadmap P1). Class **B**: the conversion
depends on matched devices, but the array is regular — a device generator with
a fixed floorplan/track plan owns it. No OpenROAD P&R goes anywhere near it.

The digital half (`verilog/rtl/dac_r2r_dig.v`) is a separate standard-cell
macro; the two abut in the wrapper.

## Topology

Voltage-mode 8-bit R-2R, single-ended, 3.3 V, following
`ihsan-sa/ece298a-r2r-dac` (the only surveyed R-2R with extracted post-layout
linearity).

```
        vout = node7
          |
   +------+------+------+ ... +------+
   |      |      |      |          |
  1R     1R     1R     1R          1R
   |      |      |      |          |
 node6  node5  node4  node3  ...  node0
   |      |      |      |          |
  2R     2R     2R     2R         2R     2R (termination)
   |      |      |      |          |       |
  drv6   drv5   drv4   drv3       drv0   vss
 (buf)  (buf)  (buf)  (buf)     (buf)
```

* One resistor unit everywhere: `W = 2.0 um`, `L = 150 um`
  (350 ohm/sq -> ~27 kOhm on gf180 `ppolyf_u`).
* `1R` = one unit; `2R` = two units in series.
* Each driven `2R` has its node-side unit shortened to `L = 148.36 um`, which
  absorbs the mean driver on-resistance (~300 ohm) without breaking the ratio.
* Each bit is driven by a non-inverting CMOS buffer (`Wn = 6 um`,
  `Wp = 16 um`, `L = 0.28 um`). The residual pull-up/pull-down difference
  cannot be trimmed; it is what sets INL.
* 25 units total: 7 series + 2x8 branches + 2 termination.

## Files

| file | role |
|---|---|
| `r2r.yaml` | all parameters and per-PDK device bindings |
| `gen_r2r.py` | pre-layout SPICE generator (`dc` and `tran` benches) |
| `measure.py` | INL/DNL (endpoint fit) and settling extraction |
| `run_matrix.py` | full corner x temperature matrix |
| `run_mismatch.py` | per-unit resistor mismatch sweep |
| `run.sh` | one-command pre-layout regression |
| `gen_gds.py` | device-array GDS generator (KLayout pya) |
| `drc.sh` | gf180 KLayout DRC wrapper (fail-closed) |

## Pre-layout results (gf180mcuA, `ppolyf_u`)

DC, 256 codes, endpoint-fit LSB = 12.8905 mV:

| corner/temp | DNL (LSB) | INL (LSB) |
|---|---|---|
| tt / -40 C | -0.005 .. +0.115 | -0.072 .. +0.046 |
| tt / 25 C | -0.003 .. +0.044 | -0.034 .. +0.013 |
| ss / -40 C | -0.006 .. +0.145 | -0.092 .. +0.056 |
| ss / 125 C | -0.020 .. +0.002 | -0.015 .. +0.008 |
| ff / 125 C | -0.124 .. +0.003 | -0.051 .. +0.073 |

Worst over the 15 corner/temperature points: **DNL 0.145 LSB, INL 0.092 LSB**,
monotonic everywhere.

Transient, 1 MOhm + 7 pF load:

| step | settling to 0.5 LSB |
|---|---|
| 0 -> 1 (1 LSB) | ~125 ns |
| 3 -> 127 (major carry) | ~1.01 us |
| 128 -> 254 | ~1.02 us |
| 255 -> 0 (full scale) | ~1.15 us |

Mismatch (per-unit length sigma, 10 seeds, tt/25 C):

| sigma/unit | worst DNL | worst INL |
|---|---|---|
| 0.2 % | 0.427 LSB | 0.225 LSB |

GF180's `ppolyf_u` model reports `mis_r = 0`, so ngspice Monte Carlo cannot
move a resistor ratio. `run_mismatch.py` perturbs each unit's length
explicitly; this is the only honest bound until the PDK ships per-instance
resistor statistics.

## Run

```
./run.sh                       # dc + transient + corner matrix
./run_mismatch.py              # mismatch sweep
./gen_r2r.py --help
../../run-analog.sh r2r gf180 gds    # write + self-check the GDS
../../run-analog.sh r2r gf180 drc    # GDS + gf180 DRC (see blocker below)
```

Everything is written under `build/` (git-ignored).

`gen_gds.py` is a KLayout pya script, not plain Python — run it as
`klayout -b -r gen_gds.py -rd out=build/r2r.gds -rd check=true`. It places 25
`ppolyf_u_resistor` PCells (one unit per 1R, trimmed unit on the node side of
every driven branch), straps them on M1 with one vertical track per ladder
node, and then checks three things: terminal coverage, pairwise net shorts,
and p-tap clashes.

Floorplan: rows at 155 um pitch, branch `b0` at the bottom, termination row at
-155, node tracks on x = 306 (per node, never a shared bus — a single bus
would short all nodes), the seven vertical 1R units at x = 316, driver pads at
y = -340 with 12 um pitch. The array is **not** single-orientation: the series
1R units are rotated 90 degrees, which does not change a poly rectangle's
resistance but does cost matching. That is a known layout trade-off, not an
oversight.

## Status / next steps

Verified: pre-layout DC linearity over 5 corners x 3 temperatures, settling,
a deterministic mismatch bound, and the digital half (lint clean, 16/16).

The generator GDS passes its own structural checks (50/50 terminals, 0 net
shorts, 0 p-tap clashes) but **DRC, LVS, PEX and post-layout linearity are
open**:

* KLayout 0.30.0 cannot run the gf180 deck — it calls
  `evaluate_nets()`/`nets()`, which need KLayout >= 0.30.9. Excluding the
  connectivity decks only moves the failure onward.
* Magic initialises Tk even under `-d null -noconsole` in this build, so it
  dies on `no display name` before reading the PDK tech file.

`drc.sh` runs the structural checks, then exits 3 with that explanation rather
than reporting a clean run. It runs the real deck unchanged on a newer
KLayout.

sky130 geometry (unit L = 27 um, trim 26.7 um at 2000 ohm/sq) is documented
in `r2r.yaml` but **not simulated**: ngspice 44.2 cannot select a bin from the
180-block sky130 BSIM4 models. `gen_r2r.py --pdk sky130` fails with that
reason. Do not quote sky130 numbers from this leaf.

See `docs/analog_dac_integration_plan.md` section 7.1 for the gate table.
