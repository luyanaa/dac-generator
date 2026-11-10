# Analog DAC integration plan

Status: research / proposal. No analog leaf is implemented yet.

The generator currently emits **digital-only** DAC macros: `pwmdac` and
`audiodac` are pure RTL, hardened with LibreLane standard cells, and drive a
1-bit pin into an off-chip RC filter. This document defines how to add real
analog DAC topologies without breaking that seam, and which topologies can be
automated at all.

See `docs/dac_topology_survey.md` for the per-repository evidence.

## 1. Classes of automation

Every topology is assigned one of three classes. The class decides the flow,
the staffing and the sign-off bar.

### (A) Digital / digitally assisted

The conversion is performed by switching digital signals; accuracy is set by
timing, filtering or averaging, not by device matching. Everything can be RTL,
synthesised and hardened by LibreLane; the only PDK-dependent parts are driver
strength and the pad.

Examples: PWM + RC, ΔΣ + RC, unit-inverter / thermometer-finger DAC,
PWM-with-dither, digital resistor-matrix DAC driven by standard-cell drivers.

### (B) Device-generated with constrained routing

The conversion depends on matched passive or active devices, but the array is
regular. It can be emitted from a parameterised device list with a fixed
floorplan, a fixed track/strap plan, dummy ring and symmetry rules. It is not
free P&R: no OpenROAD auto-placement for the analog core. The generator owns
placement and routing templates; DRC/LVS/PEX are run on the result.

Examples: R-2R ladder, resistor string / Kelvin divider, binary-weighted
resistor array, unit-current-steering matrix, MIM capacitor array (CDAC).

### (C) Must be manually laid out

Matching, coupling, EM/IR, parasitics or custom devices exceed what a template
can guarantee. Needs an expert layout, iterative extraction, and often custom
shields/guard rings/dummies. A generator can still provide a skeleton and the
device sizes, but a human signs off the geometry.

Examples: high-resolution CDAC with a sized bridge capacitor, current-steering
with DEM/calibration and tight SFDR, CML/HBT DACs, any topology needing
common-centroid + custom supply/ground + EM closure.

A single chip normally mixes classes: a **(B)** analog array plus an **(A)**
standard-cell decoder/DEM/calibration engine.

## 2. Topology classification

| Topology | Class | Why | Reusable reference |
|---|---|---|---|
| PWM + RC (`pwmdac`) | A | pure RTL; RC off-chip | this repo |
| ΔΣ + RC (`audiodac`) | A | pure RTL; 1-bit + RC | this repo |
| Unit-inverter / finger DAC | A | digital drive strength; monotonic by construction | ttsky/tt08 (digital half) |
| R-2R ladder | B | ratio is one unit device, 2R = two in series; switch Ron sets INL | `ihsan-sa/ece298a-r2r-dac` |
| Resistor string / Kelvin | B/C | binary-tree Kelvin: 2^N unit resistors + TG tree; switch Ron sets DNL; buffered output is hard analog | `sky130_ef_ip__rdac3v_8bit`, `dineshannayya/8bit_dac` |
| Binary-weighted resistor | B/C (≤6 bit) | weights 1,2,4,... need ratio control; impractical above ~6 bit; use R-2R or string | none implemented |
| Unit-current-steering matrix | B | matched current cells + thermometer; needs dummies/centroid and EM/IR | `2AMLogic/gf180-current-dac`, `alinja/skydacmagic` |
| Current-steering + DEM/cal | B + A | array is B, DEM/cal engine is A | `alinja/skydacmagic` (offline DEM) |
| Binary-weighted current-steering | C | W/L-weighted cells; matching and glitch are hand-tuned | `tt08-vga-fun` red/green |
| Switched-capacitor / CDAC | B/C | matched MIM array; bridge cap and switches need hand tuning | `sky130_ef_ip__cdac3v_12bit` (C), `SiliclusterV3_2_cap_DAC` (B) |
| Serial two-cap charge-sharing DAC | B | 2 equal MIM banks + op-amp; generated + PEX proven | `SiliclusterV3_2_cap_DAC` |
| CML / HBT DAC | C | custom HBT cells, 50 Ω environment, EM | `MacAnalog/dn-002-...-ihp130` |

### Key finding

Only two of the surveyed analog references have credible **extracted
post-layout** linearity data:

- `ihsan-sa/ece298a-r2r-dac`: generated GDS, DRC/LVS, Magic PEX, 9 corners,
  INL 0.355 LSB / DNL 0.141 LSB, 1.2 µs settling.
- `jonahsaunders/SiliclusterV3_2_cap_DAC`: script-generated GDS, shields,
  full-RC PEX, 9 corners × 256 codes, worst INL 0.553 LSB / DNL 0.538 LSB,
  32 mismatch seeds, buffer stability 120 cases.

The rest are schematic-only, LVS-only, or have no linearity numbers. Do not
treat a clean DRC/LVS or a behavioral Monte Carlo as analog sign-off.

## 3. PDK capability gate

Analog topologies are only offered on PDKs that provide the required devices.
The generator must select the allowed topology set per PDK instead of failing
at DRC time.

| Device | sky130 | gf180 | ihp130 | ics55 | freepdk45 | OR1 |
|---|---|---|---|---|---|---|
| Precision poly resistor | `res_xhigh_po` | `ppolyf_u` / `_2k` | `rhigh` | `res_poly` | — | limited |
| MIM capacitor | `cap_mim_m3_1/2` | `cap_mim_1f0fF/1f5fF` | `mim` / `rfmim` | unconfirmed | — | poly/pwell caps only |
| NPN HBT | — | — | `npn13G2` | — | — | — |
| Thick-oxide / 3.3–5 V MOS | `g5v0` | `_03v3` | `sg13g2` 3.3 V | I/O devices | — | — |

Implications:

