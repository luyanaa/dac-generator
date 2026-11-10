# Unit-current-steering DAC leaf

Third analog leaf (roadmap P3). Mixed: the 30-cell current-source array (the
15 unary cells plus the 1/2/4/8 binary cells) is generated and signed off
(`gen_gds.py`, `signoff.py`); the switch matrix, the wide-swing cascode bias,
the I-V resistor and the differential wrapper are class **C** hand layout. The
digital half (`verilog/rtl/dac_csteer_dig.v`) is a generated standard-cell
macro. No OpenROAD P&R near the analog core.

## Topology

8-bit, 4+4 segmentation, following `2AMLogic/gf180-current-dac` in
`docs/dac_topology_survey.md`:

```
  vdd ──┬──────────── 15 unary cells, 16 LSB each ────────────┐
        │   (thermometer, rotated by DWA)                      │
        │                                                      ├─ out ── I-V ── vout
        └──────────── binary cells 8/4/2/1 LSB ────────────────┘
```

* `I_LSB = 1 uA`, full scale 255 uA. Into an ideal I-V (virtual ground) that
  is 255 mV at 1 kOhm.
* 4 MSBs unary so DEM has something to rotate where linearity matters (the
  major carries); 4 LSBs binary so the cell count stays at 15+4 instead of 63.
* Each cell is a cascoded PMOS mirror (`W/L = 8/1 um` mirror, `8/0.5 um`
  cascode) with a separate 16 uA reference branch.

## Why virtual ground

A current DAC is characterised into **0 V**, which is what an opamp I-V (or a
shorted input) presents. With a passive I-V resistor the cell output
conductance becomes a code-dependent gain error: the 425 kOhm cell ro across a
255 mV full-scale output costs **DNL +6.8 / INL +8.1 LSB** at `R = 1 kOhm`.
The leaf therefore specifies an active I-V (or a much higher-impedance /
regulated-cascode output) and the regression reports both:

| bench | DNL (LSB) | INL (LSB) |
|---|---|---|
| virtual ground, sigma = 0 (control) | 0.000 | 0.000 |
| virtual ground, 1.8 %/cell | -0.886 .. +0.320 | -0.479 .. +1.370 |
| passive 1 kOhm I-V, 1.8 %/cell | -0.837 .. +6.786 | 0.000 .. +8.125 |

The control run is exact, so the error is the injected cell mismatch, not the
measurement path.

## Device cell (`run_cell.py`)

One unit cell, cascoded PMOS mirror, with the cascode gate held at 1.5 V in
this bench so that only the mirror/cascode pair is measured.  The production
bias generator (next section) reproduces the same operating point from one
16 uA reference, without the ideal source:

| corner | temp | I_cell | ro |
|---|---|---|---|
| tt | 25 C | 15.766 uA | 425 kOhm |
| ff | 25 C | 15.874 uA | 549 kOhm |
| ss | 25 C | 15.632 uA | 275 kOhm |
| fs | 25 C | 15.679 uA | 326 kOhm |
| sf | 25 C | 15.843 uA | 508 kOhm |
| tt | -40 C | 15.728 uA | 390 kOhm |
| tt | +125 C | 15.821 uA | 473 kOhm |

ro is fitted over the flat window `Vout = 0.05..1.0 V`; the mirror carries
15.77 uA rather than 16 because its Vds differs from the diode reference, a
systematic gain error that the endpoint fit absorbs.

Gate-referred sensitivity at tt/25 C:

| voff | dI/I | per mV |
|---|---|---|
| 5 mV | -2.615 % | -0.523 %/mV |
| 10 mV | -5.197 % | -0.520 %/mV |
| 20 mV | -10.263 % | -0.513 %/mV |

so `dI/I = -0.519 %/mV`. With Pelgrom `A_VT = 10 mV*um` and
`W*L = 8*1 um^2`, `sigma_VT = 3.5 mV`, hence `sigma_I/I = 1.8 %` per unit
cell - the number the dc bench injects. Binary cells are `2^k` parallel unit
cells, so their sigma is scaled by `sqrt(2^k)`.

## Switch and replica cascode bias (`run_switch.py`)

