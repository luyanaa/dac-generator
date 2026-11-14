"""Generate the ics55 P5 video DAC row: 255 cells + replica + 510 pads.

    klayout -b -r gen_gds.py -z            # -> build/video_ics55.gds

The cell is the one closed in `gen_cell.py` (mirror 8/1, cascode 8/0.5,
pair 4/0.28), placed on the same 7.5 um pitch and pad plan as the gf180 /
sky130 / IHP leaves: 255 cells in a row, `d_`/`db_` pads on a 3.75 um grid
(pad j at 2.25 + j*3.75), 510 M2 pads at the bottom.

Routing plan:
  * vdd / vbp / vcp buses on M2 above the row, M1 stubs + V1 from each cell;
  * iout / idump on two M1 buses below the row, M1 stubs from the pair drains;
  * the pair gates go to the pads on M2: an M1 jog out of the gate island,
    a V1, a vertical M2 run (clear of the per-cell `cd` M2 route) and a
    horizontal jog into the pad;
  * the replica (mirror + cascode, diode-connected) sits right of the row
    with an `iref` pad on its vcp node - the on-chip bias generator.

The cell count is 255 and the pads 510; the row is 1912.5 um wide.
"""
import os
import sys

import klayout.db as db

PCELS = "/grid/icsprout55-pdk/libs.tech/klayout/pcells"
sys.path.insert(0, PCELS)
import ics55_mos_analog  # noqa: E402

L_ACT = (2, 1)
L_NW = (9, 1)
L_POLY = (41, 1)
L_NP = (52, 1)
L_PP = (53, 1)
L_CT = (72, 1)
L_M1 = (81, 1)
L_M2 = (82, 1)
L_V1 = (91, 1)

N = int(os.environ.get("N_CELLS", "255"))
PITCH = 7.5
PAD_X0 = 2.25
PAD_PITCH = 3.75
PAD_Y = (-18.2, -17.6)
PAD_W = 0.6


def side(L):
    return L / 2.0 + 0.055 + 0.09 + 0.03


def islands(W, L, cx, cy):
    s = side(L)
    dx = 2 * s
    x0 = cx - dx / 2.0
    y0 = cy - W / 2.0
    ct = [x0 + 0.075, x0 + 0.075 + L + 0.2]
    left = (ct[0] - 0.07, y0 - 0.16, ct[0] + 0.07, y0 + W - 0.07)
    right = (ct[1] - 0.07, y0 + 0.10, ct[1] + 0.07, y0 + W + 0.16)
    gate = (cx - 0.07, y0 + W + 0.305, cx + 0.07, y0 + W + 0.625)
    return left, right, gate


class Row:
    def __init__(self):
        self.ly = db.Layout()
        self.ly.dbu = 0.001
        self.top = self.ly.create_cell("dac_video_ana")
        self.pcells = {}

    def u(self, v):
        return int(round(v / self.ly.dbu))

    def box(self, layer, x1, y1, x2, y2):
        self.top.shapes(self.ly.layer(*layer)).insert(
            db.Box(self.u(x1), self.u(y1), self.u(x2), self.u(y2)))

    def text(self, layer, s, x, y):
        self.top.shapes(self.ly.layer(*layer)).insert(
            db.Text(s, db.Trans(db.Vector(self.u(x), self.u(y)))))

    def dev(self, dev, W, L, cx, cy):
        key = (dev, W, L)
        if key not in self.pcells:
            self.pcells[key] = self.ly.create_cell(
                "ics55_mos_analog", "ICsprout55",
                {"dev_type": dev, "w": W, "l": L, "fingers": 1,
                 "guard_ring": 0, "ring_metal": 0})
        self.top.insert(db.CellInstArray(
            self.pcells[key].cell_index(),
            db.Trans(db.Vector(self.u(cx), self.u(cy)))))
        return islands(W, L, cx, cy)

    def cell(self, x, y=0.0):
        """Place one P5 cell; returns the net anchor points."""
        m = self.dev("p", 8.0, 1.0, x + 0.0, y)
        c = self.dev("p", 8.0, 0.5, x + 2.2, y)
        a = self.dev("n", 4.0, 0.28, x + 0.6, y - 7.5)
        b = self.dev("n", 4.0, 0.28, x + 2.4, y - 7.5)
        # md: mirror right -> cascode left
        self.box(L_M1, m[1][0], y - 0.3, c[0][2], y + 0.3)
        # cd: cascode right -> M2 -> pair sources
        def via(cx, cy):
            self.box(L_M1, cx - 0.085, cy - 0.085, cx + 0.085, cy + 0.085)
            self.box(L_V1, cx - 0.045, cy - 0.045, cx + 0.045, cy + 0.045)
        # Offset the V1 from the cascode-drain CT in y: a V1 stacked exactly
        # on a CT makes Magic lose the lower contact (the drain extracts as a
        # zero-area node).  The M1 island is tall enough for the 0.12 um
        # offset, and the M2 cd route is extended to reach it.
        via(c[1][0] + 0.07, y + 0.12)
        self.box(L_M2, c[1][0] + 0.005, y - 8.365, c[1][0] + 0.135, y + 0.20)
        for p in (a, b):
            via(p[0][0] + 0.07, y - 8.3)
        self.box(L_M2, a[0][0] + 0.005, y - 8.365, c[1][0] + 0.135, y - 8.235)
        return {"vdd": (x - 0.6, y), "vbp": (x, y + 4.465),
                "vcp": (x + 2.2, y + 4.465),
                "d": (x + 0.6, y - 5.035), "db": (x + 2.4, y - 5.035),
                "iout": (x + 0.84, y - 7.5), "idump": (x + 2.64, y - 7.5)}


