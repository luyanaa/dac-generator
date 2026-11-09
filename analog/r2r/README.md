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
| `signoff.py` | fail-closed DRC / LVS / PEX (Magic, gf180) |

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
../../run-analog.sh r2r gf180 prelayout  # DC + tran + corner matrix
../../run-analog.sh r2r gf180 gds        # build + self-check the GDS
../../run-analog.sh r2r gf180 drc        # build + Magic DRC
../../run-analog.sh r2r gf180 lvs        # build + extracted-netlist LVS
../../run-analog.sh r2r gf180 pex        # build + hierarchical PEX
../../run-analog.sh r2r gf180 all        # prelayout + all three signoff gates
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

## Signoff (gf180mcuA)

The array is signed off through Magic, because gf180 ships no KLayout DRC deck
in this install. `signoff.py` is the single fail-closed entry point and
`run-analog.sh r2r gf180 {gds,drc,lvs,pex,all}` drives it.

| gate | result |
|---|---|
| DRC (`drc check` / `drc catchup` / `drc count total`) | 0 items |
| LVS (Magic-extracted netlist, graph check) | 25 resistors: 17 unit at 150.0 um + 8 trim at 148.36 um; 9-row ladder, 7-unit 1R chain, termination 2R, ports `vss b0..b7 n0..n6 vout` |
| PEX (hierarchical, `cthresh`/`rthresh` 0) | 25 instances, 37 C entries; per-net geometric caps reported (e.g. `vss` 35.8 fF, `b7` 140.6 fF, `vout` 5.7 fF) |

Two things the first signoff caught, both in `gen_gds.py`:

* **M1.2a at every row.** `rb` sat at `X_RB = 152.4`, which put ra's right M1
  terminal (ending at 150.53 um) only 0.14 um from rb's p-tap M1 tab (starting
  at 150.67 um) — under the 0.23 um rule. `X_RB = 152.7` gives a 0.44 um gap.
  The poly gap was fine; the metal was not, which is why the self-check did not
  see it.
* **Floating labels.** The `n0..n7` labels sat at `X_BUS + 4` and the `vout`
  text above the pad, both off metal. Magic turned them into eight `n*_uq0`
  dangling ports plus a dangling `vout`, while the real output was the pad's
  `n7`. The labels are now on the straps and the pad carries `vout`.

The DRC claim is scoped to Magic's gf180 rule set: spacing, width, enclosure,
overlap and via rules. Density/coverage checks (DCF.1a/b, PL.8, M1.4-M5.4,
MT.3) are not in the tech's `drc` section, so no fill or density waiver is
claimed for this macro.

LVS is a graph check, not a netgen compare: there is no schematic netlist for
this macro and the contract is topological. The expected ladder is written in
`signoff.py` independently of `gen_gds.py`'s placement, and
`./signoff.py --selftest` mutates the extracted netlist (drop a unit, retarget
a trim) to prove the gate actually rejects wrong connectivity.

Still open, and **not claimed**:

* post-layout DC/transient sweep of the extracted ladder (the netlist is kept
  for it — Magic does not model the poly resistor's distributed R-C, so a
  post-layout linearity number needs a device model the deck does not provide);
* the per-bit CMOS drivers, the vdd/vss ring and the wrapper around the
  digital half: hand work, class C.

sky130 geometry (unit L = 27 um, trim 26.7 um at 2000 ohm/sq) is documented
in `r2r.yaml` but **not simulated**: ngspice 44.2 cannot select a bin from the
180-block sky130 BSIM4 models. `gen_r2r.py --pdk sky130` fails with that
reason. Do not quote sky130 numbers from this leaf.

See `docs/analog_dac_integration_plan.md` section 7.1 for the gate table.
