#!/usr/bin/env python3
"""Write a top-cell-only GDS for macro-level DRC.

The full macro GDS carries ~18k standard-cell/filler instances plus the
generated via cells.  The ics55 DRC deck's ``cell_exclusion=true`` mode screens
those interiors, but on this design it builds a multi-GB instance-union region
and runs the machine out of memory.  A top-only GDS is the equivalent, cheaper
screen: keep the ``dac_video_dig`` cell's own shapes (routing, pins, power
straps and the DEF labels) and flatten the generated VIA cells so cut geometry
survives.  Standard-cell internals are library-qualified IP and are checked by
the cell-level DRC instead.

Usage:
    klayout -b -r top_only_gds.py -z
    (env IN_GDS / OUT_GDS, defaults to the final LibreLane streamout)
"""

import glob
import os

import pya

HERE = os.path.dirname(os.path.abspath(__file__))
RUN = os.path.join(HERE, "runs", "dac_video_ics55")


def _latest(pattern):
    paths = sorted(glob.glob(os.path.join(RUN, pattern)), key=os.path.getmtime)
    if not paths:
        raise SystemExit(f"no {pattern} under {RUN}")
    return paths[-1]


IN_GDS = os.environ.get(
    "IN_GDS",
    _latest("*-klayout-streamout/dac_video_dig.gds"),
)
OUT_GDS = os.environ.get(
    "OUT_GDS", os.path.join(HERE, "runs", "dac_video_ics55", "top_only.gds")
)
TOP = os.environ.get("TOP", "dac_video_dig")


def is_via(cell):
    return cell.name.upper().startswith("VIA")


def main():
    src = pya.Layout()
    src.read(IN_GDS)
    top = src.cell(TOP)
    if top is None:
        raise SystemExit(f"top cell {TOP!r} not found in {IN_GDS}")

    dst = pya.Layout()
    dst.dbu = src.dbu
    out = dst.create_cell(TOP)

    via_insts = [inst for inst in top.each_inst() if is_via(inst.cell)]
    for li in range(src.layers()):
        info = src.get_info(li)
        shp = out.shapes(dst.layer(info))
        r = pya.Region()
        for shape in top.shapes(li).each():
            if shape.is_text():
                shp.insert(shape)
            else:
                r.insert(shape.polygon)
        for inst in via_insts:
            rr = pya.Region(inst.cell.begin_shapes_rec(li))
            rr.transform(inst.trans)
            r += rr
        if not r.is_empty():
            shp.insert(r)

    dst.write(OUT_GDS)
    print(
        f"wrote {OUT_GDS}: top-only cell {TOP}, "
        f"{dst.cells()} cells, {len(via_insts)} via instances flattened"
    )


if __name__ == "__main__":
    main()
