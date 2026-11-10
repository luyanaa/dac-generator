# Video-rate binary current-steering DAC leaf

Fifth analog leaf (roadmap P5). The 255-unit cell array is a **reusable layout
generator** (`gen_gds.py`) with a fail-closed signoff; the digital half
(`verilog/rtl/dac_video_dig.v`) is a standard-cell macro, and the wrapper that
abuts the two, the output pad/ESD and the cable driver are class C hand
layout. No OpenROAD P&R near the analog core.

Named target: **8 bit, 25 MS/s (40 ns), single-ended video output**. This is
the first leaf with a speed target rather than a resolution one; the point is
to answer whether a plain binary decoder is viable at 8 bit/25 MS/s when the
weights are made of *parallel unit cells* rather than scaled devices.

## Topology

```
  code[7:0] -> one register -> 8 binary switch banks
                                1 + 2 + 4 + ... + 128 identical unit cells
                                        |
                                        +-- out -- I-V -- cable driver -- 75 ohm
```

* 255 identical unit cells, 16 uA each (measured P3 cell: cascoded PMOS
  mirror, W/L 8/1 + 8/0.5 um, gf180 tt 25 C), full scale 4.08 mA.
* Weights are parallel copies of the same cell, not scaled devices. A bit-7
  bank is 128 unit cells in parallel, so its relative mismatch is
  sigma_unit/sqrt(128), not sigma_unit.
* No DEM and no segmentation: that is P3's answer, not this leaf's. Here the
  decoder is the cheapest possible (one bit per bank) and the question is
  what that costs.
* 37.5 ohm at the DAC (75 ohm line, double terminated), 153 mV full scale;
  the cable driver supplies the 1 Vpp gain.

## Results

Model: 255 ideal current cells with a per-cell gain error and finite ro (the
P3 measured constants), endpoint fit. All numbers below are **pre-layout**;
the extracted DC transfer is in *Layout* below (it is exact by construction
there, because all 255 cells are drawn identically - its job is the operating
point, and it earned that job).

| bench | DNL (LSB) | INL (LSB) |
|---|---|---|
| ideal, zero mismatch (bench check) | 0.000 | 0.000 |
| binary decode, 1.8 %/cell, seed 0 | -0.176 .. +0.176 | -0.199 .. +0.199 |
| binary, 37.5 ohm passive load | -0.176 .. +0.176 | -0.198 .. +0.200 |
| unary decode, same cells, seed 0 | -0.052 .. +0.065 | -0.142 .. +0.097 |
| binary, 20 seeds (worst) | **0.680** | 0.442 |
| unary, 20 seeds (worst) | 0.066 | 0.487 |

**Binary decoding costs DNL at the carries, not INL.** Over 20 mismatch seeds
the binary array exceeds the 0.5 LSB DNL target in 5 seeds (worst 0.680); the
same 255 cells with a thermometer decoder never exceed 0.13. INL is the same
in both, as it must be: it is the accumulated cell mismatch, not the decode.
So at 8 bit a pure binary decoder is a *cheap* decoder, not a linear one -
either calibrate/trim the MSB bank or take P3's 4+4 + DEM.

**The load is not the limit; the decoder is.** The cascoded P3 cell measures
425 Mohm, not the 425 kohm an earlier kOhm/MOhm printout slip carried into
this leaf (see `../csteer/README.md`). Each active cell gives up `Vout/ro` to
its own ro, so into 37.5 ohm the array loses 2.2e-5 of its current at full
scale: a 0.006 LSB gain error whose code dependence is second order, i.e.
0.001 LSB of INL with perfect cells and 0.200 LSB with 1.8 %/cell mismatch -
the same as the virtual-ground run (0.199). The regression sweeps
37.5 / 100 / 300 / 550 ohm, the last being the 2.24 V compliance edge of a
3.3 V supply at 4.08 mA, and all four sit within 0.02 LSB of each other. ro
would cost 1 LSB at `R ~ ro_unit/255` = 1.7 Mohm, which needs 7 kV at full
scale, so no transimpedance stage is required: a resistor into the cable
driver is enough.

**The binary carry glitch is the timing item in the behavioural model.** It is
superseded by *Dynamic settling* below, which runs the extracted netlist. One
code step, each bit slice delayed by k x 25 ps, 20 ps edges, 37.5 ohm || 2 pF:

| step | bit skew | glitch outside the envelope | settle to 0.5 LSB |
|---|---|---|---|
| 127 -> 128 | 0 ps | 0.0 LSB | 262 ps |
| 127 -> 128 | 25 ps | **51.4 LSB** | 740 ps |
| 63 -> 64 | 25 ps | 25.3 LSB | 663 ps |
| 255 -> 0 | 25 ps | 0.0 LSB (falling only) | 834 ps |

The model says the glitch is large but short: 0.83 ns worst, 2 % of the 40 ns
period, so the digital half turns it into a contract - `ready` stays low for a
settle window after every launch and `stb` is ignored meanwhile. Extraction
takes that back: the real glitch is 103 LSB and the bias tail is still moving
at 40 ns, so a `ready` window inside the period cannot rescue a carry. The
model's other requirement stands: the eight banks must be launched with
matched clock/data delay, because 25 ps of slice skew is already 51 LSB
mid-code.

Speed budget at 25 MS/s:

| term | value |
|---|---|
| array settling (worst, 25 ps skew) | 0.83 ns |
| period at 25 MS/s | 40 ns |
| margin | 48x |
| digital guard (`SETTLE_CYCLES` = 4 at 100 MHz) | 40 ns |

In this model the array is not the speed limit; the extracted run below shows
the bias network is, and that the output driver and clock/data skew are not
reachable until it is fixed.

## Digital half

`verilog/rtl/dac_video_dig.v`, `dac_video_dig_tb.v` (9148 checks, lint
clean). One register drives all 255 switch lines, so the logic adds no
inter-bit skew; `valid` is a one-cycle launch pulse and `ready` enforces the
settling window (`SETTLE_CYCLES`, default 4) during which `stb` is ignored.
`dout` only ever changes on an accepted launch.

`dout` is **one bit per physical cell**, not per code bit: the analog array is
255 identical cells and each exposes exactly one switch gate, so the weight is
the number of cells on a net. Cell j belongs to the smallest k with
j < 2^(k+1) - 1 (bit 0 -> cell 0; bit 1 -> 1..2; ... bit 7 -> 127..254), which
the RTL expands in a generate loop and the testbench re-expands independently.

## Layout

`gen_gds.py` emits `build/video.gds` (KLayout + the PDK pfet PCell; no
transistor geometry is drawn by hand):