- `freepdk45` stays **digital-only** (PWM/ΔΣ). No MIM, no precision resistor.
- `ics55`/`OR1` need a device audit before R/C topologies are exposed; only
  the digital backends are safe today.
- `ihp130` is the only candidate for CML/HBT.
- `sky130`/`gf180`/`ihp130` can host R-2R, resistor-string, current-steering
  and CDAC leaves.

## 4. Interface contract for analog leaves

Keep the existing rule: **a leaf macro is a hard block with a plain digital
interface**. The decoder/DEM/calibration engine lives outside the analog core
(or in a separate standard-cell macro), so it can be synthesised and retargeted
per PDK.

```
module dac_<top>_ana #(parameter N = 8) (
    input  [N-1:0] code_i,       // binary or thermometer, per macro
    input          clk_i,        // optional retiming in the analog macro
    input          rst_n_i,
    input  [15:0]  cal_i,        // optional trim/cal word
    input          en_i,
    output         vout_p,       // or iout_p
    output         vout_n,       // differential optional
    inout          vref_p, vref_n,
    inout          ibias,        // current-steering / CML
    inout          vcm,          // CDAC / resistor-string mid
    inout          vdd, vss
);
```

Rules:

- Pin order and side are fixed by a `pin_order.cfg`-style file; the wrapper
  uses abutment, not a router, between the digital and analog macros. The
  analog side publishes the contract as data: `analog/csteer` writes
  `build/pinplan.json` (name, layer, pad bbox) and its `pins` stage fails if
  any of the 60 switch pins is off the 2.75 um grid or out of cell order.
- Power domains (1.8 V core / 3.3 V I/O / 5 V switch) are explicit; level
  shifters are part of the digital macro, not the analog core.
- No bidirectional analog bus at the digital boundary; the code bus is
  unidirectional and registered before the pad.
- The analog macro does not contain a standard-cell P&R region. If it needs
  logic, that logic is a separate `_dig` macro.

## 5. Composition options

1. **Two macros abutted (preferred).** `dac_<top>_dig` (LibreLane, stdcells)
   + `dac_<top>_ana` (generated analog). Abut in `user_project_wrapper` or a
   small top wrapper. Preserves the digital flow and lets each macro be
   verified independently.
2. **Analog leaf with embedded decoder.** Only for very small decoders and
   only if the PDK flow can mix stdcells with analog devices in one GDS. Not
   recommended: the decoder then inherits the analog DRC/LVS flow.
3. **Digital-only seat.** Extend `dac_wrap` with additional `DAC_KIND` values
   for PWM/ΔΣ variants; no analog macro involved. This is the fallback for
   `freepdk45`/`ics55`/`OR1`.

## 6. Directory and flow changes

```
analog/<topology>/
    <topology>.yaml          # N, unit R/C/I, PDK overrides, pin plan
    gen_<topology>.py        # device list, placement, track/strap router
    tb/                      # ngspice pre-layout benches
    pex/                     # extraction, corners, Monte Carlo
verilog/rtl/dac_<top>_dig.v  # decoder / DEM / calibration / sequencer
openlane/dac_<top>_dig/      # LibreLane config (stdcell only)
```

- Digital: unchanged `./run.sh dac_<top>_dig <pdk>`.
- Analog: new `./run-analog.sh <topology> <pdk>` that runs the device
  generator, KLayout/Magic DRC, netgen LVS, Magic PEX, then ngspice corners
  and Monte Carlo. It must fail on missing PEX or missing corners, unlike the
  current digital flow which may skip views.
- Co-simulation: Verilator/Icarus for the digital macro, ngspice for the
  extracted analog macro; a chip-level top bench drives the code bus and
  measures INL/DNL/SFDR/settling.
- CI: add a per-topology regression matrix. Class A runs RTL + FPGA. Class B
  additionally requires DRC/LVS + PEX + corners. Class C requires a manual
  review checklist and EM/IR.

## 7. Verification gates

| Gate | A | B | C |
|---|---|---|---|
| RTL / functional | required | required | required |
| DRC / LVS | — | required | required |
| PEX + corner sim | — | required | required |
| Monte Carlo (mismatch) | — | required if the PDK supports per-instance mismatch | required |
| INL/DNL | — | required over corners | required over corners + silicon correlation |
| Settling / output impedance | — | required | required |
| EM / IR / coupling | — | spot checks | full sign-off |
| Manual layout review | — | spot checks | required |

Known PDK gotcha: GF180 poly resistors have `mis_r = 0` in the current
model, so Monte Carlo cannot move a resistor ratio. Use a deterministic
per-unit sensitivity (e.g. ±1 % → INL) until per-instance mismatch exists.
Sky130 Pelgrom parameters are available in the model but reference repos often
use a Python model instead of SPICE MC.

### 7.1 P1 (R-2R) status: which gates are actually closed

| Gate | State | Evidence |
|---|---|---|
| Pre-layout DC linearity | closed (gf180) | 15 corner x temp, DNL 0.145 / INL 0.092 LSB, monotonic |
| Pre-layout settling | closed (gf180) | 125 ns LSB step, 1.15 us full scale, 1 MOhm + 7 pF |
| Mismatch bound | closed, deterministic | 0.2 %/unit, 10 seeds, DNL 0.427 / INL 0.225 LSB |
| Digital half | closed | `dac_r2r_dig` lint clean, TB 16/16, hardened config added |
| Device-array GDS | closed | `gen_gds.py`, 25 `ppolyf_u_resistor` PCells, 462 x 1466 um; self-checks 50/50 terminals, 0 net shorts, 0 tab clashes |
| DRC | closed | Magic `drc check` / `drc catchup` / `drc count total`: 0 items |
| LVS | closed | extracted netlist: 17 unit (150.0 um) + 8 trim (148.36 um) = 25 resistors; 9-row ladder, 7-unit 1R chain, termination 2R, ports `vss b0..b7 n0..n6 vout` |
| PEX | closed (netlist) | hierarchical, `cthresh`/`rthresh` 0: 25 instances, 37 C entries; per-net geometric caps reported, not gated |
| Post-layout linearity | **closed for the ladder (gf180, PEX)** | `postlayout.py` reconstructs the poly R-C from the PDK model (`ppolyf_u` rsh 350 ohm/sq + 60 ohm/sq ends, `fox_sub` 8.85e-5 F/m2) on the extracted geometry and splits each body into 20 segments. Both the verbatim extraction and the segmented line are run: DNL -0.001/+0.041, INL -0.014/+0.036 LSB, Vfs 3.28712 V for both, full-scale delta 0.0059 mV; the distributed poly R-C adds +0.9 ns to a 1139 ns worst settle, so the load owns settling. Not claimed: the DAC above the ladder (drivers, TG tree, digital macro) |

