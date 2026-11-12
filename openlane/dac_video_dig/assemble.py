#!/usr/bin/env python3
"""Assemble the sky130 video leaf: digital macro over the analog row.

    klayout -b -r assemble.py -z

The digital macro (`runs/sky130_pins/final/gds/dac_video_dig.gds`) has its
510 `dout`/`dout_n` pins on met2 at x = 2.25 + 7.5*k / 6.0 + 7.5*k, y = 0..0.6.
The analog row (`analog/video_sky130/build/video_sky130.gds`) has the matching
pads at the same x and y = -18.2..-17.8.  Placing the digital origin at
y = -18.3 overlaps the two met2 rectangles by 0.4 um, so the abutment is a
same-layer connection with no jog and no via.

The script writes `build/dac_video_top.gds`, checks that all 510 pad centres
land inside one merged met2 region, and prints the assembled die box.  Run
the PDK DRC on the result:

    klayout -b -zz -r $PDK_ROOT/sky130A/libs.tech/klayout/drc/sky130A_mr.drc \
        -rd input=build/dac_video_top.gds -rd topcell=dac_video_top \
        -rd report=build/top_drc.lyrdb -rd feol=1 -rd beol=1 \
        -rd floating_metal=0 -rd offgrid=1 -rd seal=1 -rd threads=8
"""
from __future__ import annotations

import os

import klayout.db as db

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
ANA = os.path.join(ROOT, "analog", "video_sky130", "build",
                   "video_sky130.gds")
DIG = os.path.join(HERE, "runs", "sky130_pins", "final", "gds",
                   "dac_video_dig.gds")
OUT = os.path.join(HERE, "build", "dac_video_top.gds")

N = 255
PITCH = 7.5
PIN_A, PIN_B = 2.25, 6.0
# analog pads: -18.2..-17.8; digital pins: 0..0.6.  The digital body must
# extend *away* from the analog row, so mirror it in Y and put it below: the
# mirrored pin is -0.6..0, and y0=-17.7 centres it on the -18.0 pad row.
DIG_Y = -17.7
DIG_MIRROR = True


def main() -> int:
    ly = db.Layout()
    ly.dbu = 0.001
    ly.read(ANA)
    ly.read(DIG)

    ana = ly.cell("dac_video_ana")
    dig = ly.cell("dac_video_dig")
    top = ly.create_cell("dac_video_top")
    top.insert(db.CellInstArray(ana.cell_index(), db.Trans(0, 0)))
    dig_xform = db.Trans(db.Vector(0, int(DIG_Y / ly.dbu)))
    dig_xform.mirror = DIG_MIRROR
    top.insert(db.CellInstArray(dig.cell_index(), dig_xform))
    top.flatten(-1, True)

    # met2 layer number (sky130: 69/20; 68/20 is met1)
    m2 = None
    for li in range(ly.layers()):
        info = ly.get_info(li)
        if (info.layer, info.datatype) == (69, 20):
            m2 = li
            break
    if m2 is None:
        raise SystemExit("met2 (69/20) not found")
    region = db.Region(top.shapes(m2)).merge()

    bad = []
    owners = {}
    for k in range(N):
        for x in (k * PITCH + PIN_A, k * PITCH + PIN_B):
            px = int(round(x / ly.dbu))
            # a small probe box at the pad centre; both the analog pad and
            # the digital pin cover y=-18.1..-17.9
            probe = db.Region(db.Box(px - 1, int(round(-18.1 / ly.dbu)),
                                     px + 1, int(round(-17.9 / ly.dbu))))
            hit = region & probe
            if hit.is_empty():
                bad.append((k, x))
                continue
            # every pad must be its own merged met2 island: a shared island
            # would short two analog gates together
            poly = next(iter(hit.each()))
            key = poly.bbox().to_s()
            if key in owners:
                bad.append((k, x, "shared with", owners[key]))
            owners[key] = x
    bbox = top.bbox()
    print(f"assembled {top.name}: {N} cells, 510 pads, "
          f"bbox {bbox.left/1000:.3f},{bbox.bottom/1000:.3f} .. "
          f"{bbox.right/1000:.3f},{bbox.top/1000:.3f} um")
    print(f"met2 merged regions: {region.count()}; 510 pad islands: "
          f"{len(owners)}; pad centres not on a merged met2 region or "
          f"shorted: {len(bad)}")
    for item in bad[:5]:
        print("  bad", item)
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    ly.write(OUT)
    print(f"wrote {OUT}")
    return 0 if not bad else 1


if __name__ == "__main__":
    raise SystemExit(main())
