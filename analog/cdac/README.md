# Binary bottom-plate CDAC leaf

Fourth analog leaf (roadmap P4). Class **B/C**: the capacitor array is a
generated device macro with a constrained (common-centroid) routing plan; the
comparator and the sampling switches need hand attention. Only the digital
half (`verilog/rtl/dac_cdac_dig.v`) is a standard-cell macro. No OpenROAD P&R
near the analog core.

Target: `../saradc_auto/gen/spec/examples/sar8_sky130.json` - 8 bit,
differential, 1.8 V, 1 MS/s, bottom-plate sampling, moscap backend.

## Topology

```
                    VCM (sample) / floating (convert)
                              │
             ┌────────────────┴────────────────┐
   VREFH ─┬──┤TG├── bit 7 ... bit 0 ── 2^i unit caps each ── dummy ──┐
          │  └───┴──────────────────────────────────────────────────────┘
   VREFL ─┴──┤TG├── ...
```

* One side is 2^N unit capacitors; bit `i` owns `2^i` of them, plus one fixed
  dummy unit so the top-plate total is exactly 2^N units. Two TGs per bit
  switch that bit's bottom plate between VREFH and VREFL.
* Differential = two such arrays with complementary codes. The top plates are
  the comparator inputs and are never switched.
* The unit cap is a sky130 MOSCAP (NMOS + PMOS, `d=s=b` on the bottom plate,
  gate on the top plate), Wn 1.4 / Wp 2.8 / L 0.15 um, 0.63 um^2.
* The dummy's bottom plate is tied to VCM, which is the flat-band minimum of
  the C(V) curve (dC/dV = 0), so the dummy is a first-order constant reference
  rather than another bias-dependent capacitor.

## The model is a 2-D charge state function, not `C_u x code`

A MOSCAP is a 3-terminal device: the well is fixed, so the top-plate charge is
a function of *both* plates, Q(vg, vb).  A 1-D C(Vg-Vb) table is not enough
for a bottom-plate array, where the top plate moves during conversion.

Two measurements on the flattened sky130 tt deck:

* `c_ff_vs_vdiff` - the small-signal C with the gate held at Vcm and the
  bottom swept (the budget view).  The unit moves 2.673 fF at 0 V to 4.411 fF
  at -0.9 V and 3.541 fF at +0.9 V.
* `cgg_ff_vs_vg_vb`, `cgb_ff_vs_vg_vb` - the full 19x19 small-signal matrix
  over vg, vb = 0..1.8 V (`measure_c2.py`): Cgg = dQg/dVg at fixed Vb and
  Cgb = dQg/dVb at fixed Vg.

The state function is built along one path (the .ac matrix is symmetric but
not exactly integrable - BSIM4 charge non-conservation):

```
Q(vg,vb) = int_0^vg Cgg(u,vb) du + int_0^vb Cgb(0,w) dw
```

Each 1-D integral is checked against a device transient ramp to <0.01 fC, and
the device charge is verified to be path independent (two ramp paths agree to
0.001 fC): `./xcheck_mos.py --ramps`.  Sampling and conversion then solve

```
sum_k Q(Vtop, Vbot_k) = sum_k Q(Vcm, Vin)                 charge conservation
```

by Newton on the top plate (`gen_cdac.py`).  `xcheck_mos.py` builds the
device-level equivalent (2^N unit MOSCAPs + ideal bottom-plate switches, top
plate sampled at Vcm then floated) and compares the final top voltage with the
model at the same code.

`--cap const` is the control: with a flat cap and no mismatch the transfer
must be exactly linear, and it is (0.000 LSB).

## Results (10 mismatch seeds, Pelgrom at the backend's own A_C)

| backend | C_unit | DNL (LSB) | INL (LSB) | fs_max |
|---|---|---|---|---|
| const (control, no mismatch) | 2.673 fF | 0.000 | 0.000 | 48 MS/s |
| MIM, A_C 0.3 %*um | 8.0 fF | -0.043 .. +0.057 | 0.037 | 17 MS/s |
| moscap, A_C 0.234 %*um | 2.673 fF | -0.185 .. +0.244 | **+/-5.86** | 48 MS/s |

