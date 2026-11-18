#!/usr/bin/env python3
"""IHP sg13g2 binary CDAC array: 256 `cmim` unit capacitors.

    KLAYOUT_PATH=<pdk>/libs.tech/klayout klayout -b -r gen_gds_ihp.py \
        [-rd out=build/cdac_ihp.gds] [-rd check=true]

One side of the 8-bit DAC is 255 switched units plus one VCM-referenced
dummy.  The unit is the PDK `cmim` PCell (7x7 um, 74.62 fF flat), because
the moscap backend is bias dependent and cannot meet 8-bit INL (the leaf
records that as a study).  Blocks are laid out bit 7 .. bit 0, dummy last;
each block's bottom plates are merged on Metal5 and brought to a pin.

Routing:
  * bottom plate  Metal5 pad (the PCell's own) -> vertical stub -> one
                  horizontal Metal5 bus per bit in the channel above the row;
  * buses         extended right to a nested L-route (bus y falls as the
                  drop x grows, so no horizontal crosses another net's
                  vertical), then up to a Metal5 pin row at y=18;
  * top plate     one TopMetal1 bar across every cap's TM1 pad, plus a TM1
                  VSH pin;
  * labels        Metal5 / TopMetal1 text layers so LVS names the nets.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent

M5 = (67, 0)
M5_LABEL = (67, 25)
TM1 = (126, 0)
TM1_LABEL = (126, 25)

N = 256
PITCH = 8.6
CELL_W = 7.0
Y0 = 0.0
# PCell extents for w=l=7 (um, relative to the cell origin)
M5_LO, M5_HI = -0.6, 7.59
TM1_LO, TM1_HI = 0.345, 6.645
# (bit or None, count), left to right
BLOCKS = [(7, 128), (6, 64), (5, 32), (4, 16), (3, 8), (2, 4), (1, 2),
          (0, 1), (None, 1)]
BUS_X0 = 9.0
BUS_DY = 0.8
PIN_Y = 18.0


def pdk_root(override=None):
    if override:
        return Path(override)
    base = Path.home() / ".ciel/ciel/ihp-sg13/versions"
    if not base.is_dir():
        sys.exit(f"{base} not found; pass -rd pdkroot=<dir>")
    return base / sorted(p.name for p in base.iterdir() if p.is_dir())[-1] / "ihp-sg13g2"


def main() -> int:
    import pya

    g = globals()

    def opt(name, default=None):
        v = g.get(name, default)
        return v if isinstance(v, (str, int, float)) else default

    root = pdk_root(opt("pdkroot"))
    out_path = Path(opt("out", str(HERE / "build" / "cdac_ihp.gds")))
    do_check = str(opt("check", "true")).lower() in ("1", "true", "yes")
    libdir = root / "libs.tech" / "klayout" / "python"
    for extra in (str(libdir),
                  str(libdir / "pycell4klayout-api" / "source" / "python")):
        if extra not in sys.path:
            sys.path.insert(0, extra)
    import sg13g2_pycell_lib  # noqa: F401

    ly = pya.Layout()
    ly.dbu = 0.001
    ly.technology_name = "sg13g2"
    top = ly.create_cell("dac_cdac_ihp")
    m5 = ly.layer(*M5)
    m5l = ly.layer(*M5_LABEL)
    tm1 = ly.layer(*TM1)
    tm1l = ly.layer(*TM1_LABEL)

    def box(x1, y1, x2, y2):
        return pya.Box(int(round(x1 * 1000)), int(round(y1 * 1000)),
                       int(round(x2 * 1000)), int(round(y2 * 1000)))

    regions: dict[tuple[int, str], pya.Region] = {}

    def add(layer, x1, y1, x2, y2, net):
        b = box(x1, y1, x2, y2)
        top.shapes(layer).insert(b)
        regions.setdefault((layer, net), pya.Region()).insert(b)
        return b

    def label(x, y, name, layer=m5l):
        top.shapes(layer).insert(
            pya.Text(name, pya.Trans(int(round(x * 1000)),
                                     int(round(y * 1000)))))

    unit = ly.create_cell("cmim", "SG13_dev", {"w": "7u", "l": "7u"})
    if unit is None:
        sys.exit("cmim PCell not available")
    print(f"cmim PCell bbox {unit.bbox().to_s()}")

    # place the 256 units, collect each cap's block/bit and centre x
    caps = []
    x = 0.0
    for bit, count in BLOCKS:
        net = "VCM" if bit is None else f"B{bit}"
        for _ in range(count):
            top.insert(pya.CellInstArray(
                unit.cell_index(),
                pya.Trans(int(round(x * 1000)), int(round(Y0 * 1000)))))
            caps.append((net, x))
            x += PITCH
    width = x - PITCH + CELL_W
    print(f"{len(caps)} cmim units, array width {width:.1f} um")

    # Bottom-plate routing.  Each bit block is contiguous, so merge its
    # caps' Metal5 pads with local bridges, tap the block once, and stack the
    # block buses in a channel below the row with the widest span deepest.
    # A wider bus then runs *under* every other block's tap, and each bus
    # reaches its pin through a nested L-route in the right margin.
    blocks = []
    for bit, count in BLOCKS:
        net = "VCM" if bit is None else f"B{bit}"
        xs = [xc for n, xc in caps if n == net]
        blocks.append((net, min(xs), max(xs)))
    # rank 0 = shortest span (rightmost block), deepest y for the widest
    blocks.sort(key=lambda b: -b[1])
    bus_y = {}
    drop_x = {}
    for k, (net, xlo, xhi) in enumerate(blocks):
        bus_y[net] = -2.0 - BUS_DY * k
        drop_x[net] = width + 1.6 + 1.6 * k

    for net, xlo, xhi in blocks:
        xs = [xc for n, xc in caps if n == net]
        # bridges between consecutive pads of this block
        for xa, xb in zip(xs, xs[1:]):
            add(m5, xa + M5_HI - 0.10, -0.45,
                xb + M5_LO + 0.10, -0.05, net)
        # single tap from the first pad down to the block bus
        tap = xs[0] + CELL_W / 2
        add(m5, tap - 0.20, M5_LO, tap + 0.20, bus_y[net] + 0.20, net)
        # horizontal bus to the right-margin drop
        add(m5, tap - 0.20, bus_y[net] - 0.20,
            drop_x[net] + 0.20, bus_y[net] + 0.20, net)
        # nested vertical to the pin row (pins above every bus)
        add(m5, drop_x[net] - 0.20, bus_y[net] - 0.20,
            drop_x[net] + 0.20, PIN_Y + 0.40, net)
        add(m5, drop_x[net] - 0.40, PIN_Y - 0.40,
            drop_x[net] + 0.40, PIN_Y + 0.40, net)
        label(drop_x[net], PIN_Y, net)

    # top plate: one TopMetal1 bar over every cap's TM1 pad + VSH pin
    add(tm1, caps[0][1] + TM1_LO, TM1_LO,
        caps[-1][1] + TM1_HI, TM1_HI, "VSH")
    add(tm1, caps[-1][1] + TM1_HI, 2.0, width + 1.6, 8.3, "VSH")
    add(tm1, width + 0.6, 3.15, width + 2.6, 7.15, "VSH")
    label(width + 1.6, 5.15, "VSH", tm1l)

    ly.flatten(top.cell_index(), -1, False)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    ly.write(str(out_path))
    b = top.bbox()
    print(f"wrote {out_path}  (bbox {b.left/1000:.1f},{b.bottom/1000:.1f};"
          f"{b.right/1000:.1f},{b.top/1000:.1f})")
    rc = 0
    if do_check:
        print(f"units      : {len(caps)}")
        netlist = [b[0] for b in blocks]
        print(f"nets       : {' '.join(netlist)}")
        all5 = pya.Region(top.begin_shapes_rec(m5))
        bad = [n for n in netlist
               if (pya.Region(box(drop_x[n] - 0.2, PIN_Y - 0.2,
                                  drop_x[n] + 0.2, PIN_Y + 0.2)) & all5).is_empty()]
        print(f"pins       : {len(netlist) - len(bad)}/{len(netlist)} covered")
        keys = sorted(regions)
        shorts = []
        for i in range(len(keys)):
            for j in range(i + 1, len(keys)):
                if keys[i][0] != keys[j][0]:
                    continue
                inter = regions[keys[i]] & regions[keys[j]]
                if not inter.is_empty():
                    bb = inter.bbox()
                    shorts.append((keys[i][1], keys[j][1],
                                   round(bb.left*ly.dbu, 2),
                                   round(bb.bottom*ly.dbu, 2),
                                   round(bb.right*ly.dbu, 2),
                                   round(bb.top*ly.dbu, 2)))
        print(f"net shorts : {len(shorts)}")
        for s in shorts[:8]:
            print("  SHORT", s)
        rc |= bool(bad) or bool(shorts)
    return rc


if __name__ == "__main__":
    import pya  # noqa: E402
    sys.exit(main())