* 768 pfet = 255 x (8/1 mirror + 8/0.5 cascode + 0.5/0.28 series supply
  switch) + a replica *cell* (the same three devices, diode connected). All
  255 cells are *identical*: the 1/2/4/.../128 weight is the digital fanout,
  so there is no per-cell width table to get wrong (P3's mistake).
* the switch sits between vdd and the mirror, gate = the cell's only pin, so
  an off cell is a real zero: no dump bus, no ground rail in the array.
* the replica bias repeats the cell's switch, on a static 0 V gate (`vgnd`).
  That is not decoration: the next section's post-layout run is what found
  that a bias branch without it is ~50 % off.
* one M2 pad per cell in cell order on an exact 7.5 um row at the bottom edge,
  on a grid the hardened digital macro can abut; `vgnd` is a separate M2 pad
  on the bias side, so it never lands under the digital macro.
* vdd is an M3 plane over the devices and iout an M3 bus under them (M3 is
  0.01 Ohm/sq against 0.09 for M1/M2; a 1.9 mm M1 bar would be hundreds of
  ohms). vbp is an M2 bar, vcp a poly bar.

`signoff.py` is the fail-closed entry point and gates, on the drawn file:

| stage | result |
|---|---|
| drc | Magic `drc count total` = 0 items at 2, 8 and 255 cells |
| lvs | 768 devices, 771 nets: 255 identical cells, a 3-device replica cell, 5 rails (vdd/vbp/vcp/iout/vgnd); each cell re-derived from its pad tag (pad -> switch gate, drain -> mirror source, mirror drain -> cascode source -> iout), and the replica's mirror source must be its own switch drain |
| pins | 260 labelled ports; 255 m2 pads on the 7.5 um grid (`pinplan.py` reads the GDS back) |
| pex | 768 instances, 4609 C entries, 198.2 kB: vdd 490 fF, vbp 311 fF, vcp 358 fF, iout 296 fF, 0.69 fF per pad |
| postlayout | 256-code DC transfer on the extracted netlist, virtual ground and 37.5 ohm: 4.080 mA full scale, 16.000 uA/cell, DNL/INL 0.000 LSB, 0 bad steps |
| mismatch | `run_mismatch_pex.py`: PDK area law drawn per extracted device, 16 samples; cell spread 0.720 % (law 0.727 %), fixed DNL 0.035..0.174 LSB, INL 0.028..0.124 LSB, 0 non-monotonic |
| tran | **fails, and that is the result** | `run_transient_pex.py`: carry transient on the PEX netlist with its capacitance; binary 127->128 settles to 118.503 LSB at 40 ns (**-9.497 LSB**), bias +31.8 mV (`vbp`) / +46.1 mV (`vcp`). A thermometer one-cell step passes (-0.432 LSB, 18.3 ns) but a thermometer full-scale step is worse (-173.3 LSB, +313 mV), and binary with an ideal bias passes (24.4 ns): the bias network is the limit, not the decoder |

The same pins stage estimates the rails from the *drawn* metal: vdd 2.4 ohm ->
1.2 mV at full code, i.e. 1.2 % of gain (2*drop/vov), which endpoint
calibration absorbs because the drop scales with the code; iout 10.7 ohm ->
21.8 mV between the farthest cell and the pad, which costs nothing in gain
(KCL still delivers every cell's current) and 3e-6 LSB/cell through ro. vbp
and vcp carry gates only, so their 311/358 fF matter for bias settling, not
IR. `--selftest` proves the gates reject 17 mutations, including a narrowed
vdd plane and a bias branch with the series switch shorted out.

### The series switch is part of the operating point

The first post-layout run measured **8.07 uA per cell, not 16 uA** (-49.5 %),
and it was right to: the cell's switch drops I*Ron inside the mirror's source,
which degenerates the mirror and costs 0.075 V of Vsg at an overdrive of only
0.23 V. A bias branch without that switch sets `vbp` for an undegenerated
8/1 and every cell then runs half current. Fixing it by adding the same switch
to the replica makes the drop common mode, so the unit current *is* the
reference current to first order - independent of Ron, corner and temperature -
and the measured 16.000 uA at `vbp` 1.951 V / `vcp` 0.505 V confirms it.

Two side effects are worth recording rather than hiding:

* the degeneration *improves* matching - it scales the cell's sensitivity to
  its mirror by gm/(1+gm*Ron) = 0.44, measured below as 0.253 %/mV instead of
  0.575 %/mV, and the cell lands at 0.72 % rather than the 1.8 % the
  pre-layout study assumed (that study stays conservative);
* the gain is now sensitive to the digital macro's *low* level: 0.1 V of
  low-level error moves a cell 1.3 %, i.e. 0.013 LSB. Per-cell spread at that
  level is negligible; a common shift is a gain term calibration already
  absorbs.

`run_postlayout.py --selftest` re-runs the deck with the replica switch
shorted out and requires the bench to reject it (8.074 uA, -49.5 %), so the
measurement cannot silently lose the mechanism it was built to check.

### Matching: the PDK's own law, on the extracted cell

The extracted transfer is exact by construction (255 identical cells), so the
leaf's linearity was still the pre-layout Pelgrom assumption: A_VT = 10 mV*um,
3.5 mV for the 8/1 mirror, 1.8 %/cell. `run_mismatch_pex.py` replaces that with
the PDK's law, drawn per *extracted device* (`delvto`/`mulu0` from
`par_vth`/`par_k` in `pfet_03v3_dss`; the wrapper itself is not used, since it
adds diffusion resistors the extraction already has and would draw once per
shared subckt).

| device | W/L (um) | sigma_Vth | sigma_beta | cell dI/I, Vth | cell dI/I, beta |
|---|---|---|---|---|---|
| mirror | 8/1 | 1.79 mV | 0.076 % | 0.253 %/mV | 0.449 %/% |
| cascode | 8/0.5 | 2.80 mV | 0.119 % | 0.0007 %/mV | 0.001 %/% |
| switch | 0.5/0.28 | 16.9 mV | 0.717 % | 0.0266 %/mV | 0.478 %/% |

The three sensitivities are *probed on the extracted cell* (2 mV of `delvto`
and 1 % of `mulu0` on each device in turn), not borrowed from the device
bench, because the cell's series switch degenerates its mirror. In quadrature
that predicts **0.727 %/cell**, dominated by mirror V_th (0.454 %), switch V_th
(0.449 %) and switch beta (0.345 %) - the 0.5/0.28 switch's 16.9 mV of V_th is
as large a matching term as the 8/1 mirror's 1.79 mV, which is the price of
putting the switch in series with the mirror's source.

Sixteen samples measure **0.720 %** (0.677..0.804), i.e. 1 % from the law.
The 256-code transfer reconstructed from those cell currents (exact
superposition, endpoint fit as in the bench) gives fixed DNL 0.035..0.174 LSB
and INL 0.028..0.124 LSB, 16/16 monotonic. Binary decode
therefore inherits 0.174 LSB of DNL at the PDK law, not the 0.680 LSB the
20-seed pre-layout study predicted at 1.8 %/cell: that study's sigma was 2.5x
pessimistic, and its 5/20 seeds over 0.5 LSB DNL do not happen here.

Gates: the zero-draw reconstruction must reproduce the measured bench transfer
(0.0004 LSB), the measured spread must land within 20 % of the law, and every
sample must meet 0.5 LSB DNL / 1.0 LSB INL and stay monotonic.
`--selftest` rejects a single draw shared by all devices (spread 0.0000 %),
per-device draws at half the law (0.345 %) and draws applied only to the
mirrors (0.489 %). 16 samples take ~16 min (one 255-point selector sweep per
sample, ~1 min); `--samples` changes the count.

### Dynamic settling: the switch in the mirror's source

The pre-layout carry study modelled each cell as an ideal current source and
held the bias at an ideal voltage. Both assumptions flatter the design, and the
extracted cell breaks both. The series switch sits in the *mirror's source*, so
switching a cell moves that source between 2.563 V (off) and 3.149 V (on) and
swings the cascode source by ~1.4 V; `vbp`/`vcp` carry the gate capacitance of
all 255 mirrors/cascodes plus 311/358 fF of extracted metal (7-10 pF on `vbp`);
and the replica driving them is *one* cell, 1/gm ~ 6-7 kOhm. That is a
50-80 ns bias pole (the measured tail is ~75 ns), longer than the 40 ns
sample period.

`run_transient_pex.py` (the `tran` stage) runs the PEX netlist *with its
capacitance* through the carries - 255 PWL pads with the yaml's 20 ps edges and
25 ps bit skew, into `r_load || c_load_pf` - and compares the value 40 ns after
the edge with the loaded DC transfer. (The PEX top subckt leaves the device
bodies on a local `VSUBS` net: fine for LVS, floating for simulation, so the
bench promotes it to a port and ties it to vdd. The patched netlist is a build
product.)

| case (20 ps edge, 25 ps skew) | settled @41 ns | error | settle to 0.5 LSB | glitch | dvbp | dvcp |
|---|---|---|---|---|---|---|
| binary 127 -> 128 | 118.503 LSB | **-9.497** | never | 103.1 LSB | +31.8 mV | +46.1 mV |
| binary 128 -> 127 | 118.410 LSB | **-8.590** | never | 98.7 LSB | +29.1 mV | +42.4 mV |
| binary 63 -> 64 | 61.560 LSB | **-2.440** | never | 48.8 LSB | +16.7 mV | +24.3 mV |
| binary 127 -> 128, bias forced | 128.266 LSB | +0.266 | 24.4 ns | 99.9 LSB | - | - |
| thermo 127 -> 128 | 127.568 LSB | -0.432 | 18.3 ns | 0.6 LSB | +1.4 mV | +1.9 mV |
| thermo 0 -> 255 | 81.721 LSB | **-173.279** | never | 80.2 LSB | +313.0 mV | +430.7 mV |
| thermo 0 -> 255, bias forced | 255.000 LSB | +0.000 | 3.0 ns | 78.8 LSB | - | - |

Binary at 25 MS/s **fails**, by an order of magnitude: 9.5 LSB low 40 ns after
the carry, and the output never enters the 0.5 LSB window. The error is a bias
tail, not a numerical spike - 2 ps and 20 ps timesteps agree to 0.007 LSB - and
it is not the cell: with `vbp`/`vcp` forced the carry settles in 24.4 ns and a
full-scale step in 3.0 ns, so every step size closes on the cell and output
path and the bias network's pole (50-80 ns) is the whole deficit.

Decode alone does not fix it, and the worst case is not the carry. A
thermometer full-scale step (0 -> 255, every cell turning on at once) is
**worse** than the binary 127 -> 128 carry even though the same 255 gates
switch: 81.7 LSB against a target of 255 (-173.3 LSB), `vbp` +313 mV against
+31.8 mV. The direction matters - the carry has 127 cells falling and 128
rising, a full-scale step has all 255 rising - so decode cannot be used to
dodge the problem. Thermometer decode buys DNL (0.680 -> 0.066 LSB at the
pre-layout sigma; at the PDK law binary is already 0.174) and one-cell
carries, but it does not make the array usable at 25 MS/s: the bias network
has to be strengthened either way.

The obvious fix - a proportionally larger replica - was sized on this same
extraction (a prediction: the macro was not regenerated), by scaling the
replica's PEX subckts and the reference current: at
8x (64/1 + 64/0.5 + 4/0.28 at 128 uA, the same current density, so the array
cells stay at 16 uA) the carry still misses at -1.13 LSB and a full-scale step
at -63 LSB, and the full-scale disturbance shrinks much more slowly than 1/M,
so the M that would close it is not credible. Scaling a single device past 8x
also hits the PDK's binned models, which stop at W = 100.01 um: a 16x replica
(128 um) silently simulated at twice the current with `vcp` negative - a trap
worth remembering, since it is a wrong answer, not an error.

What the array actually needs is a stiff bias pin: ~2.5 pC has to be recovered
into 8 pF to 1.6 mV in 39 ns, i.e. an output impedance of ~900 Ohm or less.
That is a small class-C buffer (source follower or one-stage amp) on `vbp` and
`vcp` - the same class as the wrapper and the output driver, not something the
array macro can generate. Until it exists, the macro is signed off on DC,
matching, DRC/LVS/PEX and pins, and the carry is open.

Gates: the settled value must be within 0.5 LSB of the loaded DC transfer at
41 ns (40 ns after the edge) and `vbp`/`vcp` within 2 mV of their DC values
(0.253 %/mV on `vbp` is ~0.32 LSB/mV at code 128, so 2 mV is the same window
seen from the cause). `--selftest` proves the gate is not vacuous: the same
carry with an ideal bias passes (128.266 LSB) and a wrong target is rejected
(-4.734 LSB). `./signoff.py --stage tran` therefore exits **1** on this leaf;
`run-analog.sh video gf180 tran` propagates that code and reports nothing it
did not measure.

## Files and how to run

```
./run.sh                 ideal + binary + unary + passive load + tran + study
./run.sh ideal           zero mismatch, the bench must be exactly linear
./run.sh dc              binary decode, 1.8 %/cell
./run.sh unary           same cells, thermometer decode (control)
./run.sh riv             binary into 37.5/100/300/550 ohm loads (all must pass)
./run.sh tran            carries at 0 and 25 ps bit skew
./run.sh study           20-seed binary-vs-unary distribution

./signoff.py             build + drc + lvs + pins + pex, gate on all four
./signoff.py --stage lvs
./signoff.py --stage postlayout   # extracted 256-code DC transfer
./signoff.py --selftest  17 mutations the gates must reject

./run_postlayout.py      virtual ground + 37.5 ohm load (add --riv 0)
./run_postlayout.py --selftest    the un-degenerated bias must be rejected

./run_mismatch_pex.py    mismatch MC on the extracted array (16 x 255-point decks)
./run_mismatch_pex.py --samples 32
./run_mismatch_pex.py --selftest  shared / half-sigma / mirror-only draws rejected

./run_transient_pex.py   carry transient, extracted netlist + capacitance
./run_transient_pex.py --decode thermo --from 127 --to 128   one cell per step
./run_transient_pex.py --stiff-bias --from 127 --to 128      the cell alone
./run_transient_pex.py --selftest  ideal bias passes, wrong target rejected

../../run-analog.sh video gf180 [prelayout|gds|drc|lvs|pex|pins|postlayout|mm|tran|all]
```

The pre-layout deck is behavioural on purpose - it models the decode and the
carry timing, while the cell current and ro come from the P3 device bench and
are copied into `video.yaml` with provenance.

Still open, and not claimed: the hardened digital macro (only the RTL exists
here), the wrapper/pin script that abuts it, and the output pad/ESD/cable
driver. The extracted DC sweep is nominal-only: the netlist carries no metal
resistance (Magic extracts capacitance only), so the vdd-drop term stays the
analytic estimate in `signoff.py`, and the DNL/INL it reports are exact by
construction - all 255 cells are drawn identically. What that sweep *is* good
for showed up immediately: it measured the array's unit current and found the
missing replica switch.

The `tran` stage was added last and it *fails*: the 25 MS/s carry does not
settle because the one-cell replica cannot drive a 7-10 pF bias node inside
40 ns (see *Dynamic settling*). That is the open item on this leaf, with the
fix sized there; until it lands, the leaf is signed off as "array operating
point and linearity closed, dynamic carry open".
