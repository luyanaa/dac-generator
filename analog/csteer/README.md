# Unit-current-steering DAC leaf

Third analog leaf (roadmap P3). Mixed: the 30-cell current-source array (the
15 unary cells plus the 1/2/4/8 binary cells), its replica cascode bias and the
60 steering switches are generated and signed off (`gen_gds.py`,
`signoff.py`) and checked again on the extracted netlist
(`run_postlayout.py`); the digital half (`verilog/rtl/dac_csteer_dig.v`, which
also generates the 60 steering levels) is a standard-cell macro. The I-V
resistor, the differential wrapper and the analog-facing pin placement are
class **C** hand layout. No OpenROAD P&R near the analog core.

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
  major carries); 4 LSBs binary. The binary field is **15 identical 1 LSB
  cells**, not four wide devices: bit 1 is one cell, bit 2 two, bit 4 four and
  bit 8 eight, all on one gate net. 30 cells total instead of 63, with every
  binary cell the same device (better matching, one PCell geometry).
* A unary cell is a cascoded PMOS mirror `W/L = 8/1 um` (cascode `8/0.5 um`)
  carrying 16 uA; a binary cell is the same stack at `0.5/1 um` carrying 1 uA,
  so the whole 8-bit field is one device flavour at two widths.

## Why virtual ground

A current DAC is characterised into **0 V**, which is what an opamp I-V (or a
shorted input) presents. With a passive I-V resistor the cell output
conductance becomes a code-dependent gain error: the 425 kOhm unary-cell ro
across the 255 mV full-scale output costs **DNL -0.07 / INL +2.4 LSB** at
`R = 1 kOhm` even with perfectly matched cells (the binary field is 16x
stiffer, so it no longer dominates this term). 2.4 LSB is still far outside an
8-bit budget, so the leaf specifies an active I-V (or a much higher-impedance /
regulated-cascode output) and the regression reports both:

| bench | DNL (LSB) | INL (LSB) |
|---|---|---|
| virtual ground, sigma = 0 (control) | 0.000 | 0.000 |
| passive 1 kOhm I-V, sigma = 0 | -0.067 .. +0.061 | 0.000 .. +2.383 |
| virtual ground, 1.8 %/unit cell | -0.890 .. +0.275 | -0.483 .. +1.373 |
| passive 1 kOhm I-V, 1.8 %/unit cell | -0.890 .. +0.321 | -0.215 .. +3.260 |

The control run is exact, so the error is the injected cell mismatch, not the
measurement path. The passive-I-V penalty is smaller than it used to be because
the binary cells are now 1 uA devices with 16x the ro of a 16 uA cell: only the
unary field still sees the full 425 kOhm.

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
`W*L = 8*1 um^2`, `sigma_VT = 3.5 mV`, hence `sigma_I/I = 1.8 %` per unary
cell - the number the dc bench injects. A 1 LSB cell is 16x smaller, so its
`sigma_VT` is 4x larger and `sigma_I/I = 7.2 %`; a binary bit of weight `w`
averages `w` of them, so `sigma = 7.2 %/sqrt(w)`. Binary mismatch is therefore
worst on bit 1, which is exactly where it costs the least DNL.

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

Static INL/DNL over 256 codes, tt/25 C, 1.8 %/unary cell gain error (7.2 %/sqrt(w)
on binary bit `w`). `dem_mean` is the average over the 15 DWA pointer positions
(what a low-frequency measurement or a decimating load sees); `dem_worst` is any
single sample.

| view | DNL (LSB) | INL (LSB) |
|---|---|---|
| fixed pointer (no DEM) | -0.890 .. +0.275 | -0.483 .. +1.373 |
| DEM mean | -0.515 .. +0.275 | -0.483 .. +0.483 |
| DEM worst sample | -0.890 .. +0.275 | -1.373 .. +1.373 |

DEM removes the first-order unary error from the averaged transfer (INL
1.373 -> 0.483 LSB) and turns it into shaped noise: 0.39 LSB rms over codes,
0.48 LSB at the worst code. At a single sample the worst INL is not better
(1.37 LSB) - DEM trades instantaneous accuracy for spectral purity, which is
the point.

Ten-seed sweep (same sigma; extremes over the seeds):

| quantity | worst | mean |
|---|---|---|
| \|DNL\| fixed pointer | 1.259 | - |
| \|INL\| fixed pointer | 1.412 | 1.145 |
| \|INL\| DEM mean | 0.740 | 0.404 |
| \|INL\| DEM worst sample | 1.710 | 1.346 |
| DEM rms at worst code | 1.003 | 0.600 |

At 8 bit and 1.8 %/unit cell the unary field is the DNL limit; DEM recovers about
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
| `run_postlayout.py` | the switch gates and the 256-code transfer re-run on the extracted core (PEX netlist) |
| `run_mismatch.py` | per-cell mismatch seed sweep |
| `run.sh` | one-command pre-layout regression |

`build/cells.json` holds the exact per-cell errors the dc bench injected, so
the analytic DEM numbers in `measure.py` and the ngspice transfer at pointer 0
agree by construction (that equality is checked: both give the same worst INL
to 1e-6 LSB).