def tag(j):
    k = 0
    while j >= 2 ** (k + 1) - 1:
        k += 1
    return f"b{k}_{j - (2 ** k - 1)}"


def well_tap(r, x0, x1):
    """Merge the PMOS wells into one NW strip with a single NTAP to vdd.

    The vendor NW1_R_1 rule requires every NW island to interact a tapped
    NTAP (NP-covered active inside NW with a CT).  The per-cell PCell wells
    are floating islands and two of them are only 0.1 um apart, which also
    breaks NW1_S_1 (0.47).  One strip over the row merges them; the NTAP at
    the left end is tied to the first cell's PMOS source (vdd) on M1.
    """
    r.box(L_NW, x0, -4.6, x1, 4.6)
    r.box(L_ACT, -1.8, -0.15, -1.3, 0.15)
    r.box(L_NP, -2.0, -0.35, -1.1, 0.35)
    r.box(L_CT, -1.595, -0.045, -1.505, 0.045)
    r.box(L_M1, -1.65, -0.16, -1.45, 0.16)
    r.box(L_M1, -1.65, -0.07, -0.5, 0.07)


def main():
    r = Row()
    x_end = (N - 1) * PITCH
    bus_x0, bus_x1 = -3.0, x_end + 24.0

    # global buses
    for y, name in ((7.3, "vdd"), (6.3, "vbp"), (5.3, "vcp")):
        r.box(L_M2, bus_x0, y - 0.1, bus_x1, y + 0.1)
    for y in (-10.0, -10.6):
        r.box(L_M2, bus_x0, y - 0.1, bus_x1, y + 0.1)

    for j in range(N):
        x = j * PITCH
        a = r.cell(x)
        if os.environ.get("PEX_LABELS"):
            # The local md interconnect has no pad label; without this text
            # Magic drops the floating M1 net and splits the mirror drain
            # from the cascode source.  The pair-source M1 island is the
            # other local net that must be named before the M2 cd route can
            # merge it with the cascode drain.
            r.text(L_M1, f"md_{j}", x + 1.2, 0.0)
            r.text(L_M1, f"cd_{j}", x + 0.36, -7.5)
        # top stubs: M1 up from each island, V1 onto its bus
        for ax, ay, bus_y in ((a["vdd"][0], 3.93, 7.3),
                              (a["vbp"][0], 4.625, 6.3),
                              (a["vcp"][0], 4.625, 5.3)):
            r.box(L_M1, ax - 0.07, ay - 0.05, ax + 0.07, bus_y + 0.045)
            r.box(L_V1, ax - 0.045, bus_y - 0.045, ax + 0.045, bus_y + 0.045)
        # bottom: pair drains to the iout / idump M2 buses
        for ax, by in ((a["iout"][0], -10.0), (a["idump"][0], -10.6)):
            r.box(L_M1, ax - 0.07, by - 0.045, ax + 0.07, -9.35)
            r.box(L_V1, ax - 0.045, by - 0.045, ax + 0.045, by + 0.045)
        # gate fanout: M1 jog out, V1, M2 down, M2 jog into the pad
        for gx, vx, px in ((a["d"][0], x + 0.1, x + PAD_X0),
                           (a["db"][0], x + 2.95, x + 6.0)):
            if gx < vx:
                r.box(L_M1, gx - 0.07, -5.11, vx + 0.07, -4.94)
            else:
                r.box(L_M1, vx - 0.07, -5.11, gx + 0.07, -4.94)
            r.box(L_M1, vx - 0.07, -17.75, vx + 0.07, -4.94)
            lo, hi = sorted((vx, px))
            r.box(L_M1, lo - 0.07, -17.75, hi + 0.07, -17.6)
            r.box(L_V1, px - 0.045, -17.745, px + 0.045, -17.655)
            net = ("d_" if px < x + 4.0 else "db_") + tag(j)
            # PEX_LABELS=1 puts the port label on the M1 gate fanout instead
            # of the M2 pad.  Magic's ext2spice does not merge the V1 equiv,
            # so the M1 net is the one the extractor can name; the M2 pad
            # then stays a small floating cap (0.14 fF) and is omitted from
            # the PEX run.  The signoff GDS keeps the M2 label for LVS.
            if os.environ.get("PEX_LABELS"):
                r.text(L_M1, net, vx, -5.0)
            else:
                r.text(L_M2, net, px, -17.9)

    # pads (M2), 3.75 um grid
    for j in range(N):
        for px in (j * PITCH + PAD_X0, j * PITCH + 6.0):
            r.box(L_M2, px - PAD_W / 2, PAD_Y[0], px + PAD_W / 2, PAD_Y[1])

    # replica: mirror + cascode, diode-connected, with the iref pad on vcp
    xr = x_end + 12.0
    m = r.dev("p", 8.0, 1.0, xr, 0.0)
    c = r.dev("p", 8.0, 0.5, xr + 2.2, 0.0)
    r.box(L_M1, m[1][0], -0.3, c[0][2], 0.3)              # md
    r.box(L_M1, m[0][0] - 0.07, -4.16, m[0][0] + 0.07, 7.345)   # vdd stub
    r.box(L_V1, m[0][0] - 0.045, 7.255, m[0][0] + 0.045, 7.345)
    r.box(L_M1, xr - 0.07, 4.625, xr + 0.07, 6.345)          # vbp stub
    r.box(L_V1, xr - 0.045, 6.255, xr + 0.045, 6.345)
    r.box(L_M1, xr + 2.2 - 0.07, 4.625, xr + 2.2 + 0.07, 5.345)  # vcp stub
    r.box(L_V1, xr + 2.2 - 0.045, 5.255, xr + 2.2 + 0.045, 5.345)
    # diode connections: mirror drain -> vbp, cascode drain -> vcp
    r.box(L_M1, m[1][0] - 0.07, 3.9, m[1][0] + 0.07, 6.345)
    r.box(L_V1, m[1][0] - 0.045, 6.255, m[1][0] + 0.045, 6.345)
    r.box(L_M1, c[1][0] - 0.07, 4.1, c[1][0] + 0.07, 5.345)
    r.box(L_V1, c[1][0] - 0.045, 5.255, c[1][0] + 0.045, 5.345)
    # iref pad on vcp, below the replica
    r.box(L_M2, xr + 2.2 - 0.065, -3.0, xr + 2.2 + 0.065, 5.26)
    r.box(L_M2, xr + 2.2 - 0.3, -3.2, xr + 2.2 + 0.3, -2.6)

    # one merged NW strip + NTAP for the row and the replica
    well_tap(r, -2.2, xr + 1.0)

    # rail labels at the left end
    for y, name in ((7.3, "vdd"), (6.3, "vbp"), (5.3, "vcp"),
                    (-10.0, "iout"), (-10.6, "idump")):
        r.text(L_M2, name, bus_x0 + 1.5, y)

    if not os.environ.get("KEEP_HIER"):
        r.top.flatten(-1, True)
    out = os.environ.get("OUT", os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "build",
        "video_ics55_hier.gds" if os.environ.get("KEEP_HIER")
        else "video_ics55.gds"))
    r.ly.write(out)
    print(f"wrote {out}: {N} cells + replica, {2*N} pads, "
          f"row {N*PITCH:.1f} x {PAD_Y[0]:.1f} um")


if __name__ == "__main__":
    main()
