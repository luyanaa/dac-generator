#!/usr/bin/env python3
"""Measure the met2 pad row and the rail labels on the drawn array.

    klayout -b -r pinplan.py -rd gds=build/video_sky130.gds -rd out=...

Runs under KLayout's Python.  Writes JSON:

    {"top": ..., "pads": [{"net","cx","cy","w","h"}...], "labels": [...]}

The signoff checks the contract (2 pads per 7.5 um cell, 3.75 um grid) on
this file, never on the generator's variables.
"""
import json
import sys

import pya

GDS = globals().get("gds")
OUT = globals().get("out")
M2 = (69, 20)
M2L = (69, 5)
M1 = (68, 20)
M1L = (68, 5)
M3 = (70, 20)
M3L = (70, 5)


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
                               "y": round(t.y * ly.dbu, 3),
                               "layer": list(layer)})
    pads = []
    for layer, kind in ((M2, "m2"), (M1, "m1"), (M3, "m3")):
        li = ly.find_layer(*layer)
        if li is None:
            continue
        for s in c.shapes(li).each():
            b = s.bbox()
            pads.append({"layer": kind,
                         "x1": round(b.left * ly.dbu, 3),
                         "y1": round(b.bottom * ly.dbu, 3),
                         "x2": round(b.right * ly.dbu, 3),
                         "y2": round(b.top * ly.dbu, 3)})
    out = {"top": c.name, "labels": labels, "shapes": pads,
           "bbox": [round(v * ly.dbu, 3) for v in
                    (c.bbox().left, c.bbox().bottom,
                     c.bbox().right, c.bbox().top)]}
    with open(OUT, "w") as f:
        json.dump(out, f, indent=1)
    print(f"wrote {OUT}: {len(pads)} shapes, {len(labels)} labels")
    return 0


if __name__ == "__main__":
    sys.exit(main())
