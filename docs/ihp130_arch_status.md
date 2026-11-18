# IHP130 DAC architecture status

Status 2026-11-19.  Scope: the four `analog/` architecture generators
(R-2R, resistor-string, unit current-steering, binary CDAC) ported to
`ihp-sg13g2`.  The video dump-tail leaf is separate and already closed.

| architecture | IHP pre-layout | IHP analog layout | DRC | reference LVS | digital macro |
|---|---|---|---|---|---|
| **R-2R** | **PASS** | 25 `rppd` units + M1, `gen_gds_ihp.py` | **0** | **PASS** | `dac_r2r_dig` IHP hardened |
| **resistor string** | **PASS** (4 kOhm unit) | 255 `rppd` units + 256 taps | **0** | **PASS** | `dac_string_dig` IHP hardened |
| **current-steering** | **PASS** at 1.2 V (cell + DEM) | 30 cells + 60 switches, `gen_gds_ihp.py` | **0** | **PASS** | `dac_csteer_dig` IHP hardened |
| **binary CDAC** | **PASS** (flat `cmim`, measured moscap study) | 256 `cmim` units, `gen_gds_ihp.py` | **0** | **PASS** | `dac_cdac_dig` IHP hardened |

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
- Layout: `gen_gds_ihp.py` -> 15 unary (8/1+8/0.5) + 15 binary (0.5/1+0.5/0.5)
  cells, replica bias, 60 `sg13_lv_nmos` 4/0.28 switches, 60-pin 2.75 um M2
  row.  IHP DRC **0**; 122-device reference CDL LVS **PASS**.
  `ihp_signoff.py` -> `build/ihp_signoff.json` (`ok: true`).
- The IHP switch geometry is the rotated SG13_dev PCell (active Y..Y+0.96,
  source Y+0.07..0.23, drain Y+0.73..0.89); via1 0.19 um / Cnt 0.16 um; p-taps
  at y=10.55 and 13.8 clear the vcp poly rail.  The differential wrapper,
  1 kOhm termination and digital half remain class-C / separate, as in gf180.

## Binary CDAC (`analog/cdac`)

- `cdac.yaml` `ihp-sg13g2`: measured `sg13_moscap_p` 2x1 um 2-D C(V) table
  (0..1.2 V, 0.05 V grid, `measure_c2_ihp.py`) and the flat `cmim` signoff cap
  (7x7 um, **74.62 fF**).
- moscap is a **study**: 6.24 fF at 0 V to 24.9 fF at -1.1 V gives DNL
  -0.500..+1.391 and INL **-26.74..+26.84 LSB**, far outside 8 bit.
- Signoff backend `cmim`: 10 Pelgrom seeds (0.043 % per unit) give DNL
  **-0.0023..+0.0025**, INL **-0.0027..+0.0027 LSB**, fs_max **18.1 MS/s**
  (target 1 MS/s), `VERDICT_mim PASS`.
- Layout: 256 `cmim` PCells in bit blocks (128/64/32/16/8/4/2/1 + VCM),
  Metal5 block buses with nested L-routes to 9 pins, TopMetal1 VSH bar.
  DRC **0**; 9-entry reference CDL (`m=128..1`) LVS **PASS**.
- `ihp_signoff.py` -> `build/ihp_signoff.json` (`ok: true`).

The differential second side, TGs and comparator stay wrapper / class-C work,
exactly as in the sky130 leaf.

## Digital macros

All four standard-cell halves are now configured and hardened on
`pdk::ihp-sg13g2` (1.2 V `sg13g2_stdcell`, 0.44 um PDN rail, IHP antenna
diode), using the `dac_video_dig` IHP flow:

| macro | die (um) | KLayout DRC | route DRC | LVS | antenna | setup/hold WNS |
|---|---|---|---|---|---|---|
| `dac_r2r_dig` | 150x100 | 0 | 0 | 0 errors, 0 unmatched | 0 | pass |
| `dac_string_dig` | 120x80 | 0 | 0 | 0 errors, 0 unmatched | 0 | pass |
| `dac_csteer_dig` | 150x100 | 0 | 0 | 0 errors, 0 unmatched | 0 | pass |
| `dac_cdac_dig` | 90x80 | 0 | 0 | 0 errors, 0 unmatched | 0 | pass |

Runs: `openlane/<macro>/runs/ihp/final`; summary metrics in
`openlane/ihp_digital_status.json`.  The analog macros above are the
device-level counterparts; the wrapper still owns their assembly.
