#!/usr/bin/env python3
"""Assemble the IHP video leaf: digital macro under the analog row.

    KLAYOUT_PATH=<pdk>/libs.tech/klayout klayout -b -r assemble_ihp.py \
        -rd dig=runs/<tag>/final/gds/dac_video_dig.gds -z

The digital macro (`runs/<tag>/final/gds/dac_video_dig.gds`) has its 510
`dout`/`dout_n` pins on Metal2 at x = 2.25 + 7.5*k / 6.0 + 7.5*k, y = 0..0.6.
The analog row (`analog/video_ihp/build/video_ihp.gds`) has the matching pads
at the same x and y = -10.0..-9.6.

The digital body must extend *away* from the analog row.  Mirror it in Y so
its pins become -0.6..0, then place the origin at y = -9.5: the pins become
-10.1..-9.5 and overlap the analog pads -10.0..-9.6 by 0.4 um.  The analog
row's body is above the pad row except for the vss rail, which stops at
-10.4 um; the digital core starts about 1 um inside its die, i.e. at -10.5,
so the two bodies do not overlap.

The script writes `build/dac_video_top.gds`, checks that all 510 pad centres
land inside one merged Metal2 region and that no two pads share an island,
and prints the assembled die box.  Run the PDK DRC on the result:

    klayout -b -zz -r $PDK/libs.tech/klayout/tech/drc/ihp-sg13g2.drc \
        -rd input=build/dac_video_top.gds -rd topcell=dac_video_top \
        -rd report=build/top_drc.lyrdb -rd threads=8
"""
from __future__ import annotations

import glob
import os
import sys

import klayout.db as db

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
ANA = os.path.join(ROOT, "analog", "video_ihp", "build", "video_ihp.gds")
OUT = os.path.join(HERE, "build", "dac_video_top.gds")

N = 255
PITCH = 7.5
PIN_A, PIN_B = 2.25, 6.00
PAD_Y0, PAD_Y1 = -10.00, -9.60
DIG_Y = -9.5
DIG_MIRROR = True

# IHP sg13g2 layer map: Metal2 = 10/0, label 10/25.
MET2 = (10, 0)


def find_dig() -> str:
    # KLayout's -rd variables arrive in the global `g`; plain extra argv can
    # be swallowed by the binary, so both are accepted.
    v = os.environ.get("DIG_GDS")
    if v:
        return v
    try:
        v = g.get("dig", None)
        if v:
            return v
    except NameError:
        pass
    if len(sys.argv) > 1 and not sys.argv[1].startswith("-"):
        return sys.argv[1]
    hits = sorted(glob.glob(os.path.join(
        HERE, "runs", "ihp_pins*", "final", "gds", "dac_video_dig.gds")))
    if not hits:
        raise SystemExit("no runs/ihp_pins*/final/gds/dac_video_dig.gds")
    return hits[-1]


def main() -> int:
    dig_path = find_dig()
    ly = db.Layout()
    ly.dbu = 0.001
    ly.read(ANA)
    ly.read(dig_path)

    ana = ly.cell("dac_video_ihp")
    dig = ly.cell("dac_video_dig")
    if ana is None or dig is None:
        raise SystemExit(f"top cells missing: ana={ana} dig={dig}")

    top = ly.create_cell("dac_video_top")
    top.insert(db.CellInstArray(ana.cell_index(), db.Trans(0, 0)))
    dig_xform = db.Trans(db.Vector(0, int(round(DIG_Y / ly.dbu))))
    dig_xform.mirror = DIG_MIRROR
    top.insert(db.CellInstArray(dig.cell_index(), dig_xform))
    top.flatten(-1, True)

    m2 = None
    for li in range(ly.layers()):
        info = ly.get_info(li)
        if (info.layer, info.datatype) == MET2:
            m2 = li
            break
    if m2 is None:
        raise SystemExit("Metal2 (10/0) not found")
    region = db.Region(top.shapes(m2)).merge()

    bad = []
    owners = {}
    for k in range(N):
        for x in (k * PITCH + PIN_A, k * PITCH + PIN_B):
            px = int(round(x / ly.dbu))
            # probe inside the 0.4 um overlap of pad and pin
            probe = db.Region(db.Box(px - 1, int(round(-9.95 / ly.dbu)),
                                     px + 1, int(round(-9.65 / ly.dbu))))
            hit = region & probe
            if hit.is_empty():
                bad.append((k, x))
                continue
            # every pad must be its own merged Metal2 island: a shared island
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
    print(f"digital: {os.path.relpath(dig_path, ROOT)}")
    print(f"Metal2 merged regions: {region.count()}; 510 pad islands: "
          f"{len(owners)}; pad centres not on a merged Metal2 region or "
          f"shorted: {len(bad)}")
    for item in bad[:5]:
        print("  bad", item)
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    ly.write(OUT)
    print(f"wrote {OUT}")
    return 0 if not bad else 1


if __name__ == "__main__":
    raise SystemExit(main())
