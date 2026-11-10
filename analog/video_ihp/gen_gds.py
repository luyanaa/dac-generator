#!/usr/bin/env python3
"""IHP sg13g2 dump-tail video array: 255 cells + replica, 1022 devices.

    KLAYOUT_PATH=<pdk>/libs.tech/klayout klayout -b -r gen_gds.py \
        [-rd out=build/video_ihp.gds] [-rd dbg_cells=2]

The devices are the PDK's own `SG13_dev` PCells (mirror pmos 8/1, cascode
pmos 8/0.5, pair nmos 4/0.28).  The PCell draws source/drain on Metal1 and
the gate as a bare GatPoly stripe, so this generator adds the gate lands, the
bulk taps (ntap1/ptap1) and the merged nwell bar - the cell core that is DRC
0 on its own.

Cell (7.5 um pitch, the 3.75 um pin grid):

    vdd - (mirror) - md - (cascode) - cd - nmos pair - iout / idump

Routing layers are chosen around the two gate buses:
  * vbp is Metal2 at y -1.2..-1.0 (the mirror gate has a via/riser),
  * vcp is Metal1 at y -1.6..-1.4 (the cascode gate neck passes *under* the
    vbp bus; a Metal2 vcp riser would short to vbp),
  * cd is Metal3, so it crosses both bias buses without touching them,
  * iout/idump are Metal3 buses below the pair, vdd is a Metal3 plane above
    the row, vss a Metal1 rail below the pad row.

The replica (right end) is the mirror+cascode, diode-connected, no switch.
"""
from __future__ import annotations

import sys

import pya

# IHP layer map (PDK sg13g2.lyp / DRC decks)
M1 = (8, 0)
M1L = (8, 25)
CONT = (6, 0)
POLY = (5, 0)
NW = (31, 0)
V1 = (19, 0)
M2 = (10, 0)
M2L = (10, 25)
V2 = (29, 0)
M3 = (30, 0)
M3L = (30, 25)

PDK_PY = "/grid/dac-generator/pdks/ihp-sg13g2/libs.tech/klayout/python"
sys.path.insert(0, PDK_PY)
sys.path.insert(0, PDK_PY + "/pycell4klayout-api/source/python")
import sg13g2_pycell_lib  # noqa: E402,F401  (registers SG13_dev)

PITCH = 7.5
MX, CX, PY = 0.31, 3.00, -6.40
PAD_Y = (-10.00, -9.60)
PAD_W = 0.60
PIN_A, PIN_B = 2.25, 6.00

# device terminal geometry (relative to the device origin)
PMOS1 = {"rail_l": (0.07, 0.23), "rail_r": (1.45, 1.61),
         "poly": (0.34, 1.34), "gc": 0.84}
PMOS05 = {"rail_l": (0.07, 0.23), "rail_r": (0.95, 1.11),
          "poly": (0.34, 0.84), "gc": 0.59}
NMOS = {"rail_l": (0.07, 0.23), "rail_r": (0.73, 0.89),
        "poly": (0.34, 0.62), "gc": 0.48}


def rect(x1, y1, x2, y2):
    q = lambda v: int(round(round(v / 0.005) * 5))
    return pya.Box(q(x1), q(y1), q(x2), q(y2))


