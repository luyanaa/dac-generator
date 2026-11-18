#!/usr/bin/env python3
"""Hierarchical IHP leaf assembly for LVS/PEX (no flattening).

    DIG_GDS=<...>/dac_video_dig.gds klayout -b -r assemble_ihp_hier.py -z

`assemble_ihp.py` flattens the top so the DRC sees one cell.  Magic SPICE
extraction and hierarchical LVS need the `dac_video_ihp` and `dac_video_dig`
cells intact, so this script inserts them as instances and only merges the
510 Metal2 pad overlaps at the top level.
"""
from __future__ import annotations

import glob
import os

import klayout.db as db

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
ANA = os.path.join(ROOT, "analog", "video_ihp", "build", "video_ihp.gds")
OUT = os.path.join(HERE, "build", "dac_video_top_hier.gds")
N, PITCH = 255, 7.5
PIN_A, PIN_B = 2.25, 6.00
DIG_Y = -9.5
MET2 = (10, 0)


def find_dig() -> str:
    v = os.environ.get("DIG_GDS")
    if v:
        return v
    hits = sorted(glob.glob(os.path.join(
        HERE, "runs", "ihp_*", "final", "gds", "dac_video_dig.gds")))
    if not hits:
        raise SystemExit("no runs/ihp_*/final/gds/dac_video_dig.gds")
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
    xf = db.Trans(db.Vector(0, int(round(DIG_Y / ly.dbu))))
    xf.mirror = True
    top.insert(db.CellInstArray(dig.cell_index(), xf))

    m2 = None
    for li in range(ly.layers()):
        info = ly.get_info(li)
        if (info.layer, info.datatype) == MET2:
            m2 = li
            break
    if m2 is None:
        raise SystemExit("Metal2 (10/0) not found")
    region = db.Region(top.begin_shapes_rec(m2)).merge()
    bad = []
    owners = {}
    for k in range(N):
        for x in (k * PITCH + PIN_A, k * PITCH + PIN_B):
            px = int(round(x / ly.dbu))
            probe = db.Region(db.Box(px - 1, int(round(-9.95 / ly.dbu)),
                                     px + 1, int(round(-9.65 / ly.dbu))))
            hit = region & probe
            if hit.is_empty():
                bad.append((k, x))
                continue
            poly = next(iter(hit.each()))
            key = poly.bbox().to_s()
            if key in owners:
                bad.append((k, x, "shared with", owners[key]))
            owners[key] = x
    bbox = top.bbox()
    print(f"hierarchical {top.name}: {N} cells, 510 pads, "
          f"bbox {bbox.left/1000:.3f},{bbox.bottom/1000:.3f} .. "
          f"{bbox.right/1000:.3f},{bbox.top/1000:.3f} um")
    print(f"digital: {os.path.relpath(dig_path, ROOT)}")
    print(f"Metal2 merged regions: {region.count()}; 510 pad islands: "
          f"{len(owners)}; bad: {len(bad)}")
    for item in bad[:5]:
        print("  bad", item)
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    ly.write(OUT)
    print(f"wrote {OUT}")
    return 0 if not bad else 1


if __name__ == "__main__":
    raise SystemExit(main())
