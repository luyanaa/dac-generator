# Video DAC digital macro (sky130) and its abutment to the analog row

Status 2026-11-12: **hardened with the 510 outputs on the exact analog pad
grid, and assembled over the analog row with 0 DRC and 0 shorts.**

## Pin template

The analog row has `d_<tag>` / `db_<tag>` pads on a 3.75 um grid at
`x = 2.25 + 7.5*k` / `6.0 + 7.5*k`, `y = -18.2 .. -17.8`.  The automatic pin
placer can only use the sky130 met2 track grid (0.46 um), so it lands on
3.68 um and drifts by up to ~19 um across the 1912.5 um row.

`gen_pin_template.py` writes a DEF template with the exact grid.  Two things
had to be fixed for `Odb.ApplyDEFTemplate` to use it:

1. **DEF pin geometry is relative to `PLACED`.**  The generator used to put
   the absolute `x` in both the `LAYER` rectangle and `PLACED`, so odb
   applied the placement twice (the template's `dout[0]` would have landed
   at 4.2 um instead of 2.25).  The rectangle is now centred on the origin
   (`-0.3..0.3`) and `PLACED` carries the absolute position; the `+ PORT`
   keyword is included.
2. **LibreLane 3.0.14 drops the string `design__die__bbox` metric** written
   by `apply_def_template.py`, then `Odb.ApplyDEFTemplate.run` indexes the
   missing key and raises `KeyError('design__die__bbox')` *after* the pins
   have been relocated.  `librelane_patch/sitecustomize.py` makes that area
   cross-check optional.  Run the flow with the patch on `PYTHONPATH`:

   ```sh
   PYTHONPATH=$PWD/openlane/dac_video_dig/librelane_patch \
   librelane openlane/dac_video_dig/config.librelane.json \
       --manual-pdk --pdk sky130A --pdk-root <sky130A-version-dir> \
       --run-tag sky130_pins
   ```

   `IO_PIN_ORDER_CFG` is kept as a fallback, but `FP_DEF_TEMPLATE` is
   authoritative in the config (`FP_TEMPLATE_MATCH_MODE: strict`).

## Hardened result (`runs/sky130_pins`)

| check | result |
|---|---|
| die / core | 1912.5 x 80 um / 1901.18 x 57.12 um |
| standard cells | 28442 instances (with tap/fill/antenna), 18042 um^2 stdcell area |
| setup / hold (worst corner) | **+0.237 ns / +0.080 ns** |
| power | 2.66 mW |
| magic DRC / KLayout DRC | **0 / 0** |
| LVS | **0** errors, 0 unmatched devices/nets/pins |
| XOR | **0** |
| antenna | **0** violating nets/pins (51 diodes inserted) |
| detailed-route DRC | **0** |
| disconnected pins | **0** |
| 510 output pins | all on `x = 2.25/6.0 + 7.5*k`, 0.6 x 0.6 um met2, y = 0..0.6 |
| LEF | 1912.5 x 80 um, `PIN dout[0] RECT 1.950 0.000 2.550 0.600` |

The final DEF/LEF/GDS are in `runs/sky130_pins/final/`.

## Assembly

`assemble.py` places the digital macro **mirrored in Y below** the analog row
(the digital pins are on its bottom edge; unmirrored they would put the
80 um digital body on top of the analog row).  The mirrored pins span
`-18.3..-17.7`, overlapping the analog pads `-18.2..-17.8` by 0.4 um on the
same met2 layer.  The assembled die is 1912.5 x 106.2 um.

```
klayout -b -r openlane/dac_video_dig/assemble.py -z
```

Result:

```
assembled dac_video_top: 255 cells, 510 pads, bbox -1.650,-98.000 .. 1917.100,8.200 um
met2 merged regions: 4386; 510 pad islands: 510;
pad centres not on a merged met2 region or shorted: 0
```

The sky130 KLayout DRC on `build/dac_video_top.gds` is **0 items**.  The
analog row alone and the digital macro alone are also 0 items; the top-level
run confirms the abutment adds no violation.

A full-chip LVS/PEX still needs a top-level netlist and an RCX run; the two
blocks are signed off separately (digital macro LVS 0, analog row LVS 0) and
the 510 pad islands are checked individually, so the abutment itself is
verified but not the combined extracted netlist.

## IHP sg13g2 (`runs/ihp_pdn44`, 1.2 V)

The same RTL is hardened on `sg13g2_stdcell` with `RESOLUTION=8`,
`ENCODING=0`, die 1912.5 x 100 um, and `pin_template_ihp130.def` (523 pins,
510 `dout/dout_n` on the exact row grid, 13 control pins on the top edge).
The IHP section of `config.librelane.json` sets `VDD_NETS=[VDD]`,
`GND_NETS=[VSS]`, `RUN_CTS=true`, `PDN_RAIL_WIDTH=0.44`, and
`RUN_MAGIC_DRC=false` (Magic DRC OOM-kills this 1912x100 macro (11,370 instances, 1,203 stdcells);
the PDK KLayout deck is the golden check).  The sky130 `IO_PIN_ORDER_CFG`
and `FP_DEF_TEMPLATE` live in `pdk::sky130*` so they cannot override IHP.

Status of the final run:

| check | result |
|---|---|
| KLayout DRC | **0** |
| Netgen LVS | **0** device/net/pin/property differences |
| setup / hold | **+5.039 ns** (slow 1.08 V 125 C) / **+0.1226 ns** (fast 1.32 V -40 C) |
| power | **0.387 mW** |
| area | die 1912.5 x 100 um, core 129,330 um^2, 1,203 stdcells + 10,167 fill |
| 510 output pins | all on `x = 2.25/6.0 + 7.5*k`, y = 0..0.6, Metal2 |
| binary order | `dout[2^k-1+i] = code[k]`, matching the row's `b{k}_{i}` tag |
| antenna | 1 net: `clk` -> `clkbuf_0_clk/A`, Metal3, 228.29 vs 200 (1.14x) |

The 255 outputs are driven by **8 code registers** (one per bit) plus output
buffers: all cells in a binary group carry the same bit, so Yosys legally
shares the register.  The outputs still launch on one clock edge.

### IHP assembly

`assemble_ihp.py` places the digital macro mirrored in Y at `y0=-9.5` below
the analog row.  The digital pins span -10.1..-9.5 and overlap the analog
pads -10.0..-9.6 by 0.4 um on Metal2 (10/0):

```sh
cd openlane/dac_video_dig
DIG_GDS=runs/ihp_pdn44/final/gds/dac_video_dig.gds \
  /usr/bin/klayout -b -r assemble_ihp.py -z
```

Result: **510 distinct merged Metal2 islands**, 0 bad centres, bbox
-1.0,-109.8 .. 1918.5,12.0 um.  The PDK KLayout DRC on the assembled
`build/dac_video_top.gds` is **0 items**.
