#!/usr/bin/env python3
"""Measure the ihp array's met2 pad row and rail labels on the drawn GDS.

    klayout -b -r pinplan.py -rd gds=build/video_ihp.gds -rd out=...

Writes {"top","labels","shapes","bbox"}; the signoff checks the 510 pads on
the 3.75 um grid and the 6 rail labels from this file, never from the
generator's variables.
"""
import json
import sys

import pya

GDS = globals().get("gds")
OUT = globals().get("out")
M1 = (8, 0)
M1L = (8, 25)
M2 = (10, 0)
M2L = (10, 25)
M3 = (30, 0)
M3L = (30, 25)


def main() -> int:
    if not GDS or not OUT:
        print("error: need -rd gds=... -rd out=...", file=sys.stderr)
        return 2
    ly = pya.Layout()
    ly.read(GDS)
    tops = list(ly.top_cells())
    if len(tops) != 1:
        print(f"error: {len(tops)} top cells", file=sys.stderr)
        return 2
    c = tops[0]
    labels = []
    for layer in (M2L, M1L, M3L):
        li = ly.find_layer(*layer)
        if li is None:
            continue
        for s in c.shapes(li).each():
            if s.is_text():
                t = s.text
                labels.append({"net": t.string, "x": round(t.x * ly.dbu, 3),
                               "y": round(t.y * ly.dbu, 3)})
    shapes = []
    for layer, kind in ((M2, "m2"), (M1, "m1"), (M3, "m3")):
        li = ly.find_layer(*layer)
        if li is None:
            continue
        for s in c.shapes(li).each():
            b = s.bbox()
            shapes.append({"layer": kind,
                           "x1": round(b.left * ly.dbu, 3),
                           "y1": round(b.bottom * ly.dbu, 3),
                           "x2": round(b.right * ly.dbu, 3),
                           "y2": round(b.top * ly.dbu, 3)})
    out = {"top": c.name, "labels": labels, "shapes": shapes,
           "bbox": [round(v * ly.dbu, 3) for v in
                    (c.bbox().left, c.bbox().bottom,
                     c.bbox().right, c.bbox().top)]}
    with open(OUT, "w") as f:
        json.dump(out, f, indent=1)
    print(f"wrote {OUT}: {len(shapes)} shapes, {len(labels)} labels")
    return 0


if __name__ == "__main__":
    sys.exit(main())