**The 8-bit limit is the moscap's bias dependence, not mismatch.** Mismatch
alone is 0.04-0.06 LSB; the 2-D charge curve is worth 5.86 LSB of bow
(+5.21 at code 32, +5.60 at 64, +3.32 at 96, 0 at both ends), and it is a
deterministic function of the code, so averaging does not remove it. DNL
stays monotonic but exceeds the 0.5 LSB target at the major carries.

The same bias dependence also compresses the transfer: the differential span
is **1.558 V for a 1.8 V reference** (0.78 V per side), i.e. the moscap array
delivers only ~43 % of the nominal full scale.  The device-level cross-check
below confirms this independently (8-bit array: code 0 -> 0.516 V, code 255
-> 1.293 V on one side, i.e. 0.777 V/side), so it is the device, not the
model.

The MIM row is a **flat-cap design that passes**, but its 8 fF/unit is the
reference profile's assumption (2 fF/um^2, A_C 0.3 %*um), not a sky130
measurement, and it costs 3x the sampling capacitance. The honest conclusion
for an 8-bit full-scale moscap CDAC is: either build it from a flat cap, or
restrict the array's voltage excursion / add capacitor calibration. The
regression gates the flat-cap design and records the moscap result as a study
(`./measure.py --cap moscap --expect study`), it does not slip it through.

Budget at the nominal unit (constant-C view, moscap):

| term | value |
|---|---|
| C_total (one side, 256 units) | 684 fF |
| kT/C, differential | 110 uV rms = 0.016 LSB (nominal 7.03 mV LSB) |
| comparator (StrongArm, measured) | 500 uV rms = 0.071 LSB (nominal) |
| settling per bit | 1.66 ns |
| sample | 6.6 ns |
| convert | 20.7 ns -> 48 MS/s |
| target | 1 MS/s |

## Device cross-check (the model vs the full MOS circuit)

`xcheck_mos.py` builds the device-level array (2^N unit MOSCAPs, ideal
bottom-plate switches, the top plate sampled at Vcm and then floated) and
compares the final top-plate voltage with the model at the same code:

```
./xcheck_mos.py --ramps                          # table + path independence
./xcheck_mos.py --bits 4 --codes 0,1,8,15        # ~2 min/code
./xcheck_mos.py --bits 8 --codes 0,1,64,128,192,255
```

* `--ramps`: every 1-D charge integral matches the device ramp to
  **0.006 fC** and the two integration paths agree to **0.0008 fC**, i.e. the
  device charge is a state function and the 2-D tables reproduce it.
* 4-bit array: worst |model - device| = **1.7 mV = 0.015 LSB** over codes
  0/1/8/15 (the 1-D model was 4.2 LSB off, which is why it was replaced).
* 8-bit array (255 units + dummy): worst |model - device| = **1.41 mV =
  0.20 LSB** over codes 0/1/64/128/192/255 (nominal 7.03 mV LSB).  The
  residual is a smooth function of code (+0.19 at 0, -0.16 at 255), i.e. the
  table's 0.1 V grid and the bilinear interpolation, not a model-form error.

The remaining mismatch is the table's 0.1 V grid, not a model-form error.

## Digital half

`verilog/rtl/dac_cdac_dig.v`, `dac_cdac_dig_tb.v` (2082 checks, 258 break
cycles, lint clean). The FSM is sample -> break -> drive and
drive -> break -> sample, and every code change goes through a break cycle:

* `b & bb == 0` in every state - VREFH and VREFL are never shorted through a
  bit node while a switch moves;
* `smp_o` (sample switch) and `pre` (top-plate reset) are released before any
  bit switch closes;
* the analog gates only ever see `code_q`, latched while sampling and on each
  accepted `stb`, never the asynchronous code bus.

## Files and how to run

