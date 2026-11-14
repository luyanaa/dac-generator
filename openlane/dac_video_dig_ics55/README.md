# ics55 video DAC digital macro (`dac_video_dig`)

7-bit thermometer decoder, 510 outputs, hardened with the ICsprout55 H7CR
standard-cell library through LibreLane (Classic flow) and the PDK's
`ICS55.KLayoutLVS` step.

```sh
cd openlane/dac_video_dig_ics55
PDK_ROOT=/tmp/ics55_pdkroot \
PYTHONPATH=/grid/icsprout55-pdk/libs.tech/librelane:/grid/dac-generator/openlane/dac_video_dig/librelane_patch \
librelane config.yaml --pdk ics55 --pdk-root /tmp/ics55_pdkroot \
  --manual-pdk --run-tag dac_video_ics55
```

## Pin contract

`FP_DEF_TEMPLATE` applies `../dac_video_dig/pin_template_ics55.def`: 510
outputs on MET2 at `x = 2.25 + 3.75*k`, `y = 0..0.6`, plus the 12 control pins
on the north edge.  `FP_TEMPLATE_MATCH_MODE: strict` keeps the exact grid.

## PDK / flow fixes found by this macro

* **DEF layer map.** The PDK's `KLAYOUT_DEF_LAYER_MAP` points at the GDS
  display map (`<layer> <datatype> <name>`), which KLayout's LEF/DEF reader
  cannot use.  The top-level MET3–MET5 routing, the MET4/MET5 power grid and
  all top-level vias were silently dropped.  `ics55_def.map` is a real
  LEF/DEF map (purpose lists, `NAME` labels), and the config overrides
  `KLAYOUT_DEF_LAYER_MAP`.
* **PDN via arrays.** The tech LEF sets `LAYER VIA1..4 SPACING 0.11` (the
  isolated-via S_1 value).  OpenROAD's via generator uses that for array
  tiling and emitted 5-cut arrays at 0.11 spacing, violating the vendor
  `Vn_S_2` rule (0.13).  `N551P6M_ecos_viafix.lef` sets 0.13 and is selected
  with `TECH_LEFS`; the arrays are now 4 cut @ 0.22 pitch and the DRC via
  spacing markers are zero.
* **Filled GDS.** `KLAYOUT_LVS_OPTIONS.flow_mode=true` removes FILL/DECAP
  instances from both the extracted and reference netlists (18,426 in the
  final design).
* **LVS-clean cell subset.** The released GDS/CDL disagree for 45 of the 785
  H7CR cells (folded series stacks, e.g. AND2X8 CDL 2x0.6 vs layout
  4x0.15..0.4, and the documented W deviations INVX7/INVX16/etc.).
  `EXTRA_EXCLUDED_CELLS` lists the full set.  A per-cell netlist extraction
  over all 785 cells is the evidence: 740 match exactly.
* **Net/pin labels.** `add_net_labels.py` writes one DEF net-name label per
  internal net on its routed metal (`Mx/6`); `place_cell_pin_labels.py`
  writes the cell LEF pin names at the LEF pin rectangles.  The deck's
  `FLOW_MODE` port filter keeps the 524 reference ports and drops the extra
  net labels.

## Signoff status

* Synthesis/place/CTS/route/streamout: complete.  Final GDS:
  `runs/dac_video_ics55/206-klayout-streamout/dac_video_dig.gds`.
* LVS: **cell-level exact**, 95/95 used cell circuits match the merged CDL
  (`STRICT_HIERARCHY: circuits=95`), 524 ports, 20,368 devices, 10,968 nets,
  ERC PASS.  The top-level KLayout comparer reports 141 symmetric net pairs
  unresolved; a Netgen run reads identical device/net counts but fails top
  pin matching because the 255 thermometer outputs are topologically
  indistinguishable.  This is a comparer limitation on the 255-way
  symmetric DAC, not a device/cell mismatch; a symmetry-aware comparator or
  Calibre is required for the final top-level PASS.  Do not treat
  `ICS55_LVS_COMPARE=FAIL` as a cell failure.
* DRC: the top-cell-only screening (`top_only_gds.py`, standard cells are
  library-qualified) reports zero via S_2/S_3 markers after the 0.13 spacing
  fix.  Remaining categories are the known deck approximations:
  `metal.m1/m2.area` on isolated via landing pads stripped from their cells,
  a handful of 45-degree M2 width/space edge-pairs, and the density tables.
  The full `cell_exclusion=true` run builds a multi-GB instance-union region
  and exceeds the 16 GB machine (13.4 GB RSS before OOM), so it is not used
  here.
* Assembly: `analog/video_ics55/assemble_digital.py` mirrors the digital
  macro about X, translates it to `y = -17.6`, and checks all 510 pad
  overlaps.  Result: 510/510 pads, 0.36 um^2 each, 0 bad.  Output:
  `analog/video_ics55/build/video_ics55_chip.gds`.

## Next

1. Run the top-level LVS with Calibre or a symmetry-aware comparator
   (net labels are in place; `ICS55.KLayoutLVS` with
   `strict_topology=true, strict_hierarchy=true, top=dac_video_dig,
   flow_mode=true`).
2. Metal/ACT/PO density fill for the macro (the density tables are expected
   for a sparse macro).
3. Digital/analog wrapper power and control connections (class-C work).