gf180 ships no KLayout DRC deck in this install, so the leaf signs off through
Magic, which does work headless here: `-dnull -noconsole` is fine, and the
earlier "needs a display" failure was really the magicrc falling back to a
stale hardcoded `~/work/open-pdks` build when `PDK_ROOT` was unset. The same
bug was fixed in `analog/cdac/signoff.py`. `analog/r2r/signoff.py` sets both
`PDK_ROOT` and `MAGIC_TECH_PATH` explicitly and is fail-closed on a missing
tool, deck, netlist or result line.

The first real DRC found one mistake the generator's own self-checks cannot
see: 18 `M1.2a` errors (M1 spacing < 0.23 um), two per row, at the same x.
`rb` sat at `X_RB = 152.4`, leaving 0.14 um between ra's right M1 terminal and
rb's p-tap M1 tab. `X_RB = 152.7` gives 0.44 um. The poly gap was always fine,
which is why a structural check on drawn straps missed it. A second bug was in
the labels: `n0..n7` sat 4 um off the bus and the `vout` text sat above the
pad, so Magic produced eight `n*_uq0` dangling ports plus a dangling `vout`
while the real output was the pad's `n7`. Labels now sit on metal and the pad
carries `vout`.

The DRC claim is scoped to Magic's gf180 rule set (spacing, width,
enclosure, overlap, via). Density/coverage rules (DCF.1a/b, PL.8,
M1.4-M5.4, MT.3) are not in the tech's `drc` section, so no fill or
density waiver is claimed for this macro.

LVS is a graph check on the extracted netlist, not a netgen device compare:
there is no schematic netlist for this macro and the contract is topological.
The expected ladder is written in `signoff.py` independently of `gen_gds.py`'s
placement tables, and `./signoff.py --selftest` proves the gate is not a no-op
by dropping a unit resistor and by retargeting a trim (both must fail, and do).

sky130 is documented but not simulated: this ngspice 44.2 cannot select bins
from the 180-block binned BSIM4 models (`could not find a valid modelname`),
because the bin expressions reference `*_slope` params that the PDK defines in
a file included later. `gen_r2r.py --pdk sky130` now fails with that reason
instead of emitting a deck full of untrustworthy numbers.

### 7.2 P2 (resistor string) status

| Gate | State | Evidence |
|---|---|---|
| String linearity | closed by construction | ideal-switch control run: DNL < 1e-6 LSB |
| Tree linearity | closed (gf180) | 255 TGs, 7 corner/temp points: worst DNL 0.133 / INL 0.132 LSB, monotonic |
| Settling | closed (gf180, tt) | 5.0 us worst step, 7 pF + 60 fF tap |
| Mismatch bound | closed, deterministic | 0.2 %/unit, 8 seeds: worst DNL 0.126 / INL 0.134 LSB |
| Digital half | closed | `dac_string_dig` break-before-make, 1826/1826, lint clean |
| Layout | **string generator closed; tree + follower class C** | `analog/string/gen_gds.py` lays out the 255-unit string (PCell units, 256 taps); the 255-TG tree and follower stay hand layout |
| DRC / LVS / PEX | **closed for the string macro** | `signoff.py`: DRC 0 items, LVS 255 units / 256 ports / one `vss-t1-...-t254-vref` chain, PEX 255 instances / 509 C entries; `--selftest` fails drop-unit and swap-tap |

The design point that decides DNL is not the resistor ratio (255 identical
units are more than accurate enough at 8 bit) but the transmission gate: its
on-resistance variation with tap voltage and its off-state load. 1 kOhm units
with 32/64 um gates give 0.13 LSB; a 4 kOhm string halves the error to
0.11 LSB but triples tap settling. Recording both, and the control run that
isolates the tree, is the only honest way to size it.

### 7.3 P3 (unit current steering + DEM) status

