# Delta-sigma modulator (`audiodac_dsmod`)

The ΔΣ backend turns a stream of 16-bit unsigned samples into a 1-bit
bitstream whose **average duty equals `data_i / 2^16`** (0 % .. 100 %,
midscale = 50 %). Both modulator orders obey this same transfer; they differ
only in where the quantization noise is shaped.

The FIFO/audio path carries *signed* 16-bit samples (`0x0000` = silence,
`0x8000` = most negative). `audiodac.v` converts them to unsigned by adding
`0x8000` before the modulator, so a signed sample `s` produces a duty of
`(s + 32768) / 65536`.

## 1st order (exact, full scale)

```
{ds_o, accu1} <= data_scaled + accu1;   // carry = output bit
```

An unsigned accumulator; the carry is the output. Over any window of
`2^16` clocks the number of carries is exactly `data_scaled`, so the DC
transfer is exact at every code, including 0 and 0xFFFF. This path is
unchanged from upstream and is the 0 dBFS/full-scale mode.

## 2nd order (CIFF, 1-bit, full rate)

The previous implementation inherited the upstream 2-bit / `fs/4` stage,
which produced `(data/2^16 + 1)/4`, i.e. 25 %..50 % duty with a half-swing
and a +25 % offset. It has been replaced with a conventional single-bit
cascade-of-integrators feed-forward (CIFF) loop clocked at the full output
rate (`fs = OSR × sample_rate`), using signed fixed point in input LSBs:

```
x  = data_scaled - 2^15            // centred input
s1 = i1 + x
u  = s1 + i2
y  = (u >= 0)                       // 1-bit quantizer
fb = y ? +2^15 : -2^15
i1 <= sat(i1 + x - fb)
i2 <= sat(i2 + i1 - fb)
```

The input is fed forward to the quantizer, so the integrators only see the
quantization error and stay small. To keep the combinational loop short for
the FPGA build, both `±2^15` feedback sums are computed in parallel and only
the final mux depends on the quantizer decision. The integrators are clamped
to `±6·2^16`; the clamp is inactive for normal audio and only bounds the state
for overload and DC-rail inputs.

Measured with the exact integer model (`verilog/tb/dsmod_model.py`):

| input code | duty | ideal |
|---|---|---|
| 0x0000 | 0.000005 | 0.000000 |
| 0x0001 | 0.000020 | 0.000015 |
| 0x4000 | 0.250000 | 0.250000 |
| 0x8000 | 0.500000 | 0.500000 |
| 0xC000 | 0.750000 | 0.750000 |
| 0xFFFE | 0.999965 | 0.999969 |
| 0xFFFF | 0.999980 | 0.999985 |

The tiny deviation at the extreme codes is the clamp/settling of the loop at
the rails, not a gain or offset error.

### Headroom

The 2nd-order loop is stable up to about **-1 dBFS**. A 0 dBFS sine overloads
it and the in-band SNR collapses:

| OSR | amplitude | SNR | max state |
|---|---|---|---|
| 128 | -0.9 dBFS (0.45) | 90.3 dB | 3.31 FS |
| 128 | -6 dBFS (0.25) | 85.6 dB | 1.14 FS |
| 128 | -12 dBFS (0.125) | 80.0 dB | 1.00 FS |
| 256 | -0.9 dBFS (0.45) | 99.5 dB | 3.58 FS |
| 256 | -6 dBFS (0.25) | 96.7 dB | 1.14 FS |
| 256 | -12 dBFS (0.125) | 91.0 dB | 1.00 FS |

Above roughly 0.5 FS the loop rings and the SNR drops to ~50 dB. **Use the
1st-order mode for signals that must reach 0 dBFS**, or leave ~1 dB of
digital headroom when using the 2nd-order mode. This is a property of the
1-bit CIFF loop, not a bug.

## Volume control (`scale_i`)

Volume is applied in 6 dB steps around midscale so that changing the volume
does not move the DC operating point:

| `scale_i` | attenuation | result for the largest positive input |
|---|---|---|
| 15 | 0 dB | 0xFFFF |
| 14 | -6 dB | 0xBFFF |
| 13 | -12 dB | 0x9FFF |
| 7 | -48 dB | 0x807F |
| 1 | -84 dB | 0x8001 |
| 0 | mute | 0x8000 (midscale → 50 % duty) |

This matches the documented/upstream API (`0` = off, `15` = max). The previous
local code had the mapping reversed (`0` = max, `15` = off) while its comments
claimed the opposite; that mismatch is fixed.

## Verification

```
cd verilog/tb
make          # iverilog self-checking testbench
make lint     # Verilator lint of the audiodac top
```

`audiodac_tb.v` checks the observable contract: 1st/2nd-order DC transfer at
0/25/50/75/100 %, volume steps and mute, OSR fetch cadence (32/64/128/256),
FIFO handshake, the sine LUT, and complementary outputs. `dsmod_model.py`
reproduces the DC/volume/SNR numbers above with the exact integer arithmetic.

FPGA smoke test (`make -C fpga`): iCE40 UP5K closes at **14.7 MHz** (the
corrected CIFF loop is deeper than the old 2-bit stage; OSR=256 at 48 kHz
needs 12.288 MHz), ECP5 reaches ~46 MHz. These are bring-up numbers, not a
signoff flow.

## Caveat on ASIC data

`docs/characterization.md` and the PPA tables were generated **before** this
fix. `results/` and `openlane/*/runs/` are gitignored and currently absent, so
the post-fix sky130/gf180/ihp130/ics55/freepdk45 timing and area have not been
re-measured. The old runs showed ~39 MHz on sky130 at a 20 MHz clock target,
so the deeper 2nd-order loop has margin, but this should be confirmed by
re-running LibreLane.
