# Unit-current-steering DAC leaf

Third analog leaf (roadmap P3). Class **C**: the 15 unary cells, the binary
cells and the cascode bias need matched, common-centroid hand layout; only the
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

One unit cell, cascoded PMOS mirror, ideal cascode-gate bias at 1.5 V
(production needs a wide-swing bias generator - a class-C layout item):

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
| `gen_csteer.py` | dc bench (ideal cells + per-cell error + `ro`) and device cell bench |
| `measure.py` | endpoint-fit DNL/INL plus the analytic DEM mean/worst/noise |
| `run_cell.py` | device cell across corners/temperature and the Vth sensitivity |
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
./run.sh                      # cell + ideal + mismatch dc + passive I-V
./run.sh dc                   # mismatch dc + DEM study
./run_cell.py                 # device cell matrix and sensitivity
./run_mismatch.py --seeds 10  # seed sweep
../../run-analog.sh csteer gf180 prelayout
make -C ../../verilog/tb dac_csteer_dig
```

## Status / next steps

Verified: device cell current and ro over 7 corner/temperature points, the Vth
sensitivity that justifies the 1.8 % sigma, dc linearity with and without DEM,
the passive-I-V penalty, and the digital half.

Not verified / not done:

* **No GDS.** `run-analog.sh csteer gf180 gds` exits 2 on purpose: the cell
  array, the binary cells and the wide-swing cascode bias are class C and need
  a matched common-centroid floorplan first.
* **No PEX / post-layout, and no layout gate attempted.** Class C: there is
  no device-level GDS, so DRC/LVS/PEX do not apply yet. The tool path exists
  (the R-2R leaf signs off through Magic in `../r2r/signoff.py`); what is
  missing is the hand layout, not a checker.
* **No output switch drivers / de-glitch.** The code is applied as a current
  step; the digital macro registers `th`/`b`, but the cell drain switches and
  their timing (make-before-break, clock feedthrough) are not modelled.
* **sky130 refuses.** Binned BSIM4 models cannot be selected by ngspice 44.2
  here, so cell matching and ro would be unverified; `gen_csteer.py` exits
  instead of emitting an untrustworthy deck.
