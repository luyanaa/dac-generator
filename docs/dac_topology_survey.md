# Survey: open-silicon analog DAC topologies

Status: research note. Companion to `docs/analog_dac_integration_plan.md`.

Sixteen public repositories were inspected for four families: switched
capacitor / CDAC, current steering, R-2R / binary-weighted resistor, and
resistor string / Kelvin divider. Two VGA-matrix projects were added because
they are often cited as "resistor DACs" but are actually MOS current DACs.
The goal is to decide what a per-PDK generator can emit, what needs a
constrained device generator, and what needs a human layout.

Legend for **Class**: **A** = digital / digitally assisted, **B** =
device-generated with constrained routing, **C** = must be manually laid out
(as shipped). See the integration plan for the definitions.

## Summary table

| Repository | PDK | Topology | Bits | Layout | Post-layout evidence | License | Class |
|---|---|---|---|---|---|---|---|
| `sky130_ef_ip__cdac3v_12bit` | sky130A | 6+6 split binary CDAC, top-plate sample | 12 | hand Magic, LVS match | none (no PEX/INL) | Apache-2.0 (in CACE) | C |
| `SiliclusterV3_2_cap_DAC` | sky130A | serial 2-cap charge sharing + buffer | 8 | script (Magic) | full-RC PEX, 9 corners, INL 0.553 / DNL 0.538 LSB, 32 MC seeds | none | B |
| `DSP_DAC_GFMPW0` | gf180 | 8× 1-bit accumulator-MSB PWM, no cap | 8 (PWM) | OpenLane | digital DRC/LVS only | Apache-2.0 | A |
| `alinja/skydacmagic` | sky130 | segmented diff current steering | 10 | none (SPICE only) | schematic tran, ~60 dB SFDR claim | none | C |
| `2AMLogic/gf180-current-dac` | gf180 | 6 unary + 4 binary current cells | 10 | generated GDS + OpenLane digital | DRC/LVS; no PEX; analytic INL yield only | Apache-2.0 | B (+A) |
| `andrsmllr/sky130_cml_dac` | sky130 | CML library cells, no DAC | — | none | none | none | C (sketch) |
| `MacAnalog/dn-002-...-ihp130` | ihp130 | 2-bit cascode HBT current steering | 2 | gdsfactory, kpex | kpex S-param/eye, typ only | non-commercial | B |
| `GREAHeaviside/dac10b-r2r-sky130` | sky130 | R-2R, unit poly, TG switches | 10 | schematic only | Python mismatch model; no PEX | GPL-3.0 | C |
| `ihsan-sa/ece298a-r2r-dac` | gf180 | R-2R, poly units + trims | 8 | gdsfactory | PEX, 9 corners, INL 0.355 / DNL 0.141 LSB | none | B |
| `dineshannayya/8bit_dac` | sky130B | resistor string, generic ndiff | 8 | hand GDS | extracted tran, TT only, no INL | Apache-2.0 | C |
| `33ronak/10-bit_DAC-sky130` | sky130 | resistor string | 10 | none (images) | photos only | none | C |
| `sky130_ef_ip__rdac3v_8bit` | sky130A | binary-tree Kelvin string + follower | 8 | hand Magic, LVS match | schematic INL fail; no PEX | Apache-2.0 | C |
| `vyges-ip/sky130-potentiometric-dac` | sky130 | vsdip binary-tree string re-import | 10 | hand Magic | extracted tran, no INL/corners | Apache-2.0 | C |
| `HarshiniS05/10bit-potentiometric-dac-sky130` | sky130 | binary-tree string, prelayout | 10 | none | prelayout tran only | none | C |
| `ttsky25a-vga-matrix-dac` | sky130A | 16×16 unit-current sink matrix | 8×3 | hand Magic + OpenLane | extracted netlist, no INL | Apache-2.0 | C (+A) |
| `tt08-vga-fun` | sky130 | binary-W/L + segmented current sink | 8×2 + 8 | hand Magic + OpenLane | schematics, no committed PEX | Apache-2.0 | C (+A) |

Hard conclusion: **only two repos have credible extracted linearity data**
(`ihsan-sa/ece298a-r2r-dac`, `SiliclusterV3_2_cap_DAC`). A clean DRC/LVS or
an analytic Monte Carlo is not analog sign-off.

---

## 1. Switched capacitor / CDAC