| Gate | State | Evidence |
|---|---|---|
| Device cell | closed (gf180) | cascoded PMOS, 7 corner/temp points: I 15.63-15.87 uA, ro 275-549 MOhm |
| Mismatch model | **closed on the PEX (gf180)** | PDK `sm141064` area law `0.7071*par_vth*1e-6/sqrt(Leff Weff)` gives sigma_VT 1.79 mV for the 8/1 unary mirror and 6.59 mV for the 0.5/1 binary cell; the extracted cell converts that to 0.99 % and 3.33 %/cell. The pre-layout 0.519 %/mV x Pelgrom 3.5 mV = 1.8 %/cell assumed A_VT 10 mV*um, i.e. 1.8x pessimistic |
| DC linearity | closed (gf180, ideal cells) | sigma=0 control exact; 1.8 %/unary cell (7.2 %/sqrt(w) binary): DNL -0.89/+0.28, INL -0.48/+1.37 LSB. On the PEX at the PDK sigma it is much better: see the post-layout mismatch row |
| DEM | closed (model) | 15-state DWA: mean INL +/-0.48, worst sample +/-1.37, 0.39 LSB rms (pre-layout 1.8 %); on the PEX at 1.0 % the mean is 0.43 and the worst pointer 1.14 |
| Digital half | closed | `dac_csteer_dig` 3733/3733 checks, lint clean, hardened config added; also generates the 60 complementary switch levels |
| Output I-V | **closed: a resistor is enough** | cascoded cell ro is 425 MOhm (not 425 kOhm: the first bench printed `ro/1e3` as kOhm), so 15 unary cells in parallel are 28 MOhm and a 1 kOhm passive I-V at 255 mV output costs 0.002 LSB with perfectly matched cells. The extracted core confirms it: 0.177 / 0.166 LSB with 0 ohm or 1 kOhm at `iout`. An opamp I-V is optional, not a requirement |
| Switch | **closed pre-layout, drawn (gf180)** | differential NMOS pair W/L 4/0.28 with the tail on the cascode drain: Ron 391 Ohm, compliance 2.26 V, event charge error 8.3 fC, pair charge error 0.3 fC, settle 55 ps; corners 301-553 Ohm / 2.10-2.44 V / 45-85 ps (`run_switch.py`) |
| Cascode bias | **closed pre-layout (gf180)** | replica of the cell with the cascode drain diode-tied: Iref 16 uA through Mref 8/1 and Mcas 8/0.5 gives vbp/vcp; 15 corner/temp points hold Icell 16.000-16.002 uA, mirror margin >= 0.57 V, cascode margin >= 1.80 V |
| Layout | **core generator closed; analog-facing pin row closed; wrapper (fragment) class C** | `analog/csteer/gen_gds.py` lays out 30 cascoded-PMOS cells in one row with shared vdd/vbp/vcp rails, the replica cascode bias, and one 4/0.28 NMOS switch pair per cell feeding `iout`/`idump`; each cell exposes `swa_<tag>`/`swb_<tag>` on M2 pads. 15 unary cells are 8/1 (16 uA), all 15 binary cells are 0.5/1 (1 uA) and the 1/2/4/8 weight is the cell count on a gate net, matching the digital fan-out. The 60 gate pins come out on one M2 row, two per cell on a uniform 2.75 um grid in cell order (`swa` then `swb`), so the hardened digital macro can abut with its outputs on that grid; `pinplan.py` re-reads the GDS and the `pins` stage gates it. The digital macro generates all 60 drive levels; the wrapper's pin script and the differential wrapper stay hand layout |
| DRC / LVS / PEX | **closed for the core macro** | `signoff.py`: DRC 0 items, LVS 122 devices (30 cells + 2 bias + 60 switches) / 126 nets (6 rails + 30 tails + 30 internal + 60 gates), pins 96 labelled ports / 60 on the 2.75 um row, PEX 122 instances / 1022 C entries; LVS also checks width against weight (8/1 unary, 0.5/1 binary, mirror must match its cascode); `--selftest` fails drop-unit, swap-gate, short-tail, drop-switch, short-drain, wrong-source, bias-gate, bias-source, cell-width, mirror-width, and five pin-plan mutations (off-grid, swapped, widened pad, dropped port, wrong layer) |
| Post-layout mismatch | **closed (gf180, PEX, PDK area law)** | `run_mismatch_pex.py`: `delvto`/`mulu0` drawn per extracted device from the PDK law, 32 samples, one 31-point deck each. Two gates: zero draws reproduce the measured transfer exactly (0.177 / 0.166 LSB), and the within-sample unary spread lands on the law (0.99 % vs 1.00 %). Fixed pointer DNL 0.268-0.658 / INL 0.364-1.142; DEM mean 0.064-0.451 DNL / 0.053-0.428 INL; 0 non-monotonic samples. The residual is the binary field (a weight-w bit is w 0.5/1 cells, sigma 3.3 %*sqrt(w) LSB), which DEM does not average - the same conclusion P5 reaches. `--selftest` rejects a single shared draw (spread collapses to 0.0000 %) and half-sigma per-device draws (0.35 %) |
| Post-layout core | **closed (gf180, PEX)** | `run_postlayout.py` on the 122-device / 1022-cap extraction: dc pair sum error 1e-5 %, Ron 391 Ohm, compliance 2.26 V, event charge 8.9 fC, pair charge 1.1 fC, settle 47 ps, and a 256-code sweep of the extracted array: FS 255.2 uA, unary step 15.99 LSB, DNL 0.177 / INL 0.166 LSB, 0 non-monotonic steps. The sweep runs into 0 V and through 1 kOhm and the two must agree to 0.05 LSB INL / 0.5 % FS - they do (0.166 vs 0.166). Gates 1 % / 800 Ohm / 1.5 V / 25 fC / 5 fC / 500 ps / 5 % / 1 LSB / 0.5 LSB / 1 LSB / termination. Deterministic transfer only; mismatch is the row above |

The design point here is the DEM state count: 15 unary cells mean 15 pointer
states, not 16. Over 15 samples every cell must see the average current, and
the bench asserts that (`k`-of-15 for `k = 1..7`). Two other results size the
leaf:

* **The cell mismatch is the DNL limit, DEM only fixes the mean.** At
  1.8 %/unit the fixed-pointer INL is 1.37 LSB for one seed (1.38 worst over
  10 seeds); DEM averaging pulls the mean to 0.48 LSB but the instantaneous
  worst sample stays at 1.37 (1.93 over 10 seeds) and adds 0.4-1.0 LSB of
  shaped noise. The ten-seed sweep is in `analog/csteer/README.md`. The PEX
  Monte Carlo (PDK area law, 1.0 %/cell) halves all of that - fixed INL
  0.36-1.14, DEM mean 0.05-0.43 - and moves the limit to the binary field:
  once the unary cells are 1 %, the 15 binary 0.5/1 cells (3.3 %/cell) set the
  residual DNL, which DEM cannot average.
