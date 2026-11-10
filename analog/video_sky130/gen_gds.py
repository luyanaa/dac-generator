#!/usr/bin/env python3
"""Generate the sky130 dump-tail video DAC array.

    klayout -b -r gen_gds.py [-rd out=build/video_sky130.gds] [-rd dbg_cells=N]

Devices come from `gen_devices.py` (magic `gencell`, 5 V pfet/nfet at W/L 8/0.5,
nf=1, guard 1 - see the README).  The guard ring is load-bearing: it is the
bulk tap.  Its side walls are li1 rings at x -1.15..-0.98 and 0.98..1.15 (um,
relative to the device origin) with li1->m1 contacts, and magic extracts a
`B` port there.  The ring also makes the nwell 3.08 um wide, so a continuous
nwell bar merges every pfet well into one vdd well (the array cannot afford
1.27 um of nwell spacing between neighbours on the 7.5 um pad grid).

The cell is the gf180 dump-tail cell:

    vdd - (mirror) - md - (cascode) - cd - NMOS pair - iout / idump

Mirror and cascode are pfet 8/0.5; the pair is nfet 8/0.5.  The mirror's gate
is on the met2 vbp bus above the row, the cascode's gate on the met2 vcp bus
on top of it, the pair's gates on the two met2 pads per cell (3.75 um row),
vdd/iout/idump are met3 buses, vss is a met1 rail, and the pfet/nfet bulk
rings are tied by met1 bars (pfet -> met3 vdd, nfet -> met1 vss).

The replica (right of the array) is the mirror+cascode, diode-connected, with
no switch; 16 uA at vcp sets the unit current.  The 100 pF on vcp is a wrapper
requirement, not part of this macro.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pya

HERE = Path(__file__).resolve().parent
BUILD = HERE / "build"
DEV_GDS = BUILD / "sky130_dev.gds"

# sky130A layers
M1 = (68, 20)
M1_LABEL = (68, 5)
V1 = (68, 44)
M2 = (69, 20)
M2_LABEL = (69, 5)
V2 = (69, 44)
M3 = (70, 20)
M3_LABEL = (70, 5)
NWELL = (64, 20)
HVI = (75, 20)
MCON = (67, 44)

NM = 1000

# Device terminals (um, relative to the device origin)
D_RAIL = (-0.525, -0.265)
S_RAIL = (0.265, 0.525)
RAIL_Y = (-4.0, 4.0)
G_PAD_TOP = (4.18, 4.44)      # m1 pad over the pfet/nfet gate contact
G_PAD_BOT = (-4.44, -4.18)
G_PAD_HALF = 0.25             # m1 gate pad half width (above the S/D rails)
BULK_X = (-1.24, -0.68)       # m1 bar over the guard ring side contacts
BULK_MID_P = -1.065          # pfet ring side contact centre
BULK_MID_N = -1.075          # nfet ring side contact centre
BULK_TOP = (-4.6, 6.2)        # pfet: ring -> above the bias buses
BULK_BOT = (-4.6, -8.4)       # nfet: ring -> down to the vss rail (rel. PAIR_Y)

PITCH = 7.5                  # cell pitch; the pin row grid
MIR_DX, CAS_DX = 0.8, 5.2    # device origins inside a cell
PAIR_Y = -10.8
RY = -11.0                   # replica cascode
PAD_Y = (-18.20, -17.80)
PAD_W = 0.60
PIN_A, PIN_B = 2.25, 6.0     # d_<tag>, db_<tag> pad centres (3.75 apart)


def box(x1, y1, x2, y2):
    return pya.Box(int(round(min(x1, x2) * NM)), int(round(min(y1, y2) * NM)),
                   int(round(max(x1, x2) * NM)), int(round(max(y1, y2) * NM)))


def main() -> int:
    g = globals()

    def opt(name, default=None):
        v = g.get(name, default)
        return v if isinstance(v, (str, int, float)) else default

    out_path = opt("out", str(BUILD / "video_sky130.gds"))
    dbg = int(opt("dbg_cells", 0))
    n_cells = 255

    if not DEV_GDS.is_file():
        sys.exit(f"error: {DEV_GDS} missing; run ./gen_devices.py")
    ly = pya.Layout()
    ly.dbu = 0.001
    ly.read(str(DEV_GDS))
    dev = {}
    for c in ly.each_cell():
        if "pfet" in c.name:
            dev["pfet"] = c
        elif "nfet" in c.name:
            dev["nfet"] = c
    for k in ("pfet", "nfet"):
        if k not in dev:
            sys.exit(f"error: no {k} cell in {DEV_GDS}")
    # magic's gencell writes D/S/G/B port labels.  They are inspection aids,
    # but after flattening they would become 1022 duplicate top-level ports.
    for c in dev.values():
        for li in ly.layer_indexes():
            sh = c.shapes(li)
            for sp in [x for x in sh.each() if x.is_text()]:
                sh.erase(sp)

    top = ly.create_cell("dac_video_ana")
    lay = {k: ly.layer(*v) for k, v in (
        ("m1", M1), ("m1l", M1_LABEL), ("v1", V1), ("m2", M2),
        ("m2l", M2_LABEL), ("v2", V2), ("m3", M3), ("m3l", M3_LABEL),
        ("nwell", NWELL), ("hvi", HVI), ("mcon", MCON))}
    regions: dict[tuple[int, str], pya.Region] = {}

    def add(layer, x1, y1, x2, y2, net):
        b = box(x1, y1, x2, y2)
        top.shapes(layer).insert(b)
        regions.setdefault((layer, net), pya.Region()).insert(b)
        return b

    def label(x, y, name, layer=None):
        top.shapes(layer or lay["m2l"]).insert(
            pya.Text(name, pya.Trans(int(round(x * NM)), int(round(y * NM)))))

    def place(kind, x, y):
        top.insert(pya.CellInstArray(dev[kind].cell_index(),
                                     pya.Trans(int(round(x * NM)),
                                               int(round(y * NM)))))

    def via(layer, x, y, size=0.15):
        top.shapes(layer).insert(box(x - size / 2, y - size / 2,
                                     x + size / 2, y + size / 2))

    def cell_bit(j):
        k = 0
        while j >= 2 ** (k + 1) - 1:
            k += 1
        return k

    def m1_rail(dx, y0, net, rail):
        """Met1 rail over one device source/drain liability rail."""
        add(lay["m1"], dx + rail[0], y0 + RAIL_Y[0],
            dx + rail[1], y0 + RAIL_Y[1], net)

    def bulk_tie(dx, y0, net, bot_y, top_y, mid=BULK_MID_P):
        """Tie a guard-ring side wall to met1.

        The PDK gencell contacts the ring only li1-side (licon), so the
        li1->m1 mcon squares are ours; a 0.17 mcon exactly under the 0.17 li1
        wall is legal (ct.4 wants it covered, m1 wants 0.03 enclosure).
        """
        x1, x2 = dx + BULK_X[0], dx + BULK_X[1]
        y = y0 - 4.4
        while y <= y0 + 4.4 + 1e-9:
            top.shapes(lay["mcon"]).insert(
                box(dx + mid - 0.085, y - 0.085,
                    dx + mid + 0.085, y + 0.085))
            y += 0.8
        add(lay["m1"], x1, bot_y, x2, top_y, net)

    def bulk_up(dx, y0=0.0):
        """pfet bulk: ring side bar -> via1 -> m2 -> via2 -> met3 vdd."""
        bulk_tie(dx, y0, "vdd", y0 - 4.6, 6.2)
        cx = dx + BULK_MID_P
        via(lay["v1"], cx, 6.0)
        add(lay["m2"], cx - 0.16, 5.80, cx + 0.16, 6.20, "vdd")
        via(lay["v2"], cx, 6.0, 0.20)

    def gate_top(dx, net, bus_y):
        """Met1 pad on the gate contact, via, met2 pad to the bias bus."""
        cx = dx
        add(lay["m1"], cx - G_PAD_HALF, G_PAD_TOP[0],
            cx + G_PAD_HALF, G_PAD_TOP[1], net)
        if net == "vcp":
            # vcp: met1 riser through the vbp bus up to the vcp bus (no via).
            add(lay["m1"], cx - G_PAD_HALF, G_PAD_TOP[0],
                cx + G_PAD_HALF, 5.44, net)
            via(lay["v1"], cx, 5.25)
            add(lay["m2"], cx - 0.16, 5.08, cx + 0.16, 5.50, net)
        else:
            via(lay["v1"], cx, 4.31)
            add(lay["m2"], cx - 0.16, bus_y[0] - 0.02, cx + 0.16, bus_y[1], net)

    def one_cell(x, tag):
        md, cd = "md_" + tag, "cd_" + tag
        d_pad, db_pad = "d_" + tag, "db_" + tag
        mx, cx = x + MIR_DX, x + CAS_DX
        # --- current sources ----------------------------------------------
        place("pfet", mx, 0)
        place("pfet", cx, 0)
        m1_rail(mx, 0, "vdd", S_RAIL)            # mirror source
        m1_rail(mx, 0, md, D_RAIL)               # mirror drain
        m1_rail(cx, 0, md, S_RAIL)               # cascode source
        m1_rail(cx, 0, cd, D_RAIL)               # cascode drain
        # mirror bulk (vdd), cascode bulk (vdd)
        bulk_up(mx)
        bulk_up(cx)
        # mirror source -> vdd plane
        via(lay["v1"], mx + 0.395, 2.0)
        add(lay["m2"], mx + 0.215, 1.70, mx + 0.575, 2.30, "vdd")
        via(lay["v2"], mx + 0.395, 2.0, 0.20)
        # md: mirror drain -> cascode source (met2 above the rails)
        via(lay["v1"], mx - 0.395, 3.5)
        via(lay["v1"], cx + 0.395, 3.5)
        add(lay["m2"], mx - 0.595, 3.30, cx + 0.595, 3.70, md)
        # cd: cascode drain -> the pair's shared source (met2 column)
        via(lay["v1"], cx - 0.395, 2.6)
        add(lay["m2"], cx - 0.595, -7.90, cx - 0.195, 2.80, cd)
        # gates
        gate_top(mx, "vbp", (4.20, 4.76))
        gate_top(cx, "vcp", (5.08, 5.50))
        # --- pair ----------------------------------------------------------
        for dx, net in ((MIR_DX, "iout"), (CAS_DX, "idump")):
            px = x + dx
            place("nfet", px, PAIR_Y)
            m1_rail(px, PAIR_Y, net, D_RAIL)      # drain
            m1_rail(px, PAIR_Y, cd, S_RAIL)       # source
            # bulk ring -> vss rail (met1, straight down)
            bulk_tie(px, PAIR_Y, "vss", PAIR_Y + 4.60, -19.20, BULK_MID_N)
        add(lay["m2"], mx + 0.245, PAIR_Y + 2.75,
            cx + 0.545, PAIR_Y + 3.25, cd)
        via(lay["v1"], mx + 0.395, PAIR_Y + 3.0)
        via(lay["v1"], cx + 0.395, PAIR_Y + 3.0)
        # iout: pair drain -> met2 column -> via2 on the met3 iout bus
        via(lay["v1"], mx - 0.395, PAIR_Y + 3.0)
        add(lay["m2"], mx - 0.595, -7.95, mx - 0.195, -2.70, "iout")
        via(lay["v2"], mx - 0.395, -2.90, 0.20)
        # idump: pair drain -> met2 patch -> via2 on the met3 idump bus
        via(lay["v1"], cx - 0.395, PAIR_Y - 3.0)
        add(lay["m2"], cx - 0.595, PAIR_Y - 3.25,
            cx - 0.195, PAIR_Y - 2.75, "idump")
        via(lay["v2"], cx - 0.395, PAIR_Y - 3.0, 0.20)
        # --- pair gates -> the pad row ------------------------------------
        for dx, net in ((MIR_DX, d_pad), (CAS_DX, db_pad)):
            gx = x + dx
            add(lay["m1"], gx - G_PAD_HALF, PAIR_Y + G_PAD_BOT[0],
                gx + G_PAD_HALF, PAIR_Y + G_PAD_BOT[1], net)
            via(lay["v1"], gx, PAIR_Y - 4.31)
            add(lay["m2"], gx - 0.20, PAD_Y[1] - 0.05, gx + 0.20,
                PAIR_Y - 4.05, net)
            px = x + (PIN_A if net == d_pad else PIN_B)
            add(lay["m2"], px - PAD_W / 2, PAD_Y[0], px + PAD_W / 2,
                PAD_Y[1], net)
            label(px, (PAD_Y[0] + PAD_Y[1]) / 2, net)
            add(lay["m2"], gx - 0.20, PAD_Y[1] - 0.05, px + 0.20,
                PAD_Y[1] + 0.35, net)

    n = dbg if dbg else n_cells
    for j in range(n):
        one_cell(j * PITCH, f"b{cell_bit(j)}_{j - (2 ** cell_bit(j) - 1)}")

    x_last = (n - 1) * PITCH
    x_end = x_last + PITCH
    x_b = x_end + 1.0
    # --- replica: mirror + cascode, diode-connected, no switch -------------
    if not dbg:
        place("pfet", x_b, 0)
        place("pfet", x_b, RY)
        # mirror: source vdd, drain = gate = vbp
        m1_rail(x_b, 0, "vdd", S_RAIL)
        m1_rail(x_b, 0, "vbp", D_RAIL)
        via(lay["v1"], x_b + 0.395, 2.0)
        add(lay["m2"], x_b + 0.25, 1.70, x_b + 0.54, 2.30, "vdd")
        via(lay["v2"], x_b + 0.395, 2.0, 0.20)
        gate_top(x_b, "vbp", (4.20, 4.76))
        via(lay["v1"], x_b - 0.395, 3.5)
        add(lay["m2"], x_b - 0.595, 3.30, x_b - 0.10, 4.76, "vbp")
        bulk_up(x_b)
        # cascode: source vbp (right rail), drain = gate = vcp
        m1_rail(x_b, RY, "vbp", S_RAIL)
        m1_rail(x_b, RY, "vcp", D_RAIL)
        bulk_tie(x_b, RY, "vdd", RY - 4.6, 6.2)
        via(lay["v1"], x_b + BULK_MID_P, 6.0)
        add(lay["m2"], x_b + BULK_MID_P - 0.16, 5.80,
            x_b + BULK_MID_P + 0.16, 6.20, "vdd")
        via(lay["v2"], x_b + BULK_MID_P, 6.0, 0.20)
        # cascode source -> vbp: out under the guard ring (the ring's bottom
        # wall carries no li1->m1 contact), then up on the right.  The met1
        # riser stays 0.15 um clear of the gate pad and of the vdd stack.
        add(lay["m1"], x_b + 0.38, -16.50, x_b + 0.64, -14.90, "vbp")
        add(lay["m1"], x_b + 0.38, -16.55, x_b + 1.20, -16.00, "vbp")
        via(lay["v1"], x_b + 1.00, -16.30)
        add(lay["m2"], x_b + 0.85, -16.50, x_b + 1.35, 4.76, "vbp")
        # cascode gate/drain -> vcp: the bottom gate pad bridges the left rail;
        # met1 then leaves under the ring on the left and climbs on the far
        # right to the vcp bus.
        add(lay["m1"], x_b - 0.525, -15.44, x_b + 0.10, -14.90, "vcp")
        add(lay["m1"], x_b - 0.525, -17.00, x_b - 0.265, -14.90, "vcp")
        add(lay["m1"], x_b - 0.525, -17.00, x_b + 2.50, -16.70, "vcp")
        add(lay["m1"], x_b + 2.20, -17.00, x_b + 2.50, 5.44, "vcp")
        via(lay["v1"], x_b + 2.35, 5.25)

    # --- rails -------------------------------------------------------------
    # One merged 5 V well across the whole pfet row (the 7.5 um pad grid is
    # below the 1.27 um nwell spacing), with its hvi marker on top.
    add(lay["nwell"], -1.60, -5.55, x_b + 2.00, 5.49, "nwell")
    add(lay["hvi"], -1.65, -16.50, x_b + 2.05, 5.54, "hvi")
    add(lay["m2"], -1.00, 4.38, x_b + 1.35, 4.76, "vbp")
    label(0.4, 4.6, "vbp", lay["m2l"])
    add(lay["m2"], -1.00, 5.08, x_b + 2.56, 5.50, "vcp")
    label(0.4, 5.2, "vcp", lay["m2l"])
    add(lay["m3"], -1.36, 0.20, x_b + 3.60, 8.20, "vdd")
    label(0.4, 7.4, "vdd", lay["m3l"])
    add(lay["m3"], -1.36, -3.60, x_b + 3.60, -1.80, "iout")
    label(0.4, -2.7, "iout", lay["m3l"])
    add(lay["m3"], -1.36, -15.00, x_b + 3.60, -13.20, "idump")
    label(0.4, -14.1, "idump", lay["m3l"])
    add(lay["m1"], -1.36, -19.40, x_b + 3.60, -19.00, "vss")
    label(0.4, -19.2, "vss", lay["m1l"])

    # Flatten the device instances: magic's `flatten` is a no-op on a
    # GDS-imported cell, and a hierarchical cell with ports makes the extractor
    # name every node "..._<id>/G" instead of the routed net.
    ly.flatten(top.cell_index(), -1, False)
    ly.cleanup()
    out = pya.Layout()
    out.dbu = ly.dbu
    out.create_cell("dac_video_ana").copy_shapes(top)
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    out.write(out_path)
    b = top.bbox()
    print(f"wrote {out_path}  (bbox {b.left * ly.dbu:.1f},"
          f"{b.bottom * ly.dbu:.1f};{b.right * ly.dbu:.1f},"
          f"{b.top * ly.dbu:.1f}, devices {n * 4 + (0 if dbg else 2)})")

    problems = []
    keys = sorted(regions, key=lambda kk: (kk[0], kk[1]))
    for i in range(len(keys)):
        for j2 in range(i + 1, len(keys)):
            if keys[i][0] != keys[j2][0]:
                continue
            inter = regions[keys[i]] & regions[keys[j2]]
            if not inter.is_empty():
                bb = inter.bbox()
                problems.append(
                    f"SHORT {keys[i][1]} <-> {keys[j2][1]} at "
                    f"({bb.left / NM:.2f},{bb.bottom / NM:.2f})")
    for p in problems:
        print("  " + p)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