## Core layout (`gen_gds.py`, `signoff.py`)

One row of 30 cascoded-PMOS cells (15 at 8/1 unary, 15 at 0.5/1 binary, mirror
left, cascode right, M1 bridge over the n-well tie), shared `vdd` on M1 and
`vbp`/`vcp` on poly/M2, the replica bias generator at the right end, and one
steering switch pair per cell:

* **Current sources.** `Mref` 8/1 from vdd to `vbp`, gate tied to its drain, and
  `Mcas` 8/0.5 from `vbp` to `vcp`, gate tied to its drain. The reference
  current enters at the `vcp` pad, so `vcp` is both the bias output and `iref`;
  no extra pin. Both bias devices reuse the terminal spans of the cells they
  replicate, which is why the bias generator is two PCell instances plus the
  gate/drain pickups.
* **Tails.** The cascode drain leaves each cell on its own pad as `cd_<tag>`,
  is lifted on M1 clear of the `vbp` rail, then carried on M2 up and across to
  a column between the two switches. Naming the net after the segmentation tag
  (`u0..u14`, `b1_0`, `b2_0..b2_1`, `b4_*`, `b8_*`) lets the LVS script
  re-derive the 4+4 weights from the netlist alone.
* **Switches.** Two 4/0.28 NFETs per cell in two rows above the sources, W
  along x: row A (`swa_<tag>`) drains into `iout`, row B (`swb_<tag>`) into
  `idump`, both sources on `cd_<tag>` and both bulks on `vss`. Since each cell
  carries its own switch, the binary weight is a count of cells sharing a gate
  net, and the complementary drive comes from the digital macro. Row A exits its
  gate on the same y band; row B's gate poly climbs over the `idump` bus
  because the next cell's gate poly blocks that band. Each of the 60 gates ends
  on its own M2 pad at the top edge.
* **Buses.** `iout`, `idump` and the two `vss` bulk rails run the full width on
  M1; the two `vss` rails are strapped on M2 at the right end.

Gates: Magic DRC 0 items, LVS 122 devices (30 cells + 2 bias + 60 switches) /
126 nets (6 rails + 30 tails + 30 internal + 60 gates), PEX 122 instances /
993 C entries. The LVS contract is written from `csteer.yaml` only and checks
the tail fan-out (one cascode drain and exactly two switch sources per
`cd_<tag>`), the drain split (one `iout`, one `idump` per cell), 60 distinct
gate nets, the 1-2-4-8 tag weights, and every device's W/L/bulk. Width is
weight: the cascode that owns a `cd_<tag>` must be 8/1 for a `u*` tag and 0.5/1
for a `b*` tag, and the mirror on the same internal node must match it - so a
binary cell silently drawn at 16 LSB fails LVS instead of merely shifting the
transfer curve. `--selftest` rejects drop-unit, swap-gate, short-tail,
drop-switch, short-drain, wrong-source, two bias mutations, a widened binary
cascode and a widened binary mirror.

Not in this macro: the gate drive itself (the digital macro generates both
phases; the wrapper only routes them to these pads), the I-V resistor and the
differential wrapper. The 256-code sweep below is a *deterministic* transfer
check; mismatch INL/DNL, the I-V and the analog-facing pin placement remain
open.

## Post-layout (`run_postlayout.py`)

`run-analog.sh csteer gf180 postlayout` (equivalently `./signoff.py --stage
postlayout`) instantiates the hierarchical PEX of the whole core — 122 devices
plus 993 coupling capacitors over 96 ports — and re-runs the two
`run_switch.py` measurements against the same thresholds, so pre- and
post-layout are directly comparable:

| metric | pre-layout | post-layout (PEX) | gate |
|---|---|---|---|
| dc pair sum error | exact | 1e-5 % | < 1 % |
| switch Ron | 391 Ohm | 391 Ohm | < 800 Ohm |
| output compliance | 2.26 V | 2.26 V | > 1.5 V |
| event charge error | 8.3 fC | 8.9 fC | < 25 fC |
| pair charge error | 0.3 fC | 1.1 fC | < 5 fC |
| settle to 0.5 LSB | 55 ps | 47 ps | < 500 ps |
| full scale (code 255) | 255 uA | 255.2 uA | 255 +- 5 % |
| unary step (code 16) | 16 LSB | 15.99 LSB | 16 +- 1 LSB |
| transfer DNL | exact | 0.177 LSB | < 0.5 LSB |
| transfer INL | exact | 0.166 LSB | < 1 LSB |
| monotonic steps | - | 0 bad | 0 |

The last five rows are a **256-code sweep of the extracted core**: every gate
is driven the way `dac_csteer_dig` drives it (thermometer on the MSBs, one
register bit fanned to all cells of a binary weight), the output is a virtual
ground, and the code steps 0..255. This is the check the layout did not have
before: it is what catches a binary field that is not actually 1 LSB per cell
(the earlier 30 x 16 uA array swept a sawtooth with 15 non-monotonic steps and
a 480 uA full scale). The residual DNL is one step at code 16 (-0.18 LSB): a
0.5 um device carries 1.2 % more current than 1/16 of the 8 um device, so the
binary LSB is 1.012 uA against a unary LSB of 1.000 uA. That offset is a drawn
width ratio, not mismatch, and is trimmable in the cell width if needed.