* **A passive I-V is usable at 8 bit.** The cascoded cell ro is 425 MOhm
  (275-549 MOhm over corners), so 1 kOhm across the 255 mV full scale costs
  0.002 LSB of INL even with perfect cells; the regression reports both
  terminations and they are indistinguishable at the mismatch level. The
  earlier "+8 LSB" figure came from reading a kOhm printout as the ro and
  entering 425 kOhm in `csteer.yaml` - a 1000x error now fixed at the bench
  print (`run_cell.py` prints MOhm) and in the yaml.

### 7.4 P4 (binary CDAC) status

Target is the SAR reference spec `../saradc_auto/gen/spec/examples/sar8_sky130.json`:
8 bit, differential, 1.8 V, 1 MS/s, bottom-plate sampling, moscap backend.

| Gate | State | Evidence |
|---|---|---|
| Device unit cap | closed (sky130, measured) | C(V) 19 points -0.9..+0.9 V: 5.022 / 2.673 / 3.964 fF; unit bench reproduces `cdac.yaml` to 0.002 % |
| Charge model | closed | floating top plate, C(V) fixed point per code; constant-C control is exact (0.000 LSB) |
| Mismatch model | closed, deterministic | measured Pelgrom A_C 0.234 %*um at 0.63 um^2 -> 0.295 %/unit |
| DC linearity, moscap | **fails the 8-bit target** | DNL -0.227/+0.684, INL +/-11.9 LSB over 10 seeds; even-symmetric bow, not mismatch |
| DC linearity, flat cap | closed (MIM assumption) | DNL -0.043/+0.057, INL 0.037 LSB; C_unit 8 fF is an assumption, not measured |
| Digital half | closed | `dac_cdac_dig` 2082/2082 checks, 258 break cycles, lint clean, hardened config added |
| Sampling/settling | closed (model) | 1.66 ns/bit, 20.7 ns convert -> 48 MS/s moscap, 17 MS/s MIM |
| Array layout | closed (class B) | 90.23 x 90.26 um, 16x16 fully populated: 255 switched units + 1 VCM dummy; every bit block is a mirror pair about the centre row/column |
| DRC | closed | `sky130A_mr.drc` (KLayout 0.30.12, `feol=true beol=true`): 0 items |
| LVS | closed | extracted netlist: 256 unit caps, bit weights 1/2/4/.../128 and VCM 1, all ten ports present |
| PEX | closed (netlist) | hierarchical `cthresh 0`: `.subckt CDAC_ARRAY` + 256 `CDAC_CAP` instances, 13910 C entries, 0.95 MB; per-net geometric caps reported (B0..B7 12-67 fF), not gated (Magic does not extract MOS channel capacitance) |
| Differential wrapper + comparator | **open, class C** | two mirrored arrays with complementary codes; StrongArm and TG bias are hand work |
| Post-layout transient sweep | **open, not claimed** | 256-code `alter`/`op` loop on the extracted netlist is the remaining pass |

The result that sizes the leaf is a negative one: **at 8 bit and 1.8 V full
scale, a bottom-plate moscap array is limited by the capacitor's bias
dependence, not by matching.** Mismatch is 0.04-0.06 LSB; the C(V) curve is
worth 11.9 LSB of code-dependent bow that no averaging removes, because it is
a deterministic function of the code. Consequences, in order of preference:

* build the array from a flat cap (MIM/poly-poly) - the MIM design passes;
* restrict the array's voltage excursion (a smaller internal VREF window) at
  the cost of SNR;
* add capacitor calibration, which the reference spec explicitly disables
  (`calibration.weights: false`).

The leaf therefore ships both backends: the flat-cap design is the gated one,
the moscap array is a recorded study (`./measure.py --cap moscap --expect
study`), so the physics stays visible instead of being tuned away.

### 7.5 P5 (video-rate binary current steering) status

Named target: 8 bit, 25 MS/s (40 ns), single-ended video, 37.5 ohm at the DAC
(75 ohm line double terminated), gf180.  The 255-cell array is generated and
signed off end to end (DRC/LVS/PEX/pins, extracted DC, mismatch MC, carry
transient).  The digital macro (which now needs 510 outputs), the wrapper that
abuts it, the output driver and the 100 pF `vcp` decoupling are class C.  The
leaf asks whether a plain binary decoder is viable at 8 bit when the weights
are parallel copies of one unit cell - the decoder cost question, not another
segmentation study.