### 1.1 `RTimothyEdwards/sky130_ef_ip__cdac3v_12bit`

- **Design.** Single-ended 12-bit **6+6 split binary** CDAC: LSB bank 64 unit
  caps, MSB bank 63 unit caps, a bridge cap sized 64/63 (7 × 7.055 µm vs the
  7 × 7 µm unit). Two stacked MIMs per weight (`cap_mim_m3_1` + `_m3_2`).
  Top-plate sampling: `HOLD` connects `VIN` to both top plates; bottom plates
  mux between `VCM`, `VL`, `VH`. Built for a SAR ADC, not as a stand-alone
  audio DAC.
- **Digital.** No SAR engine. The leaf exposes a binary pin bus
  `SELD0..SELD11`, plus `RST`, `HOLD`, and 1.8→3.3 V level shifters. A caller
  must sequence it.
- **Layout.** Hand Magic, no generator/GDS in the archived tree. Hierarchical
  `cdac_unit_cap` arrayed 10×9, connect cells for near/far/none/split,
  interleaved bit labels and a `D` dummy ring, separate switch and level
  shifter arrays. LVS top cell matches uniquely; subcells match only after
  flattening. The checked-in `drc.log` is only a header, so DRC is **not**
  proven.
- **Post-layout.** No PEX, no corners, no INL/DNL.
- **Verdict.** The reference for *what a matched CDAC leaf looks like*, and
  for the split/bridge sizing. Not a reusable generator. Class **C** as
  shipped; a future generator can tile the unit + connect cells (class B) but
  the bridge and sample switch still need hand tuning.

### 1.2 `jonahsaunders/SiliclusterV3_2_cap_DAC`

- **Design.** Not a binary CDAC. 8-bit **serial two-capacitor charge-sharing**
  DAC (Suarez/Gray/Hodges 1975): two 16 × (14 × 14 µm) MIM banks (6.454 pF
  each), common centroid; each bit charges one bank to a reference, then
  shares charge with the other; LSB first. A separate 26 × 26 µm cap
  compensates the output buffer. Single-ended buffered output.
- **Digital.** Three externally timed phases (`charge_high`, `charge_low`,
  `share`); no code bus, no SAR/sequencer. Off-chip example driver only.
- **Layout.** Script-generated (`build_circuit.py`, `build_layout.py`,
  `physical_verify.py`, `extract.py`): 4×8 common-centroid array, ground
  shields between sample/hold buses and cap columns, M4/M5 power grid, M4
  signal pins. GDS DRC 0, antenna 0, LVS unique, ERC 0.
- **Post-layout.** Full RC + coupling from the delivered GDS, star-mesh
  reduction, ngspice 9 corners × 256 codes × 32 mismatch seeds. Worst INL
  0.553 LSB, DNL −0.031..0.538 LSB, all monotonic; buffer 120 stability
  cases, worst PM 71.25°, 0.5-LSB settling 6.41 µs; hold drift 0.003 LSB /
  50 µs at 85 °C. No ENOB.
- **Verdict.** The best evidence that a **class B** capacitive leaf is
  realistic: generate the array, shields and a fixed power grid, then run PEX
  and corners. The hard parts are the matched banks, charge injection of the
  TGs, and the op-amp. It is a serial DAC, not a parallel-bus DAC; a generator
  would need to add a sequencer macro.

### 1.3 `vijayank88/DSP_DAC_GFMPW0`

- Not a CDAC. An 8-channel 8-bit phase-accumulator PWM (MSB to GPIO) plus a
  Wishbone MAC on gf180, hardened by OpenLane. No capacitors, no analog
  filtering on chip; `io_oeb` is tied off, so the PWM may not even reach the
  pads. Class **A** only in the weak sense of off-chip RC filtering.

---

## 2. Current steering

### 2.1 `alinja/skydacmagic`

- **Design.** Segmented differential current steering, 10 bit (5 thermometer
  + 3 thermometer + 2 binary). Cascoded NMOS mirror cells, LVT differential
  switches with deliberately skewed inverters for make-before-break, 50 Ω
  loads to 1.8 V. MSB unit bias 0.2 mA; LSB cells scaled ×1/8, /2, /4.
- **Digital.** No RTL. Thermometer decode and DEM run **offline in Octave**
  and become per-switch PWL sources. The SPICE core wants individual gate
  pins, not a bus.
