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
either calibrate/trim the MSB bank or take P3's 4+4 + DEM.  At the extracted
cell's own 1.00 %/cell the worst fixed DNL over 16 samples is 0.30 LSB (see
*Matching*), i.e. this leaf's 1.8 % assumption was the pessimistic corner and
binary decode does pass - with less margin than the pre-layout table suggests.

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

**The carry is the timing item, and the behavioural model got it wrong.** The
pre-layout deck (ideal current sources, stiff bias) put the 25 ps bit-skew
carry at 51.4 LSB with a 740 ps settle, which the digital half turned into a
`ready` window.  The extracted netlist said otherwise - the first macro's
carry never settled at 40 ns - and the fix was a cell change, not a decoder
change: see *Why the cell changed* and *Dynamic settling*.  The pre-layout
numbers below are kept only because they motivated the digital `ready`
contract; the signoff numbers are the extracted ones.

| step | bit skew | glitch outside the envelope | settle to 0.5 LSB (model) |
|---|---|---|---|
| 127 -> 128 | 0 ps | 0.0 LSB | 262 ps |
| 127 -> 128 | 25 ps | **51.4 LSB** | 740 ps |
| 63 -> 64 | 25 ps | 25.3 LSB | 663 ps |
| 255 -> 0 | 25 ps | 0.0 LSB (falling only) | 834 ps |

The model's one surviving requirement is layout-side: the eight banks must be
launched with matched clock/data delay, because 25 ps of slice skew is already
51 LSB mid-code in that model.

## Digital half

`verilog/rtl/dac_video_dig.v`, `dac_video_dig_tb.v` (9148 checks, lint
clean). One register drives all 255 switch lines, so the logic adds no
inter-bit skew; `valid` is a one-cycle launch pulse and `ready` enforces the
settling window (`SETTLE_CYCLES`, default 4) during which `stb` is ignored.
`dout` only ever changes on an accepted launch.

`dout` is **one bit per physical cell**, not per code bit: the analog array is
255 identical cells, so the weight is the number of cells on a net. Cell j
belongs to the smallest k with j < 2^(k+1) - 1 (bit 0 -> cell 0; bit 1 ->
1..2; ... bit 7 -> 127..254), which the RTL expands in a generate loop and the
testbench re-expands independently.

One change is **not yet in the RTL**: the dump-tail cell needs the
*complementary* pair (`d_<tag>` on iout, `db_<tag>` on idump), i.e. 510
outputs, where the current RTL drives 255 one-hot lines.  That is a class-C
follow-up like the wrapper; the analog macro already exposes both pads on the
3.75 um grid.

## Layout

`gen_gds.py` emits `build/video.gds` (KLayout + the PDK pfet/nfet PCells; no
transistor geometry is drawn by hand):

* 1022 devices = 255 x (8/1 mirror + 8/0.5 cascode + 2 x 4/0.28 NMOS) + a
  2-device replica.  All 255 cells are *identical*: the 1/2/4/.../128 weight is
  the digital fanout, so there is no per-cell width table to get wrong.
* the cell is a **dump-tail** current source: vdd -> mirror (gate `vbp`) ->
  cascode (gate `vcp`) -> the shared source of the NMOS pair; the pair's gates
  are the cell's two pads `d_<tag>` / `db_<tag>`, its drains `iout` / `idump`.
  The 16 uA tail flows at all times and is *steered*, so neither the mirror's
  Vgs nor its Vds moves with the code (see *Why the cell changed* below).
* the replica is the same mirror+cascode, diode-connected: 16 uA sinked at
  `vcp` sets the unit current.  No switch - this cell has no source drop to
  reproduce.
* two M2 pads per cell in cell order on an exact 3.75 um row, so a hardened
  digital macro with 510 outputs can abut; `vss` is an M1 rail (bulk ties only,
  no current) with its own M2 pad on the bias side.
* vdd is an M3 plane over the devices; iout and idump are M3 buses under them
  (M3 is 0.01 Ohm/sq against 0.09 for M1/M2).  vbp is an M2 bar, vcp a poly
  bar.  The cell is 21.7 um tall (y -11.6..10.1): the pair, the dump bus and
  the second pad row live below the current sources.

`signoff.py` is the fail-closed entry point and gates, on the drawn file:

