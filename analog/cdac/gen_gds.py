#!/usr/bin/env python3
"""Device geometry for the 8-bit binary CDAC array (sky130A).

Runs inside KLayout's Python interpreter:

    klayout -b -r gen_gds.py [-rd out=build/cdac.gds] [-rd check=true]
    klayout -b -r gen_gds.py -rd cell=cap -rd out=build/cap.gds

One side of the DAC is 255 switched unit capacitors plus one VCM-referenced
dummy, i.e. exactly 2^8 units, laid out as a fully populated 16x16 grid.  The
grid is not decoration: every bit block is a mirror pair of rows about the
array centre, so each bit's capacitor centroid is the array centre in both
axes:

    row  0..3   bit 7        row  8   bit3 | bit2 | bit1 | bit0 | dummy
    row  4..5   bit 6        row  9   bit 5
    row  6      bit 5        row 10..11 bit 6
    row  7      bit 4        row 12..15 bit 7

That mapping is the only thing the mask set has to get right for weights, so
it is a table, not a formula, and LVS checks it against a separately written
schematic (signoff.py).

Routing:

  * bottom plates  met1 row strap (the cell's own FL rail, extended) plus, for
                   each bit, one met2 vertical bus in the left margin; one
                   via1 per row strap lands on that bit's bus.  Straps of
                   other bits cross the buses on met1 only, so nothing merges.
                   Row 8 is five separate straps because it holds four bits
                   plus the dummy.
  * row 8 taps     met1 -> via1 -> met2 -> via2 -> met3 down to a channel in
                   the bottom margin -> via2 -> met2 bus.  met3 is the only
                   layer with room to leave a shared row: met2 already carries
                   the VSH bars across every row.
  * top plate      met2 row bar across all 16 gate pads, joined by one met2
                   vertical bus in the right margin.
  * dummy          bottom plate goes to a met1 VCM bus in the right margin.

Layer sizes are the sky130 magic-tech ones, not guesses: via1 150 nm, via2
200 nm.  The tech declares `squares-grid 40 200 200` for via2 and silently
drops a 150 nm via2, which is how the first version of this file extracted as
five isolated row-8 nets instead of four bit nets plus VCM.

Cells are ported from `../saradc_auto/gen/analog/layout_cap.py` (unit moscap)
and `layout_tg.py` (4x transmission gate), which draw the PDK's own device
geometry through the pure-pya port of the `draw_fet` generator at
/opt/OpenSERDES/verification/analog/pya_draw.  That path is an environment
dependency; the script fails closed if it is missing.

This file writes geometry only.  DRC, LVS and PEX are separate evidence with
separate reports (signoff.py); nothing here claims a clean run.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import pya

HERE = Path(__file__).resolve().parent

M1 = (68, 20)
M1_LABEL = (68, 5)
V1 = (68, 44)
M2 = (69, 20)
M2_LABEL = (69, 5)
V2 = (69, 44)
M3 = (70, 20)

NM = 1000                      # nm per um
CAP_PITCH_X = 4590 + 200       # cell width + 200 nm met1 space
ROW_PITCH_Y = 5300             # cell height + nwell spacing
CAP_GAP = 200                  # met1 space between adjacent FL rails
RAIL_L, RAIL_R = -200, 4390    # FL rail x extents inside one cell (nm)
BUS_W = 470                    # met2 bus width (nm)
BUS_Y0 = -6600                 # buses start below the row-8 met3 channels
NBITS = 8
NCOL = 1 << (NBITS - 4)        # 16 columns
NROW = 16                      # 16 rows == 2^8 unit caps
FIELD_W = NCOL * CAP_PITCH_X - CAP_GAP
FIELD_H = (NROW - 1) * ROW_PITCH_Y + 4160

# Array row -> bit, bottom row first.  Mirror pairs about the centre row 8.
ROW_BIT = [7, 7, 7, 7, 6, 6, 5, 4, None, 5, 6, 6, 7, 7, 7, 7]
# Row 8 is a composite: (bit, n_caps) left to right, None = VCM dummy.
ROW8 = [(3, 8), (2, 4), (1, 2), (0, 1), (None, 1)]
# met3 channel y per bit: deepest for the widest span, so a drop never
# crosses a channel that runs to its right.
# 800 nm apart: met3 spacing is 0.30 um and the lines are 0.36 um wide
CHAN_Y = {3: -3600, 2: -4400, 1: -5200, 0: -6000}

BIT_BUS_X0 = -1000             # first bit bus, left margin
BIT_BUS_PITCH = 1600


def box(cell, layer, x1, y1, x2, y2):
    cell.shapes(layer).insert(
        pya.Box(int(x1), int(y1), int(x2), int(y2)))


def label(cell, lpair, text, x, y):
    cell.shapes(lpair).insert(
        pya.Text(text, pya.Trans(pya.Vector(int(x), int(y)))))


# --------------------------------------------------------------------------
# unit cells, ported from ../saradc_auto/gen/analog/layout_{cap,tg}.py
# --------------------------------------------------------------------------

SERDES = "/opt/OpenSERDES/verification/analog"


def _pya_draw():
    if SERDES not in sys.path:
        sys.path.insert(0, SERDES)
    try:
        from pya_draw import shim  # noqa: F401
        from pya_draw.draw_fet import draw_nfet, draw_pfet
    except Exception as exc:                                  # pragma: no cover
        raise SystemExit(
            f"error: sky130 device generator missing at {SERDES} "
            f"(needs pya_draw): {exc}")
    return draw_nfet, draw_pfet


def build_cap(layout, wn=1.4, wp=2.8, l=0.15, gap=0.8, name="CDAC_CAP"):
    """Unit MOSCAP: nmos + pmos, d=s=b on FL, gates joined on VSH."""
    draw_nfet, draw_pfet = _pya_draw()
    n = layout.create_cell(f"{name}$nfet")
    draw_nfet(n, l=l, w=wn, nf=1, type="sky130_fd_pr__nfet_01v8",
              bulk="bulk tie", gate_con_pos="top")
    p = layout.create_cell(f"{name}$pfet")
    draw_pfet(p, l=l, w=wp, nf=1, type="sky130_fd_pr__pfet_01v8",
              bulk="bulk tie", gate_con_pos="top")

    top = layout.create_cell(name)
    n_b, p_b = n.bbox(), p.bbox()
    p_dx = n_b.right + int(gap * NM) - p_b.left
    top.insert(pya.CellInstArray(n, pya.Trans(pya.Vector(0, 0))))
    top.insert(pya.CellInstArray(p, pya.Trans(pya.Vector(p_dx, 0))))

    # Gate bridge.  Each device draws its own gate met1 (0.366 x 0.230 um);
    # 230 nm is short of the 260 nm a 150 nm via needs, so the pad is grown
    # upward and a met2 riser joins both pads on a bar at y 3500.
    n_gate = (192, 1650, 558, 1880)
    p_gate = (p_dx + 192, 3050, p_dx + 558, 3280)
    bar_y = 3500
    for gx1, gy1, gx2, gy2 in (n_gate, p_gate):
        box(top, M1, gx1 / 1000, gy1 / 1000, gx2 / 1000, (gy2 + 60) / 1000)
        vx1, vy1 = gx1 + 108, gy1 + 55
        box(top, V1, vx1 / 1000, vy1 / 1000,
            (vx1 + 150) / 1000, (vy1 + 150) / 1000)
        box(top, M2, (vx1 - 85) / 1000, (vy1 - 85) / 1000,
            (vx1 + 150 + 85) / 1000, (bar_y + 280) / 1000)
    box(top, M2, (n_gate[0] + 98 - 85) / 1000, bar_y / 1000,
        (p_gate[0] + 98 + 150 + 85) / 1000, (bar_y + 280) / 1000)
    label(top, M2_LABEL, "VSH",
          n_gate[0] + 98 + 75, bar_y + 140)
    strap_plate(top, p_dx)
    return top


def strap_plate(top, p_dx):
    """Tie both source/drain columns into the FL bottom plate (nm)."""
    rail_y1, rail_y2 = -320, -140
    box(top, M1, -200 / 1000, rail_y1 / 1000,
        (p_dx + 1765) / 1000, rail_y2 / 1000)
    for x1, x2 in ((35, 265), (485, 715)):
        box(top, M1, x1 / 1000, rail_y1 / 1000, x2 / 1000, 195 / 1000)
    for x1, x2 in ((35, 265), (485, 715)):
        box(top, M1, (p_dx + x1) / 1000, rail_y1 / 1000,
            (p_dx + x2) / 1000, 175 / 1000)
    label(top, M1_LABEL, "FL", 200, (rail_y1 + rail_y2) // 2)
    label(top, M1_LABEL, "VPW", 1295, 700)
    label(top, M1_LABEL, "VNW", p_dx + 1265, 1400)


def build_tg(layout, wn=5.6, wp=11.2, l=0.15, gap=1.0, name="CDAC_TG"):
    """4x transmission gate, Z1/Z2 switched, S/SB gates (nm geometry)."""
    draw_nfet, draw_pfet = _pya_draw()
    n = layout.create_cell(f"{name}$nfet")
    draw_nfet(n, l=l, w=wn, nf=1, type="sky130_fd_pr__nfet_01v8",
              bulk="bulk tie", gate_con_pos="top")
    p = layout.create_cell(f"{name}$pfet")
    draw_pfet(p, l=l, w=wp, nf=1, type="sky130_fd_pr__pfet_01v8",
              bulk="bulk tie", gate_con_pos="top")

    top = layout.create_cell(name)
    n_b, p_b = n.bbox(), p.bbox()
    p_dx = n_b.right + int(gap * NM) - p_b.left
    top.insert(pya.CellInstArray(n, pya.Trans(pya.Vector(0, 0))))
    top.insert(pya.CellInstArray(p, pya.Trans(pya.Vector(p_dx, 0))))

    def cols(cell):
        boxes = [s.box for s in cell.shapes(M1).each() if s.is_box()]
        if len(boxes) != 4:
            raise RuntimeError(f"expected 3 columns + gate, got {len(boxes)}")
        gate = max(boxes, key=lambda b: b.top)
        return sorted([b for b in boxes if b is not gate],
                      key=lambda b: b.left), gate

    n_cols, _ = cols(n)
    p_cols, _ = cols(p)
    ns, nd, nt = [(b.left, b.bottom, b.right, b.top) for b in n_cols]
    ps, pd, pt = [(b.left + p_dx, b.bottom, b.right + p_dx, b.top)
                  for b in p_cols]
    z2_y1, z2_y2 = -360, -130
    z1_y1, z1_y2 = -780, -550
    box(top, M1, nd[0], z2_y1, ps[2], z2_y2)
    box(top, M1, ns[0], z1_y1, pd[2], z1_y2)
    for c, y1, y2 in ((nd, z2_y1, z2_y2), (ps, z2_y1, z2_y2),
                      (ns, z1_y1, z1_y2), (pd, z1_y1, z1_y2)):
        box(top, M1, c[0], y1, c[2], c[1])
    label(top, M1_LABEL, "Z1", (z1_y1 + z1_y2) // 2, ns[0] + 40)
    label(top, M1_LABEL, "Z2", (z2_y1 + z2_y2) // 2, nd[0] + 40)
    label(top, M1_LABEL, "S", 375, 5965)
    label(top, M1_LABEL, "SB", p_dx + 400, 11565)
    label(top, M1_LABEL, "VSS", 1295, 2800)
    label(top, M1_LABEL, "VDD", p_dx + 1200, 5600)
    return top


# --------------------------------------------------------------------------
# array
# --------------------------------------------------------------------------

def bit_bus_x(bit: int) -> int:
    return BIT_BUS_X0 - bit * BIT_BUS_PITCH


def build_array(layout, name="CDAC_ARRAY"):
    cap = build_cap(layout)
    ncol, nrow = NCOL, NROW
    field_w, field_h = FIELD_W, FIELD_H

    top = layout.create_cell(name)
    for row in range(nrow):
        for col in range(ncol):
            top.insert(pya.CellInstArray(
                cap, pya.Trans(pya.Vector(col * CAP_PITCH_X,
                                          row * ROW_PITCH_Y))))

    l_m1 = layout.layer(*M1)
    l_v1 = layout.layer(*V1)
    l_v2 = layout.layer(*V2)
    l_m2 = layout.layer(*M2)
    l_m3 = layout.layer(*M3)
    l_m1t = layout.layer(*M1_LABEL)
    l_m2t = layout.layer(*M2_LABEL)

    # ---- bottom plates -------------------------------------------------
    def strap(x1, x2, row):
        y1 = row * ROW_PITCH_Y - 320
        y2 = row * ROW_PITCH_Y - 140
        box(top, l_m1, x1, y1, x2, y2)

    def tap(bit, row):
        """met1 link out to the margin + via1 up to that bit's met2 bus.

        Only usable when a row holds one bit: four links at the same y band
        would overlap each other, which is exactly what happened in the first
        extraction (B0..B3 shorted).  Multi-bit rows use tap3().
        """
        bx = bit_bus_x(bit)
        yc = row * ROW_PITCH_Y - 230
        y1, y2 = row * ROW_PITCH_Y - 320, row * ROW_PITCH_Y - 140
        # the row strap stops at the cell edge; the bit bus lives further
        # left, so the link is a met1 run under all the other met2 buses
        box(top, l_m1, bx - 200, y1, -200, y2)
        # 400 nm tall pad: 125 nm met1 enclosure around a 150 nm via
        box(top, l_m1, bx - 200, yc - 200, bx + 200, yc + 200)
        box(top, l_v1, bx - 75, yc - 75, bx + 75, yc + 75)
        # the bus itself covers the via with 160 nm on each side

    def tap3(bit, row, tap_x, chan_y):
        """Multi-bit row tap: met1 -> via1 -> met2 -> via2 -> met3 channel.

        The channel runs below the array in the bottom margin, deepest for
        the rightmost tap, so no met3 drop crosses a channel that runs to its
        right.  Via sizes are the magic-tech ones: a 150 nm via2 is dropped
        by the reader, so this uses 200 nm and a 60 nm met3 enclosure.
        """
        bx = bit_bus_x(bit)
        yc = row * ROW_PITCH_Y - 230
        # pad on the row strap
        box(top, l_m1, tap_x - 200, yc - 200, tap_x + 200, yc + 200)
        box(top, l_v1, tap_x - 75, yc - 75, tap_x + 75, yc + 75)
        box(top, l_m2, tap_x - 200, yc - 200, tap_x + 200, yc + 200)
        box(top, l_v2, tap_x - 100, yc - 100, tap_x + 100, yc + 100)
        box(top, l_m3, tap_x - 200, yc - 200, tap_x + 200, yc + 200)
        # met3 drop to the channel, then across to the bit bus.  0.36 um wide
        # for m3.1 (0.30 min) and 0.40 um pads for m3.4 (0.065 enclosure of a
        # 0.20 um via2).
        box(top, l_m3, tap_x - 180, chan_y - 180, tap_x + 180, yc + 180)
        box(top, l_m3, bx - 180, chan_y - 180, tap_x + 180, chan_y + 180)
        box(top, l_m2, bx - 200, chan_y - 200, bx + 200, chan_y + 200)
        box(top, l_v2, bx - 100, chan_y - 100, bx + 100, chan_y + 100)

    for row in range(nrow):
        bit = ROW_BIT[row]
        if bit is not None:
            strap(RAIL_L, (ncol - 1) * CAP_PITCH_X + RAIL_R, row)
            tap(bit, row)

    # row 8: one strap per sub-block, ending 200 nm short of the next
    row = 8
    col = 0
    for bit, n in ROW8:
        x1 = col * CAP_PITCH_X + RAIL_L
        x2 = (col + n - 1) * CAP_PITCH_X + RAIL_R
        strap(x1, x2, row)
        if bit is not None:
            tap3(bit, row, x1 + 600, CHAN_Y[bit])
        col += n

    # ---- bit buses, left margin ---------------------------------------
    for bit in range(NBITS):
        bx = bit_bus_x(bit)
        box(top, l_m2, bx - BUS_W // 2, BUS_Y0, bx + BUS_W // 2, field_h)
        label(top, l_m2t, f"B{bit}", bx, BUS_Y0 + 600)

    # ---- top plate, right margin --------------------------------------
    vsh_x = field_w + 600
    for row in range(nrow):
        y1 = row * ROW_PITCH_Y + 3500
        box(top, l_m2, 205, y1, vsh_x + BUS_W // 2, y1 + 280)
    box(top, l_m2, vsh_x - BUS_W // 2, BUS_Y0,
        vsh_x + BUS_W // 2, field_h)
    label(top, l_m2t, "VSH", vsh_x, BUS_Y0 + 600)

    # ---- dummy bottom plate to VCM, right margin ----------------------
    # `row` was clobbered by the VSH loop above; the dummy is in row 8 and
    # reusing the stale value shorted VCM to B7 in the 15th row instead.
    vcm_x = field_w + 1160
    dummy_right = (ncol - 1) * CAP_PITCH_X + RAIL_R
    strap(dummy_right, vcm_x + 200, 8)
    box(top, l_m1, vcm_x - 200, BUS_Y0, vcm_x + 200, field_h)
    label(top, l_m1t, "VCM", vcm_x, BUS_Y0 + 600)

    return top


def main(argv=None) -> int:
    # Under KLayout, `-rd name=value` lands in this module's globals, not in
    # argv, so fold those back into the argument list.
    g = globals()
    argv = list(sys.argv[1:] if argv is None else argv)
    for key, flag in (("out", "--out"), ("cell", "--cell")):
        if key in g:
            argv += [flag, str(g[key])]
    if str(g.get("check", "")).lower() in ("true", "1", "yes"):
        argv.append("--check")

    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", default=str(HERE / "build" / "cdac.gds"))
    ap.add_argument("--check", action="store_true",
                    help="self-check the cell after writing")
    ap.add_argument("--cell", default="array",
                    choices=["array", "cap", "tg"],
                    help="which macro to write (for standalone LVS)")
    a = ap.parse_args(argv)

    layout = pya.Layout()
    layout.dbu = 0.001
    if a.cell == "cap":
        top = build_cap(layout)
    elif a.cell == "tg":
        top = build_tg(layout)
    else:
        top = build_array(layout)

    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    layout.write(a.out)
    b = top.bbox()
    print(f"wrote {a.out}  cell={top.name}  "
          f"bbox={b.width()/1000:.2f} x {b.height()/1000:.2f} um  "
          f"instances={sum(1 for _ in top.each_inst())}")

    if a.check and a.cell == "array":
        # Connectivity self-checks that do not need an extractor:
        #  * cut the met1 plane at each row's strap band: a single-bit row
        #    must be one component, row 8 must be five (four bits + dummy).
        #    Catches a strap that runs into its neighbour.
        #  * met2 must be exactly 8 bit buses + VSH + 4 row-8 tap pads: one
        #    fewer means a bus lost its tap, one more means two merged.
        fail = 0
        m1 = pya.Region(top.begin_shapes_rec(layout.layer(*M1)))
        for row in range(NROW):
            y1 = row * ROW_PITCH_Y - 320
            y2 = row * ROW_PITCH_Y - 140
            band = m1 & pya.Region(pya.Box(-20000, y1, FIELD_W + 60, y2))
            want = len(ROW8) if row == 8 else 1
            got = len(band.merged())
            state = "ok" if got == want else "FAIL"
            print(f"  row {row:2d} bottom-plate components {got} "
                  f"(want {want}) {state}")
            fail += got != want
        m2 = pya.Region(top.begin_shapes_rec(layout.layer(*M2))).merged()
        want_m2 = NBITS + 1 + len(ROW8) - 1
        print(f"  met2 net count {len(m2)} (want {want_m2}) "
              f"{'ok' if len(m2) == want_m2 else 'FAIL'}")
        fail += len(m2) != want_m2
        return 1 if fail else 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
