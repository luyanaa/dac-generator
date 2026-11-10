#!/usr/bin/env python3
r"""Generate the 255-cell array of the 8-bit 25 MS/s video DAC (P5).

This is the reusable *device* generator for P5: 255 **identical** switched
cascoded-PMOS unit cells in one row, the shared bias/supply distribution, the
replica cascode bias generator, and the analog-facing pin row.  It does not
draw transistor geometry: every device is the PDK `pfet` PCell, and the script
only adds the M1/poly straps, the via stacks and the terminal pads.

The 1/2/4/.../128 weight is the *cell count* on each gate net, not the device
width: all 255 cells are the same 8/1 mirror + 8/0.5 cascode, and the cell tag
carries the binary grouping (`b7_63` is the 64th cell of the 128-cell bit-7
bank), so LVS re-derives the weighting from the netlist alone.

Cell (P5 differs from P3 in one respect: the switch sits between the supply
and the mirror, so there is no steering pair, no idump, and *off* really is
zero current):

      vdd plane (M3, y = 0.2..8.2, over the devices)
        |
      [sw pfet 0.5/0.28]      <- gate is the cell's only pin
        |
      [mirror 8/1] --- [cascode 8/0.5] --> iout (M3 bus, y = -2.6..-1.8)
        |                    |
       vbp (M2 rail)      vcp (poly bar)

  * the mirror bulk tie is still vdd; the mirror *source* is now the switch
    drain, which is the whole point of the series switch.
  * the switch is rotated (R90) and placed under the mirror, so the cell is
    one pin wide instead of two and the pin riser drops straight down.
  * the pin row is at the bottom edge on a uniform 7.5 um grid: one M2 pad per
    cell, in cell order, so a hardened digital macro can abut below it.
  * the cascode drain is wired straight down to the shared iout bus, so the
    array has a single output node (single-ended video output).

Supply distribution: vdd is an M3 plane 8 um wide over the ~1.9 mm array, each
cell tapping it through its own via1/via2 stack.  M3 is 0.01 Ohm/sq in gf180
against 0.09 for M1/M2, so the same current costs a tenth of the drop; a 1.9 mm
M1 bar would be hundreds of ohms.  iout is an M3 bus below the devices for the
same reason: a resistive output bus would eat the cascode's compliance.

What it does not contain (class C, hand layout, see README):

  * the output pad / ESD / cable driver,
  * the digital macro (`verilog/rtl/dac_video_dig.v`, 255 registered switches)
    and the wrapper that abuts it,
  * the wrapper pin script (it must read `build/pinplan.json`).

Usage (KLayout's interpreter, not system python3):
    klayout -b -r gen_gds.py [-rd out=build/video.gds] [-rd check=true]
                             [-rd dbg_cells=N]
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pya

HERE = Path(__file__).resolve().parent

# --- pfet PCell geometry at ld=0.44 (probed from the PDK PCell, um) ---------
LD = 0.44
MIR_L = 1.0              # mirror: W/L 8/1   (the P3 measured cell)
CAS_L = 0.5              # cascode: W/L 8/0.5
W = 8.0
CAS_DX = 2.98            # cascode origin; comp gap 0.34 (DF.3a wants 0.28)
PITCH = 7.5              # cell pitch; the pin row grid

SW_L = 0.28              # supply switch
SW_W = 0.5
SW_X = 0.37              # switch origin: under the mirror source strip
SW_Y = -1.50

M1 = (34, 0)
M1_LABEL = (34, 10)
VIA1 = (35, 0)
M2 = (36, 0)
M2_LABEL = (36, 10)
VIA2 = (38, 0)
M3 = (42, 0)
M3_LABEL = (42, 10)
POLY = (30, 0)
POLY_LABEL = (30, 10)
CONTACT = (33, 0)

# rails / bands
Y_VBP = (8.44, 8.80)     # mirror gate bias, on M2 across the array
Y_VBP_POLY = 8.85        # poly riser end: 0.10 of poly over the contact
Y_VCP = (9.45, 9.85)     # cascode gate bias, on poly across the array
Y_PLANE = (0.20, 8.20)   # vdd plane, M3
Y_IOUT = (-3.60, -1.80)  # output bus, M3 (MT30.1: 1.8 um min width)
Y_PIN = (-4.60, -4.20)   # analog-facing pin row, M2
PIN_W = 0.60
PIN_DX = 1.00            # pin centre inside the cell


def left_term():
    return (-0.01, 0.37)


def right_term(l):
    return (0.51 + l, 0.89 + l)


def gate_span(l):
    return (0.44, 0.44 + l)


def tie_span():
    return (-0.76, -0.32)


def comp_span(l):
    return (-0.76, 0.88 + l)


def nwell_span(l):
    return (-0.88, 1.31 + l)


# --- rotated (R90) pfet at (X, Y): probed, W/L 0.5/0.28 --------------------
def sw_terms(X, Y):
    """Terminal geometry of the rotated supply switch."""
    return {
        "comp": (X - SW_W, X, Y, Y + 1.16),
        "src": (X - 0.51, X + 0.01, Y - 0.01, Y + 0.37),
        "drain": (X - 0.51, X + 0.01, Y + 0.79, Y + 1.17),
        "gate": (X - 0.72, X + 0.22, Y + 0.44, Y + 0.72),
        "tie": (X - 0.50, X, Y - 0.76, Y - 0.32),
        "nwell": (X - 0.93, X + 0.43, Y - 0.88, Y + 1.59),
    }


def cell_bit(j):
    """Binary bit of unit cell j: smallest k with j < 2**(k+1) - 1."""
    k = 0
    while j >= 2 ** (k + 1) - 1:
        k += 1
    return k, j - (2 ** k - 1)


def load_cfg():
    try:
        import yaml
    except ImportError:  # pragma: no cover
        sys.exit("PyYAML is required: pip install pyyaml")
    with open(HERE / "video.yaml") as f:
        return yaml.safe_load(f)


def pdk_root() -> Path:
    base = Path(os.path.expanduser("~/.ciel/ciel/gf180mcu/versions"))
    if not base.is_dir():
        sys.exit(f"{base} not found; pass -rd pdkroot=<dir>")
    return base / sorted(p.name for p in base.iterdir() if p.is_dir())[-1] / "gf180mcuA"


def main() -> int:
    g = globals()

    def opt(name, default=None):
        v = g.get(name, default)
        return v if isinstance(v, (str, int, float)) else default

    out_path = opt("out", str(HERE / "build" / "video.gds"))
    do_check = str(opt("check", "false")).lower() in ("1", "true", "yes")
    cfg = load_cfg()
    n_bits = int(cfg["bits"])
    n_cells = 2 ** n_bits - 1

    root = Path(opt("pdkroot") or pdk_root())
    libdir = root / "libs.tech" / "klayout" / "tech" / "pymacros"
    if str(libdir) not in sys.path:
        sys.path.insert(0, str(libdir))
    from klayout_api_cells import gf180mcu_klayoutapi  # noqa: E402

    lib = gf180mcu_klayoutapi()
    ly = pya.Layout()
    ly.dbu = 0.001
    top = ly.create_cell("dac_video_ana")
    m1 = ly.layer(*M1)
    m1_lbl = ly.layer(*M1_LABEL)
    via1 = ly.layer(*VIA1)
    m2 = ly.layer(*M2)
    m2_lbl = ly.layer(*M2_LABEL)
    via2 = ly.layer(*VIA2)
    m3 = ly.layer(*M3)
    m3_lbl = ly.layer(*M3_LABEL)
    poly = ly.layer(*POLY)
    poly_lbl = ly.layer(*POLY_LABEL)
    cont = ly.layer(*CONTACT)

    def box(x1, y1, x2, y2):
        return pya.Box(int(round(x1 * 1000)), int(round(y1 * 1000)),
                       int(round(x2 * 1000)), int(round(y2 * 1000)))

    # keyed by (layer, net): the same net on poly and on M1 may overlap freely
    regions: dict[tuple[int, str], pya.Region] = {}

    def add(layer, x1, y1, x2, y2, net):
        b = box(x1, y1, x2, y2)
        top.shapes(layer).insert(b)
        regions.setdefault((layer, net), pya.Region()).insert(b)
        return b

    def label(x, y, name, layer=m1_lbl):
        top.shapes(layer).insert(
            pya.Text(name, pya.Trans(int(round(x * 1000)), int(round(y * 1000)))))

    # ---------- cells -----------------------------------------------------
    cells = []
    for j in range(n_cells):
        k, i = cell_bit(j)
        cells.append(("b%d_%d" % (k, i), k))

    dbg = int(opt("dbg_cells", 0))
    if dbg:
        cells = cells[:dbg]

    pcell_cache: dict[tuple[float, float], object] = {}

    def pfet_pcell(l, w):
        key = (round(l, 6), round(w, 6))
        if key not in pcell_cache:
            pcell_cache[key] = ly.create_cell(
                "pfet", lib.name(),
                {"l": l, "w": w, "ld": LD, "nf": 1,
                 "bulk": "Bulk Tie", "volt": "3.3V"})
        return pcell_cache[key]

    nsw = sw_terms(SW_X, SW_Y)

    for k, (tag, bit) in enumerate(cells):
        x = k * PITCH
        out_net = "d_" + tag
        top.insert(pya.CellInstArray(pfet_pcell(MIR_L, W).cell_index(),
                                     pya.Trans(int(x * 1000), 0)))
        top.insert(pya.CellInstArray(pfet_pcell(CAS_L, W).cell_index(),
                                     pya.Trans(int((x + CAS_DX) * 1000), 0)))
        top.insert(pya.CellInstArray(pfet_pcell(SW_L, SW_W).cell_index(),
                                     pya.Trans(pya.Trans.R90,
                                               int((x + SW_X) * 1000),
                                               int(SW_Y * 1000))))

        # PCell terminals, for the self-check and for the straps below.
        lt = left_term()
        rt_m = right_term(MIR_L)
        rt_c = right_term(CAS_L)
        tie = tie_span()
        regions.setdefault((m1, "n_" + tag), pya.Region()).insert(
            box(x + rt_m[0], -0.01, x + rt_m[1], W + 0.01))   # mirror drain
        regions.setdefault((m1, "n_" + tag), pya.Region()).insert(
            box(x + CAS_DX + lt[0], -0.01, x + CAS_DX + lt[1], W + 0.01))
        regions.setdefault((m1, "vdd"), pya.Region()).insert(
            box(x + tie[0], 0.0, x + tie[1], W))              # mirror tie
        regions.setdefault((m1, out_net), pya.Region()).insert(
            box(x + lt[0], -0.01, x + lt[1], W + 0.01))       # mirror source
        regions.setdefault((m1, "iout"), pya.Region()).insert(
            box(x + CAS_DX + rt_c[0], -0.01,
                x + CAS_DX + rt_c[1], W + 0.01))              # cascode drain
        regions.setdefault((m1, "vdd"), pya.Region()).insert(
            box(x + nsw["src"][0], nsw["src"][2],
                x + nsw["src"][1], nsw["src"][3]))
        regions.setdefault((m1, out_net), pya.Region()).insert(
            box(x + nsw["drain"][0], nsw["drain"][2],
                x + nsw["drain"][1], nsw["drain"][3]))
        regions.setdefault((m1, "vdd"), pya.Region()).insert(
            box(x + nsw["tie"][0], nsw["tie"][2],
                x + nsw["tie"][1], nsw["tie"][3]))
        regions.setdefault((poly, out_net), pya.Region()).insert(
            box(x + nsw["gate"][0], nsw["gate"][2],
                x + nsw["gate"][1], nsw["gate"][3]))
        g = gate_span(MIR_L)
        regions.setdefault((poly, "vbp"), pya.Region()).insert(
            box(x + g[0], -0.22, x + g[1], W + 0.22))
        g = gate_span(CAS_L)
        regions.setdefault((poly, "vcp"), pya.Region()).insert(
            box(x + CAS_DX + g[0], -0.22, x + CAS_DX + g[1], W + 0.22))

        # --- mirror drain -> cascode source, over the top (P3's bridge) ----
        add(m1, x + rt_m[0], W - 0.01, x + rt_m[1], 8.55, "n_" + tag)
        add(m1, x + CAS_DX + lt[0], W - 0.01,
            x + CAS_DX + lt[1], 8.55, "n_" + tag)
        add(m1, x + rt_m[0], 8.25, x + CAS_DX + lt[1] - 0.04, 8.55,
            "n_" + tag)

        # --- switch ------------------------------------------------------
        # drain -> mirror source
        add(m1, x + lt[0], -0.33, x + lt[1], 0.02, out_net)
        # source + bulk tie -> vdd, then left and up into the mirror tie strip
        add(m1, x + nsw["tie"][0], -1.84, x + nsw["src"][1], -1.13, "vdd")
        add(m1, x - 0.64, -1.84, x + nsw["tie"][0], -1.50, "vdd")
        add(m1, x - 0.64, -1.84, x - 0.39, 0.30, "vdd")

        # --- mirror gate -> vbp (poly -> contact -> M1 -> via1 -> M2) -----
        g = gate_span(MIR_L)
        add(poly, x + g[0], W + 0.22, x + g[1], Y_VBP_POLY, "vbp")
        add(m1, x + 0.50, 8.44, x + 1.24, 8.80, "vbp")
        top.shapes(cont).insert(box(x + 0.57, 8.51, x + 0.81, 8.75))
        top.shapes(via1).insert(box(x + 0.90, 8.50, x + 1.16, 8.76))

        # --- switch gate -> pin (poly paddle -> contact -> M1 -> via1) ----
        add(poly, x + 0.59, -1.06, x + 1.34, -0.78, out_net)
        add(poly, x + 0.68, -1.14, x + 1.30, -0.70, out_net)
        top.shapes(cont).insert(box(x + 0.76, -1.03, x + 1.00, -0.79))
        add(m1, x + 0.70, -1.12, x + 1.30, -0.74, out_net)
        top.shapes(via1).insert(box(x + 0.98, -1.02, x + 1.24, -0.76))

        # --- cascode gate -> vcp (poly riser, no contact) -----------------
        g = gate_span(CAS_L)
        add(poly, x + CAS_DX + g[0], W + 0.22,
            x + CAS_DX + g[1], Y_VCP[1], "vcp")

        # --- cascode drain -> iout ----------------------------------------
        add(m1, x + CAS_DX + rt_c[0], -3.20,
            x + CAS_DX + rt_c[1], 0.02, "iout")
        top.shapes(via1).insert(box(x + CAS_DX + rt_c[0] + 0.06, -3.14,
                                    x + CAS_DX + rt_c[1] - 0.06, -2.88))
        add(m2, x + CAS_DX + rt_c[0] - 0.02, -3.22,
            x + CAS_DX + rt_c[1] + 0.02, -2.50, "iout")
        top.shapes(via2).insert(box(x + CAS_DX + rt_c[0] + 0.04, -2.85,
                                    x + CAS_DX + rt_c[1] - 0.04, -2.55))

        # --- vdd tie -> M3 plane (via1 - M2 patch - via2) -----------------
        top.shapes(via1).insert(box(x - 0.68, 1.02, x - 0.42, 1.28))
        add(m2, x - 0.76, 0.96, x - 0.34, 1.76, "vdd")
        top.shapes(via2).insert(box(x - 0.69, 1.40, x - 0.39, 1.70))

        # --- pin ----------------------------------------------------------
        add(m2, x + 0.89, -4.30, x + 1.29, -0.72, out_net)
        add(m2, x + PIN_DX - PIN_W / 2, Y_PIN[0],
            x + PIN_DX + PIN_W / 2, Y_PIN[1], out_net)
        label(x + PIN_DX, (Y_PIN[0] + Y_PIN[1]) / 2, out_net, m2_lbl)

    n_placed = len(cells)
    x_last = (n_placed - 1) * PITCH
    x_end = x_last + PITCH
    x_b = x_end + 1.0                    # replica bias generator origin

    # ---------- shared distribution ---------------------------------------
    # vdd plane on M3, over the devices, both ends open (the wrapper straps it).
    add(m3, -1.36, Y_PLANE[0], x_b + CAS_DX + 1.30, Y_PLANE[1], "vdd")
    label(x_last / 2, (Y_PLANE[0] + Y_PLANE[1]) / 2, "vdd", m3_lbl)

    # vbp on M2: crosses the cascode gate risers (poly) and the output risers
    # (M1) without a via, so it is one net end to end; each cell reaches it
    # through its own contact/via1 stack.
    add(m2, -1.36, Y_VBP[0], x_b + CAS_DX + 1.24, Y_VBP[1], "vbp")
    label(x_last / 2, (Y_VBP[0] + Y_VBP[1]) / 2, "vbp", m2_lbl)

    # vcp on poly: straight bar from the first cascode gate riser to the
    # replica cascode's riser at the right end, so the 255 gates and the bias
    # diode are one drawn net (a bar that stopped at the last cell left the
    # replica on its own island - caught by the LVS stage).
    g0 = gate_span(CAS_L)
    add(poly, CAS_DX + g0[0], Y_VCP[0], x_b + CAS_DX + g0[1] + 0.02,
        Y_VCP[1], "vcp")

    # iout bus on M3 under the devices, straight to both ends.
    add(m3, -1.36, Y_IOUT[0], x_b + CAS_DX + 1.30, Y_IOUT[1], "iout")
    label(0.5, (Y_IOUT[0] + Y_IOUT[1]) / 2, "iout", m3_lbl)

    # ---------- replica cascode bias --------------------------------------
    # One 16 uA reference injected at the vcp pad drives
    #   Mref (8/1)   vdd -> vbp, gate = drain = vbp
    #   Mcas (8/0.5) vbp -> vcp, gate = drain = vcp
    # so vbp is the mirror gate and vcp one cascode Vgs below it.  The replica
    # has no series switch: the cells' switches degenerate their own mirrors,
    # which is a systematic gain term (see README, and the post-layout bench
    # measures it), not a matching term.
    pcell_mir = pfet_pcell(MIR_L, W)
    pcell_cas = pfet_pcell(CAS_L, W)
    top.insert(pya.CellInstArray(pcell_mir.cell_index(),
                                 pya.Trans(int(x_b * 1000), 0)))
    top.insert(pya.CellInstArray(pcell_cas.cell_index(),
                                 pya.Trans(int((x_b + CAS_DX) * 1000), 0)))
    g = gate_span(MIR_L)
    rt = right_term(MIR_L)
    # Mref source + tie to vdd: one M1 bar under the device, then a via stack
    # up to the plane on the tie strip (same stack as a cell).
    add(m1, x_b - 0.78, -0.75, x_b + 2.24, -0.30, "vdd")
    add(m1, x_b - 0.01, -0.75, x_b + 0.37, 0.02, "vdd")
    add(m1, x_b - 0.76, -0.75, x_b - 0.32, 0.02, "vdd")
    add(m1, x_b + CAS_DX - 0.76, -0.75, x_b + CAS_DX - 0.32, 0.02, "vdd")
    top.shapes(via1).insert(box(x_b - 0.68, 1.02, x_b - 0.42, 1.28))
    add(m2, x_b - 0.76, 0.96, x_b - 0.34, 1.76, "vdd")
    top.shapes(via2).insert(box(x_b - 0.69, 1.40, x_b - 0.39, 1.70))
    # Mref gate + drain -> vbp
    add(poly, x_b + g[0], W + 0.22, x_b + g[1], Y_VBP_POLY, "vbp")
    add(m1, x_b + 0.50, 8.44, x_b + rt[1], 8.80, "vbp")
    top.shapes(cont).insert(box(x_b + 0.57, 8.51, x_b + 0.81, 8.75))
    add(m1, x_b + rt[0], 8.01, x_b + rt[1], 8.46, "vbp")
    top.shapes(via1).insert(box(x_b + 0.90, 8.50, x_b + 1.16, 8.76))
    # Mcas source -> vbp, gate + drain -> vcp
    g = gate_span(CAS_L)
    rt = right_term(CAS_L)
    add(m1, x_b + CAS_DX - 0.01, 8.01, x_b + CAS_DX + 0.37, 8.80, "vbp")
    top.shapes(via1).insert(box(x_b + CAS_DX + 0.05, 8.46,
                                x_b + CAS_DX + 0.31, 8.72))
    add(poly, x_b + CAS_DX + g[0], W + 0.22,
        x_b + CAS_DX + g[1], Y_VCP[1], "vcp")
    add(m1, x_b + CAS_DX + 0.50, Y_VCP[0],
        x_b + CAS_DX + rt[1] + 0.35, 10.05, "vcp")
    top.shapes(cont).insert(box(x_b + CAS_DX + 0.58, 9.53,
                                x_b + CAS_DX + 0.80, 9.75))
    add(m1, x_b + CAS_DX + rt[0], 8.01,
        x_b + CAS_DX + rt[1], Y_VCP[0] + 0.02, "vcp")
    # vcp pad to the right of the last cascode riser.
    xc = x_b + CAS_DX + rt[1] + 0.30
    add(poly, x_b + CAS_DX + g[1], Y_VCP[0], xc + 0.45, Y_VCP[1], "vcp")
    top.shapes(cont).insert(box(xc + 0.09, 9.52, xc + 0.33, 9.76))
    add(m1, xc, Y_VCP[0], xc + 0.60, 10.05, "vcp")
    label(xc + 0.3, 9.75, "vcp")

    # ---------- self-check ------------------------------------------------
    problems = []
    if do_check:
        want_dev = 3 * n_placed + 2
        want_pins = n_placed if not dbg else dbg
        if len(cells) != want_pins:
            problems.append(f"{len(cells)} cells, want {want_pins}")
        # different nets must not touch on the same layer
        keys = sorted(regions, key=lambda kk: (kk[0], kk[1]))
        for i in range(len(keys)):
            for j in range(i + 1, len(keys)):
                if keys[i][0] != keys[j][0]:
                    continue
                inter = regions[keys[i]] & regions[keys[j]]
                if not inter.is_empty():
                    bb = inter.bbox()
                    problems.append(
                        f"SHORT {keys[i][1]} <-> {keys[j][1]} at "
                        f"({bb.left / 1000:.2f},{bb.bottom / 1000:.2f})")
        print(f"devices    : {want_dev} pfet "
              f"(3 per cell + replica bias), {len(cells)} unit cells")
        print(f"pins       : {len(cells)} switch gates on a {PITCH} um M2 row "
              f"at y={Y_PIN[0]}")
        print(f"rails      : vdd M3 plane {Y_PLANE[0]}..{Y_PLANE[1]}, "
              f"vbp M2 {Y_VBP}, vcp poly {Y_VCP}, iout M3 {Y_IOUT}")
        for p in problems:
            print("  " + p)
    if problems:
        sys.exit(1)

    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    ly.write(out_path)
    b = top.bbox()
    print(f"wrote {out_path}  (bbox {b.left / 1000:.1f},{b.bottom / 1000:.1f};"
          f"{b.right / 1000:.1f},{b.top / 1000:.1f})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