- **Layout.** None.
- **Post-layout.** Schematic transient only, one corner (`ff_mm`, 125 °C).
  README claims ~60 dB SFDR "over temperature and process in mismatch
  simulation"; no committed MC or INL/DNL table, no PEX.
- **Verdict.** A good cell-level study; class **C**. The layout, matching and
  DEM must be built from scratch.

### 2.2 `2AMLogic/gf180-current-dac`

- **Design.** 10 bit, 6 unary MSBs (63 × 16 units) + 4 binary LSBs = 1023
  live units, differential, 2 mA full scale, I_LSB ≈ 1.955 µA, 50 Ω loads.
  Cascoded sources with switches above the cascode.
- **Digital.** A real RTL partition: `dac_digital.v` takes `din[9:0]` and
  emits 63 unary + 4 binary, retimed once. But the analog macro expects 67
  separate switch pins; the two partitions are **not connected** in the repo.
- **Layout.** Script-generated GDS (`gen_array.py`): 34×34 sites, dummy ring,
  1023 unit cells, 133 dummies, point-symmetric switching order, fixed
  M2–M5 directions. Every wire is minimum width; `vbn`/`iref` top-only and
  outputs bottom-only, so column IR is one-sided. Digital is a separate
  OpenROAD GDS, not abutted.
- **Post-layout.** DRC/LVS clean; **no PEX, no SPICE linearity**. The 99.92 %
  INL/DNL yield is an analytic Pelgrom model, not simulation. Signoff manifest
  explicitly leaves PVT, MC, post-layout and characterization unmet.
- **Verdict.** The best **class B** template for a current-steering array plus
  a standard-cell decoder. Not signoff-clean; min-width routing and one-sided
  rails would not pass EM/IR.

### 2.3 `andrsmllr/sky130_cml_dac`

- A cell library toward a CML DAC: differential pair W=20/L=0.15, 1 mA ideal
  tail, 300 Ω, plus mirror benches. No decoder, no array, no layout, no PEX.
  Class **C** sketch; ignore for integration.

### 2.4 `MacAnalog/dn-002-tx-driver-pam4-ihp130`

- **Design.** 2-bit PAM-4 driver on ihp130 SiGe: one LSB + two identical MSB
  cascode HBT cells, emitter degeneration, 50 Ω collector loads, behavioral
  tails. Not a Nyquist DAC.
- **Digital.** Analog CML base inputs; no bit bus, no decoder.
- **Layout.** gdsfactory generator, center-fed H-tree input, MSB rows
  innermost, widened output bus, min-width TM1. DRC/LVS on the signed tiers;
  open items: cascode-rail bypass, EM on 20+ mA paths, HBT/rsil dummies, thin
  ground cage.
- **Post-layout.** kpex CC netlists committed; typ-only S-params/eyes (BW
  61–81 GHz, RLM 0.995). No INL/DNL. Non-commercial license.
- **Verdict.** Class **B** generator pattern for a tiny high-speed output
  stage, not a multi-bit DAC. ihp130-only.

### 2.5 VGA repos (MOS current, not resistor)

`ttsky25a-vga-matrix-dac`: 3 × 8-bit 16×16 **unit-current sink matrix**,
binary row/column selection, 15-line thermometer row/column, two dummy cells,
5 V NMOS sink, external 500 Ω–1 kΩ to 3.3 V and an external I-to-V. Hand
Magic array with abutted `icellwrap`, OpenLane controller. Committed extracted
`csdac255.sim.spice`, but no INL/DNL/raw data.

`tt08-vga-fun`: red/green **binary-weighted** current steering (W/L-weighted
bits, hand-tuned), on-chip ~2.34 kΩ poly I-to-V; blue is a 4-segment × 3
matched-cell sink with a 2-bit transistor thermometer. Hand Magic, OpenLane
controller, no committed extracted netlists or linearity.

Both are class **C** for the analog leaf, class **B/A** for the controller.
They are video experiments ("rough", slew 60–80 ns vs a 40 ns pixel), not
precision DAC references.

---

## 3. R-2R and binary-weighted resistor

### 3.1 `GREAHeaviside/dac10b-r2r-sky130`

- **Design.** 10-bit single-ended R-2R. One bit cell = three identical
  `res_xhigh_po_1p41` at L=14.1: two in series (2R) and one shunt (R). LSB
  termination is one more unit plus five shorted dummies. CMOS TG switches
  driven by **eight** `inv_x64` per bit, local decaps.