```
./run.sh                 unit C(V) + control + MIM design + moscap study
./run.sh unit            device bench, must reproduce cdac.yaml to <2 %
./run.sh control         constant-C array == exact
./run.sh mim             flat-cap 8-bit design, gated on the SAR spec
./run.sh moscap          measured array, recorded study

./measure_c2.py --write  re-measure Cgg/Cgb(Vg,Vb) into cdac.yaml (~5 min)
./xcheck_mos.py --ramps  validate Q(vg,vb) against device charge ramps
./xcheck_mos.py --bits 4 --codes 0,1,8,15   full MOS array vs model

../../run-analog.sh cdac sky130 [prelayout|gds|drc|all]
```

`deck_sky130.py` builds the flattened tt deck (1.95 MB) from the PDK corner
tree; sky130 1.8 V devices are subcircuits, so they are instantiated with
`X`, not `M`. The deck's undefined `*_diff` mismatch parameters are declared
zero once, which is what makes the corner tree usable from ngspice.

## Array layout and signoff

`gen_gds.py` builds one side of the DAC: 255 switched unit capacitors plus one
VCM-referenced dummy, i.e. exactly 2^8 units in a fully populated 16x16 grid
(90.23 x 90.26 um). The grid is the common-centroid plan, not decoration:

```
row  0..3  bit 7     row  8  bit3 | bit2 | bit1 | bit0 | dummy
row  4..5  bit 6     row  9  bit 5
row  6     bit 5     row 10..11 bit 6
row  7     bit 4     row 12..15 bit 7
```

Every bit block is a mirror pair of rows about the centre, so its capacitor
centroid is the array centre in both axes. Bottom plates use met1 row straps
plus one met2 bus per bit in the left margin; row 8 holds four bits on one
row, so it leaves on met3 channels in the bottom margin (met2 already carries
the top-plate bars across every row). The top plate is a met2 bar per row
joined by a right-margin bus; the dummy's bottom plate goes to a separate
met1 VCM bus.

`signoff.py` is the fail-closed gate and `run-analog.sh cdac sky130
gds|drc|all` drives it:

| gate | result |
|---|---|
| DRC (`sky130A_mr.drc`, 0.30.12, feol+beol) | 0 items |
| LVS (weights from the extracted netlist) | 256 units: B0..B7 = 1/2/4/8/16/32/64/128, VCM = 1; all ten ports |
| PEX (hierarchical, `cthresh 0`) | `.subckt CDAC_ARRAY` + 256 `CDAC_CAP` instances, 13910 C entries, 0.95 MB |

LVS is a count of unit-cap instances per bit net, not a netgen device compare:
a 256-instance capacitor array has no unique device-level answer, so the
netlist's own weights are the contract, and `WANT` in `signoff.py` is written
independently of the `ROW_BIT`/`ROW8` tables in `gen_gds.py`.

Two sky130/Magic details that silently broke the first extraction:

* the magic tech declares `squares-grid 40 200 200` for via2, so a 150 nm via2
  is **dropped by the reader**; via2 must be 200 nm and met3 must enclose it by
  >= 65 nm (m3.4), with met3 >= 360 nm wide (m3.1) and >= 300 nm spaced
  (m3.2). All of those are DRC rules, so the geometry uses them directly.
* `sky130A.magicrc` falls back to a hardcoded `~/.ciel/.../build/<hash>` path
  when `PDK_ROOT` is unset in the environment; magic then loads no technology
  and exits 0 with no netlist. `signoff.py` sets `PDK_ROOT` explicitly.

PEX is evidence, not a ratio claim: Magic extracts geometric capacitance and
does not model the MOS channel, so per-bit capacitance against the nominal
2.673 fF/unit would have a made-up denominator. It is run with
`ext2spice hierarchy on` because the flat form has no `.subckt` at all and
keeps each capacitor's port nets under hierarchical alias names; the
hierarchical deck states the array's ten ports and its 256 instances
outright. Each bit net's geometric capacitance is reported under
`steps.pex.net_cap_ff` in `build/signoff.json` (B0..B7 12-67 fF, VSH 89 fF);
cross-cell coupling is attributed to alias names, so those are a floor.

Still open, and not claimed: the differential wrapper (two mirrored arrays
driven with complementary codes), the comparator and TG bias (class C hand
work), and the 256-code post-layout transient sweep. The next pass is a
`.control` loop of `alter`/`op` over the extracted netlist.
