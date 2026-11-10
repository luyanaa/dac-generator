#!/usr/bin/env python3
"""IHP sg13g2 dump-tail cell core: 4 PCell devices + gate lands + taps.

    KLAYOUT_PATH=<pdk>/libs.tech/klayout klayout -b -r gen_gds.py \
        [-rd out=build/video_ihp_core.gds] [-rd dbg_cells=2]

This is the **cell core**, not yet the full array: it places the two pmos
(mirror 8/1, cascode 8/0.5), the two nmos (pair 4/0.28), their gate contacts
and the bulk taps, and stops there.  The array routing (md/cd, vbp/vcp, pads,
rails, replica) still has to be drawn around it; see the README.

The devices are the PDK's own `SG13_dev` PCells, which *are* usable headless:

  * the PCell library must be imported after KLayout's technology is set
    (`layout.technology_name = "sg13g2"`) and with the PDK's python tree on
    `sys.path`; otherwise `create_cell` returns nil;
  * parameters are **unit strings** (`"8u"`, `"0.5u"`), not metres: the
    `cni` wrapper in this PDK parses `Numeric("8.0u")`, and a float raises
    `could not convert string to float`;
  * the PCell cells are dynamic; `layout.flatten(top)` is what materialises
    the geometry before writing the GDS.

The PCell draws the source/drain on Metal1 and the gate as a bare GatPoly
stripe, with no gate contact and no bulk tap.  This generator adds:
  * a poly land at each gate end, wide enough that the contact keeps the 0.07
    um GatPoly enclosure on the 0.28 um nmos gate (a 0.16 contact cannot fit
    the bare gate), with no narrow poly finger (Gat.a/Gat.b);
  * the 1.00 um nBuLay enclosure around the ntap (NBL.e) and the nwell bar
    merged across the pfet row;
  * ntap1 (pfet well -> vdd later) and ptap1 (nmos substrate -> vss later).

The first four rules that had to be solved are recorded in the README.
"""
from __future__ import annotations

import sys

import pya

# IHP layer map (from the PDK's sg13g2.lyp / DRC decks)
M1 = (8, 0)
M1_LABEL = (8, 1)
CONT = (6, 0)
POLY = (5, 0)
NW = (31, 0)

PDK_PY = "/grid/dac-generator/pdks/ihp-sg13g2/libs.tech/klayout/python"
sys.path.insert(0, PDK_PY)
sys.path.insert(0, PDK_PY + "/pycell4klayout-api/source/python")
import sg13g2_pycell_lib  # noqa: E402,F401  (registers SG13_dev)

# device origins in one cell (um)
MX, CX, PY = 0.31, 3.00, -6.0
PITCH = 7.5

# gate land geometry: (poly x1, poly x2, contact centre) relative to the
# device origin; the nmos land is deliberately wider than the 0.28 gate so
# the outward finger is >= Gat.a 0.13.
LANDS = {
    "pmos1": (0.34, 1.34, 0.84),
    "pmos05": (0.34, 0.84, 0.59),
    "nmos": (0.34, 0.62, 0.48),
}


def rect(x1, y1, x2, y2):
    q = lambda v: int(round(round(v / 0.005) * 5))  # 5 nm grid
    return pya.Box(q(x1), q(y1), q(x2), q(y2))


def main() -> int:
    g = globals()
    out_path = g.get("out", "/grid/dac-generator/analog/video_ihp/build/"
                             "video_ihp_core.gds")
    dbg = int(g.get("dbg_cells", 1))

    ly = pya.Layout()
    ly.dbu = 0.001
    ly.technology_name = "sg13g2"
    top = ly.create_cell("dac_video_ihp")
    m1 = ly.layer(*M1)
    cont = ly.layer(*CONT)
    poly = ly.layer(*POLY)
    nw = ly.layer(*NW)

    def place(kind, kw, x, y):
        c = ly.create_cell(kind, "SG13_dev", kw)
        top.insert(pya.CellInstArray(c.cell_index(),
                                     pya.Trans(int(round(x * 1000)),
                                               int(round(y * 1000)))))

    for j in range(dbg):
        x = j * PITCH
        place("pmos", {"l": "1u", "w": "8u", "ng": 1}, x + MX, 0)
        place("pmos", {"l": "0.5u", "w": "8u", "ng": 1}, x + CX, 0)
        place("nmos", {"l": "0.28u", "w": "4u", "ng": 1}, x + MX, PY)
        place("nmos", {"l": "0.28u", "w": "4u", "ng": 1}, x + CX, PY)
        place("ntap1", {}, x + 1.5, 9.2)
        place("ptap1", {}, x + 1.5, -8.2)
        # merged pfet well, tall enough to give the ntap's nBuLay its 1 um
        ly.flatten(top.cell_index(), -1, False)
        top.shapes(nw).insert(rect(x - 0.5, -0.31, x + 4.6, 10.5))
        # pfet gates
        for kind, dx, y0 in (("pmos1", MX, 0.0), ("pmos05", CX, 0.0)):
            p1, p2, gc = LANDS[kind]
            top.shapes(poly).insert(rect(x + dx + p1, y0 - 0.5,
                                        x + dx + p2, y0 - 0.17))
            top.shapes(cont).insert(rect(x + dx + gc - 0.08, y0 - 0.40,
                                        x + dx + gc + 0.08, y0 - 0.24))
            top.shapes(m1).insert(rect(x + dx + gc - 0.15, y0 - 0.47,
                                      x + dx + gc + 0.15, y0 - 0.18))
        # nmos gate lands
        for dx in (MX, CX):
            gc = dx + LANDS["nmos"][2]
            top.shapes(poly).insert(rect(x + gc - 0.28, PY - 0.50,
                                        x + gc + 0.30, PY - 0.17))
            top.shapes(cont).insert(rect(x + gc - 0.08, PY - 0.43,
                                        x + gc + 0.08, PY - 0.27))
            top.shapes(m1).insert(rect(x + gc - 0.18, PY - 0.54,
                                      x + gc + 0.18, PY - 0.20))

    ly.flatten(top.cell_index(), -1, False)
    out = pya.Layout()
    out.dbu = ly.dbu
    out.create_cell("dac_video_ihp").copy_shapes(top)
    out.write(out_path)
    b = out.top_cells()[0].bbox()
    print(f"wrote {out_path} (bbox {b.left * out.dbu:.2f},"
          f"{b.bottom * out.dbu:.2f};{b.right * out.dbu:.2f},"
          f"{b.top * out.dbu:.2f}, cells {dbg})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
