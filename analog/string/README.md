# Resistor-string (Kelvin) DAC leaf

Second analog leaf (roadmap P2). Class **C**: the string is regular enough to
generate, but the switch tree, the tap routing and the output follower need
human layout. No OpenROAD P&R near it. The digital half
(`verilog/rtl/dac_string_dig.v`) is a separate standard-cell macro.

## Topology

8-bit voltage-mode string, 3.3 V, following the binary-tree Kelvin references
in `docs/dac_topology_survey.md` (`sky130_ef_ip__rdac3v_8bit`,
`vyges-ip/sky130-potentiometric-dac`).

```
  vref ──┬── Ru ──┬── Ru ── ... ──┬── Ru ── vss       255 units
         t255    t254            t1   t0
           │       │              │    │
           └───────┴── 8-level binary transmission-gate tree ── out
                    (255 TGs, one on per level, 8 in series)
                                                            │
                                                    follower ── vout
```

* `Ru = 1 kOhm` (`W = 2 um`, `L = 5.714 um`, 350 ohm/sq) so the string is
  255 kOhm: 12.9 uA at 3.3 V, 42.6 uW.
* **Binary tree, not a 1-of-256 matrix.** A matrix needs 65536 switches; the
  tree needs 255 and every code passes exactly 8 in series, so the nominal
  switch resistance is code-independent and only its *variation* matters.
* Every switch is one transmission gate (3.3 V devices, `Wn = 32 um`,
  `Wp = 64 um`, `L = 0.28 um`), the same size at every level.
* The tap node is high impedance (up to ~128 kOhm) so the leaf has no drive of
  its own. The follower is a separate leaf; the benches close the loop with an
  ideal unity-gain follower to separate string/tree error from buffer error.

## Why Ru is 1 kOhm

Ru is a three-way trade-off and the value is **measured**, not asserted:

| Ru | TG (Wn/Wp) | DNL (LSB) | worst tap settling |
|---|---|---|---|
| 1 kOhm | 32/64 um | 0.133 | ~8 us |
| 1 kOhm | 16/32 um | 0.156 | ~8 us |
| 4 kOhm | 16/32 um | 0.109 | ~30 us |

(All tt/25 C, ideal-switch control run gives DNL 0.000, so the error is entirely
the MOS tree.) Larger Ru lowers the tree error but its higher tap impedance
costs settling; 1 kOhm with the wide gate is the compromise. Switch width is
*not* free either: wider lowers Ron but raises the tap capacitance and the
off-state load.

## Files

| file | role |
|---|---|
| `string.yaml` | parameters and per-PDK device bindings |
| `gen_string.py` | pre-layout SPICE generator (`dc`, `tran`, `--rtg`, `--mismatch`) |
| `measure.py` | INL/DNL for tap and buffered output, and settling |
| `run_matrix.py` | corner x temperature matrix |
| `run_mismatch.py` | per-unit resistor mismatch sweep |
| `run.sh` | one-command pre-layout regression |
| `gen_gds.py` | reusable 255-unit string GDS generator (KLayout pya) |
| `signoff.py` | fail-closed DRC / LVS / PEX for the string macro |

## Pre-layout results (gf180mcuA, tt/25 C)

Endpoint-fit LSB = 12.941 mV, 256 codes, real TG tree:

| signal | DNL (LSB) | INL (LSB) |
|---|---|---|
| raw tap | -0.133 .. +0.133 | -0.072 .. +0.132 |
| buffered | -0.133 .. +0.133 | -0.072 .. +0.132 |

Monotonic. The buffered output tracks the tap to within the follower gain
error, which confirms that the tree, not the buffer, sets linearity here.

Control run with ideal switches (`--rtg 100`) gives DNL/INL < 1e-6 LSB, which
is the check that the measurement path does not invent the error.

Corner/temperature matrix (`run_matrix.py`, tap node; the buffered output
follows it within the follower gain error):

