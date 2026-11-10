#!/usr/bin/env python3
"""Device geometry for the sky130 dump-tail video array.

    klayout -b -r gen_gds.py [-rd out=build/video_sky130.gds] [-rd check=true]

The cell is the one the device study sized (`analog/video/pdk_cell.py
sky130`): the 1.8 V logic PMOS cannot stack two diodes at 16 uA inside 1.8 V,
so the array runs the 5 V g5v0d10v5 devices at 3.3 V, mirror 8/0.5, cascode
8/0.5, steering pair 8/0.5.  Layout comes from the same drawer the CDAC leaf
uses (`/opt/OpenSERDES/.../pya_draw`), which draws the 5 V devices; its
`hvntm_layer` is missing from `layers_def.py`, so the generator patches it to
sky130's 125/20 before drawing.

Rails, from the gf180 macro's scheme adapted to sky130:
  * vdd is a met3 plane over the devices; iout and idump are met3 buses under
    them (met3 is 0.074 Ohm/sq against met1's 0.125).
  * vbp is a met2 bar (each mirror's gate m1 pad -> via1 -> met2), vcp a met2
    bar one row up (each cascode's gate -> via1 -> met2).
  * vss is a met1 rail (bulk ties only).
  * two met2 pads per cell on a 3.75 um row for the pair's gates.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pya

HERE = Path(__file__).resolve().parent

# sky130A layer map (drawing / label)
M1 = (68, 20)
M1_LABEL = (68, 5)
V1 = (68, 44)
M2 = (69, 20)
M2_LABEL = (69, 5)
V2 = (69, 44)
M3 = (70, 20)
M3_LABEL = (70, 5)

NM = 1000                      # nm per um
PITCH = 7.5                    # cell pitch, um
DEV_W = 8.0                    # W of every device, um
PFET = "sky130_fd_pr__pfet_g5v0d10v5"
NFET = "sky130_fd_pr__nfet_g5v0d10v5"
PFET_L = NFET_L = 0.5

# Device terminal geometry probed from the drawer at W=8, L=0.5 (nm), origin
# at the device's diffusion lower-left:
#   diff (0,0)-(1100,8000); m1 source x 35..265, drain x 1500..1730 (pfet)
#   or 1530..1760 (nfet), y 75..7925; gate m1 x 300..800, y 8200..8530;
#   bulk tie m1 x 1420..1810 (pfet) / 1420..1870 (nfet), y 0..8000.
SRC = (35, 265)
DRN_P = (1500, 1730)
DRN_N = (1530, 1760)
GATE = (300, 800, 8200, 8530)
TIE = (1420, 1810)

PAD_PITCH = 3.75
PAD_W = 0.60
PAD_H = 0.40
PAD_Y = (-11.60, -11.20)


def _draw_fet():
    sys.path.insert(0, "/opt/OpenSERDES/verification/analog")
    from pya_draw import shim  # noqa: F401
    from pya_draw.draw_fet import draw_nfet, draw_pfet
    import pya_draw.draw_fet as df
    # layers_def.py omits the HV N-tunnel implant; sky130 hvntm.drawing is
    # 125/20 (sky130A.lyp).  Without it the 5 V nfet path raises NameError.
    if not hasattr(df, "hvntm_layer"):
        df.hvntm_layer = (125, 20)
    return draw_pfet, draw_nfet


def cell_bit(j: int) -> int:
    k = 0
    while j >= 2 ** (k + 1) - 1:
        k += 1
    return k


def main() -> int:
    g = globals()

    def opt(name, default=None):
        v = g.get(name, default)
        return v if isinstance(v, (str, int, float)) else default

    out_path = opt("out", str(HERE / "build" / "video_sky130.gds"))
    do_check = str(opt("check", "false")).lower() in ("1", "true", "yes")
    n_cells = 255
    dbg = int(opt("dbg_cells", 0))

    draw_pfet, draw_nfet = _draw_fet()
    ly = pya.Layout()
    ly.dbu = 0.001
    top = ly.create_cell("dac_video_ana")
    lay = {k: ly.layer(*v) for k, v in (
        ("m1", M1), ("m1l", M1_LABEL), ("v1", V1), ("m2", M2),
        ("m2l", M2_LABEL), ("v2", V2), ("m3", M3), ("m3l", M3_LABEL))}

    regions: dict[tuple[int, str], pya.Region] = {}

    def box(x1, y1, x2, y2):
        return pya.Box(int(round(min(x1, x2) * NM)),
                       int(round(min(y1, y2) * NM)),
                       int(round(max(x1, x2) * NM)),
                       int(round(max(y1, y2) * NM)))

    def add(layer, x1, y1, x2, y2, net):
        b = box(x1, y1, x2, y2)
        top.shapes(layer).insert(b)
        regions.setdefault((layer, net), pya.Region()).insert(b)
        return b

    def label(x, y, name, layer=None):
        top.shapes(layer or lay["m2l"]).insert(
            pya.Text(name, pya.Trans(int(round(x * NM)), int(round(y * NM)))))

    def dev_pcell(kind, w, l):
        c = ly.create_cell(f"{kind}_{w:g}_{l:g}")
        if not c.shapes(pya.LayerInfo(0, 0)).is_empty():
            return c
        if kind == "pfet":
            draw_pfet(c, l=l, w=w, nf=1, type=PFET, bulk="bulk tie",
                      gate_con_pos="top")
        else:
            draw_nfet(c, l=l, w=w, nf=1, type=NFET, bulk="bulk tie",
                      gate_con_pos="top")
        return c

    def place(cell, x, y):
        top.insert(pya.CellInstArray(cell.cell_index(),
                                     pya.Trans(int(round(x * NM)),
                                               int(round(y * NM)))))

    m_p = dev_pcell("pfet", DEV_W, PFET_L)
    m_n = dev_pcell("nfet", DEV_W, NFET_L)

    # Device placement: mirror and cascode side by side at the top, the pair
    # directly below.

    def one_cell(x, tag):
        md = "md_" + tag
        cd = "cd_" + tag
        # --- mirror (source vdd, drain md) -------------------------------
        place(m_p, x, 0)
        add(lay["m1"], x + SRC[0] / NM, 0.075, x + SRC[1] / NM, 7.925,
            "vdd")
        add(lay["m1"], x + DRN_P[0] / NM, 0.075, x + DRN_P[1] / NM, 7.925,
            md)
        # --- cascode (source md, drain the tail) ------------------------
        place(m_p, x + 2.5, 0)
        add(lay["m1"], x + 2.5 + SRC[0] / NM, 0.075,
            x + 2.5 + SRC[1] / NM, 7.925, md)
        add(lay["m1"], x + 2.5 + DRN_P[0] / NM, 0.075,
            x + 2.5 + DRN_P[1] / NM, 7.925, cd)
        add(lay["m1"], x + DRN_P[0] / NM, 0.075, x + DRN_P[1] / NM, 7.925,
            md)
        add(lay["m1"], x + DRN_P[0] / NM, 7.80, x + 2.5 + SRC[1] / NM, 8.15,
            md)
        # --- pair (shared source = tail) --------------------------------
        for k, net in ((0.0, "iout"), (2.5, "idump")):
            place(m_n, x + k, -9.5)
            add(lay["m1"], x + k + SRC[0] / NM, -9.425,
                x + k + SRC[1] / NM, -1.575, cd)
            add(lay["m1"], x + k + DRN_N[0] / NM, -9.425,
                x + k + DRN_N[1] / NM, -1.575, net)
        # --- gates: m1 pad -> via1 -> met2 ------------------------------
        for gx, net in ((x, "vbp"), (x + 2.5, "vcp")):
            add(lay["m1"], gx + GATE[0] / NM, GATE[2] / NM,
                gx + GATE[1] / NM, GATE[3] / NM, net)
            # sky130 via1 is a fixed 0.15 square: an array, never a bar.
            for vx in (0.325, 0.545):
                add(lay["v1"], gx + vx, 8.28, gx + vx + 0.15, 8.43, net)
            add(lay["m2"], gx + 0.30, 8.15, gx + 0.80, 8.60, net)
        # --- pair gate pads (two per cell on the 3.75 um grid) ----------
        for k, net in ((0.0, "d_" + tag), (3.75, "db_" + tag)):
            add(lay["m2"], x + k + 0.60, PAD_Y[0], x + k + 1.20, PAD_Y[1],
                net)
            label(x + k + 0.90, (PAD_Y[0] + PAD_Y[1]) / 2, net)

    n = dbg if dbg else n_cells
    for j in range(n):
        one_cell(j * PITCH, f"b{cell_bit(j)}_{j - (2 ** cell_bit(j) - 1)}")

    x_last = (n - 1) * PITCH
    x_end = x_last + PITCH
    x_b = x_end + 1.0
    # Rails.
    add(lay["m3"], -1.36, 0.20, x_b + 4.30, 8.20, "vdd")
    label(x_last / 2, 4.2, "vdd", lay["m3l"])
    add(lay["m3"], -1.36, -3.60, x_b + 4.30, -1.80, "iout")
    label(0.5, -2.7, "iout", lay["m3l"])
    add(lay["m3"], -1.36, -9.60, x_b + 4.30, -7.80, "idump")
    label(0.5, -8.7, "idump", lay["m3l"])
    add(lay["m1"], -1.36, -11.00, x_b + 4.30, -10.60, "vss")
    label(0.5, -10.8, "vss", lay["m1l"])

    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    ly.write(out_path)
    b = top.bbox()
    print(f"wrote {out_path}  (bbox {b.left * ly.dbu:.1f},"
          f"{b.bottom * ly.dbu:.1f};{b.right * ly.dbu:.1f},"
          f"{b.top * ly.dbu:.1f})")
    problems = []
    if do_check:
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
    if problems:
        sys.exit(1)
    return 0


if __name__ == "__main__":
    sys.exit(main())