The unit cell ends at the cascode drain; the steering switch is a
**differential NMOS pair** whose tail is that drain, one drain to `ioutp` and
the other to `idump`.  A pair rather than two independent switches because the
sum of the two drain currents is the cell current at every control voltage:
the cascode drain never floats, make-before-break only redistributes the tail,
and the current source stays shielded from the output by the cascode.  Each
switch is `W/L = 4/0.28 um`, gates driven by complementary 0..3.3 V levels
(a local inverter or the complementary digital outputs).

**Bias generator.**  It is a replica of the cell with the cascode drain tied
to its own gate: `Mref` (8/1) is diode-connected from vdd to `vbp`, `Mcas`
(8/0.5) from `vbp` to `vcp`, and the 16 uA reference sinks at `vcp`.  Both
devices carry `Iref`, so `vbp` is the mirror gate and `vcp` is one cascode
`Vgs` below it.  The real cell's mirror drain settles at `vbp`, i.e. it copies
both the mirror bias and the cascode `Vgs`.  No second reference, no ideal
source, and the current is set by `Iref`, not by a resistor.

Bias matrix, 5 corners x 3 temperatures (`Icell` should track `Iref`):

| corner | temp | I_cell | vbp | vcp | mirror Vds-Vov | cascode Vds-Vov |
|---|---|---|---|---|---|---|
| tt | 25 C | 16.001 uA | 2.170 | 0.782 | 0.789 V | 1.955 V |
| ff | 25 C | 16.001 uA | 2.308 | 1.110 | 0.670 V | 2.107 V |
| ss | 25 C | 16.001 uA | 2.032 | 0.452 | 0.908 V | 1.804 V |
| fs | 25 C | 16.001 uA | 2.072 | 0.550 | 0.875 V | 1.849 V |
| sf | 25 C | 16.001 uA | 2.268 | 1.013 | 0.702 V | 2.061 V |

Across the full 15-point matrix `I_cell = 16.000..16.002 uA`, `vbp =
2.01..2.36 V`, `vcp = 0.38..1.25 V`, the mirror margin is `>= 0.57 V` and the
cascode margin `>= 1.80 V`.  The bias is **not** a 2-Vov wide-swing cascode:
the I-V holds the output at 0 V and the 3.3 V supply leaves more than 1 V, so
the replica's deep-saturation setting is the robust choice; a 2-Vov bias would
buy headroom this leaf does not need.

**One steering event**, tt/25 C, 10 fF on the switching node, 0.2 ns gate
edges with a 30 ps overlap:

| quantity | value |
|---|---|
| switch Ron (per device) | 391 Ohm (301..553 over corners) |
| output compliance (1 % I) | 2.26 V (2.10..2.44) |
| cascode drain swing during the event | 13 mV (10..19) |
| integrated charge error on `ioutp` | 8.3 fC (~0.03 LSB at 4 MS/s) |
| pair charge error (`ioutp`+`idump`) | 0.3 fC |
| settle to +-0.5 uA after the edge | 55 ps (45..85) |

The peak displacement current is 67..92 uA, but it is the drain displacement
through the gate-drain capacitance: it cancels between the two drains (pair
charge error 0.3 fC) and the opamp I-V absorbs the 8 fC net charge.  The
cascode drain moves only ~13 mV, so the cell current is unchanged during the
event.

## Pre-layout linearity and DEM

Static INL/DNL over 256 codes, tt/25 C, 1.8 %/unit cell gain error. `dem_mean`
is the average over the 15 DWA pointer positions (what a low-frequency
measurement or a decimating load sees); `dem_worst` is any single sample.

| view | DNL (LSB) | INL (LSB) |
|---|---|---|
| fixed pointer (no DEM) | -0.886 .. +0.320 | -0.479 .. +1.370 |
| DEM mean | -0.511 .. +0.320 | -0.479 .. +0.479 |
| DEM worst sample | -0.886 .. +0.320 | -1.370 .. +1.370 |

DEM removes the first-order unary error from the averaged transfer (INL
1.370 -> 0.479 LSB) and turns it into shaped noise: 0.39 LSB rms over codes,
0.48 LSB at the worst code. At a single sample the worst INL is not better
(1.37 LSB) - DEM trades instantaneous accuracy for spectral purity, which is
the point.

Ten-seed sweep (same sigma):

