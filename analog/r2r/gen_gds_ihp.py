#!/usr/bin/env python3
"""IHP sg13g2 R-2R ladder layout (rppd units + M1 straps).

    KLAYOUT_PATH=<pdk>/libs.tech/klayout klayout -b -r gen_gds_ihp.py \
        [-rd out=build/r2r_ihp.gds] [-rd check=true]

The generator places the same 25-unit ladder as `gen_r2r.py`: 7 series 1R,
8 x (ra + rb trimmed) branches and the 2R termination.  The unit is the PDK
`rppd` PCell at W=2 um, R=19.5 kOhm (260 ohm/sq); the trimmed unit is
R=19.287 kOhm, which absorbs the 1.2 V driver on-resistance measured by the
pre-layout bench.  Only Metal1 straps are drawn; the bit drivers are the
digital macro / wrapper (same split as the gf180 leaf).

Floorplan (um):
    row i (i=-1 termination, 0..7): y = i*165
    ra at x=0; rb at x=160; node bus x=322; series 1R x=332
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent

# IHP layer map
M1 = (8, 0)
M1_PIN = (8, 2)
M1_LABEL = (8, 25)

PITCH = 165.0
X_RB = 160.0
X_BUS = 322.0
X_SER = 332.0
BUS_W = 0.4
Y_PAD = -360.0
PAD = 8.0
N = 8
UNIT_R = "19.5k"
TRIM_R = "19.287k"
UNIT_W = "2u"


def load_cfg():
    import yaml
    with open(HERE / "r2r.yaml") as f:
        return yaml.safe_load(f)


def pdk_root(override=None):
    if override:
        return Path(override)
    fam, name = "ihp-sg13", "ihp-sg13g2"
    base = Path(os.path.expanduser(f"~/.ciel/ciel/{fam}/versions"))
    if not base.is_dir():
        sys.exit(f"{base} not found; pass -rd pdkroot=<version dir>")
    ver = sorted(p.name for p in base.iterdir() if p.is_dir())[-1]
    return base / ver / name


def main() -> int:
    import pya

    g = globals()

    def opt(name, default=None):
        v = g.get(name, default)
        return v if isinstance(v, (str, int, float)) else default

    root = pdk_root(opt("pdkroot"))
    out_path = Path(opt("out", str(HERE / "build" / "r2r_ihp.gds")))
    do_check = str(opt("check", "true")).lower() in ("1", "true", "yes")
    libdir = root / "libs.tech" / "klayout" / "python"
    if str(libdir) not in sys.path:
        sys.path.insert(0, str(libdir))
    if str(libdir / "pycell4klayout-api" / "source" / "python") not in sys.path:
        sys.path.insert(0, str(libdir / "pycell4klayout-api" / "source" / "python"))
    import sg13g2_pycell_lib  # noqa: F401

    ly = pya.Layout()
    ly.dbu = 0.001
    ly.technology_name = "sg13g2"
    top = ly.create_cell("dac_r2r_ihp")
    m1 = ly.layer(*M1)
    m1_pin = ly.layer(*M1_PIN)
    m1_lbl = ly.layer(*M1_LABEL)

    def make_res(rval: str):
        return ly.create_cell("rppd", "SG13_dev", {
            "Calculate": "l", "R": rval, "w": UNIT_W, "b": 0,
            "ps": "0.28u"})

    unit = make_res(UNIT_R)
    trim = make_res(TRIM_R)

    def pins(cell):
        boxes = [sh.bbox() for sh in cell.shapes(m1_pin).each()]
        boxes.sort(key=lambda b: b.top)
        if len(boxes) < 2:
            sys.exit(f"rppd PCell has {len(boxes)} M1 pin boxes")
        a, b = boxes[0], boxes[-1]
        return ((a.center().x * ly.dbu, a.center().y * ly.dbu),
                (b.center().x * ly.dbu, b.center().y * ly.dbu))

    unit_a, unit_b = pins(unit)
    trim_a, trim_b = pins(trim)
    print(f"unit pin y {unit_a[1]:.2f}..{unit_b[1]:.2f}; "
          f"trim pin y {trim_a[1]:.2f}..{trim_b[1]:.2f}")

    def place(cell, x, y, rot=None):
        tr = (pya.Trans(rot, pya.Point(int(x * 1000), int(y * 1000)))
              if rot is not None else pya.Trans(int(x * 1000), int(y * 1000)))
        top.insert(pya.CellInstArray(cell.cell_index(), tr))
        return tr

    def apply(tr, pt):
        p = tr * pya.Point(int(round(pt[0] * 1000)),
                           int(round(pt[1] * 1000)))
        return (p.x / 1000.0, p.y / 1000.0)

    routes = {}

    def wire(pts, net, width=0.4):
        for (x1, y1), (x2, y2) in zip(pts, pts[1:]):
            if abs(x1 - x2) < 1e-9 and abs(y1 - y2) < 1e-9:
                continue
            w = width / 2
            box = pya.Box(int(round((min(x1, x2) - w) * 1000)),
                          int(round((min(y1, y2) - w) * 1000)),
                          int(round((max(x1, x2) + w) * 1000)),
                          int(round((max(y1, y2) + w) * 1000)))
            top.shapes(m1).insert(box)
            routes.setdefault(net, pya.Region()).insert(box)

    def pad(x, y, name):
        h = PAD / 2
        box = pya.Box(int((x - h) * 1000), int((y - h) * 1000),
                      int((x + h) * 1000), int((y + h) * 1000))
        top.shapes(m1).insert(box)
        routes.setdefault(name, pya.Region()).insert(box)
        top.shapes(m1_lbl).insert(
            pya.Text(name, pya.Trans(int(x * 1000), int(y * 1000))))

    def label(x, y, name):
        top.shapes(m1_lbl).insert(
            pya.Text(name, pya.Trans(int(x * 1000), int(y * 1000))))

    def nname(i):
        return "vout" if i == N - 1 else f"n{i}"

    def yrow(i):
        return i * PITCH

    terminals = []
    for i in range(-1, N):
        y = yrow(i)
        cell_b = unit if i == -1 else trim
        pb = unit_b if i == -1 else trim_b
        ta = place(unit, 0.0, y, rot=pya.Trans.R270)
        tb = place(cell_b, X_RB, y, rot=pya.Trans.R270)
        a0 = apply(ta, unit_a)
        b0 = apply(ta, unit_b)
        a1 = apply(tb, (trim_a if i != -1 else unit_a))
        b1 = apply(tb, pb)
        net_mid = f"mid{i}"
        net_node = "n0" if i == -1 else nname(i)
        cy = y - 6.0
        wire([b0, (b0[0], cy), (a1[0], cy), a1], net_mid)
        terminals += [(net_mid, *b0), (net_mid, *a1)]
        wire([b1, (X_BUS, b1[1])], net_node)
        terminals.append((net_node, *b1))
        if i >= 0:
            net_bit = f"b{i}"
            xd = -14.0 - i * 12.0
            wire([a0, (a0[0], y - 6.0), (xd, y - 6.0), (xd, Y_PAD)], net_bit)
            pad(xd, Y_PAD, net_bit)
        else:
            net_bit = "vss"
            wire([a0, (a0[0], Y_PAD - 20.0), (-140.0, Y_PAD - 20.0),
                  (-140.0, Y_PAD)], net_bit)
            pad(-140.0, Y_PAD, net_bit)
        terminals.append((net_bit, *a0))

    # node bus tracks, one row each
    y_hi = yrow(N - 1) + 2.5
    for i in range(N):
        y_lo = yrow(-1) - 2.0 if i == 0 else yrow(i) - 10.0
        wire([(X_BUS, y_lo), (X_BUS, yrow(i) + 2.5)], nname(i), width=BUS_W)

    # vertical series 1R between adjacent nodes
    for i in range(1, N):
        y0 = yrow(i - 1) + 2.5
        tr = place(unit, X_SER, y0)  # vertical, terminals at bottom/top
        bot = apply(tr, unit_a)
        topp = apply(tr, unit_b)
        wire([bot, (X_BUS, bot[1])], nname(i - 1))
        wire([topp, (X_BUS, topp[1])], nname(i))
        terminals += [(f"n{i-1}", *bot), (f"n{i}", *topp)]
        label(bot[0] - 1.0, bot[1], f"n{i-1}")

    for i in range(N - 1):
        label(X_BUS, yrow(i) - 4.0, f"n{i}")
    vout_y = y_hi + 12.0
    wire([(X_BUS, y_hi), (X_BUS, vout_y)], "vout")
    pad(X_BUS, vout_y, "vout")

    ly.flatten(top.cell_index(), -1, True)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    ly.write(str(out_path))
    print(f"wrote {out_path}  (bbox {top.dbbox()})")

    rc = 0
    if do_check:
        allm1 = pya.Region(top.begin_shapes_rec(m1))
        bad = []
        for net, x, y in terminals:
            probe = pya.Region(pya.Box(int((x - 0.15) * 1000),
                                       int((y - 0.15) * 1000),
                                       int((x + 0.15) * 1000),
                                       int((y + 0.15) * 1000)))
            if (probe & allm1).is_empty():
                bad.append((net, x, y))
        print(f"terminals : {len(terminals) - len(bad)}/{len(terminals)} covered")
        for b in bad[:12]:
            print(f"  MISSING {b[0]} at ({b[1]:.2f}, {b[2]:.2f})")
        rc |= bool(bad)
        names = sorted(routes)
        shorts = []
        for i, n1 in enumerate(names):
            for n2 in names[i + 1:]:
                if not (routes[n1] & routes[n2]).is_empty():
                    shorts.append((n1, n2))
        print(f"net shorts: {len(shorts)}")
        for s in shorts[:12]:
            print(f"  SHORT {s[0]} <-> {s[1]}")
        rc |= bool(shorts)
    return rc


if __name__ == "__main__":
    import pya  # noqa: E402
    sys.exit(main())