Only cell `u0` switches; the other 29 are parked on `idump`, so every metric is
u0's own current after subtracting the parked contribution. The change from
the pre-layout bench is exactly the layout: the switching node carries its
extracted capacitance instead of a guessed 10 fF, `iout`/`idump` carry their
bus caps (7.8 / 8.8 fF), the 60 gate nets 0.7 fF each and the 30 tails 1.4 fF
each. Peak displacement is 86.5 uA and the tail swings 15.4 mV.

This is a core-level result: the drawn switches behave, the charge numbers are
real, the 256-code transfer is monotonic with the right segmentation, and the
layout adds nothing fatal. It is **not** a mismatch linearity claim: the PEX
netlist has one deterministic model for all 30 cells, so static INL/DNL under
process mismatch still comes from the pre-layout Pelgrom model above, and the
I-V, the wrapper and the analog-facing pin placement are still missing. The
stage is fail-closed: no PEX, or a PEX older than `csteer.gds`, exits 2 instead
of running a stale netlist.


## Digital half

`verilog/rtl/dac_csteer_dig.v`: 4-to-15 rotated thermometer decode, DWA
pointer advanced by the incoming unary count modulo 15, registered `th`/`b` so
the analog switches never see the asynchronous code bus.

The same module generates the steering drive: `swa_u[14:0]`/`swb_u[14:0]` and
`swa_b1_0`/`swa_b2`/`swa_b4`/`swa_b8` (with their complements), wired so the
vector index is the physical cell and the port names match the analog pads
(`swa_b4[j]` -> `swa_b4_<j>`). A binary bit drives all its cells from one
register bit, so the weight is the cell count (1/2/4/8) and no second decode
exists. Both phases come from the same register, so the pair is complementary
by construction; the wrapper adds no inversion, only the physical connection.
What is still hand work is the pin placement on the analog-facing edge: the 60
switch pins have to land on the 5.5 um cell pitch that `gen_gds.py` uses for the
control pads.

DWA has **15 pointer states**, not 16: there are 15 unary cells. Over 15
consecutive samples of a constant code with `k` unary cells, every physical
cell is selected exactly `k` times, which is what equalises the per-cell gain
error.

`dac_csteer_dig_tb.v`: 3733 checks - reset, all 256 codes against a reference
rotated-thermometer model, pointer recurrence, full-scale, one-cycle `valid`,
the `k`-of-15 fairness property for `k = 1..7`, and the switch drive against
the reference decode (fan-out, binary replication, complementary phase).
Verilator lint clean.

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
../../run-analog.sh csteer gf180 postlayout  # same switch gates on the PEX core
make -C ../../verilog/tb dac_csteer_dig
```

## Status / next steps

Verified: device cell current and ro over 7 corner/temperature points, the Vth
sensitivity that justifies the 1.8 % sigma, the replica cascode bias over the
full 15-point corner/temperature matrix, one steering event (Ron, compliance,
charge and settling), dc linearity with and without DEM, the passive-I-V
penalty, the digital half, and the switch metrics again on the extracted core
(`run_postlayout.py`).

Not verified / not done:

* **Core macro generated.** `run-analog.sh csteer gf180 gds|drc|lvs|pex|all`
  builds the 30-cell array, the replica bias and the 60 steering switches
  through `signoff.py`: Magic DRC 0 items, LVS 122 devices / 30 cells / 60
  switches / 126 nets, PEX 122 instances / 993 C entries; `--selftest` fails
  drop-unit, swap-gate, short-tail, drop-switch, short-drain, wrong-source,
  bias-gate and bias-source.
* **Switch drive is generated, not placed.** `run_switch.py` closes the device
  sizing (Ron, charge, settling), the layout places both NFETs of every pair,
  and `dac_csteer_dig` now generates all 60 `swa`/`swb` levels (3733 checks).
  Still hand work: the analog-facing pin placement at the 5.5 um cell pitch,
  the I-V resistor and the differential wrapper.
* **No full-DAC post-layout.** The core macro is extracted and re-checked on
  the PEX netlist (`run_postlayout.py`: Ron 391 Ohm, compliance 2.26 V, event
  charge 8.9 fC, pair charge 1.1 fC, settle 47 ps, all gates PASS), but
  post-layout linearity of the leaf is not claimed: that needs the wrapper,
  the output resistor and the switch drive in one netlist.
* **Switch drivers are assumed.** The event bench drives the pair with ideal
  0..3.3 V edges and a 30 ps overlap. A real standard-cell inverter adds
  skew/jitter and the digital macro has no de-glitch; those are not modelled.
* **sky130 refuses.** Binned BSIM4 models cannot be selected by ngspice 44.2
  here, so cell matching and ro would be unverified; `gen_csteer.py` exits
  instead of emitting an untrustworthy deck.
