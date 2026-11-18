# IHP sg13g2 leaf: full-chip LVS / PEX / RCX

Status 2026-11-19.  The "full chip" is the leaf:

```
dac_video_wrapper
├── dac_video_ihp   255 dump-tail cells + replica, 1022 devices
├── dac_video_dig   8-bit binary macro, 1,203 stdcells + fill
└── 510 Metal2 pad overlaps (0.4 um) + 21 port stubs
```

## Full-chip LVS

`fullchip_lvs.py` regenerates `build/dac_video_wrapper.gds` and runs Magic
hierarchical extraction; the top comparison sees the row and digital
block subcircuits and their 510-pad interconnect.
The reference is the row's 1022-device CDL in Magic's `s/g/d/b` X-device pin
order, the digital gate-level netlist (empty stdcell subckts, so the stdcells
are black boxes), and one top port `vdd`.

```
Netgen: top-level compare: 2 block instances / 530 nets
Final result: Circuits match uniquely.
```

- Row internals: `gen_cdl.py` + `run_lvs.py` COMPARE mode **PASS**
  ("Netlists match", 1022 devices / 516 ports).
- Digital internals: LibreLane Netgen LVS **PASS** (0 device/net/pin
  differences).
- Top-level: the 510 pad islands, the row rails (`vdd/vss/vbp/vcp/iout/
  idump`), the digital supplies (`dvdd`/`vss`) and the 13 control ports are
  connected and match (`fullchip_lvs.json`, `fullchip_lvs.rpt`).
- The report lists property errors in `dac_video_ihp` (W/L/area of the
  extracted row devices vs the X-device reference); the row topology is the
  independently-passing KLayout reference-CDL LVS.

## PEX / RCX

| block | extraction | devices | R | C | cap |
|---|---|---|---|---|---|
| assembled top | Magic hierarchical, C | 12,013 | 0 | 19,491 | 2.711 pF |
| analog row | Magic `extract do resistance`, RC | 1,022 | **4,456** | **10,077** | 2.849 pF |
| digital macro | OpenRCX SPEF | 1,207 cells | 1,214 nets R+C | 1,214 nets | 2.795 pF |
| top connections | 0.4 um Metal2 overlaps | 510 | 0 | 0 | 0 |

Full RC = row Magic RCX (R+C) + digital OpenRCX SPEF (R+C); the top PEX
supplies the full-chip capacitance.  The 510 top connections are same-layer
0.4 um overlaps, so there is no top-level wire to extract.  A top-level
`top_pex_rcx.spice` run with `extract do resistance` is also started from the
wrapper GDS; it is the same extraction with the assembled digital cell.

Files:

- `build/fullchip_lvs.json`, `build/fullchip_lvs.rpt`
- `build/fullchip_rcx.json`
- `build/top_pex.spice` (2.711 pF, 12,013 devices)
- `build/row_pex_rcx.spice` (4,456 R / 10,077 C)
- `openlane/dac_video_dig/runs/ihp_ant/final/spef/nom/dac_video_dig.nom.spef`
- `build/dac_video_wrapper.gds` (21 ports, 510 islands, DRC 0)