| stage | result |
|---|---|
| drc | Magic `drc count total` = 0 items on the full 1022-device array |
| lvs | 1022 devices, 1026 nets: 255 identical 4-device cells + a 2-device replica, 6 rails (vdd/vss/vbp/vcp/iout/idump); each cell re-derived from its pad pair (`d_`/`db_` -> NMOS -> shared tail -> cascode -> mirror -> vdd), with negative checks for the old `vgnd`/`n_ref` and for a PMOS on a pad |
| pins | 516 labelled ports: 510 pads on the 3.75 um grid + 6 rails (`pinplan.py` reads the GDS back) |
| pex | 1022 instances, 7912 C entries, 321.4 kB: vdd 404 fF, vbp 307 fF, vcp 359 fF, iout 208 fF, idump 333 fF, vss 875 fF, 1.02 fF per pad |
| postlayout | 256-code DC transfer on the extracted netlist, virtual ground and 37.5 ohm: 4.080 mA full scale, 16.001 uA/cell, DNL/INL 0.000 LSB, 0 bad steps, `vbp` 2.170 V / `vcp` 0.782 V |
| mismatch | `run_mismatch_pex.py`: PDK area law drawn per extracted device, 16 samples; cell spread 1.00 % (law 1.004 %), fixed DNL 0.05..0.30 LSB, INL 0.05..0.20 LSB, 0 non-monotonic |
| tran | `run_transient_pex.py`: 127->128 **128.000 LSB (0.000), 2.30 ns**; full scale 0->255 **254.693 (-0.307), 2.72 ns**; vbp/vcp within 0.48 mV; with the wrapper's 100 pF on `vcp` |