| Gate | State | Evidence |
|---|---|---|
| Device cell | **changed to a dump tail** | 8/1 mirror (source vdd, gate vbp) + 8/0.5 cascode (gate vcp) + a 4/0.28 NMOS pair steering the constant 16 uA tail to `iout`/`idump`; the mirror's Vgs *and* Vds are code-independent.  The first cell (a series PMOS in the mirror's source) closed DC/matching and failed the carry - see *Why the cell changed* |
| Array model | closed | 255 identical unit cells grouped 1/2/4/.../128; full scale 4.080 mA |
| DC, binary decode (pre-layout) | **marginal at the pre-layout sigma** | seed 0 DNL -0.176/+0.176, INL -0.199/+0.199; 20 seeds worst DNL **0.680**, INL 0.442; 5/20 seeds exceed 0.5 LSB DNL.  At the PDK area law the extracted array gives 0.24 worst - see *Post-layout mismatch* |
| DC, unary decode (control) | closed | same 255 cells, same seeds: worst DNL 0.066, INL 0.487 |
| DC, passive load (pre-layout) | **passes; the load is not the limit** | 425 MOhm cell ro makes the 37.5 ohm load a 0.006 LSB gain error: INL -0.198/+0.200 LSB vs -0.199/+0.199 virtual ground, and 37.5/100/300/550 ohm all within 0.02 LSB.  1 LSB would need a 1.7 MOhm load |
| Binary carry, pre-layout model | **superseded** | 51.4 LSB / 740 ps at 127->128 in the ideal-current-source model; the extracted series-switch cell gave 103 LSB and never settled, which is why the cell changed |
| Speed, pre-layout model | **superseded** | 0.83 ns worst settling in the behavioural model; the extracted dump-tail cell settles in 2.3-2.7 ns |
| Array macro | **closed (gf180)** | `gen_gds.py`: 1022 devices = 255 x (8/1 mirror + 8/0.5 cascode + 2 x 4/0.28 NMOS) + a 2-device replica; no standard cell in the macro; 510 M2 pads on a 3.75 um row; vss M1 rail, idump M3 bus |
| DRC | closed | Magic `drc count total` = 0 items on the full array |
| LVS | closed | 1022 devices, 1026 nets: 255 identical 4-device cells re-derived from the pad pair (`d_`/`db_` -> NMOS -> shared tail -> cascode -> mirror -> vdd), a 2-device replica, 6 rails; negative checks for the old `vgnd`/`n_ref`, for a PMOS on a pad and for an NMOS source on a rail; `--selftest` rejects 12 mutations |
| PEX | closed | 1022 instances, 7912 C entries (321.4 kB): vdd 404 fF, vbp 307 fF, vcp 359 fF, iout 208 fF, idump 333 fF, vss 875 fF |
| Pins / rails | closed | 516 ports: 510 M2 pads, cell order, exact 3.75 um grid (two per cell, so a 510-output digital macro abuts) plus a `vss` pad on the bias side; vdd plane 2.4 ohm = 1.2 mV at full code (1.2% gain, endpoint-calibrated), iout bus 10.7 ohm = 21.8 mV one-ended (0 LSB/cell through ro), idump the same class; vbp/vcp/vss carry no DC current |
| Post-layout DC | closed (nominal) | `run_postlayout.py`: 256-code sweep on the extracted netlist, virtual ground and 37.5 ohm - 4.080 mA full scale, **16.001 uA/cell**, DNL/INL 0.000 LSB, 0 bad steps, `vbp` 2.170 V / `vcp` 0.782 V.  Nominal only: Magic extracts capacitance, not metal R, and identical cells make the transfer exact by construction, so this gates the operating point, not linearity |
| Post-layout mismatch | **closed (PDK area law)** | `run_mismatch_pex.py`: `delvto`/`mulu0` per extracted device from the PDK law (pfet and nfet), 16 samples of a 255-point selector sweep.  Cell spread **1.00 %** vs the law's 1.003 % - the mirror's Vth alone (0.558 %/mV x 1.79 mV = 1.00 %); the pair's sensitivity is 0.000 %/mV because it sits in the drain path.  Fixed DNL **0.12..0.24** LSB, INL 0.09..0.16, 16/16 monotonic; the zero-draw reconstruction reproduces the bench transfer to 0.0000 LSB.  `--selftest` rejects a shared draw, half-sigma draws and pair-only draws |
| Post-layout carry | **closed** | `run_transient_pex.py`: 510 PWL pads, 20 ps edges, 25 ps bit skew, 25 MS/s.  127->128 **128.000 LSB (+0.000), 0.5 LSB at 2.30 ns**; 128->127 and 63->64 likewise; full scale 0->255 **254.693 (-0.307), 2.72 ns**; `vbp`/`vcp` within 0.48 mV.  With the wrapper's 100 pF on `vcp`: without it the full-scale step lands at -4.3 LSB (device level), and that cap is a documented wrapper requirement |
| Glitch | recorded, not gated | the steering pair's switching charge into the 2 pF output is a ~340-450 LSB spike decaying in ~3 ns (clear of the 40 ns sample); larger than the old cell's 103 LSB and a spec for the output filter |
| Other PDKs (device level) | **ihp-sg13g2 closes the carry; sky130 sized at 3.3 V; icsprout55 blocked** | `analog/video/pdk_cell.py` applies the same cell to the other three processes.  IHP 1.8 V lv (PSP103, OSDI): the gf180 sizes fit (8/1 needs Vsg 0.57 V); carry **+0.024 LSB** with the bias flat, full scale **-0.412 LSB** with 220 pF on vcp (100 pF gives -0.86, so that PDK wants more decoupling).  sky130: the 1.8 V logic PMOS cannot stack two diodes at 16 uA (the replica's vcp goes negative), so the cell runs the 5 V g5v0d10v5 devices at 3.3 V; their bins reject l=1.0 and l=0.28 ("could not find a valid modelname"), so all three devices are 8/0.5 - 16 uA/cell at vbp 2.192 / vcp 0.843 V, full scale **+0.242 LSB** but the carry **+0.562 LSB** with the bias flat (0.06 LSB outside the window; the cell/output settling at this pair geometry, so the sizing needs one more pass).  icsprout55: **blocked at the models** - the .mdl bins are selected by .param expressions over the instance w/l (`wum = w*1e6`), which ngspice cannot evaluate, and the PDK readme says HSPICE-only.  Layouts stay gf180-only |
| Digital half | **needs the complementary pair** | `dac_video_dig` supplies 255 one-hot lines; the dump-tail cell needs `d_`/`db_` (510 outputs).  Class C follow-up, like the wrapper |

**Why the cell changed.** The first macro put a 0.5/0.28 PMOS in series with
the mirror's source - true zero, no dump - and closed DC and matching
(16.000 uA/cell, 0.720 %/cell, fixed DNL 0.174).  Its extracted carry then
failed by an order of magnitude (118.503 LSB, -9.497) because switching a cell
moved the mirror source 0.59 V and the cascode source 1.4 V into 7-10 pF of
gate load driven by a one-cell replica at 1/gm ~ 6-7 kOhm (50-80 ns pole).
Thermometer decode (-173 LSB at full scale), an 8x scaled replica
(-1.13 / -63 LSB) and moving the switch to the mirror's drain
(-2.30 / +54 LSB) were all measured and all insufficient: the 255 mirror
gates' charge still changes by ~10 fC per cell.  Only a cell whose mirror keeps
both Vgs and Vds constant avoids it, so the tail now keeps flowing and is
steered.  Cost: 4 devices per cell, 2 pins, vss/idump rails, a 100 pF wrapper
cap, and the cell sigma rose 0.72 -> 1.00 % because the degeneration is gone
(DNL 0.174 -> 0.30 worst, still inside 0.5).

Two extraction findings from the first cell, kept because they shaped this
one: (1) the vcp poly bar stopped at the last cell, leaving the 255 cascode
gates on an unnamed island (LVS caught it); (2) the post-layout bench measured
8.07 uA per cell instead of 16 because the series switch degenerated the
mirror and the replica did not reproduce the drop - the fix then was to repeat
the switch in the replica, and in this cell it is to remove it from both.

## 8. Application fit

| Target | Best fit | Note |
|---|---|---|
| Audio, 16 bit, 48 kHz | existing ΔΣ + RC (A) | no analog leaf needed; 0 dBFS via 1st order |
| Video, 8 bit, 25 MHz | current-steering (C with trim/segmentation; pure binary decode costs 0.68 LSB DNL) | external 75 Ω line; a resistor output is enough (no transimpedance stage) |
| General 8–12 bit, low speed | R-2R (B) | smallest area at 8–10 bit |
| Mid-speed monotonic, 8 bit | resistor string (B, buffered) | 2^N resistors, switch Ron sets DNL; Edwards 8-bit fails its own INL with a follower |
| High-speed / RF | CML/HBT (C) | ihp130 only |
| SAR/ADC reuse | CDAC (B/C) | needs sample-and-hold + comparator, not just a DAC |

Do not chase 16-bit R-2R or resistor-string DACs on an open PDK without
trimming/calibration: switch Ron and resistor mismatch dominate well before
16 bit.

## 9. Phased roadmap

- **P0 (no analog).** Keep `pwmdac`/`audiodac` as the portable default. Add
  the PDK capability table and the `DAC_KIND` enum to `dac_wrap`; document
  that `freepdk45`/`ics55`/`OR1` are digital-only until audited.
- **P1 (first analog leaf). DONE on gf180** (sky130 geometry documented, not
  simulated): pre-layout + GDS + DRC + LVS + PEX. R-2R 8-bit following
  `ihsan-sa/ece298a-r2r-dac`: generated 25-PCell array, fixed M1 track plan,
  digital code register macro, 15-corner + deterministic mismatch.
  DNL 0.145 / INL 0.092 LSB, 1.15 us full-scale settling. Magic signoff:
  DRC 0 items, LVS 17 unit + 8 trim, PEX 25 instances / 37 C entries.
  Post-layout poly R-C: Magic deliberately does not extract resistor-body
  parasitics, so `postlayout.py` rebuilds them from the extracted geometry and
  the `ppolyf_u`/`fox_sub` constants (rsh 350, r_dl/r_dw, 1 um end resistors,
  cj 8.85e-5 F/m2) and compares a lumped against a 20-section line. DC agrees
  to 0.006 mV (DNL -0.001/+0.041, INL -0.014/+0.036 LSB at tt/25). Transient
  (1 MOhm // 7 pF load, 60 us/step, 50 ns grid): worst step 255->0 = 1.139 us
  lumped vs 1.140 us segmented, i.e. the reconstructed poly body R-C adds
  ~1 ns to settling. The full-DAC post-layout sweep is still not claimed.
- **P2. DONE on gf180 (pre-layout + digital half + string macro).** 8-bit
  binary-tree Kelvin string, 255 units, 255-TG tree, ideal-follower bench:
  DNL 0.133 / INL ±0.13 LSB at tt/25, ideal-switch control shows the error is
  entirely MOS-tree, 5.0 us worst step settling. Higher INL than P1 as
  predicted, but not the Edwards ±2 LSB failure - the difference is the wide
  uniform TG and the tap impedance choice. The string is generated and signed
  off (`analog/string/gen_gds.py`, DRC 0, LVS 255 units, PEX 255 instances);
  the TG tree and follower stay class C hand layout, so `run-analog.sh string
  gf180 gds` builds and checks the string macro, not the whole DAC.
- **P3. DONE on gf180 (pre-layout + digital half + array macro).** 8-bit 4+4
  unit-current-steering 8-bit + standard-cell thermometer/DWA, following
  `2AMLogic/gf180-current-dac` for the array and `alinja/skydacmagic` for the
  cell. Device cell I 15.77 uA, ro 425 MOhm, Vth sensitivity 0.519 %/mV ->
  1.8 %/unary cell (7.2 %/sqrt(w) on binary bit w). Fixed-pointer INL 1.37 LSB;
  DEM mean 0.48 LSB at 0.39 LSB rms. A 1 kOhm passive I-V is enough: 0.002 LSB
  of INL with perfect cells, and the extracted core measures the same transfer
  into 0 ohm and 1 kOhm. The core is generated and
  signed off (`analog/csteer/gen_gds.py`: 15 unary 8/1 cells, 15 binary 0.5/1
  cells, replica cascode bias, 60 steering switches; DRC 0, LVS 122 devices /
  126 nets with a width-vs-weight check, PEX 122 instances). The switch gates
  and a 256-code sweep re-pass on the extracted core (`run_postlayout.py`:
  FS 255.2 uA, DNL 0.18 / INL 0.17 LSB, monotonic) - that sweep is what caught
  and closed the earlier all-16-uA array, which transferred a sawtooth. The
  digital macro generates all 60 complementary switch levels and the analog
  side publishes the abutment grid (60 pins, 2.75 um pitch, `build/pinplan.json`,
  gated by the `pins` stage). Static mismatch is measured on the same
  extracted devices (`run_mismatch_pex.py`, PDK area law, 32 samples): 1.0 %
  per unary cell (the pre-layout 1.8 % was 1.8x pessimistic), DEM mean
  0.06-0.45 DNL / 0.05-0.43 INL, 0 non-monotonic samples, with the residual
  in the binary carry rather than the unary field. `run-analog.sh csteer gf180
  gds` builds the core macro only: the wrapper's pin script and the
  differential wrapper stay class C hand layout (no hardened `dac_csteer_dig`
  is built here, so no wrapper GDS exists), and the I-V is a 1 kOhm resistor.
- **P4. DONE on sky130 (model + digital half + array macro).** 8-bit
  differential binary bottom-plate CDAC against the SAR reference spec.
  Charge-based C(V) model on the measured sky130 moscap. Mismatch costs
  0.04-0.06 LSB; the moscap's 2.67 -> 5.02 fF bias dependence costs 11.9 LSB
  INL, so the 8-bit design point is a flat cap (MIM, 0.037 LSB) and the
  moscap array is recorded as a study. `dac_cdac_dig` 2082/2082 checks, lint
  clean. The array macro is generated and signed off: `gen_gds.py` lays out
  255 switched + 1 VCM-dummy units in a fully populated 16x16 grid (mirror
  pairs about the centre, so every bit's centroid is the array centre), and
  `signoff.py` gates DRC 0 items, LVS weight counts 1..128 + VCM 1 on the
  extracted netlist, and PEX (256 instances, 0.95 MB). `run-analog.sh cdac sky130
  gds|drc|all` drives it. Still open, and explicitly not claimed: the
  differential wrapper (two mirrored arrays), the comparator/TG bias (class
  C) and the 256-code post-layout transient sweep.
- **P5. DONE on gf180 (dump-tail array, signed off end to end).** 8 bit,
  25 MS/s video-rate binary current steering, 255 parallel unit cells decoded
  1/2/4/.../128.  Binary decode is INL-neutral but costs carry DNL: 0.680
  worst vs 0.066 for the same cells with a thermometer decoder (5/20 seeds over
  0.5 LSB) - at the pre-layout 1.8 %/cell sigma.  At the PDK area law the
  extracted array's worst fixed DNL is **0.30 LSB** (INL 0.20) over 16 samples,
  16/16 monotonic, so the binary penalty is real but inside the 0.5 LSB
  target.  A passive 37.5 ohm load is fine (0.006 LSB gain error; no
  transimpedance stage).
  The cell is a **dump tail**: an 8/1 mirror and 8/0.5 cascode keep 16 uA
  flowing while a 4/0.28 NMOS pair steers it to `iout` or `idump`, so the
  mirror's Vgs and Vds never move with the code.  That is the answer to the
  leaf's timing question: the first cell - a series PMOS in the mirror's
  source, true zero/no dump - closed DC and matching (16.000 uA/cell,
  0.720 %/cell, DNL 0.174) and then failed the extracted carry by 9.5 LSB and
  never settled.  Thermometer decode (-173 LSB full scale), an 8x scaled
  replica (-1.13/-63) and moving the switch to the drain (-2.30/+54) were each
  measured and none closed it; ~10 fC per cell of mirror gate charge has to go
  somewhere whichever terminal the switch interrupts.  With the tail steered,
  the extracted 127->128 carry is **128.000 LSB (+0.000) at 2.30 ns** and the
  full-scale step **254.693 (-0.307) at 2.72 ns**, with `vbp`/`vcp` inside
  0.48 mV - the residual is a 5 mV cascode-gate kick, handled by the wrapper's
  100 pF on `vcp`, and a ~400 LSB/3 ns switching spike that the 40 ns sample
  is clear of.
  The macro is generated and signed off: 1022 devices (4 per cell) + a
  2-device replica, 510 M2 pads on a 3.75 um row, vss M1 rail, idump M3 bus;
  DRC 0, LVS 1022 devices/1026 nets re-derived from each pad pair, PEX 1022
  instances/7912 C entries, 516 labelled ports.  `signoff.py --selftest`
  rejects 12 LVS, 5 pin and 1 rail mutation.
  `run-analog.sh video gf180 gds|drc|lvs|pex|pins|postlayout|mm|tran|all`
  drives it.  Still open, and class C: the digital macro (the RTL still drives
  255 one-hot lines, not the cell's 510 complementary pair), the wrapper and
  its pin script, the output pad/ESD/cable driver, and placing that 100 pF
  `vcp` cap.  The same cell is now sized for the other three PDKs at the
  device level (`analog/video/pdk_cell.py`, see 7.5): IHP 1.8 V closes the
  carry (+0.023 LSB), sky130 moves to the 5 V devices at 3.3 V because the
  1.8 V PMOS cannot stack two diodes at 16 uA, and icsprout55 is blocked at
  the models (HSPICE-only).  Their layouts are the next step.  CML/HBT
  remains blocked: ihp130 has no installed HBT models, so there is no SiGe
  device to build from.

## 10. Risks / non-goals

- **Matching is not a digital problem.** A clean decoder does not buy INL.
- **Binary-weighted resistor DACs do not scale.** No surveyed repo implements
  one above ~6 bit; ratio spread and switch Ron force R-2R or a string.
- **A buffered string DAC is not automatically linear.** The Edwards 8-bit is
  LVS-clean and still fails its own INL spec; budget output-follower and
  switch-Ron work.
- **Open PDK mismatch models are incomplete** (GF180 `mis_r=0`), so
  post-layout MC can understate resistor ratio error.
- **Analog extraction is the long pole.** Budget PEX runtime and corner
  explosion; reference repos spend most of their effort there.
- **Do not route the analog core through OpenROAD.** The reference where this
  was attempted (`dineshannayya/8bit_dac`) hardened only a digital stub.
- **Licenses vary.** `ihsan-sa` has no license; `MacAnalog` is
  non-commercial; `GREAHeaviside` is GPL-3.0. Only `sky130_ef_ip__*`,
  `2AMLogic`, `Silicluster`-adjacent, `ttsky`/`tt08` are Apache/MIT-ish;
  verify before copying layout or netlists.
- **No silicon correlation** in any surveyed repo. All linearity numbers are
  extracted-layout simulation.
