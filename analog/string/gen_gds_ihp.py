#!/usr/bin/env python3
"""IHP sg13g2 255-unit resistor string (rppd) layout.

    KLAYOUT_PATH=<pdk>/libs.tech/klayout klayout -b -r gen_gds_ihp.py \
        [-rd out=build/string_ihp.gds] [-rd check=true]

The string is 255 `rppd` units of 1 kOhm (W=2 um, 260 ohm/sq -> L=7.692 um)
in series, with one M1 tap pad per node (`t1..t254`, `vss`, `vref`).  The
transmission-gate tree and the output follower remain class-C hand layout,
exactly as in the gf180 leaf; this generator owns the matched resistor array.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
M1 = (8, 0)
M1_PIN = (8, 2)
M1_LABEL = (8, 25)


def load_cfg():
    import yaml
    with open(HERE / "string.yaml") as f:
        return yaml.safe_load(f)


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
    out_path = Path(opt("out", str(HERE / "build" / "string_ihp.gds")))
    do_check = str(opt("check", "true")).lower() in ("1", "true", "yes")
    cfg = load_cfg()
    n = 255
    ly = pya.Layout()
    ly.dbu = 0.001
    ly.technology_name = "sg13g2"
    top = ly.create_cell("dac_string_ihp")
    m1 = ly.layer(*M1)
    m1_pin = ly.layer(*M1_PIN)
    m1_lbl = ly.layer(*M1_LABEL)

    libdir = root / "libs.tech" / "klayout" / "python"
    if str(libdir) not in sys.path:
        sys.path.insert(0, str(libdir))
    if str(libdir / "pycell4klayout-api" / "source" / "python") not in sys.path:
        sys.path.insert(0, str(libdir / "pycell4klayout-api" / "source" / "python"))
    import sg13g2_pycell_lib  # noqa: F401

    unit = ly.create_cell("rppd", "SG13_dev", {
        "Calculate": "l", "R": "4.004k", "w": "2u", "b": 0, "ps": "0.28u"})
    boxes = sorted((sh.bbox() for sh in unit.shapes(m1_pin).each()),
                   key=lambda b: b.top)
    pa = boxes[0].center()
    pb = boxes[-1].center()
    ua = (pa.x * ly.dbu, pa.y * ly.dbu)
    ub = (pb.x * ly.dbu, pb.y * ly.dbu)
    pitch = (ub[1] - ua[1]) + 2.6
    print(f"unit pins y {ua[1]:.2f}..{ub[1]:.2f}, pitch {pitch:.2f}")

    def place(cell, x, y, rot=None):
        tr = (pya.Trans(rot, pya.Point(int(x * 1000), int(y * 1000)))
              if rot is not None else pya.Trans(int(x * 1000), int(y * 1000)))
        top.insert(pya.CellInstArray(cell.cell_index(), tr))
        return tr

    def apply(tr, pt):
        p = tr * pya.Point(int(round(pt[0] * 1000)), int(round(pt[1] * 1000)))
        return (p.x / 1000.0, p.y / 1000.0)

    routes = {}

    def box(x1, y1, x2, y2):
        return pya.Box(int(round(x1 * 1000)), int(round(y1 * 1000)),
                       int(round(x2 * 1000)), int(round(y2 * 1000)))

    def wire(pts, net, width=0.4):
        for (x1, y1), (x2, y2) in zip(pts, pts[1:]):
            if abs(x1 - x2) < 1e-9 and abs(y1 - y2) < 1e-9:
                continue
            w = width / 2
            b = box(min(x1, x2) - w, min(y1, y2) - w,
                    max(x1, x2) + w, max(y1, y2) + w)
            top.shapes(m1).insert(b)
            routes.setdefault(net, pya.Region()).insert(b)

    def pad(x, y, name):
        h = 0.4
        b = box(x - h, y - h, x + h, y + h)
        top.shapes(m1).insert(b)
        routes.setdefault(name, pya.Region()).insert(b)
        top.shapes(m1_lbl).insert(
            pya.Text(name, pya.Trans(int(x * 1000), int(y * 1000))))

    terminals = []
    xs = [i * pitch for i in range(n)]
    for x in xs:
        place(unit, x, 0.0, rot=pya.Trans.R270)

    y_series = -2.2
    for i in range(n - 1):
        tr = pya.Trans(pya.Trans.R270, pya.Point(int(xs[i] * 1000), 0))
        b = apply(tr, ub)
        tr2 = pya.Trans(pya.Trans.R270, pya.Point(int(xs[i + 1] * 1000), 0))
        a = apply(tr2, ua)
        net = f"t{i + 1}"
        wire([b, (b[0], y_series), (a[0], y_series), a], net)
        pad((b[0] + a[0]) / 2, y_series, net)
        terminals.append((net, (b[0] + a[0]) / 2, y_series))

    tr0 = pya.Trans(pya.Trans.R270, pya.Point(0, 0))
    a0 = apply(tr0, ua)
    pad(a0[0] - 1.5, a0[1], "vss")
    top.shapes(m1).insert(box(a0[0] - 1.5 - 0.4, a0[1] - 0.4,
                              a0[0] + 0.4, a0[1] + 0.4))
    wire([a0, (a0[0] - 1.5, a0[1])], "vss")
    terminals.append(("vss", a0[0] - 1.5, a0[1]))

    trn = pya.Trans(pya.Trans.R270, pya.Point(int(xs[-1] * 1000), 0))
    bn = apply(trn, ub)
    pad(bn[0] + 1.5, bn[1], "vref")
    top.shapes(m1).insert(box(bn[0] + 1.1, bn[1] - 0.4,
                              bn[0] + 1.9, bn[1] + 0.4))
    wire([bn, (bn[0] + 1.5, bn[1])], "vref")
    terminals.append(("vref", bn[0] + 1.5, bn[1]))

    ly.flatten(top.cell_index(), -1, True)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    ly.write(str(out_path))
    print(f"wrote {out_path}  (bbox {top.dbbox()})")
    rc = 0
    if do_check:
        allm1 = pya.Region(top.begin_shapes_rec(m1))
        bad = []
        for net, x, y in terminals:
            probe = pya.Region(box(x - 0.15, y - 0.15, x + 0.15, y + 0.15))
            if (probe & allm1).is_empty():
                bad.append((net, x, y))
        print(f"terminals : {len(terminals) - len(bad)}/{len(terminals)} covered")
        for b in bad[:8]:
            print("  MISSING", b)
        rc |= bool(bad)
        names = sorted(routes)
        shorts = []
        for i, n1 in enumerate(names):
            for n2 in names[i + 1:]:
                if not (routes[n1] & routes[n2]).is_empty():
                    shorts.append((n1, n2))
        print(f"net shorts: {len(shorts)}")
        for s in shorts[:8]:
            print("  SHORT", s)
        rc |= bool(shorts)
    return rc


if __name__ == "__main__":
    import pya  # noqa: E402
    sys.exit(main())