The pins stage also estimates the rails from the *drawn* metal: vdd 2.4 ohm ->
1.2 mV at full code (1.2 % of gain, endpoint-calibrated), iout 10.7 ohm ->
21.8 mV one-ended (a compliance term: KCL still delivers every cell's current,
so it costs 0 LSB/cell through ro), idump the same bus class (it only shifts
the dump switch's source), and vbp/vcp/vss carry no DC current - their
307/359/875 fF matter for settling, not IR.  `--selftest` proves the gates
reject 12 LVS mutations (dropped/relabelled/re-drained devices, a broken bias
diode, the old PMOS-on-a-pad cell, an NMOS bulk off vss, ...), 5 pin-plan
mutations and a narrowed vdd plane.

### Why the cell changed: the first macro failed the carry

The first P5 cell put a 0.5/0.28 PMOS *in series with the mirror's source*
(between vdd and the source), which gave an off cell a true zero and no dump
bus.  Its DC and matching closed - 16.000 uA/cell, 0.720 %/cell, fixed DNL
0.174 LSB - and then the extracted carry transient failed by an order of
magnitude: 127->128 settled to 118.503 LSB (-9.497) at the 40 ns period and
never entered the 0.5 LSB window, with `vbp` +31.8 mV / `vcp` +46.1 mV.

The mechanism: switching a cell moved its mirror source between 2.563 V and
3.149 V (0.59 V) and its cascode source by ~1.4 V; the 255 gates load the bias
lines with 7-10 pF; the one-cell replica drives them at 1/gm ~ 6-7 kOhm - a
50-80 ns pole against a 40 ns period.  Three attempts, each measured on the
extracted netlist, were not enough:

| attempt | carry | full scale 0->255 |
|---|---|---|
| thermometer decode (one cell per step) | -0.43 LSB, 18.3 ns | **-173 LSB** (all 255 sources move together) |
| 8x scaled replica (64/1 + 64/0.5 + 4/0.28 at 128 uA) | -1.13 LSB | -63 LSB |
| switch moved to the mirror's drain (rewired PEX) | -2.30 LSB | +54 LSB |

With the bias forced, the same cell closed (carry 24.4 ns, full scale 3.0 ns),
so the bias network was the whole deficit - and the reason none of the three
works is that the 255 mirror gates' charge still has to change by ~10 fC per
cell whichever terminal the switch interrupts (Cgs x 0.59 V before, Cgd x
2.45 V after).  Only a cell whose mirror keeps *both* Vgs and Vds constant
avoids that charge, which means the tail must keep flowing and be steered.

What the change costs: 4 devices per cell (768 -> 1022), two pads instead of
one (510), a vss bulk rail, an idump bus, and 100 pF on `vcp` in the wrapper.
The cell's mismatch also got worse, 0.72 -> 1.00 %/cell: the series switch used
to degenerate the mirror (0.253 %/mV), and without it the mirror shows its full
0.558 %/mV.  Fixed DNL went 0.174 -> 0.30 LSB worst over 16 samples, still inside the
0.5 target.

### Matching: the PDK's own law, on the extracted cell

The extracted transfer is exact by construction (255 identical cells), so the
leaf's linearity comes from `run_mismatch_pex.py`: the PDK's Pelgrom law drawn
per *extracted device* (`delvto`/`mulu0` from `par_vth`/`par_k` of
`pfet_03v3_dss` and `nfet_03v3_dss`; the statistical subckts themselves are not
used, since they add diffusion resistors the extraction already has and would
draw once per shared subckt).

| device | W/L (um) | sigma_Vth | sigma_beta | cell dI/I, Vth | cell dI/I, beta |
|---|---|---|---|---|---|
| mirror | 8/1 | 1.79 mV | 0.076 % | 0.558 %/mV | 0.994 %/% |
| cascode | 8/0.5 | 2.80 mV | 0.119 % | 0.0016 %/mV | 0.0019 %/% |
| pair (each) | 4/0.28 | 6.92 mV | 0.679 % | 0.000 %/mV | 0.000 %/% |

The three sensitivities are *probed on the extracted cell* (2 mV of `delvto`
and 1 % of `mulu0` on each device in turn).  The pair's is exactly zero: it
sits in the drain path, so its Vth moves the tail node's voltage, not the
current.  The mirror alone sets the cell, and in quadrature that predicts
**1.003 %/cell**, dominated by its Vth (1.00 %) with 0.076 % from its beta.

Sixteen samples measure **1.00 %** (0.90..1.06), i.e. the law.  The 256-code
transfer reconstructed from those cell currents (exact superposition,
endpoint fit) gives fixed DNL 0.05..0.30 LSB and INL 0.05..0.20, 16/16
monotonic: binary decode inherits ~0.30 LSB of DNL, so the leaf's 0.5 LSB DNL
target still holds, with less margin than the series-switch cell had (0.174)
because the degeneration is gone.

Gates: the zero-draw reconstruction must reproduce the measured bench transfer
(0.0000 LSB), the measured spread must land within 20 % of the law, and every
sample must meet 0.5 LSB DNL / 1.0 LSB INL and stay monotonic.  `--selftest`
rejects a single draw shared by all devices (spread 0.0000 %), per-device draws
at half the law (0.50 %) and pair-only draws (0.00 % - the structural check
that the pair is not in the current path).  Sixteen samples take ~16 min (one
255-point selector sweep per sample); `--samples` changes the count.

### Dynamic settling: the dump tail

The extracted cell keeps 16 uA flowing at all times, so the code only changes
*which* NMOS in the pair conducts.  The mirror's Vgs and Vds are then
code-independent, and the bias lines see no charge: measured, `vbp` and `vcp`
move by 0.00 mV on the carry and <= 0.5 mV on the full-scale step.

`run_transient_pex.py` (the `tran` stage) runs the PEX netlist *with its
capacitance* through the carries - 510 PWL pads (`d_`/`db_` complementary) with
the yaml's 20 ps edges and 25 ps bit skew, into `r_load || c_load_pf` - and
compares the value 40 ns after the edge with the loaded DC transfer.

| case (20 ps edge, 25 ps skew) | settled @41 ns | error | settle to 0.5 LSB | bias at 41 ns |
|---|---|---|---|---|
| binary 127 -> 128 | 128.000 LSB | +0.000 | 2.30 ns | vbp +0.00 mV, vcp +0.00 mV |
| binary 128 -> 127 | 128.000 LSB | +0.000 | 2.31 ns | 0.00 mV |
| binary 63 -> 64 | 64.000 LSB | +0.000 | 2.31 ns | 0.00 mV |
| thermo 0 -> 255 | 254.693 LSB | -0.307 | 2.72 ns | vbp +0.23 mV, vcp +0.48 mV |

Two residuals are worth recording rather than hiding:

* the **cascode-gate kick**.  When the pair moves, the cascode's drain swings
  ~0.15 V and its Cgd kicks `vcp`; 5 mV there is 3.8 LSB at code 255.  The
  cell has no room for a 100 pF cap, so it is a *wrapper requirement*: the
  bench models it (`--vcp-cap-pf`, default 100) and without it the full-scale
  step lands at -4.3 LSB (device level).  With it, -0.31.
* the **switching spike**.  The pair's own charge into the 2 pF output is a
  ~340-450 LSB spike that decays in ~3 ns, present even with an ideal `vcp`
  and larger than the old cell's 103 LSB.  The 40 ns sample point is clear of
  it, so it is a glitch spec for the output filter, not a settling error.

Gates: the settled value must be within 0.5 LSB of the loaded DC transfer at
41 ns (40 ns after the edge) and `vbp`/`vcp` within 0.7 mV of their DC values
(the mirror's measured 0.558 %/mV is 0.71 LSB/mV at code 128, so 0.7 mV is the
same window seen from the cause; the measured worst is 0.48 mV).  `--selftest` proves the gate is not vacuous: the same
carry with an ideal bias passes and a wrong target is rejected.
`./signoff.py --stage tran` and `run-analog.sh video gf180 tran` now pass.

### Other PDKs: the same cell, sized per process

`pdk_cell.py` applies the cell to the other PDKs this repo has data for.  The
topology does not change - mirror + cascode + steering pair, the tail always
on - but the sizes do, because 16 uA needs a very different Vov per process:

| PDK | supply | devices | mirror | cascode | pair | vbp / vcp | carry | full scale |
|---|---|---|---|---|---|---|---|---|
| sky130 | 3.3 V | g5v0d10v5 | 8/0.5 | 8/0.5 | 8/0.5 | 2.192 / 0.843 V | +0.562 (fail) | +0.242 |
| ihp-sg13g2 | 1.8 V | lv (PSP103) | 8/1 | 8/0.5 | 4/0.28 | 1.232 / 0.627 V | +0.024 LSB | -0.412 LSB |
| icsprout55 | 1.2 V | nm1p2/pm1p2 | - | - | - | - | - | **blocked** |

* **ihp-sg13g2** (130 nm, PSP103 OSDI): the gf180 sizes fit unchanged - an 8/1
  PMOS needs only Vsg 0.57 V at 16 uA.  Carry **+0.024 LSB** at 2.57 ns with
  the bias flat; full-scale **-0.412 LSB** at 3.35 ns with 220 pF on `vcp`
  (100 pF gives -0.86, so this PDK wants more decoupling than gf180's 100 pF).
* **sky130**: the 1.8 V logic PMOS cannot stack two diodes at 16 uA inside
  1.8 V - measured, the replica's `vcp` is driven *negative* because the sink
  pulls harder than the stack can supply - so the cell moves to the 5 V
  thick-oxide devices at 3.3 V.  Their bins fix the geometry: `l=1.0` and
  `l=0.28` give "could not find a valid modelname", so all three devices are
  8/0.5.  The operating point then carries **16 uA/cell** (76.8 mV at code 128
  into 37.5 ohm) with vbp 2.192 / vcp 0.843 V and the tail at 4 mV; the carry
  and full-scale transients are the next run.  The 1.8 V variant also has a
  *startup* trap: the all-off solution is self-consistent (the pair's source
  floats to vdd and the pair is off), so the bench nodesets the tails - a real
  bias network would need the same.
* **icsprout55** (55 nm, 1.2 V): **blocked at the model level**.  The PDK's
  `.mdl` cards select their bin with `.param` expressions over the *instance*
  w/l (`wum = w*1e6`, `xbin = f(wum)`), which ngspice cannot evaluate
  (`Undefined parameter [w]` -> `could not find a valid modelname`), and the
  PDK's own readme says "for hspice only".  That is a model-porting job, not a
  sizing one.

Not claimed: layouts.  The macro, the DRC/LVS/PEX/pins stages and the bench
nets in this leaf stay gf180-only; the per-PDK numbers above are what a
generator for that PDK would be sized from.

### Layout closure per PDK: what the tooling actually gives us

`analog/video_sky130/gen_gds.py` is the first attempt at a sky130 macro (the
same 4-device cell, 510 met2 pads on a 3.75 um row, met3 vdd/iout/idump
planes, met1 vss rail), and it is where the closure stops:

* **sky130**.  The only in-repo device drawer is `pya_draw`
  (`/opt/OpenSERDES`), and it has no headless support for the devices this
  cell needs: its 5 V path raises `NameError: hvntm_layer` (the layer is
  missing from `layers_def.py`; sky130's `hvntm.drawing` is 125/20 and the
  generator patches it), and the drawn 5 V pfet puts HVI outside its own
  nwell (DRC `hvi.2a`).  The drawer is also *context-sensitive*: the same
  devices inside the CDAC array pass the sky130A_mr deck (0 items, 181 rule
  categories exercised), while isolated probes of them report 75-91 items
  (`licon.1`, `ct.1_b`, `ct.2`, `MR_licon.SP.1`) - so a sky130 cell must be
  iterated as a full-context layout, not assembled from isolated devices.
  `via.1a_b` also showed that sky130 vias are fixed 0.15 squares with 0.06
  enclosures, not the bars a gf180-style router draws.
* **ihp-sg13g2**.  The tooling is complete - KLayout `sg13g2_pycell_lib`,
  `tech/drc/run_drc.py`, `tech/lvs/run_lvs.py`, and a magic tech - but the
  repo has no ihp generator/drawer to start from: the cell geometry (device
  terminals, rails, 510 pads) has to be written and DRC'd from scratch.
* **icsprout55**.  The KLayout cell
  `libs.tech/klayout/pcells/ics55_mos_analog.py` says in its own header that
  its geometry is a "DRAWN-TEMPLATE ... NOT foundry DRC rules (no DRC
  released)", so a macro built on it would not be a DRC closure even if the
  deck (`ics55_drc.drc`) ran; the models are HSPICE-only as recorded above.

So the three layout closures are device-layout engineering tasks on top of
the sizing done here, not plumbing: each needs a DRC-clean device drawer (or
verified PDK pcells) and a full-context DRC iteration, then the LVS/PEX
contract.  The gf180 macro keeps the leaf's signoff; the per-PDK cell data
and the sky130 skeleton are what that work starts from.

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
./signoff.py --selftest  12 LVS + 5 pin + 1 rail mutations rejected

./run_postlayout.py      virtual ground + 37.5 ohm load (add --riv 0)
./run_postlayout.py --selftest    a bias mirror off vdd must be rejected

./run_mismatch_pex.py    mismatch MC on the extracted array (16 x 255-point decks)
./run_mismatch_pex.py --samples 32
./run_mismatch_pex.py --selftest  shared / half-sigma / pair-only draws rejected

./run_transient_pex.py   carry transient, extracted netlist + capacitance
./run_transient_pex.py --decode thermo --from 127 --to 128   one cell per step
./run_transient_pex.py --stiff-bias --from 127 --to 128      the cell alone
./run_transient_pex.py --decode thermo --from 0 --to 255     full scale
./run_transient_pex.py --selftest  ideal bias passes, wrong target rejected

../../run-analog.sh video gf180 [prelayout|gds|drc|lvs|pex|pins|postlayout|mm|tran|all]
```

The pre-layout deck is behavioural on purpose - it models the decode and the
carry timing, while the cell current and ro come from the P3 device bench and
are copied into `video.yaml` with provenance.  It describes the decode, not
this cell: the extracted stages above are the signoff.

Still open, and not claimed: the hardened digital macro (only the RTL exists
here, and it still drives 255 lines instead of the cell's 510), the
wrapper/pin script that abuts it, the output pad/ESD/cable driver, and the
100 pF `vcp` decoupling that the wrapper has to place (the `tran` stage models
it; without it the full-scale step lands at -4.3 LSB).  The extracted DC sweep
is nominal-only: the netlist carries no metal resistance (Magic extracts
capacitance only), so the vdd-drop term stays the analytic estimate in
`signoff.py`, and the DNL/INL it reports are exact by construction - all 255
cells are drawn identically.  What that sweep *is* good for showed up
immediately: it measured the array's unit current and found the missing
replica switch in the first cell.