| quantity | worst | mean |
|---|---|---|
| \|DNL\| fixed pointer | 1.501 | 0.74 |
| \|INL\| fixed pointer | 1.375 | 1.193 |
| \|INL\| DEM mean | 0.966 | 0.510 |
| \|INL\| DEM worst sample | 1.928 | 1.409 |
| DEM rms at worst code | 1.003 | 0.600 |

At 8 bit and 1.8 %/cell the unary field is the DNL limit; DEM recovers about
half the static INL. Trimming or larger cells is the next step if a tighter
DNL is required.

## Files

| file | role |
|---|---|
| `csteer.yaml` | parameters, segmentation, cell sizing, `ro`, Pelgrom sigma |
| `gen_csteer.py` | dc bench, device cell, and the switch/bias netlists |
| `measure.py` | endpoint-fit DNL/INL plus the analytic DEM mean/worst/noise |
| `run_cell.py` | device cell across corners/temperature and the Vth sensitivity |
| `run_switch.py` | replica bias matrix + one steering event (Ron, compliance, charge, settling) |
| `run_mismatch.py` | per-cell mismatch seed sweep |
| `run.sh` | one-command pre-layout regression |

`build/cells.json` holds the exact per-cell errors the dc bench injected, so
the analytic DEM numbers in `measure.py` and the ngspice transfer at pointer 0
agree by construction (that equality is checked: both give the same worst INL
to 1e-6 LSB).

## Digital half

`verilog/rtl/dac_csteer_dig.v`: 4-to-15 rotated thermometer decode, DWA
pointer advanced by the incoming unary count modulo 15, registered `th`/`b` so
the analog switches never see the asynchronous code bus.

DWA has **15 pointer states**, not 16: there are 15 unary cells. Over 15
consecutive samples of a constant code with `k` unary cells, every physical
cell is selected exactly `k` times, which is what equalises the per-cell gain
error.

`dac_csteer_dig_tb.v`: 3007 checks - reset, all 256 codes against a reference
rotated-thermometer model, pointer recurrence, full-scale, one-cycle `valid`,
and the `k`-of-15 fairness property for `k = 1..7`. Verilator lint clean.

## Run

```
./run.sh                      # cell + switch/bias + ideal + mismatch dc + passive I-V
./run.sh dc                   # mismatch dc + DEM study
./run.sh switch               # replica bias matrix + steering event
./run_cell.py                 # device cell matrix and sensitivity
./run_switch.py               # same switch/bias regression directly
./run_mismatch.py --seeds 10  # seed sweep
../../run-analog.sh csteer gf180 prelayout
../../run-analog.sh csteer gf180 all      # array macro: DRC/LVS/PEX
../../run-analog.sh csteer gf180 gds
make -C ../../verilog/tb dac_csteer_dig
```

## Status / next steps

Verified: device cell current and ro over 7 corner/temperature points, the Vth
sensitivity that justifies the 1.8 % sigma, the replica cascode bias over the
full 15-point corner/temperature matrix, one steering event (Ron, compliance,
charge and settling), dc linearity with and without DEM, the passive-I-V
penalty, and the digital half.

Not verified / not done:

* **Current-source array macro generated.** `run-analog.sh csteer gf180
  gds|drc|lvs|pex|all` builds the 30-cell array through `signoff.py`: Magic DRC
  0 items, LVS 60 devices / 30 cells / 52 nets / fan-out 1-2-4-8, PEX 60
  instances / 268 C entries; `--selftest` fails drop-unit, swap-gate and
  short-out.
* **Switch and bias are pre-layout only.** `run_switch.py` closes the design
  (sizes, bias, charge, settling); drawing the 30 switch pairs, the local
  complementary drive and the `iout`/`idump` buses is the next generator step.
  The I-V and the differential wrapper stay class C.
* **No full-DAC post-layout.** The array macro is extracted and checked, but
  there is no switch/bias layout, so post-layout linearity of the leaf is not
  claimed.
* **Switch drivers are assumed.** The event bench drives the pair with ideal
  0..3.3 V edges and a 30 ps overlap. A real standard-cell inverter adds
  skew/jitter and the digital macro has no de-glitch; those are not modelled.
* **sky130 refuses.** Binned BSIM4 models cannot be selected by ngspice 44.2
  here, so cell matching and ro would be unverified; `gen_csteer.py` exits
  instead of emitting an untrustworthy deck.
