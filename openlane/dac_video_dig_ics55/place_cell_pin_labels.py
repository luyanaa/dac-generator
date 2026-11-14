#!/usr/bin/env python3
"""Place std-cell pin labels on their LEF pin metal.

The vendor cell GDS carries pin texts, but they sit beside the pins rather
than on the conductor, so KLayout's LVS extractor cannot use them to name the
cell boundary nets.  This script parses the cell LEF and writes one label per
pin at the centre of the first pin rectangle, on the matching conductor layer
(datatype 6).  The digital macro's LVS then sees the CDL pin names (A, B, Y,
VDD, VSS, ...) instead of numeric boundary pins.

Usage:
    klayout -b -r place_cell_pin_labels.py -z
"""

import glob
import os
import re

import pya

HERE = os.path.dirname(os.path.abspath(__file__))
RUN = os.path.join(HERE, "runs", "dac_video_ics55")


def _latest(pattern):
    paths = sorted(glob.glob(os.path.join(RUN, pattern)), key=os.path.getmtime)
    if not paths:
        raise SystemExit(f"no {pattern} under {RUN}")
    return paths[-1]
LEF = os.environ.get(
    "LEF",
    "/grid/icsprout55-pdk/libs.ref/ics55_LLSC_H7CR/lef/ics55_LLSC_H7CR_ecos.lef",
)
IN_GDS = os.environ.get("IN_GDS", _latest("*-klayout-streamout/dac_video_dig.gds"))
OUT_GDS = os.environ.get("OUT_GDS", os.path.join(RUN, "dac_video_dig_pinlabeled.gds"))

LAYER = {
    "MET1": (81, 1),
    "MET2": (82, 1),
    "MET3": (83, 1),
    "MET4": (84, 1),
    "MET5": (85, 1),
}


def parse_lef(path):
    macros = {}
    cell = None
    pin = None
    layer = None
    in_port = False
    for line in open(path, errors="replace"):
        s = line.strip()
        if s.startswith("MACRO "):
            cell = s.split()[1]
            macros[cell] = {}
            continue
        if cell is None:
            continue
        if s.startswith("PIN "):
            pin = s.split()[1]
            macros[cell][pin] = {}
            continue
        if s == "PORT":
            in_port = True
            continue
        if s.startswith("LAYER "):
            if in_port:
                layer = s.split()[1]
            continue
        if s.startswith("RECT ") and pin and layer in LAYER:
            nums = [float(x) for x in s.replace(';',' ').split()[1:]]
            if len(nums) == 4 and layer not in macros[cell][pin]:
                macros[cell][pin][layer] = tuple(nums)
            continue
        if s == "END":
            if pin is not None and not in_port:
                pin = None
            elif pin is not None and in_port:
                in_port = False
            continue
        if s.startswith("END ") and pin is None:
            cell = None
    return macros


def main():
    macros = parse_lef(LEF)
    ly = pya.Layout()
    ly.read(IN_GDS)
    count = 0
    cells = 0
    for cell in ly.each_cell():
        pins = macros.get(cell.name)
        if not pins:
            continue
        cells += 1
        for pin, layers in pins.items():
            for layer, (x1, y1, x2, y2) in layers.items():
                li = ly.layer(LAYER[layer][0], 6)
                x = int(round((x1 + x2) / 2.0 * 1000))
                y = int(round((y1 + y2) / 2.0 * 1000))
                cell.shapes(li).insert(pya.Text(pin, pya.Trans(pya.Point(x, y))))
                count += 1
    ly.write(OUT_GDS)
    print(f"wrote {OUT_GDS}: {cells} cells, {count} LEF pin labels")


if __name__ == "__main__":
    main()