| corner | temp | DNL (LSB) | INL (LSB) |
|---|---|---|---|
| tt | 25 C | -0.133 .. +0.133 | -0.072 .. +0.132 |
| ff | 25 C | -0.057 .. +0.057 | -0.057 .. +0.043 |
| ss | 25 C | -0.100 .. +0.061 | -0.101 .. +0.005 |
| fs | 25 C | -0.070 .. +0.070 | -0.071 .. +0.008 |
| sf | 25 C | -0.016 .. +0.016 | -0.017 .. +0.008 |
| tt | -40 C | -0.047 .. +0.047 | -0.048 .. +0.001 |
| tt | 125 C | -0.092 .. +0.092 | -0.020 .. +0.091 |

Worst over the matrix: **DNL 0.133 LSB, INL 0.132 LSB**, monotonic in every
point. The error is not monotonic in corner, which is expected: it is a
difference of MOS conductances, not a resistor ratio.

Per-unit resistor mismatch, 0.2 %/unit, 8 seeds, tt/25 C (explicit length
perturbation, since gf180 reports `mis_r = 0`):

| seed | \|DNL\|max | \|INL\|max |
|---|---|---|---|
| worst | 0.126 | 0.134 |
| mean | 0.063 | 0.074 |

Mismatch does not stack on top of the tree error in the worst case - some
seeds pull the two in opposite directions (seed 8 gives 0.017). Estimating
them in quadrature is therefore more honest than adding them: at 0.2 %/unit
the leaf stays inside 0.2 LSB.

Settling (7 pF load, 60 fF tap cap, 10 us per step): 5.0 us for 3 -> 127,
2.7 us for the 127 -> 128 major carry, 0.85 us for 129 -> 254, plus the
follower's own settling.

## Run

```
./run.sh                       # dc + transient + matrix
./run_mismatch.py --seeds 10   # explicit per-unit mismatch
../../run-analog.sh string gf180 prelayout
```

## Status / next steps

Verified: pre-layout linearity and settling at the typical corner, the
ideal-switch control, and the digital half (1826/1826 checks, lint clean).

### Generated string macro (P2 layout, first half)

`gen_gds.py` is the reusable device generator: it places one
`ppolyf_u_resistor` PCell per unit and draws the series/tap/bulk straps on M1,
parameterised by `bits` and `unit_l`. It does not draw resistor geometry.

* 255 units at 5.714 um, pitch `unit_l + 2.6`; the 2.6 leaves 0.37 um between
  the right M1 terminal of one unit and the p-tap tab of the next (the same
  M1.2a margin that bit the R-2R at `X_RB`).
* Every node has an M1 tap pad at y=-1, labelled `t1..t254`; the ends are
  `vss` and `vref`. The series strap dives to y=-1 so it passes under the next
  unit's p-tap (which spans y=0..2); a centreline strap would short to it.
* Macro: 2120 x 4.6 um, 256 labelled terminals, self-check clean.

`signoff.py` drives the three gates through Magic, exactly as
`../r2r/signoff.py` does for P1:

| gate | result |
|---|---|
| DRC | 0 items |
| LVS | 255 unit resistors (5.714 um), 256 ports; the extracted netlist is a single chain `vss - t1 - ... - t254 - vref` |
| PEX | 255 instances, 509 C entries (per-net geometric caps reported, not gated) |

`./signoff.py --selftest` drops a unit and retargets a tap; both mutations must
fail, and do.

Run:

```
../../run-analog.sh string gf180 gds|drc|lvs|pex|all
```

What the generator does **not** contain, and still not verified:

* **The 255-TG binary tree.** It is the routing problem, not a device array:
  255 taps must enter an 8-level tree without crossing the string, and each
  TG is a 32/64 um pass gate. That floorplan is class C and needs a human
  layout; generating the string alone does not close the leaf.
* **The output follower.** Offset and gain error are not included; the benches
  use an ideal 0.999-gain buffer.
* **Post-layout linearity of the complete DAC.** The string macro is signed
  off on its own; the tree and follower are not in it.

The pre-layout numbers in the tables above are schematic-level and still
stand; the string macro changes none of them.
