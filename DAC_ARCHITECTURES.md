# Reusable Digital-DAC Architectures

Two fully-digital DAC structures are implemented as interchangeable leaf
macros. Both take a parallel data word in and emit a 1-bit stream on a single
output pin; an external (or parasitic) RC low-pass filter reconstructs the
analog value. Because the modulator is pure RTL and the output stage is a
standard-cell buffer, both are process-portable — the only PDK-dependent part
is the output driver strength.

| Property | `pwmdac` (PWM-DAC) | `audiodac` (ΔΣ-DAC) |
|---|---|---|
| Bitstream | periodic PWM | noise-shaped 1-bit ΔΣ |
| ENOB @ same OSR | lower | higher (noise pushed OOB) |
| Analog spec | mid/low-freq, mid accuracy | higher-fidelity audio |
| Output stage | single GPIO | `ds_o`/`ds_n_o` complementary |
| Filter | 1st-order RC (fc ≪ f_pwm) | RC, higher tolerance |
| Complexity | minimal (counter+compare) | FIFO+modulator+testgen |

## Shared interface contract (the reusable seam)

Every DAC core conforms to one logical interface so a wrapper can select the
backend without rewiring:

```
input  [BW-1:0] data_i        // parallel sample (UINT, or INT + offset)
input           data_rdy_i    // host has valid data (FIFO-less: level load)
input           clk_i, rst_n_i
output wire     bitstream_o   // 1-bit stream -> GPIO -> RC filter
output wire     bitstream_n_o // complementary (optional, for differential RC)
config bus:     osr/mode/volume fields (from config_reg_mux)
```

`data_i` may come from `audiodac_fifo` (streaming, ISR-driven) or a config
register (`config_reg_mux` writes a static level). The generator keeps the
FIFO optional so a core can be instantiated stand-alone or register-fed.

## Architecture #1 — `pwmdac` (PWM + RC)

`verilog/rtl/pwmdac.v` + `pwmdac_pwm.v` (the modulator cell, reused by other
backends) + `pwmdac_level.v` (static-level register feed).

- **Modulator**: free-running `BW`-bit counter vs. `data_i` compare →
  `bitstream = (cnt < duty)`. Duty = `data_i/2^BW` exactly; zero dead logic.
- **Params**: `BW` (default 12 → up to ~0.024% LSB step), optional
  `DITHER`/`CENTER_ALIGNED` mode for lower EMI.
- **Refresh**: a new `data_i` is sampled once per PWM period (no tearing).
- **Output**: `bitstream_o` to one GPIO; `RC` off-die (or on-die parasitic
  R + pad-cap as the pole). `f_pwm = f_clk / 2^BW`.

## Architecture #2 — `audiodac` (ΔΣ → RC)

`verilog/rtl/audiodac.v` (existing) — 1st/2nd-order ΔΣ, `ds_o`/`ds_n_o`,
`osr_i` 32/64/128/256, `volume_i` (0 = mute, 15 = 0 dB, 6 dB steps),
FIFO + sine testgen. The modulator core is `audiodac_dsmod` (reused directly
by the generator when a ΔΣ backend is selected). The 1st-order path is an
exact full-scale accumulator; the 2nd-order path is a 1-bit CIFF loop that is
stable to about -1 dBFS (use 1st order for 0 dBFS). See
`docs/delta_sigma.md`.

## Generator integration

`run.sh` + `openlane/<macro>/config.librelane.json` harden each core as a leaf
macro on any supported PDK (sky130/gf180/ihp130/freepdk45/ics55/OR1 — the
updated OR1 deck has async-reset FFs). Both use `IO_PIN_V_LENGTH=2`/`IO_PIN_H_LENGTH=2`
(workaround for the LibreLane `io_place.py` dbu²→µm² bug) and
`RUN_REPAIR_DESIGN=false` + `MAX_FANOUT_CONSTRAINT=80` on high-fanout configs.

To swap backends in `user_project_wrapper`: the `ds_o`→`io_out[k]` assignment
is the single switch point; `pwmdac` and `audiodac` expose the same `ds_o`/
`ds_n_o` contract so either modulator can drive the pad.

## Analog topologies (research)

The generator currently emits digital backends only. A survey of 16
open-silicon analog DAC references and an integration plan are in
`docs/dac_topology_survey.md` and `docs/analog_dac_integration_plan.md`.
Summary: R-2R and resistor-string are generator-friendly (class B); CDAC and
current-steering need constrained device generation or manual layout;
binary-weighted resistor DACs do not scale past ~6 bit; PDKs without MIM or
precision resistors (`freepdk45`) stay digital-only.

Implemented so far, each as a device-level leaf with a separate standard-cell
digital half (`_dig`) abutted in the wrapper:

| leaf | dir | digital half | state |
|---|---|---|---|
| 8-bit R-2R | `analog/r2r/` | `dac_r2r_dig` | pre-layout + generator GDS; DRC/PEX blocked |
| 8-bit resistor string | `analog/string/` | `dac_string_dig` | pre-layout; layout class C |
| 8-bit unit current steering (4+4 + DWA) | `analog/csteer/` | `dac_csteer_dig` | pre-layout + DEM model; layout class C, active I-V required |
| 8-bit differential binary CDAC (SAR target) | `analog/cdac/` | `dac_cdac_dig` | model + digital half; layout class B/C, array pass open |

`./run-analog.sh <topology> <pdk> [prelayout\|gds\|drc\|all]` is the analog
entry point and fails closed: it refuses a stage it cannot actually run
instead of reporting a skipped view as a pass.
