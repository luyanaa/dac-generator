#!/usr/bin/env python3
r"""Extract the P5 macro's port geometry from the written GDS (KLayout script).

    klayout -b -r pinplan.py -rd gds=build/video.gds -rd out=build/pinplan.json

`signoff.py` runs this after the GDS is written and then checks the result
against the pin contract, so the contract is verified on the *drawn* metal
rather than on the generator's intent.  For every label the script takes the
smallest shape that contains the label point - for a gate pin that is the pad,
not the riser it hangs from - which also catches a label left on a net with no
metal under it.

P5's array is wider than P3's, so the shared distribution is on M3 (via2) as
well as M2/M1; those layers are included here, or the vdd plane / iout bus
would be reported as unlabelled.

Output (um, absolute):

    {"top": ..., "pins": {"d_b0_0": {"layer": "m2",
                                     "bbox": [x0, y0, x1, y1]}, ...}}
"""
import json
import sys

import pya

g = globals()
gds = g.get("gds")
out = g.get("out")
if not gds or not out:
    sys.exit("usage: -rd gds=<file> -rd out=<json>")

# gf180 GDS layer map: M3 is 42/0 (37/0 is Pad), Via2 is 38/0.
LAYERS = {"m1": (34, 0), "via1": (35, 0), "m2": (36, 0), "via2": (38, 0),
          "m3": (42, 0), "poly": (30, 0), "contact": (33, 0)}
LABELS = {34: "m1", 36: "m2", 42: "m3", 30: "poly"}

ly = pya.Layout()
ly.read(str(gds))
top = ly.top_cell()
dbu = ly.dbu

shapes = {}
for name, (layer, datatype) in LAYERS.items():
    li = ly.find_layer(layer, datatype)
    shapes[name] = list(top.shapes(li).each()) if li is not None else []

pins = {}
problems = []


def um(b):
    return [round(b.left * dbu, 4), round(b.bottom * dbu, 4),
            round(b.right * dbu, 4), round(b.top * dbu, 4)]


for lbl_layer, base in sorted(LABELS.items()):
    li = ly.find_layer(lbl_layer, 10)
    if li is None:
        continue
    for sh in top.shapes(li).each():
        if not sh.is_text():
            continue
        name = sh.text.string
        d = sh.text_dtrans.disp          # micron units
        pt = pya.Point(int(round(d.x * 1000)), int(round(d.y * 1000)))
        # Smallest shape on the label's own layer (then the others) that
        # contains the point: the pad, not the bus or the riser.
        best = None
        for lname in (base, "m3", "m2", "m1", "poly"):
            for poly in shapes.get(lname, ()):
                if poly.is_box():
                    if not poly.box.contains(pt):
                        continue
                    bb = poly.box
                elif poly.inside(pt):
                    bb = poly.bbox()
                else:
                    continue
                area = (bb.right - bb.left) * (bb.top - bb.bottom)
                if best is None or area < best[0]:
                    best = (area, lname, bb)
            if best:
                break
        if best is None:
            problems.append(f"{name}: label at ({d.x:.3f},{d.y:.3f}) is not "
                            f"on metal")
            continue
        _, lname, bb = best
        got = {"layer": lname, "bbox": um(bb)}
        if name in pins:
            # Several labels on one net are normal (vcp is labelled at the
            # array end and again at the replica bias).  The ports are counted
            # by name, and the LVS/PEX stage still proves the two labels are
            # one net, so only the first shape is reported.
            pins[name]["labels"] = pins[name].get("labels", 1) + 1
            continue
        pins[name] = dict(got, labels=1)

with open(str(out), "w") as f:
    json.dump({"top": top.name, "dbu": dbu, "pins": pins,
               "problems": problems}, f, indent=1, sort_keys=True)
    f.write("\n")
print(f"pinplan: {len(pins)} labelled ports, {len(problems)} problems")
for p in problems:
    print("  " + p)
