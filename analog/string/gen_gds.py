#!/usr/bin/env python3
r"""Generate the resistor-string (Kelvin divider) array: 255 matched units.

This is the reusable device generator for P2.  It places the PDK's
`ppolyf_u_resistor` PCell for every unit and draws the series/tap/bulk straps
on M1; it never draws resistor geometry itself.  The switch tree and the
output follower are *not* here (see README): the tree is 255 transmission
gates whose layout is a routing problem, not a device-array problem, and the
follower is a separate leaf.

Floorplan (one row; all dimensions um):

    y=3   ------------------------------------------------- vss bus
           |     |     |     |            (one drop per unit p-tap)
    y=2   [tap] [tap] [tap] ...           p-tap tabs
    y=1   =====unit=====unit=====unit====  series body (x = 5.714)
    y=-1  \___/     \___/     \___/        series strap + t_k pad

* Unit pitch is `unit_l + 2.6`: 2.6 um is what the PCell needs between the
  right M1 terminal of one unit and the p-tap M1 tab of the next (0.37 um
  metal gap; the poly gap is larger).  This is the same class of bug the R-2R
  DRC found at X_RB, so the margin is explicit here.
* Every node k gets a tap pad on M1 at y=-1, labelled `t<k>`.  Node 0 is the
  bottom of the string (`vss`, also the bulk bus) and node 255 is `vref`.
* The series strap dives to y=-1 so it passes *under* the next unit's p-tap,
  which spans y=0..2.  A strap at the device centreline would short to the
  tap.

Usage (KLayout's Python interpreter, not the system python3):
    klayout -b -r gen_gds.py [-rd out=build/string.gds] [-rd check=true]
                             [-rd bits=8] [-rd unit_l=5.714]
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import pya

HERE = Path(__file__).resolve().parent

# --- PCell geometry, from gf180mcuA/.../klayout_api_cells/draw_res.py --------
POLY_ENC = 0.51          # poly extension past the body on each side
TERM_IN = 0.16           # M1 terminal strip inner offset from body edge
TERM_HW = 0.17           # M1 terminal strip half-width
TAB_X = (-1.73, -1.37)   # p-tap (bulk) tab, local x

M1 = (34, 0)
M1_LABEL = (34, 10)


def term_a(length: float):
    return (-TERM_IN - TERM_HW, 1.0)


def term_b(length: float):
    return (length + TERM_IN + TERM_HW, 1.0)


def apply(trans, pt):
    p = trans * pya.Point(int(round(pt[0] * 1000)), int(round(pt[1] * 1000)))
    return (p.x / 1000.0, p.y / 1000.0)


def load_cfg():
    try:
        import yaml
    except ImportError:  # pragma: no cover
        sys.exit("PyYAML is required: pip install pyyaml")
    with open(HERE / "string.yaml") as f:
        return yaml.safe_load(f)


def pdk_root(pdk: str, override: str | None) -> Path:
    if override:
        return Path(override)
    fam = {"gf180": ("gf180mcu", "gf180mcuA"),
           "sky130": ("sky130", "sky130A")}[pdk]
    base = Path(os.path.expanduser(f"~/.ciel/ciel/{fam[0]}/versions"))
    if not base.is_dir():
        sys.exit(f"{base} not found; pass -rd pdkroot=<dir>")
    return base / sorted(p.name for p in base.iterdir() if p.is_dir())[-1] / fam[1]


def main() -> int:
    g = globals()

    def opt(name, default=None):
        v = g.get(name, default)
        return v if isinstance(v, (str, int, float)) else default

    pdk = opt("pdk", "gf180")
    if pdk != "gf180":
        sys.exit(f"gen_gds.py: only gf180 is supported (got {pdk})")
    out_path = opt("out", str(HERE / "build" / "string.gds"))
    do_check = str(opt("check", "false")).lower() in ("1", "true", "yes")

    cfg = load_cfg()
    bits = int(opt("bits", cfg["bits"]))
    unit_l = float(opt("unit_l", cfg["unit_l"]))
    unit_w = float(cfg["unit_w"])
    n_units = 2 ** bits - 1
    n_taps = n_units + 1

    root = pdk_root(pdk, opt("pdkroot"))
    libdir = root / "libs.tech" / "klayout" / "tech" / "pymacros"
    if str(libdir) not in sys.path:
        sys.path.insert(0, str(libdir))
    from klayout_api_cells import gf180mcu_klayoutapi  # noqa: E402

    lib = gf180mcu_klayoutapi()
    ly = pya.Layout()
    ly.dbu = 0.001
    top = ly.create_cell("dac_string_ana")
    m1 = ly.layer(*M1)
    m1_lbl = ly.layer(*M1_LABEL)

    # PCell: `l` is the short (drawn width) dimension, `w` the long (length).
    unit = ly.create_cell("ppolyf_u_resistor", lib.name(),
                          {"l": unit_w, "w": unit_l})

    # Pitch leaves 0.37 um between the right M1 terminal of a unit (ends at
    # L + 0.50) and the p-tap M1 tab of the next (starts at pitch - 1.73).
    pitch = unit_l + 2.6
    y_body = 0.0
    y_series = -1.0
    y_bus = 3.0
    strap_w = 0.4
    pad = 0.8

    routes = {}
    terminals = []

    def box(x1, y1, x2, y2):
        return pya.Box(int(round(x1 * 1000)), int(round(y1 * 1000)),
                       int(round(x2 * 1000)), int(round(y2 * 1000)))

    def wire(pts, net, width=strap_w):
        for (x1, y1), (x2, y2) in zip(pts, pts[1:]):
            if abs(x1 - x2) < 1e-9 and abs(y1 - y2) < 1e-9:
                continue
            w = width / 2
            b = box(min(x1, x2) - w, min(y1, y2) - w,
                    max(x1, x2) + w, max(y1, y2) + w)
            top.shapes(m1).insert(b)
            routes.setdefault(net, pya.Region()).insert(b)

    def label(x, y, name):
        top.shapes(m1_lbl).insert(
            pya.Text(name, pya.Trans(int(x * 1000), int(y * 1000))))

    def tappad(x, y, name):
        top.shapes(m1).insert(box(x - pad / 2, y - pad / 2,
                                  x + pad / 2, y + pad / 2))
        routes.setdefault(name, pya.Region()).insert(
            box(x - pad / 2, y - pad / 2, x + pad / 2, y + pad / 2))
        label(x, y, name)
        terminals.append((name, x, y))

    xs = [i * pitch for i in range(n_units)]
    for i, x in enumerate(xs):
        tr = pya.Trans(int(round(x * 1000)), int(round(y_body * 1000)))
        top.insert(pya.CellInstArray(unit.cell_index(), tr))

    # --- series chain + one tap pad per node --------------------------------
    for i in range(n_units - 1):
        x1 = xs[i] + unit_l + TERM_IN + TERM_HW      # right terminal centre
        x2 = xs[i + 1] - TERM_IN - TERM_HW           # left terminal centre
        net = f"t{i + 1}"
        # Dives below the device band so it passes under the next p-tap.
        wire([(x1, 1.0), (x1, y_series), (x2, y_series), (x2, 1.0)], net)
        tappad((x1 + x2) / 2, y_series, net)

    # node 0 (left end) and node 255 (right end) get their own pads
    x0 = xs[0] - TERM_IN - TERM_HW
    top.shapes(m1).insert(box(x0 - pad / 2, 1 - pad / 2,
                              x0 + pad / 2, 1 + pad / 2))
    routes.setdefault("vss", pya.Region()).insert(
        box(x0 - pad / 2, 1 - pad / 2, x0 + pad / 2, 1 + pad / 2))
    label(x0, 1.0, "vss")
    terminals.append(("vss", x0, 1.0))

    xn = xs[-1] + unit_l + TERM_IN + TERM_HW
    top.shapes(m1).insert(box(xn - pad / 2, 1 - pad / 2,
                              xn + pad / 2, 1 + pad / 2))
    routes.setdefault("vref", pya.Region()).insert(
        box(xn - pad / 2, 1 - pad / 2, xn + pad / 2, 1 + pad / 2))
    label(xn, 1.0, "vref")
    terminals.append(("vref", xn, 1.0))

    # --- bulk (p-tap) bus ---------------------------------------------------
    tx = (TAB_X[0] + TAB_X[1]) / 2
    for x in xs:
        wire([(x + tx, 2.0), (x + tx, y_bus)], "vss")
    wire([(xs[0] + tx, y_bus), (xs[-1] + tx, y_bus)], "vss")
    # Tie the bottom of the string (node 0) to the bulk bus.
    wire([(x0, 1.0), (x0, y_bus)], "vss")

    if do_check:
        problems = []
        # terminal coverage: pad centre inside a shape of the same net
        for net, x, y in terminals:
            if net not in routes:
                problems.append(f"{net}: no route")
                continue
            pt = pya.Point(int(x * 1000), int(y * 1000))
            if not any(b.bbox().contains(pt) for b in routes[net].each()):
                problems.append(f"{net}: pad not on metal")
        # pairwise net overlap (a short) — only between different nets
        names = sorted(routes)
        for a in range(len(names)):
            for b in range(a + 1, len(names)):
                inter = routes[names[a]] & routes[names[b]]
                if not inter.is_empty():
                    bb = inter.bbox()
                    problems.append(
                        f"SHORT {names[a]} <-> {names[b]} at "
                        f"({bb.left / 1000:.2f},{bb.bottom / 1000:.2f})")
        if problems:
            print(f"wrote {out_path}  (bbox {_bbox(top)})")
            for p in problems:
                print("  " + p)
            sys.exit(1)
        print(f"terminals : {len(terminals)}/{n_taps} labelled")
        print("net shorts: 0")

    ly.write(out_path)
    print(f"wrote {out_path}  (bbox {_bbox(top)})")
    return 0


def _bbox(top):
    b = top.bbox()
    return (f"({b.left / 1000:.1f},{b.bottom / 1000:.1f};"
            f"{b.right / 1000:.1f},{b.top / 1000:.1f})")


if __name__ == "__main__":
    sys.exit(main())
