# FPGA synthesis / place-and-route

Smoke-test the digital DAC RTL with the OSS CAD Suite (`yosys` + `nextpnr`),
independently of the ASIC/LibreLane flow. No board or pin constraints are
used, so `nextpnr` places the I/O automatically.

## Run

```sh
cd fpga
make                  # audiodac on iCE40 + ECP5, pwmdac/dac_wrap on ECP5
make audiodac-ecp5-bit
make clean
```

`OSS_CAD_SUITE` defaults to `/opt/oss-cad-suite`; override it on the command
line if the toolchain lives elsewhere. `FREQ` (ECP5) defaults to 20 MHz to
match the 50 ns ASIC SDC; `FREQ_ICE` defaults to 18 MHz (see below).

## Results (yosys 0.70, nextpnr)

| top | device | LUT / LC | FF | RAM | I/O | Fmax |
|---|---|---|---|---|---|---|
| `audiodac` (ΔΣ) | iCE40 UP5K sg48 | 760 / 5280 LC | 120 | 1 | 39 / 39 | 18.1 MHz |
| `audiodac` (ΔΣ) | ECP5 25k CABGA256 | 726 / 24288 | 120 | 1 × DP16KD | 39 / 197 | 52.2 MHz |
| `pwmdac` (PWM) | ECP5 25k CABGA256 | 209 / 24288 | 79 | 0 | 41 / 197 | 145 MHz |
| `dac_wrap` (ΔΣ) | ECP5 25k CABGA256 | 806 / 24288 | 120 | 1 × DP16KD | 55 / 197 | 54.1 MHz |

- `audiodac` uses exactly the 39 user I/O of the UP5K sg48 package. The
  PWM backend needs 41 and `dac_wrap` exposes the union of both backends
  (55), so those are ECP5-only unless the test ports are trimmed.
- On ECP5 the critical path is the delta-sigma adder chain
  (`g_dsm.dac.dsmod0.mod2_out`), not the FIFO.
- `pwmdac` maps its 32×12 FIFO to distributed RAM (`TRELLIS_DPR16X4`), not
  a block RAM, on ECP5.
- The 20 MHz target is comfortable on ECP5; the UP5K build closes at
  ~18 MHz (the corrected sine LUT costs ~160 extra LUTs versus the
  pre-fix build, which no longer met 20 MHz).

## Sine LUT bug found by this flow

`audiodac_sinegen` built the sine table as a flat ascending vector
`[0:BW*2**LUT_SIZE-1]` and selected an entry with
`SINE_CONST[read_ptr*BW +: BW]`. Icarus and Yosys disagree on the bit order
of that construct: RTL simulation produces a sine, the yosys netlist
produces a different table. With `LUT_SIZE=7`, `SINE_AMPL=0.5` (the
`audiodac` configuration) the first eight post-synthesis samples were
`-9152, -13920, 5904, 27696, ...` instead of
`571, 1427, 2280, 3126, ...`.

The RTL now uses a 2-D array:

```verilog
wire signed [BW-1:0] SINE_CONST [0:(2**LUT_SIZE)-1];
assign data_o = tst_sinegen_en_i ? SINE_CONST[read_ptr] : 0;
```

Pre- and post-synthesis simulation now match for both `LUT_SIZE=6`
(default) and `LUT_SIZE=7` (`audiodac`).

**Impact on the ASIC runs:** all six delivered `audiodac` GDS were
synthesized before this fix, so their `tst_sinegen_en_i=1` test-sine mode is
wrong. The normal FIFO → delta-sigma audio path is unaffected. Re-run
`audiodac` on all PDKs when LibreLane is available; the mux structure and
the `read_ptr` fanout that the timing closure targets are unchanged.

## Bitstreams (Project Trellis)

The ECP5 `*-bit` targets pack the nextpnr config with Project Trellis
(`ecppack` 1.4) and the result can be read back with `ecpunpack`:

```sh
make audiodac-ecp5-bit
ecpunpack build/audiodac_ecp5.bit /tmp/audiodac.config
```

All three ECP5 bitstreams report `LFE5U-25F`, IDCODE `0x41111043`
(`LFE5U-25F-6CABGA256`). Change `ECP5_DEV` in the Makefile for a different
device/package. There are no pin constraints (LPF), so I/O placement is
automatic; add an LPF before programming a real board. `ecppack --svf`
can also emit an SVF for JTAG programming.

## Caveats

- This is a bring-up/resource smoke test, not signoff. The ASIC flow remains
  the reference for timing, area and power.
- `nextpnr` is run with `--pcf-allow-unconstrained` / `--lpf-allow-unconstrained`
  because there is no board definition in the repo.
