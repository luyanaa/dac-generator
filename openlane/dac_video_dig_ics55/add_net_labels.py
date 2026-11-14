#!/usr/bin/env python3
"""Add DEF net-name labels to the streamed macro GDS.

KLayout's LVS extractor names nets from text on the conductor layers.  The
LibreLane streamout writes only the 522 pin labels, so every internal net of
the digital macro extracts as ``$N``; the flat/hierarchical comparer then has
to resolve 510 identical thermometer branches and gives up.  Writing one text
label per DEF net (on the routed metal layer, datatype 6) gives the extracted
netlist the same net names as the CDL, which removes the ambiguity.

The deck's FLOW_MODE port filter keeps only the 524 reference top ports, so
these extra labels do not become pins in the LVS comparison.

Usage:
    klayout -b -r add_net_labels.py -z
    (env DEF / IN_GDS / OUT_GDS / TOP)
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


DEF = os.environ.get("DEF", _latest("*-odb-cellfrequencytables/dac_video_dig.def"))
IN_GDS = os.environ.get("IN_GDS", _latest("*-klayout-streamout/dac_video_dig.gds"))
OUT_GDS = os.environ.get("OUT_GDS", os.path.join(RUN, "dac_video_dig_labeled.gds"))
TOP = os.environ.get("TOP", "dac_video_dig")

LAYERS = {
    "MET1": (81, 6),
    "MET2": (82, 6),
    "MET3": (83, 6),
    "MET4": (84, 6),
    "MET5": (85, 6),
}


def main():
    lines = open(DEF, errors="replace").read().splitlines()
    # Pin nets already carry their pin label; a second net label would make
    # the extractor produce composite names such as "dout[127]|net127".
    pstart = next(i for i, l in enumerate(lines) if l.startswith("PINS "))
    pend = next(i for i, l in enumerate(lines[pstart:], pstart) if l.startswith("END PINS"))
    pin_nets = set()
    for line in lines[pstart:pend]:
        m = re.match(r"\s*-\s+\S+\s+\+\s+NET\s+(\S+)", line)
        if m:
            pin_nets.add(m.group(1))
    start = next(i for i, l in enumerate(lines) if l.startswith("NETS "))
    end = next(i for i, l in enumerate(lines[start:], start) if l.startswith("END NETS"))

    labels = {}
    skipped = []
    cur = None
    body = []

    def flush():
        if cur is None or cur in labels:
            return
        for layer in ("MET2", "MET3", "MET4", "MET5", "MET1"):
            m = re.search(
                layer + r"\s*\(\s*(-?\d+)\s+(-?\d+)",
                "\n".join(body),
            )
            if m:
                labels[cur] = (LAYERS[layer], int(m.group(1)), int(m.group(2)))
                return
        skipped.append(cur)

    for line in lines[start:end]:
        m = re.match(r"\s*-\s+(\S+)\s", line)
        if m:
            flush()
            cur = m.group(1)
            body = []
            if cur in pin_nets:
                cur = None
        else:
            body.append(line)
    flush()

    ly = pya.Layout()
    ly.read(IN_GDS)
    top = ly.cell(TOP)
    for name, (layer, x, y) in labels.items():
        shp = top.shapes(ly.layer(*layer))
        shp.insert(pya.Text(name, pya.Trans(pya.Point(x, y))))
    ly.write(OUT_GDS)

    print(
        f"wrote {OUT_GDS}: {len(labels)} net labels, "
        f"{len(skipped)} nets without a routed metal segment"
    )
    if skipped:
        print("skipped:", skipped[:20])


if __name__ == "__main__":
    main()
