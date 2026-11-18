# IHP sg13g2 video DAC: PPA and SFDR

Status 2026-11-18.  The analog row is the 1.2 V series-bias array
(`analog/video_ihp`, `iref=16.032 uA`, `Cvcp=470 pF`, `Cvbp=100 pF`); the
digital macro is the IHP `ihp_ant` run in `openlane/dac_video_dig`.

## Analog electrical PPA

| item | value |
|---|---|
| resolution / encoding | 8 bit, binary, 255 cells |
| update rate | 25 MS/s (40 ns) |
| LSB into 37.5 ohm | **0.601 mV** (16.032 uA) |
| full-scale current | **4.124 mA** |
| analog power, all cells on | **4.949 mW** at 1.2 V |
| analog power, 7-cycle sine average | **2.475 mW** |
| digital power | **0.3865 mW** (`ihp_ant` final metrics) |
| total power, full scale / sine average | **5.335 / 2.861 mW** |
| energy per full-scale sample | **213.4 pJ** |
| analog row area | 1918.5 x 26.6 = **51,032 um^2** |
| digital die area | 1912.5 x 100 = **191,250 um^2** |
| assembled bbox | 1918.5 x 121.8 = **233,673 um^2** |

The analog power uses the extracted row DC (4.0866 mA at 16.032 uA/cell) and
the full-scale sum from the 1.2 V mismatch transfer.  The digital power is
the `ihp_ant` LibreLane `power__total` (0.3865 mW at 1.2 V, 100 MHz).

## Static SFDR / SNDR / ENOB

The row settles in **2.3 ns** while the update period is **40 ns**
(`signoff.py --stage tran`: carry 0.029 LSB at 40 ns), so the spectrum is
dominated by the static transfer.  The 16-seed PSP103 mismatch one-hot data
(`build/mm_seed*.dat`, `signoff.py --stage mm`) is superposed into the
256-code binary transfer; a **256-sample, 7-cycle coherent sine** is evaluated
through the measured zero-mismatch and seed transfers and the FFT gives the
figures.  This is the same method as `video_ics55/static_sfdr.py`.

| transfer | SFDR | SNDR | ENOB |
|---|---|---|---|
| zero mismatch | **58.90 dB** | 49.35 dB | 7.90 bit |
| 16-seed mean | **58.80 dB** | 49.33 dB | 7.90 bit |
| worst seed (seed 0) | **58.39 dB** | 49.35 dB | 7.90 bit |
| measured DNL / INL (16 seeds) | **0.1467 / 0.0906 LSB** | | |

The dynamic carry (127 -> 128) is **0.029 LSB** at 40 ns, so it does not add
a code-dependent spur above the static floor.  The static result is reproduced
by `python3 static_sfdr.py` (`build/static_sfdr.json`); the full transistor
sine is not run because 256 samples x 40 ns is ~10 us and the 1022-device row
takes minutes per 40 ns carry.

## Full-chip

The assembled leaf (`dac_video_top`: row + digital macro, 510 merged pads) is
the full-chip DRC/LVS target.  Its SFDR is the row static SFDR above; the
digital part is a 25 MS/s binary code driver whose outputs settle with the
registered code.  A top-level SPEF/RCX and a combined LVS are tracked in
`docs/ihp130_video_closure_gap.md`.
