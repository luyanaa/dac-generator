#!/usr/bin/env python3
"""Generate the R-2R analog-core GDS: matched resistor array + ladder straps.

This is a *device generator with a fixed floorplan*, not a placer: every unit
comes from the PDK's `ppolyf_u_resistor` PCell, so the device geometry (poly,
SAB, implant, contacts, M1 terminals, p-tap) is exactly what the PDK draws.
The script only places instances, straps them on M1, and labels the nets.

Floorplan (all dimensions um):

    row i  = one branch (driver side -> node side)
    y_i    = i * 155            i = 0..7
    y_-1   = -155               termination 2R (node0 -> vss)

      x=0          150.3  152.4      301.1   306   316
      |<-- ra -->|        |<-- rb -->|      |bus|  |series|
      A          B  (U)   A          B      |   |  | 1R x7|
                                             node bus

* `ra` is a full unit, `rb` is the trimmed unit, so each 2R branch is
  unit + trim in series, as in `gen_r2r.py`.
* The node is the right-hand end of `rb`; all nodes are collected on a
  vertical M1 bus at x = 306.
* The seven 1R series units are vertical (R90) at x = 316, one per node pair,
  and strap to the same bus.  Rotating a poly rectangle does not change its
  resistance; it does mean the array is not a single-orientation array, which
  is called out in the README.
* Each unit's p-tap (bulk) tab is on its left edge, x = -1.73..-1.37 in local
  coordinates.  No metal is routed through that window at the device's own y
  band: every escape goes down into the routing channel first.

Ports (M1 pads + labels):
    b0..b7   driver inputs, bottom edge
    vout     node7
    vss      termination return

What this file does NOT contain yet: the per-bit CMOS buffers (they are
modelled in `gen_r2r.py` as `drv_wn`/`drv_wp`) and the vdd/vss ring.  See
README "Status".

Usage (KLayout's Python interpreter, not the system python3):
    klayout -b -r gen_gds.py [-rd out=build/r2r.gds] [-rd check=true]
                             [-rd pdk=gf180] [-rd pdk_root=<dir>]
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent

# --- PCell geometry, from gf180mcuA/.../klayout_api_cells/draw_res.py --------
# A unit of length L (model r_length), width W = 2.0, drawn with its body
# starting at the instance origin and running along +x.
POLY_ENC = 0.51          # poly extension past the body on each side
TERM_HW = 0.17           # terminal strip half-width (strip is 0.34 wide)
TERM_IN = 0.16           # strip inner offset from body edge
TAB_X = (-1.73, -1.37)   # p-tap (bulk) tab, local x

# --- floorplan --------------------------------------------------------------
PITCH = 155.0            # row pitch; a 150 um unit + routing channel
# rb origin.  This is set by metal, not by poly: ra's right M1 terminal ends
# at x = unit_l + TERM_IN + TERM_HW + 0.2 = 150.53 and rb's p-tap M1 tab starts
# at X_RB - 1.73, so X_RB = 152.4 left only a 0.14 um gap and tripped M1.2a
# (0.23 um).  152.7 gives a 0.44 um gap; the poly gap is 2.19.
X_RB = 152.7             # rb origin (clears ra's M1 terminal + rb's tab)
X_BUS = 306.0            # node bus centreline
BUS_W = 2.0
X_SER = 316.0            # vertical 1R column (body x = X_SER-2 .. X_SER)
Y_PAD = -340.0           # driver pad row
PAD = 8.0                # pad size

M1 = (34, 0)
M1_LABEL = (34, 10)

# terminal centres of an unrotated unit, relative to its origin
def term_a(length: float) -> tuple[float, float]:
    return (-TERM_IN - TERM_HW, 1.0)


def term_b(length: float) -> tuple[float, float]:
    return (length + TERM_IN + TERM_HW, 1.0)


def tab_centre(length: float) -> tuple[float, float]:
    return ((TAB_X[0] + TAB_X[1]) / 2, 1.0)


def apply(trans, pt):
    """Apply a pya.Trans to a float (um) point."""
    p = trans * pya.Point(int(round(pt[0] * 1000)), int(round(pt[1] * 1000)))
    return (p.x / 1000.0, p.y / 1000.0)


def main() -> int:
    # KLayout passes script options as -rd name=value, which land in globals().
    g = globals()

    def opt(name, default=None):
        v = g.get(name, default)
        # -rd values are strings; module-level functions also live in globals()
        return v if isinstance(v, (str, int, float)) else default

    pdk = opt("pdk", "gf180")
    if pdk != "gf180":
        sys.exit(f"gen_gds.py: only gf180 is supported (got {pdk})")
    out_path = opt("out", str(HERE / "build" / "r2r.gds"))
    do_check = str(opt("check", "false")).lower() in ("1", "true", "yes")
    pdk_root_opt = opt("pdkroot")

    cfg = load_cfg()
    root = pdk_root(pdk, pdk_root_opt)
    libdir = root / "libs.tech" / "klayout" / "tech" / "pymacros"
    if str(libdir) not in sys.path:
        sys.path.insert(0, str(libdir))
    from klayout_api_cells import gf180mcu_klayoutapi  # noqa: E402

    lib = gf180mcu_klayoutapi()
    ly = pya.Layout()
    ly.dbu = 0.001
    top = ly.create_cell("dac_r2r_ana")
    m1 = ly.layer(*M1)
    m1_lbl = ly.layer(*M1_LABEL)

    unit_cell = ly.create_cell("ppolyf_u_resistor", lib.name(),
                               {"l": cfg["unit_w"], "w": cfg["unit_l"]})
    trim_cell = ly.create_cell("ppolyf_u_resistor", lib.name(),
                               {"l": cfg["unit_w"], "w": cfg["trim_l"]})

    def place(cell, x, y, rot=None):
        trans = pya.Trans(rot, pya.Point(int(x * 1000), int(y * 1000))) \
            if rot is not None else pya.Trans(int(x * 1000), int(y * 1000))
        top.insert(pya.CellInstArray(cell.cell_index(), trans))
        return trans

    routes = {}             # net -> pya.Region of the straps we drew
    tabs = []               # p-tap windows, in absolute um

    def wire(pts, net, width=0.4):
        """Axis-aligned M1 strap through a list of (x, y) points."""
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

    nbits = int(cfg["bits"])
    terminals = []          # (net, x, y) for --check

    def nname(i):
        """Route key for ladder node i; node nbits-1 is the external output."""
        return "vout" if i == nbits - 1 else f"n{i}"

    def yrow(i):
        return i * PITCH

    # --- branches and termination ------------------------------------------
    for i in range(-1, nbits):
        y = yrow(i)
        cell_b = unit_cell if i == -1 else trim_cell
        len_b = cfg["unit_l"] if i == -1 else cfg["trim_l"]
        ta = place(unit_cell, 0.0, y)          # ra (driver / vss side)
        tb = place(cell_b, X_RB, y)            # rb (node side)
        a0 = apply(ta, term_a(cfg["unit_l"]))
        b0 = apply(ta, term_b(cfg["unit_l"]))
        a1 = apply(tb, term_a(len_b))
        b1 = apply(tb, term_b(len_b))
        # mid node: U-route through the channel below the row (the tab of rb
        # sits between the two devices at the device y band).
        net_mid = f"mid{i}"
        net_node = "n0" if i == -1 else nname(i)
        cy = y - 6.0
        wire([b0, (b0[0], cy), (a1[0], cy), a1], net_mid)
        terminals += [(net_mid, *b0), (net_mid, *a1)]
        # node (or vss for the termination row) goes to the bus
        wire([b1, (X_BUS, b1[1])], net_node)
        terminals.append((net_node, *b1))
        # far end of ra: bit input, or vss for the termination row
        if i >= 0:
            net_bit = f"b{i}"
            xd = -14.0 - i * 12.0
            wire([a0, (a0[0], y - 6.0), (xd, y - 6.0), (xd, Y_PAD)], net_bit)
            pad(xd, Y_PAD, net_bit)
        else:
            net_bit = "vss"
            # below the pad row, so it never crosses the driver drops
            wire([a0, (a0[0], Y_PAD - 20.0), (-140.0, Y_PAD - 20.0),
                  (-140.0, Y_PAD)], net_bit)
            pad(-140.0, Y_PAD, net_bit)
        terminals.append((net_bit, *a0))
        # p-tap window of both devices (must stay metal-free)
        for tr, ln in ((ta, cfg["unit_l"]), (tb, len_b)):
            a = apply(tr, (TAB_X[0], -0.3))
            b = apply(tr, (TAB_X[1], 2.3))
            tabs.append((min(a[0], b[0]), min(a[1], b[1]),
                         max(a[0], b[0]), max(a[1], b[1])))

    # --- node tracks --------------------------------------------------------
    # One vertical M1 track per node, all on the same x.  They never touch
    # because each spans only its own row: [y_i - 10, y_i + 2.5].  A single
    # "bus" would short every ladder node together.
    y_hi = yrow(nbits - 1) + 2.5
    for i in range(nbits):
        y_lo = yrow(-1) + 1.0 if i == 0 else yrow(i) - 10.0
        # The top node is the external output; keep one route key for it so
        # the self-check does not see "n7" and "vout" as two nets in a short.
        wire([(X_BUS, y_lo), (X_BUS, yrow(i) + 2.5)], nname(i), width=BUS_W)

    # --- series 1R units (vertical, R90) ------------------------------------
    for i in range(1, nbits):
        y0 = yrow(i - 1) + 2.5
        tr = place(unit_cell, X_SER, y0, rot=pya.Trans.R90)
        # R90: local (x, y) -> (-y, x)
        bot = apply(tr, term_a(cfg["unit_l"]))
        topp = apply(tr, term_b(cfg["unit_l"]))
        wire([bot, (X_BUS, bot[1])], nname(i - 1))
        wire([topp, (X_BUS, topp[1])], nname(i))
        terminals.append((f"n{i-1}", *bot))
        terminals.append((f"n{i}", *topp))
        # On the strap, not beside it: a label that misses the metal becomes a
        # dangling port in the extracted netlist (n*_uq0 in the first LVS run).
        label(bot[0] - 1.0, bot[1], f"n{i-1}")
        a = apply(tr, (TAB_X[0], -0.3))
        b = apply(tr, (TAB_X[1], 2.3))
        tabs.append((min(a[0], b[0]), min(a[1], b[1]),
                     max(a[0], b[0]), max(a[1], b[1])))

    # --- labels + vout pad --------------------------------------------------
    # n7 is the output; label the pad with the external name instead of adding
    # a second, floating text beside it.  One label per external net, on metal.
    for i in range(nbits - 1):
        label(X_BUS, yrow(i) - 4.0, f"n{i}")
    vout_y = y_hi + 12.0
    wire([(X_BUS, y_hi), (X_BUS, vout_y)], "vout")
    pad(X_BUS, vout_y, "vout")

    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    ly.write(str(out))
    print(f"wrote {out}  (bbox {top.dbbox()})")

    rc = 0
    if do_check:
        rc |= verify(top, ly, m1, terminals, routes, tabs)
    return rc


def verify(top, ly, m1, terminals, routes, tabs) -> int:
    """Three checks that catch the mistakes a layout generator actually makes.

    1. every terminal point has M1 under it (transform/placement errors),
    2. no two distinct nets share metal (short),
    3. no strap crosses a resistor's p-tap window (net-to-substrate short).
    """
    rc = 0
    allm1 = pya.Region(top.begin_shapes_rec(m1))

    bad = []
    for net, x, y in terminals:
        probe = pya.Region(pya.Box(int((x - 0.15) * 1000), int((y - 0.15) * 1000),
                                   int((x + 0.15) * 1000), int((y + 0.15) * 1000)))
        if (probe & allm1).is_empty():
            bad.append((net, x, y))
    print(f"terminals : {len(terminals) - len(bad)}/{len(terminals)} covered")
    for b in bad[:12]:
        print(f"  MISSING {b[0]} at ({b[1]:.2f}, {b[2]:.2f})")
    rc |= bool(bad)

    # The bus is shared on purpose: every node strap touches it, and touching
    # metal of different nets is a short.  Check each net against the bus plus
    # every other net, ignoring the terminal strips of the devices themselves.
    names = sorted(routes)
    shorts = []
    for i, n1 in enumerate(names):
        for n2 in names[i + 1:]:
            if (routes[n1] & routes[n2]).is_empty():
                continue
            shorts.append((n1, n2))
    print(f"net shorts: {len(shorts)}")
    for s in shorts[:12]:
        print(f"  SHORT {s[0]} <-> {s[1]}")
    rc |= bool(shorts)

    overlapping = []
    for net, reg in routes.items():
        for (x0, y0, x1, y1) in tabs:
            win = pya.Region(pya.Box(int(x0 * 1000), int(y0 * 1000),
                                     int(x1 * 1000), int(y1 * 1000)))
            if not (reg & win).is_empty():
                overlapping.append((net, x0, y0))
    print(f"tab clashes: {len(overlapping)}")
    for o in overlapping[:12]:
        print(f"  TAB {o[0]} near ({o[1]:.2f}, {o[2]:.2f})")
    rc |= bool(overlapping)
    return rc


def load_cfg():
    try:
        import yaml
    except ImportError:  # pragma: no cover
        sys.exit("PyYAML is required: pip install pyyaml")
    with open(os.path.join(HERE, "r2r.yaml")) as f:
        return yaml.safe_load(f)


def pdk_root(pdk: str, override: str | None) -> Path:
    if override:
        return Path(override)
    fam, name = "gf180mcu", "gf180mcuA"
    base = Path(os.path.expanduser(f"~/.ciel/ciel/{fam}/versions"))
    if not base.is_dir():
        sys.exit(f"{base} not found; pass --pdk-root")
    ver = sorted(p.name for p in base.iterdir() if p.is_dir())[-1]
    return base / ver / name


if __name__ == "__main__":
    import pya  # noqa: E402  (only available under the KLayout interpreter)
    sys.exit(main())
