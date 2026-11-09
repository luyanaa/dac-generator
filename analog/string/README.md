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

Not verified:

* **No GDS yet.** `run-analog.sh string gf180 gds` exits 2 on purpose. The
  string array is mechanical, but the 255-TG tree, the tap routing (255
  taps into an 8-level tree without crossing the string) and the follower are
  class C and need a human floorplan first. A generator for the string-only
  block would be easy and would not close any gate on its own.
* **Follower is a separate leaf.** Its offset and gain error are not included;
  only its ideal 0.999 gain is modelled.
* DRC/LVS/PEX blocked by the KLayout 0.30.0 limitation documented in
  `../r2r/README.md` and `docs/analog_dac_integration_plan.md` section 7.1.