def main() -> int:
    g = globals()
    out_path = g.get("out", "/grid/dac-generator/analog/video_ihp/build/"
                             "video_ihp.gds")
    dbg = int(g.get("dbg_cells", 255))
    n = dbg if dbg < 255 else 255

    ly = pya.Layout()
    ly.dbu = 0.001
    ly.technology_name = "sg13g2"
    top = ly.create_cell("dac_video_ihp")
    lay = {k: ly.layer(*v) for k, v in (
        ("m1", M1), ("m1l", M1L), ("cont", CONT), ("poly", POLY),
        ("nw", NW), ("v1", V1), ("m2", M2), ("m2l", M2L),
        ("v2", V2), ("m3", M3), ("m3l", M3L))}
    regions: dict[tuple[int, str], pya.Region] = {}

    cells: dict[str, pya.Cell] = {}

    def dev(kind, kw):
        key = kind + repr(sorted(kw.items()))
        if key not in cells:
            cells[key] = ly.create_cell(kind, "SG13_dev", kw)
        return cells[key]

    def add(layer, x1, y1, x2, y2, net):
        b = rect(x1, y1, x2, y2)
        top.shapes(layer).insert(b)
        regions.setdefault((layer, net), pya.Region()).insert(b)
        return b

    def via(layer, x, y, size=0.19):
        top.shapes(layer).insert(rect(x - size / 2, y - size / 2,
                                      x + size / 2, y + size / 2))

    def label(x, y, name, layer):
        top.shapes(layer).insert(pya.Text(name, pya.Trans(
            int(round(x * 1000)), int(round(y * 1000)))))

    def place(kind, kw, x, y):
        c = dev(kind, kw)
        top.insert(pya.CellInstArray(c.cell_index(),
                                     pya.Trans(int(round(x * 1000)),
                                               int(round(y * 1000)))))

    def gate_land_p(gc, y0, net):
        """pfet gate: poly land + contact + m1 pad below the active."""
        add(lay["poly"], gc - 0.25, y0 - 0.50, gc + 0.50, y0 - 0.17, net)
        top.shapes(lay["cont"]).insert(
            rect(gc - 0.08, y0 - 0.40, gc + 0.08, y0 - 0.24))
        add(lay["m1"], gc - 0.15, y0 - 0.47, gc + 0.15, y0 - 0.18, net)

    def gate_land_n(gc, y0, net):
        """nmos gate: wider land (0.28 gate cannot hold the 0.16 contact)."""
        add(lay["poly"], gc - 0.28, y0 - 0.50, gc + 0.30, y0 - 0.17, net)
        top.shapes(lay["cont"]).insert(
            rect(gc - 0.08, y0 - 0.43, gc + 0.08, y0 - 0.27))
        add(lay["m1"], gc - 0.18, y0 - 0.54, gc + 0.18, y0 - 0.20, net)

    def bulk_tap(x, y):
        place("ntap1", {}, x + 1.5, y)
        place("ptap1", {}, x + 1.5, y)

    def cell(x, tag):
        mx, cx = x + MX, x + CX
        d_pad, db_pad = "d_" + tag, "db_" + tag
        md, cd = "md_" + tag, "cd_" + tag
        # --- devices + taps + wells ---------------------------------------
        place("pmos", {"l": "1u", "w": "8u", "ng": 1}, mx, 0)
        place("pmos", {"l": "0.5u", "w": "8u", "ng": 1}, cx, 0)
        place("nmos", {"l": "0.28u", "w": "4u", "ng": 1}, mx, PY)
        place("nmos", {"l": "0.28u", "w": "4u", "ng": 1}, cx, PY)
        place("ntap1", {}, x + 1.5, 9.2)
        place("ptap1", {}, x + 1.5, -8.2)
        add(lay["nw"], x - 0.5, -0.31, x + 4.6, 10.5, "nw")
        # --- gate lands ----------------------------------------------------
        gate_land_p(mx + PMOS1["gc"], 0, "vbp")
        gate_land_p(cx + PMOS05["gc"], 0, "vcp")
        gate_land_n(mx + NMOS["gc"], PY, d_pad)
        gate_land_n(cx + NMOS["gc"], PY, db_pad)
        # --- md: mirror drain -> cascode source (m2 over the row) ---------
        add(lay["m1"], mx + 0.01, 7.75, mx + 0.29, 8.35, md)
        add(lay["m1"], cx + 0.89, 7.75, cx + 1.17, 8.35, md)
        via(lay["v1"], mx + 0.15, 8.10)
        via(lay["v1"], cx + 1.03, 8.10)
        add(lay["m2"], mx - 0.01, 7.95, cx + 1.19, 8.45, md)
        # --- cd: cascode drain -> pair shared source (m3 over both buses) --
        add(lay["m1"], cx - 0.03, -0.25, cx + 0.26, 0.25, cd)
        via(lay["v1"], cx + 0.15, 0.0)
        add(lay["m2"], cx - 0.05, -0.30, cx + 0.35, 0.30, cd)
        via(lay["v2"], cx + 0.15, 0.0)
        add(lay["m3"], cx - 0.05, -4.70, cx + 0.35, 0.10, cd)
        # pair source bar + m1 pads on the pair source rails
        add(lay["m2"], mx + 0.72, PY + 1.60, cx + 1.00, PY + 2.00, cd)
        for sdx in (mx, cx):
            add(lay["m1"], sdx + 0.73, PY + 1.55, sdx + 0.99, PY + 1.95, cd)
            via(lay["v1"], sdx + 0.86, PY + 1.80)
        via(lay["v2"], cx + 0.15, PY + 1.85)
        # --- vbp: m2 bus at -1.2..-1.0 ------------------------------------
        via(lay["v1"], mx + PMOS1["gc"], -0.32)
        add(lay["m2"], mx + 0.62, -1.10, mx + 1.06, -0.28, "vbp")
        # --- vcp: m1 bus at -1.8..-1.6 ------------------------------------
        add(lay["m1"], cx + PMOS05["gc"] - 0.10, -1.80,
            cx + PMOS05["gc"] + 0.10, -0.18, "vcp")
        # --- pair gates -> pad row (m1 risers, m2 stubs) ------------------
        for dx, net, px in ((MX, d_pad, PIN_A), (CX, db_pad, PIN_B)):
            gx = x + dx + NMOS["gc"]
            add(lay["m1"], gx - 0.11, PAD_Y[1] - 0.25, gx + 0.11, PY - 0.15,
                net)
            via(lay["v1"], gx, PY - 0.35)
            add(lay["m2"], gx - 0.30, PAD_Y[1] - 0.05, x + px + 0.25,
                PAD_Y[1] + 0.30, net)
            via(lay["v1"], gx, PAD_Y[1] + 0.15)
            add(lay["m2"], x + px - PAD_W / 2, PAD_Y[0],
                x + px + PAD_W / 2, PAD_Y[1], net)
            label(x + px, (PAD_Y[0] + PAD_Y[1]) / 2, net, lay["m2l"])
        # --- iout / idump --------------------------------------------------
        add(lay["m1"], mx + 0.02, -3.2, mx + 0.28, -2.8, "iout")
        via(lay["v1"], mx + 0.15, -3.0)
        add(lay["m2"], mx + 0.02, -3.2, mx + 0.28, -2.8, "iout")
        via(lay["v2"], mx + 0.15, -3.0)
        add(lay["m3"], mx + 0.02, -7.0, mx + 0.28, -3.0, "iout")
        add(lay["m1"], cx + 0.02, PY, cx + 0.24, PY + 0.30, "idump")
        via(lay["v1"], cx + 0.13, PY + 0.11)
        add(lay["m2"], cx - 0.05, -8.1, cx + 0.31, PY + 0.20, "idump")
        via(lay["v2"], cx + 0.13, -8.0)
        # --- vdd stack + bulk ties -----------------------------------------
        add(lay["m1"], mx + 1.39, 7.2, mx + 1.67, 7.6, "vdd")
        via(lay["v1"], mx + 1.53, 7.4)
        add(lay["m2"], mx + 1.37, 7.2, mx + 1.69, 7.6, "vdd")
        via(lay["v2"], mx + 1.53, 7.4)
        add(lay["m3"], mx + 1.37, 7.4, mx + 1.69, 10.8, "vdd")
        via(lay["v1"], x + 1.89, 9.4)
        add(lay["m2"], x + 1.73, 9.2, x + 2.05, 9.6, "vdd")
        via(lay["v2"], x + 1.89, 9.4)
        # vss: ptap -> the m1 rail below the pads
        add(lay["m1"], x + 1.70, -10.40, x + 2.08, -7.50, "vss")

    tags = []
    for j in range(n):
        k = 0
        while j >= 2 ** (k + 1) - 1:
            k += 1
        tags.append(f"b{k}_{j - (2 ** k - 1)}")
    for j, tag in enumerate(tags):
        cell(j * PITCH, tag)

    x_last = (n - 1) * PITCH
    x_end = x_last + PITCH
    x_b = x_end + 1.0

    if dbg >= 255:
        # --- replica: mirror + cascode, diode-connected, no switch --------
        rx, rcx, ry = x_b + MX, x_b + CX, -14.0
        place("pmos", {"l": "1u", "w": "8u", "ng": 1}, rx, 0)
        place("pmos", {"l": "0.5u", "w": "8u", "ng": 1}, rcx, ry)
        place("ntap1", {}, x_b + 1.5, 9.2)
        add(lay["nw"], x_b - 0.5, -14.40, x_b + 4.6, 10.5, "nw")
        gate_land_p(rx + PMOS1["gc"], 0, "vbp")
        gate_land_p(rcx + PMOS05["gc"], ry, "vcp")
        # mirror source -> vdd
        add(lay["m1"], rx + 1.39, 7.2, rx + 1.67, 7.6, "vdd")
        via(lay["v1"], rx + 1.53, 7.4)
        add(lay["m2"], rx + 1.37, 7.2, rx + 1.69, 7.6, "vdd")
        via(lay["v2"], rx + 1.53, 7.4)
        add(lay["m3"], rx + 1.37, 7.4, rx + 1.69, 10.8, "vdd")
        via(lay["v1"], x_b + 1.89, 9.4)
        add(lay["m2"], x_b + 1.73, 9.2, x_b + 2.05, 9.6, "vdd")
        via(lay["v2"], x_b + 1.89, 9.4)
        # mirror drain -> vbp bus (drain and gate are one node)
        add(lay["m1"], rx + 0.02, 3.3, rx + 0.28, 3.7, "vbp")
        via(lay["v1"], rx + 0.15, 3.5)
        add(lay["m2"], rx - 0.05, 3.7, rx + 0.35, -1.10, "vbp")
        via(lay["v1"], rx + PMOS1["gc"], -0.32)
        add(lay["m2"], rx + 0.62, -1.10, rx + 1.06, -0.28, "vbp")
        # cascode source -> vbp (m3 vertical crossing both buses)
        add(lay["m1"], rcx + 0.91, -10.7, rcx + 1.17, -10.3, "vbp")
        via(lay["v1"], rcx + 1.03, -10.5)
        add(lay["m2"], rcx + 0.83, -10.7, rcx + 1.23, -10.3, "vbp")
        via(lay["v2"], rcx + 1.03, -10.5)
        add(lay["m3"], rcx + 0.83, -10.5, rcx + 1.23, -1.10, "vbp")
        via(lay["v2"], rcx + 1.03, -1.30)
        add(lay["m2"], rcx + 0.83, -1.50, rcx + 1.23, -1.10, "vbp")
        # cascode drain/gate -> vcp
        add(lay["m1"], rcx + 0.07, ry - 0.47, rcx + 0.50, ry - 0.18, "vcp")
        add(lay["m1"], rcx + 0.07, ry - 0.60, rcx + 0.23, ry, "vcp")
        add(lay["m1"], rcx + 0.02, -13.95, rcx + 0.30, -13.65, "vcp")
        via(lay["v1"], rcx + 0.15, ry + 0.2)
        add(lay["m2"], rcx - 0.05, ry - 0.05, rcx + 0.35, ry + 0.45, "vcp")
        via(lay["v2"], rcx + 0.15, ry + 0.2)
        add(lay["m3"], rcx - 0.05, ry + 0.2, rcx + 0.35, -1.90, "vcp")
        via(lay["v2"], rcx + 0.15, -1.90)
        add(lay["m2"], rcx - 0.05, -2.00, rcx + 0.35, -1.60, "vcp")
        via(lay["v1"], rcx + 0.15, -1.70)

    # --- rails -------------------------------------------------------------
    add(lay["m2"], -1.0, -1.20, x_b + 4.23, -1.00, "vbp")
    label(0.4, -1.10, "vbp", lay["m2l"])
    add(lay["m1"], -1.0, -1.81, x_b + 3.35, -1.59, "vcp")
    label(0.4, -1.70, "vcp", lay["m1l"])
    add(lay["m3"], -1.0, 10.60, x_b + 5.00, 12.00, "vdd")
    label(0.4, 11.2, "vdd", lay["m3l"])
    add(lay["m3"], -1.0, -7.00, x_b - 1.00, -6.60, "iout")
    label(0.4, -6.8, "iout", lay["m3l"])
    add(lay["m3"], -1.0, -8.20, x_b - 1.00, -7.80, "idump")
    label(0.4, -8.0, "idump", lay["m3l"])
    add(lay["m1"], -1.0, -10.60, x_b - 0.50, -10.20, "vss")
    label(0.4, -10.4, "vss", lay["m1l"])

    # flatten the PCell instances, then write a one-top GDS
    ly.flatten(top.cell_index(), -1, False)
    out = pya.Layout()
    out.dbu = ly.dbu
    out.create_cell("dac_video_ihp").copy_shapes(top)
    out.write(out_path)
    b = out.top_cells()[0].bbox()
    print(f"wrote {out_path} (bbox {b.left * out.dbu:.2f},"
          f"{b.bottom * out.dbu:.2f};{b.right * out.dbu:.2f},"
          f"{b.top * out.dbu:.2f}, cells {n}, devices {4 * n + (2 if dbg >= 255 else 0)})")

    problems = []
    keys = sorted(regions, key=lambda kk: (kk[0], kk[1]))
    for i in range(len(keys)):
        for j in range(i + 1, len(keys)):
            if keys[i][0] != keys[j][0]:
                continue
            inter = regions[keys[i]] & regions[keys[j]]
            if not inter.is_empty():
                bb = inter.bbox()
                problems.append(f"SHORT {keys[i][1]} <-> {keys[j][1]} at "
                                f"({bb.left * 0.001:.2f},{bb.bottom * 0.001:.2f})")
    for p in problems[:12]:
        print("  " + p)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
