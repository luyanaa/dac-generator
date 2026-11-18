# IHP130 DAC architecture status

Status 2026-11-19.  Scope: the four `analog/` architecture generators
(R-2R, resistor-string, unit current-steering, binary CDAC) ported to
`ihp-sg13g2`.  The video dump-tail leaf is separate and already closed.

| architecture | IHP pre-layout | IHP analog layout | DRC | reference LVS | digital macro |
|---|---|---|---|---|---|
| **R-2R** | **PASS** | 25 `rppd` units + M1, `gen_gds_ihp.py` | **0** | **PASS** | `dac_r2r_dig` still gf180 config |
| **resistor string** | **PASS** (4 kOhm unit) | 255 `rppd` units + 256 taps | **0** | **PASS** | `dac_string_dig` still gf180 config |
| **current-steering** | **PASS** at 1.2 V (cell + DEM) | not ported (gf180 PCell geometry) | — | — | `dac_csteer_dig` still gf180 config |
| **binary CDAC** | not started | not ported (sky130 moscap C(V) table) | — | — | `dac_cdac_dig` still sky130 config |

## R-2R (`analog/r2r`)

- `r2r.yaml` `ihp-sg13g2`: `sg13_lv` 1.2 V, `rppd` 260 ohm/sq, unit
  W=2/L=150 um (19.5 kOhm), trim 19.287 kOhm, drivers Wn=3/Wp=8 L=0.13.
- Pre-layout: DNL **-0.041..+0.004 LSB**, INL **-0.067..0.000**, monotonic,
  worst settling **723 ns** (0/1/127/128/255, 1 us/step).
- Layout: 25 `rppd` PCells + M1 straps, 50/50 terminals covered; DRC **0**.
- LVS: reference 16-resistor ladder (8 x 2R, 7 x 1R, 1 termination),
  **PASS, Netlists match**.
- `ihp_signoff.py` -> `build/ihp_signoff.json`.

## Resistor string (`analog/string`)

- `string.yaml` `ihp-sg13g2`: `sg13_lv` 1.2 V, `rppd` 260 ohm/sq, **4 kOhm**
  unit (W=2/L=30.769 um), TGs Wn=8/Wp=10 L=0.13.
- The 1 kOhm short `rppd` PCell has 0.001-grid pSD/polyres slivers and fails
  the PDK offgrid rule; the 4 kOhm option (already in the README) is DRC
  clean.  Pre-layout: DNL **-0.038..+0.008**, INL **-0.147..+0.129**,
  monotonic; worst settling **290 ns** with ideal 100 ohm switches.
- Layout: 255 `rppd` units + `t1..t254`, `vss`, `vref`, 256/256 terminals,
  DRC **0**.
- LVS: reference 255-resistor string, **PASS**.
- `ihp_signoff.py` -> `build/ihp_signoff.json`.

The TG tree and follower are class-C hand layout, exactly as in the gf180
leaf; the generated split is the matched resistor string.

## Current-steering (`analog/csteer`)

- `csteer.yaml` `ihp-sg13g2`: `sg13_lv` 1.2 V, unit 8/1 mirror + 8/0.5
  cascode, `vcp=0.10 V` (1.5 V was 3.3 V-only).
- Device bench `run_cell.py --pdk ihp-sg13g2`: **15.92 uA**, **ro 1.3 MOhm**,
  Vth sensitivity **-0.813 %/mV**.
- Ideal-cell/DEM pre-layout with the 1.8 % Pelgrom model: bench DNL
  **-0.890..+0.275**, INL **-0.483..+1.373**; DEM-mean DNL
  **-0.515..+0.275**, INL **-0.483..+0.483**, dem noise 391 mLSB rms.
- The 30-cell/60-switch **GDS** is still the gf180 `pfet` PCell generator;
  porting the M1/poly geometry and the 5.5 um analog pin row to the IHP
  `sg13_lv` PCells is the next step.  The switch drivers and differential
  wrapper were class-C in gf180 too.

## Binary CDAC (`analog/cdac`)

Not started on IHP.  The leaf's unit is a **sky130 MOSCAP** whose measured
`Cgg(Vg,Vb)` / `Cgb(Vg,Vb)` tables are in `cdac.yaml`; the model is a
2-D charge state function because the top plate floats.  An IHP port needs:

1. measure the IHP `moscap_n/p` (or `cmim`) C(V) tables at 1.2 V;
2. rebuild the unit capacitor and the 2x256 array with the IHP PCells;
3. port the SAR digital macro (`dac_cdac_dig`) to `sg13g2_stdcell`.

The existing generator (`gen_cdac.py`, `gen_gds.py`, `signoff.py`) is
sky130-specific at the device/C(V) level, so no IHP number is claimed.

## Digital macros

`openlane/dac_r2r_dig`, `dac_string_dig`, `dac_csteer_dig`, `dac_cdac_dig`
still have only their original PDK configs (`gf180mcu*` / `sky130*`), no
`pdk::ihp-sg13g2` and no `runs/`.  The IHP digital flow that already works is
`openlane/dac_video_dig` (`ihp_ant`); the four macros above still need their
IHP pin plan and hardening.