- **Digital.** Plain `D[0:9]` + `en` + `strb`, per-bit D latch. Clean bus.
- **Layout.** **None.** README says layout/post-layout are TODOs; only utility
  cell GDS exist. No common-centroid, no routed array, no DRC/LVS.
- **Post-layout.** A Python Pelgrom/MC engine (example: 13 LSB DNL, ENOB 6.84
  at 1 MHz) and a code-by-code OP sweep (TT only); no extracted netlist, no
  committed results.
- **Verdict.** Good schematic reference for the unit-resistor + 2R-series
  construction and the Ron problem. Class **C** as shipped; the ratio itself
  is generator-friendly. GPL-3.0.

### 3.2 `ihsan-sa/ece298a-r2r-dac`

- **Design.** 8-bit single-ended R-2R on gf180, 25 `ppolyf_u` units, all
  W=2.0 µm; series/termination L=150 µm (≈27 kΩ), driven 2R trimmed to
  L=148.36 µm to absorb mean driver Ron (~295 Ω). No TGs: one `buf_20` per
  bit. No output buffer. Spec explicitly notes pull-up/pull-down ΔRon
  (~280 Ω) cannot be trimmed, which is why R was raised from 250 Ω (41 LSB
  INL) to 27 kΩ (0.23 LSB).
- **Digital.** Plain `dac_code[7:0]`; the digital block adds a code register,
  ramp/sine/hold modes outside the analog leaf.
- **Layout.** gdsfactory generator: one horizontal poly unit per row, left
  ends aligned, common vss strip, buffers with shared rails, fixed
  via1/M2/M1 track plan, M3 straps, right-edge pins, no dummies/centroid.
  DRC pass, LVS pass; bbox ≈211 × 140 µm.
- **Post-layout.** 9 corners pre-layout: DNL 0.141 LSB, INL 0.355 LSB,
  monotonic, settle 1.441 µs; Magic PEX (2910 R / 2084 C): settle 1.202 µs,
  10–90 % 424 ns, glitch 14.9–23.8 pV·s. No ENOB; no per-instance resistor MC
  (`mis_r=0` on gf180).
- **Verdict.** The best **class B** R-2R template: generated array, fixed
  routing, DRC/LVS/PEX, honest limits (1.2 µs into 100 Ω + 7 pF). Not 16-bit;
  MSB ratio error costs ~128·e LSB. No license file.

### 3.3 Binary-weighted resistor

None of the surveyed repos is a true binary-weighted resistor DAC (weights
1, 2, 4, ... as separate resistor values). The two "binary-weighted" designs
found are **current** steering (tt08 red/green). This is consistent with
practice: beyond ~6 bits the resistor ratio spread makes a binary-weighted
array impractical; implementations use R-2R (two resistors per bit) or a
resistor string. Treat "binary-weighted resistor DAC" as a 4–6 bit topology,
or as a teaching variant, not as a target for 8–16 bit.

---

## 4. Resistor string / Kelvin divider

All three surveyed string DACs are **binary-tree Kelvin dividers** (an N-bit
block = two (N−1) blocks + one switch), not thermometer-segmented strings.

### 4.1 `RTimothyEdwards/sky130_ef_ip__rdac3v_8bit`

- **Design.** 8-bit hierarchical binary string. Leaf column = 10 ×
  `res_high_po_0p35` (W=0.35, L=3.16), taps via 5 V CMOS pass gates
  (nfet W=0.65 / pfet W=1, L=0.5). 16 columns per half, two halves, MSB `b7`
  through two pass gates, four dummy columns. Output buffered by a
  `follower_amp` from the sample/hold IP. External 3.3 V / 0 V references.
- **Digital.** Plain `b[7:0]` + `ena` on 1.8 V, with on-chip 1.8→3.3 V level
  shifters; no decoder.
- **Layout.** Hand Magic. LEF 84.6 × 156.3 µm. LVS unique match (1814
  devices / 739 nets). The checked-in `drc.log` is a large violation list,
  not a clean result.
- **Post-layout.** CACE is configured for rcx + INL + 50-iteration MC, but the
  published report is **schematic only** and fails its own limits: INL typ
  1.136 LSB, max 3.995 vs ±2; offset and gain also fail; DNL ~0. No PEX,
  no settling number.
