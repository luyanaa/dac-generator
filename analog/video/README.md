# Video-rate binary current-steering DAC leaf

Fifth analog leaf (roadmap P5). Class **C**: the 255-unit cell array, its
binary switch banks and the output stage are hand layout; only the digital
half (`verilog/rtl/dac_video_dig.v`) is a standard-cell macro. No OpenROAD P&R
near the analog core.

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
P3 measured constants), endpoint fit. All numbers are pre-layout.

| bench | DNL (LSB) | INL (LSB) |
|---|---|---|
| ideal, zero mismatch (bench check) | 0.000 | 0.000 |
| binary decode, 1.8 %/cell, seed 0 | -0.176 .. +0.176 | -0.199 .. +0.199 |
| unary decode, same cells, seed 0 | -0.052 .. +0.065 | -0.142 .. +0.097 |
| binary, 20 seeds (worst) | **0.680** | 0.442 |
| unary, 20 seeds (worst) | 0.066 | 0.487 |

**Binary decoding costs DNL at the carries, not INL.** Over 20 mismatch seeds
the binary array exceeds the 0.5 LSB DNL target in 5 seeds (worst 0.680); the
same 255 cells with a thermometer decoder never exceed 0.13. INL is the same
in both, as it must be: it is the accumulated cell mismatch, not the decode.
So at 8 bit a pure binary decoder is a *cheap* decoder, not a linear one -
either calibrate/trim the MSB bank or take P3's 4+4 + DEM.

**The output impedance still matters at 37.5 ohm.** A passive 37.5 ohm load
turns the 1.67 kohm array ro (425 kohm per cell / 255) into a code-dependent
gain: INL +1.517 LSB, a fail. Endpoint calibration removes the constant part
but not the code dependence. The leaf therefore requires a transimpedance
(virtual-ground) I-V or a regulated cascode raising the *unit* cell ro to
about 1.3 Mohm; the 37.5 ohm passive case is kept in the regression as the
negative result.

**The binary carry glitch is the timing item.** One code step, each bit slice
delayed by k x 25 ps, 20 ps edges, 37.5 ohm || 2 pF:

| step | bit skew | glitch outside the envelope | settle to 0.5 LSB |
|---|---|---|---|
| 127 -> 128 | 0 ps | 0.0 LSB | 260 ps |
| 127 -> 128 | 25 ps | **50.8 LSB** | 735 ps |
| 63 -> 64 | 25 ps | 25.1 LSB | 661 ps |
| 255 -> 0 | 25 ps | 0.0 LSB (falling only) | 833 ps |

The glitch is large but short: 0.83 ns worst, 2 % of the 40 ns period. It is
not a linearity error if nothing samples inside it, so the digital half turns
it into a contract - `ready` stays low for a settle window after every launch
and `stb` is ignored meanwhile. The remaining requirement is layout: the eight
banks must be launched with matched clock/data delay, because the model's
25 ps is already 51 LSB at mid-code.

Speed budget at 25 MS/s:

| term | value |
|---|---|
| array settling (worst, 25 ps skew) | 0.83 ns |
| period at 25 MS/s | 40 ns |
| margin | 48x |
| digital guard (`SETTLE_CYCLES` = 4 at 100 MHz) | 40 ns |

The array is not the speed limit; the output driver and the clock/data skew
are.

## Digital half

`verilog/rtl/dac_video_dig.v`, `dac_video_dig_tb.v` (9148 checks, lint
clean). One register drives all eight switch banks, so the logic adds no
inter-bit skew; `valid` is a one-cycle launch pulse and `ready` enforces the
settling window (`SETTLE_CYCLES`, default 4) during which `stb` is ignored.
`dout` only ever changes on an accepted launch.

## Files and how to run

```
./run.sh                 ideal + binary + unary + passive load + tran + study
./run.sh ideal           zero mismatch, the bench must be exactly linear
./run.sh dc              binary decode, 1.8 %/cell
./run.sh unary           same cells, thermometer decode (control)
./run.sh riv             binary into the real 37.5 ohm load (negative result)
./run.sh tran            carries at 0 and 25 ps bit skew
./run.sh study           20-seed binary-vs-unary distribution

../../run-analog.sh video gf180 [prelayout|gds|drc|all]
```

`run-analog.sh video gf180 gds` refuses with exit 2: this is class C, there
is no array generator, and pretending otherwise would be worse than
refusing. The deck is behavioural on purpose - it models the decode and the
carry timing, while the cell current and ro come from the P3 device bench and
are copied into `video.yaml` with provenance.

Still open, and not claimed: any layout, DRC/LVS/PEX, the output stage, and a
post-layout rerun of the carry transients with extracted bit-slice skew.
