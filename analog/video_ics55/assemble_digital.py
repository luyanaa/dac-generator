#!/usr/bin/env python3
"""Assemble the ics55 digital macro under the analog row.

The analog leaf (`analog/video_ics55/gen_gds.py`) puts the 510 gate pads on
M2 at y=-18.2..-17.6, x=2.25+3.75*k.  The hardened digital macro
(`openlane/dac_video_dig_ics55`) has the 510 outputs on the same grid at
y=0..0.6.  Mirroring the digital macro about the x axis and translating it by
y=-17.6 makes both pad rectangles coincide exactly, so the two child cells
are physically connected at the shared pad row.

Usage:
    klayout -b -r assemble_digital.py -z
    (paths from env ANALOG_GDS / DIGITAL_GDS / OUT_GDS, or defaults)
"""

import os
import sys

import pya

HERE = os.path.dirname(os.path.abspath(__file__))
ANALOG = os.environ.get(
    "ANALOG_GDS", os.path.join(HERE, "build", "video_ics55_lvt.gds")
)
DIGITAL = os.environ.get(
    "DIGITAL_GDS",
    os.path.join(
        HERE,
        "..",
        "..",
        "openlane",
        "dac_video_dig_ics55",
        "runs",
        "dac_video_ics55",
        "final",
        "gds",
        "dac_video_dig.gds",
    ),
)
OUT = os.environ.get(
    "OUT_GDS", os.path.join(HERE, "build", "video_ics55_chip.gds")
)

N_CELLS = int(os.environ.get("N_CELLS", "255"))
PAD_PITCH = 3.75
PAD_X0 = 2.25
PAD_W = 0.6
# Digital pad row y=0..0.6; analog pad row y=-18.2..-17.6.
DIGITAL_DY = -17.6

L_M2 = (82, 1)


def main():
    analog = pya.Layout()
    analog.read(ANALOG)
    digital = pya.Layout()
    digital.read(DIGITAL)

    ana_top = analog.top_cell()
    dig_top = digital.top_cell()

    top = pya.Layout()
    top.dbu = analog.dbu
    chip = top.create_cell("dac_video_chip")

    # Analog row stays at the origin.
    ana_idx = top.add_cell(ana_top.name)
    top.cell(ana_idx).copy_tree(ana_top)
    chip.insert(pya.CellInstArray(ana_idx, pya.Trans()))

    # Digital macro: mirror about x, then translate to share the pad row.
    dig_idx = top.add_cell(dig_top.name)
    top.cell(dig_idx).copy_tree(dig_top)
    dy = int(round(DIGITAL_DY / top.dbu))
    trans = pya.Trans(0, True, 0, dy)
    chip.insert(pya.CellInstArray(dig_idx, trans))

    # Verify all 510 pads coincide: intersection of the analog M2 pad and the
    # transformed digital M2 pad must be the full 0.6 x 0.6 pad.
    ana_m2 = pya.Region(ana_top.begin_shapes_rec(analog.find_layer(*L_M2)))
    dig_m2 = pya.Region(dig_top.begin_shapes_rec(digital.find_layer(*L_M2)))
    dig_m2.transform(trans)
    want = (PAD_W / top.dbu) ** 2
    bad = []
    areas = []
    for j in range(2 * N_CELLS):
        x = PAD_X0 + PAD_PITCH * j
        pad = pya.Region(
            pya.Box(
                int(round((x - PAD_W / 2) / top.dbu)),
                int(round(-18.2 / top.dbu)),
                int(round((x + PAD_W / 2) / top.dbu)),
                int(round(-17.6 / top.dbu)),
            )
        )
        a = (ana_m2 & pad).area()
        d = (dig_m2 & pad).area()
        inter = ((ana_m2 & pad) & (dig_m2 & pad)).area()
        areas.append(inter)
        if abs(a - want) > 1 or abs(d - want) > 1 or abs(inter - want) > 1:
            bad.append((j, x, a, d, inter))

    top.write(OUT)
    print(f"wrote {OUT}")
    print(
        f"analog={ANALOG} digital={DIGITAL} top={chip.name} "
        f"bbox={chip.bbox()}"
    )
    print(
        f"pads checked={2 * N_CELLS} min_overlap={min(areas):.1f} "
        f"bad={len(bad)}"
    )
    for j, x, a, d, inter in bad[:10]:
        print(f"  BAD pad {j} x={x:.3f} ana={a:.1f} dig={d:.1f} inter={inter:.1f}")
    if bad:
        sys.exit(1)


if __name__ == "__main__":
    main()