- **Verdict.** The only hardened, LVS-clean string macro in the set, but it is
  **not linearity-clean**. The follower and switch resistance dominate. Class
  **C** as shipped; a generator could tile the matched column at a fixed
  pitch and stamp the binary tree (class B), but the follower/level-shifter
  remain hand analog.

### 4.2 `vyges-ip/sky130-potentiometric-dac`

- A re-import of `vsdip/avsddac_3v3_sky130_v2`, not a new design. 10-bit
  binary tree, ideal 4 × 250 Ω leaf → 1024 × 250 Ω, 1023 CMOS TGs. Hand Magic
  layout. Extracted netlist uses `res_generic_nd` W=0.17/L=0.81 (extracted
  517.9 Ω, not 250 Ω), 4092 + 4092 FETs. No level shifter, no output buffer;
  1.8 V gates drive a 3.3 V ladder. No GDS/LEF/DRC/LVS; extracted transient
  only, no INL/DNL/corners.
- **Verdict.** Do not harden this leaf. Class **C**, and a cautionary example
  of ideal-R schematic vs extracted generic-diffusion R.

### 4.3 `HarshiniS05/10bit-potentiometric-dac-sky130`

- Prelayout only: 1024 × 500 Ω ideal + 1023 `TG2`, external `dN`/`dNb`
  complements, no buffer, no layout/GDS. Staircase waveforms only; no
  INL/DNL/PEX. Class **C** (not a macro). Useful only as a tree-composition
  description.

### 4.4 String-DAC findings

- The **unit resistor + transmission gate** is the generator leaf; the binary
  tree is a regular stamp once the pitch and switch topology are frozen.
- 8 bits already needs 255–320 taps and 255 switches; 10 bits is 1023. Area
  and switch parasitics grow fast.
- **Switch Ron is in series with the tap and directly sets DNL/INL.** The
  Edwards 8-bit still fails INL with a follower; do not expect 10+ bit
  monotonicity without trim or a larger string resistance (which then slows
  settling).
- The output follower is hard analog (class C) and often dominates settling
  and offset.

---

## 5. Cross-cutting conclusions

1. **Most references are not signoff-grade.** Only two have extracted
   linearity (R-2R and serial CDAC). The rest stop at schematics, LVS, or
   analytic mismatch models. Budget most of the effort for PEX, corners and
   MC, not for the RTL decoder.
2. **The digital half is easy and reusable.** A plain code bus plus a
   standard-cell decoder/thermometer/DEM/sequencer is a solved problem. Every
   serious repo keeps it outside the analog leaf.
3. **Layout regularity decides the class.** R-2R and string arrays reduce to
   one repeated unit and a fixed tree; a generator can place and route them
   with constraints (class B). CDAC bridges, current-steering matching and
   compensation, and CML cells need hand tuning (class C).
4. **Binary-weighted resistor DACs are not practical above ~6 bits.** Use
   R-2R or a string instead. No surveyed repo implements one.
5. **PDK device availability is the hard gate.** MIM: sky130/gf180/ihp130.
   Precision poly R: sky130/gf180/ihp130/ics55. HBT: ihp130 only.
   freepdk45 has neither, so it stays digital-only.
6. **Mismatch models are incomplete.** gf180 poly resistors have `mis_r=0`;
   sky130 references often substitute a Python Pelgrom model. Use
   deterministic per-unit sensitivity until per-instance MC exists.
7. **Licenses block reuse.** `ihsan-sa` and `Silicluster` have no license;
   `MacAnalog` is non-commercial; `GREAHeaviside` is GPL-3.0. The Apache-2.0
   references are `sky130_ef_ip__*`, `2AMLogic`, and the VGA repos.

## 6. What to build first

Following the evidence, the lowest-risk order is:

1. **R-2R 8-bit** on gf180/sky130, copying the `ihsan-sa` generated array +
   fixed track plan + PEX loop.
2. **Resistor-string 8-bit**, reusing the same generator and adding the
   binary tree + a buffered output; expect worse INL than R-2R unless the
   switch Ron is engineered.
3. **Unit-current-steering 8-bit** with a standard-cell thermometer, copying
   `2AMLogic` for the array and `skydacmagic` for the cell.
4. **CDAC** only behind a SAR/ADC target; reuse Edwards' sizing and
   Saunders' generator/PEX method.

The existing PWM and ΔΣ + RC backends remain the portable default, especially
on PDKs without MIM or precision resistors.
