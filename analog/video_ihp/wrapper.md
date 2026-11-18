# IHP sg13g2 video DAC wrapper and bias

Status 2026-11-18.  The wrapper is the 1.2 V leaf-level interface around the
assembled row + digital macro.  It is a **probe/port wrapper**, not a
chip-level ESD pad ring: the user project wrapper (or the test board) supplies
the external 470 pF / 100 pF decoupling and the 37.5 ohm output load.

## Ports (21)

| side | ports |
|---|---|
| analog row | `vdd`, `vss`, `vbp`, `vcp`, `iout`, `idump` |
| digital macro | `dvdd`, `dvss`, `clk`, `code[0..7]`, `stb`, `rst_n`, `valid`, `ready` |
| internal | the 510 `dout`/`dout_n` are already abutted to the row's `d_`/`db_` Metal2 pads |

`vdd/vss` and `dvdd/dvss` are kept as separate 1.2 V domains; tie them at the
board if a single rail is used.  `vbp`/`vcp` are brought out for the external
decoupling and for bias observation.

## Bias: 1.66 kohm from vcp to vss

The row's `iref` pin is a current **sink** from `vcp` to ground.  The
diode-connected replica self-biases at `vcp = 26.6 mV`, so a `rppd` resistor
from `vcp` to `vss` of **1660 ohm** (6.38 squares at W=1 um) sinks
**16.09 uA/cell** without a current mirror.  The resistor is small
(~6.4 um^2); it can be placed in the wrapper or on the board.  A vdd-to-vcp
resistor would be wrong (it sources current into the diode).

`wrapper_bias.py` runs the extracted row (`build/pex.spice`) with the resistor
and the 470/100 pF caps:

| case | result |
|---|---|
| DC, code 255, R=1660 | **4.1031 mA** total, **16.091 uA/cell**, `vcp 26.62 mV`, `vbp 631.53 mV`, `iout 153.27 mV` |
| carry 127 -> 128, 40 ns | **0.030 LSB**, `vbp` drift **-0.024 mV**, `vcp` drift **-0.052 mV** |

The earlier ideal 16.032 uA source gave 4.0866 mA and 0.029 LSB; the resistor
is 0.37 % high at 1.2 V, well inside the row's 2 % DC gate.  The resistor
tolerance (rppd process) is the dominant bias spread and can be trimmed by
changing the 6.38 squares or by an external resistor.

External components:

- `Cvcp = 470 pF` from `vcp` to `vss` (P5 full-scale study: 470 pF gives
  0.457 LSB; 330 pF gives 0.549 LSB);
- `Cvbp = 100 pF` from `vbp` to `vss`;
- `Rl = 37.5 ohm`, `Cl = 2 pF` on `iout`;
- `iref`/`vcp`/`vbp`/`iout`/`idump` are probe-accessible.

## Wrapper layout

`openlane/dac_video_dig/wrapper_connect.py` builds
`build/dac_video_wrapper.gds` from the hierarchical `dac_video_ihp` and
`dac_video_dig` cells:

- the row's six rails get same-layer stubs at x=-3..-1 and labels on their
  own label layers;
- the digital `clk/code/stb/rst_n/valid/ready` Metal2 pins get 0.6 um stubs
  down to y=-112 with labels;
- the digital `VDD`/`VSS` TopMetal1 pins (LEF rectangles at x 18.26..20.46 /
  24.46..26.66) get TopMetal1 extensions to y=-20 and `dvdd`/`dvss` labels;
- the 510 Metal2 pad islands are re-checked: **510 distinct islands, 0 bad**.

Result: `dac_video_wrapper` bbox -3.0,-112.0 .. 1918.5,12.0 um, 21 ports,
510 islands.  The wrapper DRC/LVS are in `build/wrapper_drc.lyrdb` and
`build/wrapper_lvs_k/`.

## What is still external

- the 1.66 kohm resistor (on-chip `rppd` or external),
- 470 pF / 100 pF decoupling,
- 37.5 ohm / 2 pF output load,
- ESD/probe pads and the board-level supply tie.

These are deliberately outside the leaf; the row and digital macro are
verified with them.
