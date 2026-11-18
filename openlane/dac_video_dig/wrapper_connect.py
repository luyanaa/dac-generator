#!/usr/bin/env python3
"""IHP video leaf wrapper: expose the block ports and the 1.2 V rails.

    DIG_GDS=<...>/dac_video_dig.gds klayout -b -r wrapper_connect.py -z

The assembled `dac_video_top` is a pair of cells: `dac_video_ihp` (row) and
`dac_video_dig` (digital).  The row's `vdd/vss/vbp/vcp/iout/idump` rails end
at x=-1 and the digital's `clk/code/stb/rst_n/valid/ready` pins are on its
bottom edge, but the assembly itself does not bring them to the top cell.
This wrapper adds short same-layer stubs and labels for those ports and for
the digital `dvdd/dvss` TopMetal1 pins, so the top cell has a complete port
list for LVS/PEX and for the external bias/decoupling network:

  analog: vdd vss vbp vcp iout idump
  digital: dvdd dvss clk code[0..7] stb rst_n valid ready
  external: 1.66 kohm from vcp to vss, 470 pF vcp-vss, 100 pF vbp-vss,
            37.5 ohm + 2 pF on iout (the wrapper_bias.py schematic).

The 510 Metal2 pad islands are unchanged.
"""
from __future__ import annotations

print("WRAPPER_START")

import glob
import os
import re

import klayout.db as db

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
ANA = os.path.join(ROOT, "analog", "video_ihp", "build", "video_ihp.gds")
OUT = os.path.join(HERE, "build", "dac_video_wrapper.gds")
DEF = os.path.join(HERE, "runs", "ihp_ant", "final", "def", "dac_video_dig.def")
DIG_Y = -9.5
M2 = (10, 0)
M2L = (10, 25)
M1 = (8, 0)
M1L = (8, 25)
M3 = (30, 0)
M3L = (30, 25)
TM1 = (126, 0)
TM1L = (126, 25)


def find_dig() -> str:
    v = os.environ.get("DIG_GDS")
    if v:
        return v
    hits = sorted(glob.glob(os.path.join(
        HERE, "runs", "ihp_*", "final", "gds", "dac_video_dig.gds")))
    if not hits:
        raise SystemExit("no runs/ihp_*/final/gds/dac_video_dig.gds")
    return hits[-1]


def control_pins() -> dict[str, float]:
    """x of the 13 control pins in the digital DEF (um)."""
    lines = open(DEF).read().splitlines()
    pins = {}
    i = 0
    while i < len(lines):
        m = re.match(r"\s*-\s+(\S+)\s+\+\s+NET\s+\S+", lines[i])
        if m:
            name = m.group(1)
            j = i + 1
            while j < len(lines) and j < i + 8:
                p = re.search(r"\+\s*PLACED\s+\(\s*(-?\d+)\s+(-?\d+)\s*\)",
                              lines[j])
                if p:
                    x, y = int(p.group(1)), int(p.group(2))
                    if y == 100000:
                        pins[name] = x / 1000.0
                    break
                if lines[j].lstrip().startswith("- "):
                    break
                j += 1
        i += 1
    return pins


def add_rect(ly, cell, lt, x0, y0, x1, y1):
    li = ly.find_layer(*lt)
    if li is None:
        li = ly.layer(*lt)
    cell.shapes(li).insert(db.Box(
        int(round(x0 / ly.dbu)), int(round(y0 / ly.dbu)),
        int(round(x1 / ly.dbu)), int(round(y1 / ly.dbu))))


def add_label(ly, cell, lt, text, x, y):
    li = ly.find_layer(*lt)
    if li is None:
        li = ly.layer(*lt)
    cell.shapes(li).insert(db.Text(text, int(round(x / ly.dbu)),
                                   int(round(y / ly.dbu))))


def main() -> int:
    dig_path = find_dig()
    print("dig", dig_path, flush=True)
    ly = db.Layout()
    ly.dbu = 0.001
    ly.read(ANA)
    print("read ana", flush=True)
    ly.read(dig_path)
    ana = ly.cell("dac_video_ihp")
    dig = ly.cell("dac_video_dig")
    print("cells", ana, dig, flush=True)
    if ana is None or dig is None:
        raise SystemExit("missing block cells")
    top = ly.create_cell("dac_video_wrapper")
    top.insert(db.CellInstArray(ana.cell_index(), db.Trans(0, 0)))
    xf = db.Trans(db.Vector(0, int(round(DIG_Y / ly.dbu))))
    xf.mirror = True
    top.insert(db.CellInstArray(dig.cell_index(), xf))

    # row rails -> x=-3..-1 stubs and labels
    rails = [
        ("vdd", M3, M3L, 10.60, 12.00),
        ("vss", M1, M1L, -10.60, -10.20),
        ("vbp", M2, M2L, -1.20, -1.00),
        ("vcp", M1, M1L, -1.81, -1.59),
        ("iout", M3, M3L, -7.00, -6.60),
        ("idump", M3, M3L, -8.20, -7.80),
    ]
    for name, lay, lab, y0, y1 in rails:
        add_rect(ly, top, lay, -3.0, y0, -1.0, y1)
        add_label(ly, top, lab, name, -2.0, (y0 + y1) / 2)

    # digital VDD/VSS TopMetal1 pins: child 14.9..83.38 / 14.49..83.79,
    # mirrored to -9.5 - y; extend them to y=-20 and label.
    add_rect(ly, top, TM1, 18.26, -93.0, 20.46, -20.0)
    add_label(ly, top, TM1L, "dvdd", 19.36, -30.0)
    add_rect(ly, top, TM1, 24.46, -93.3, 26.66, -20.0)
    add_label(ly, top, TM1L, "dvss", 25.56, -30.0)

    # control pins on Metal2: extend down to y=-112 and label
    pins = control_pins()
    print("pins", pins, flush=True)
    if len(pins) != 13:
        raise SystemExit(f"expected 13 control pins, got {len(pins)}: {pins}")
    for name, x in pins.items():
        add_rect(ly, top, M2, x - 0.30, -112.0, x + 0.30, -109.5)
        add_label(ly, top, M2L, name, x, -111.0)

    # 510 pad islands still independent?
    m2 = ly.find_layer(*M2)
    region = db.Region(top.begin_shapes_rec(m2)).merge()
    bad = []
    owners = {}
    N, PITCH = 255, 7.5
    for k in range(N):
        for x in (k * PITCH + 2.25, k * PITCH + 6.00):
            px = int(round(x / ly.dbu))
            probe = db.Region(db.Box(px - 1, int(round(-9.95 / ly.dbu)),
                                     px + 1, int(round(-9.65 / ly.dbu))))
            hit = region & probe
            if hit.is_empty():
                bad.append((k, x)); continue
            poly = next(iter(hit.each()))
            key = poly.bbox().to_s()
            if key in owners:
                bad.append((k, x, "shared", owners[key]))
            owners[key] = x
    print(f"wrapper {top.name}: ports 21, 510 islands {len(owners)}, "
          f"bad {len(bad)}; bbox {top.bbox().to_s()}")
    for item in bad[:5]:
        print("  bad", item)
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    ly.write(OUT)
    print(f"wrote {OUT}")
    return 0 if not bad else 1


if __name__ == "__main__":
    raise SystemExit(main())
