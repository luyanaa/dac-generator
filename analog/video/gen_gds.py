#!/usr/bin/env python3
r"""Generate the 255-cell array of the 8-bit 25 MS/s video DAC (P5).

This is the reusable *device* generator for P5: 255 **identical** switched
cascoded-PMOS unit cells in one row, the shared bias/supply distribution, a
replica *cell* as the bias generator (same switch, mirror and cascode, diode
connected), and the analog-facing pin row.  It does not draw transistor
geometry: every device is the PDK `pfet` PCell, and the script only adds the
M1/poly straps, the via stacks and the terminal pads.

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
  * the bias branch repeats the cell's series switch, because that switch
    drops I*Ron in the mirror's source and so sets the operating point: a
    bias branch without it runs the cells ~50 % low.  (Removed with the
    source switch: the dump-tail cell keeps the tail flowing, so the bias
    branch is just the two diode-connected devices.)  Its gate was `vgnd`, a
    static 0 V reference the wrapper grounds - the one port besides the four
    rails.
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

NS_L = 0.28              # steering pair: one 4/0.28 NMOS per destination
NS_W = 4.0
PAIR_DX = 5.0            # pair origin; comp from x+1.0 to x+5.0
PAIR_YA = -6.4           # row A (iout); row B is 2.8 um below

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
Y_IDUMP = (-9.60, -7.80)  # dump bus, M3 (MT30.1: 1.8 um min width)
Y_VSS = (-11.00, -10.60)  # bulk-tie rail, M1 (no current, so no M3)
Y_PIN = (-11.60, -11.20)  # analog-facing pin row, M2
PIN_W = 0.60
PIN_A = 2.25             # d_<tag>  pad centre within the cell
PIN_B = 6.00             # db_<tag> pad centre; B - A = 3.75


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
        return pya.Box(int(round(min(x1, x2) * 1000)),
                       int(round(min(y1, y2) * 1000)),
                       int(round(max(x1, x2) * 1000)),
                       int(round(max(y1, y2) * 1000)))

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
    # -rd pair=0 drops the steering pair: a bisect switch for DRC work only.
    do_pair = str(opt("pair", "1")).lower() not in ("0", "false", "no")
    do_parts = set(str(opt("parts", "abcdef")).replace(",", ""))
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

    lt = left_term()
    rt_m = right_term(MIR_L)
    rt_c = right_term(CAS_L)
    tie = tie_span()

    def reg(layer, net, x1, y1, x2, y2):
        regions.setdefault((layer, net), pya.Region()).insert(
            box(x1, y1, x2, y2))

    # The steering pair: one 4/0.28 NMOS per destination, rotated (W along x).
    # Probed from the PDK nfet PCell at ld=0.44, the same numbers csteer uses.
    nfet_pcell = ly.create_cell("nfet", lib.name(),
                                {"l": NS_L, "w": NS_W, "ld": LD, "nf": 1,
                                 "bulk": "Bulk Tie", "volt": "3.3V"})

    def nsw(X, Y):
        return {
            "comp": (X - NS_W, Y, X, Y + 1.16),
            "src": (X - NS_W, Y - 0.01, X, Y + 0.37),
            "drain": (X - NS_W, Y + 0.79, X, Y + 1.17),
            "gate": (X - NS_W - 0.22, Y + 0.44, X + 0.22, Y + 0.72),
            "tie": (X - NS_W, Y - 0.76, X, Y - 0.32),
        }

    def draw_pair(x, tag):
        """The dump-tail steering pair and both gate pin paths.

        The mirror's source is vdd and its drain feeds the cascode; the pair
        takes the constant tail from the cascode's drain (`cd_<tag>`) and
        steers it to `iout` or `idump`.  Neither terminal of the mirror moves
        with the code, which is the whole point of this cell.
        """
        XA = x + PAIR_DX
        YA, YB = PAIR_YA, PAIR_YA - 2.8
        cd = "cd_" + tag
        for Y, row_net, gate_net in ((YA, "iout", "d_" + tag),
                                     (YB, "idump", "db_" + tag)):
            t = nsw(XA, Y)
            top.insert(pya.CellInstArray(
                nfet_pcell.cell_index(),
                pya.Trans(pya.Trans.R90, int(XA * 1000), int(Y * 1000))))
            reg(m1, cd, *t["src"])
            reg(m1, row_net, *t["drain"])
            reg(poly, gate_net, *t["gate"])
            reg(m1, "vss", *t["tie"])
            if "b" in do_parts:
                # bulk tie -> vss: M1 arm out to the left, one via1
                add(m1, x + 0.34, Y - 0.82, x + 1.06, Y - 0.38, "vss")
                top.shapes(via1).insert(box(x + 0.42, Y - 0.74,
                                            x + 0.68, Y - 0.48))
        # vss strap down the left edge to the M1 rail, clear of the drains
        if "b" in do_parts:
            add(m2, x + 0.30, -10.99, x + 0.76, YA - 0.38, "vss")
            top.shapes(via1).insert(box(x + 0.42, -10.93, x + 0.68, -10.67))
        # pair tail (cd): one M2 riser on the right edge, three via1s
        if "c" in do_parts:
            add(m2, XA - 0.46, YB - 0.16, XA - 0.08, -2.74, cd)
            for Y in (YA, YB):
                top.shapes(via1).insert(box(XA - 0.40, Y + 0.05,
                                            XA - 0.14, Y + 0.31))
            top.shapes(via1).insert(box(XA - 0.40, -3.08, XA - 0.14, -2.82))
        # row A drain -> iout, row B drain -> idump (via1, M2, via2)
        for Y, row_net, y2, y1 in ((YA, "iout", -3.10, -5.62),
                                   (YB, "idump", -7.96, -8.92)):
            if "d" not in do_parts:
                continue
            add(m1, x + 1.05, Y + 0.79, x + 1.51, Y + 1.35, row_net)
            top.shapes(via1).insert(box(x + 1.13, Y + 0.92,
                                        x + 1.39, Y + 1.18))
            add(m2, x + 1.06, y1, x + 1.48, y2, row_net)
            top.shapes(via2).insert(box(x + 1.12, y2 - 0.36,
                                        x + 1.42, y2 - 0.06))
        # gate paddles: poly past the active, one contact, M1 pad, via1, M2
        # riser.  The M1 pad keeps 0.23+ to the pair's drain strips (x+5.0),
        # so the paddles reach x+5.70 (d) and x+6.70 (db).
        for Y, gate_net, pxc, ybot in ((YA, "d_" + tag, x + 5.72, -9.86),
                                       (YB, "db_" + tag, x + 6.72, -10.62)):
            if "e" not in do_parts:
                continue
            g = nsw(XA, Y)
            gm = (g["gate"][1] + g["gate"][3]) / 2
            # The paddle starts 0.12 outside the diffusion (PL.5a wants 0.10)
            # and merges with the gate bar's own 0.22 overhang, so the gate's
            # y extent over the active never changes.
            add(poly, XA + 0.12, gm - 0.22, pxc, gm + 0.22, gate_net)
            c = pxc - 0.40
            top.shapes(cont).insert(box(c, gm - 0.12, c + 0.24, gm + 0.12))
            add(m1, c - 0.06, gm - 0.22, c + 0.40, gm + 0.22, gate_net)
            top.shapes(via1).insert(box(c + 0.01, gm - 0.13,
                                        c + 0.27, gm + 0.13))
            add(m2, c - 0.05, ybot, c + 0.33, gm + 0.16, gate_net)
        # pin row: two pads per cell on a 3.75 um grid, cell order d then db
        if "f" in do_parts:
            for pnet, px in (("d_" + tag, PIN_A), ("db_" + tag, PIN_B)):
                add(m2, x + px - PIN_W / 2, Y_PIN[0],
                    x + px + PIN_W / 2, Y_PIN[1], pnet)
                label(x + px, (Y_PIN[0] + Y_PIN[1]) / 2, pnet, m2_lbl)
        # d pad feed: M2 left at -10.20, then a stub down into the pad
        if "f" in do_parts:
            add(m2, x + PIN_A - 0.35, -10.20, x + 5.67, -9.82, "d_" + tag)
            add(m2, x + PIN_A - 0.30, -11.30, x + PIN_A + 0.05, -9.92,
                "d_" + tag)
        # db pad feed: its riser is over the pad column already
        if "f" in do_parts:
            add(m2, x + PIN_B - 0.22, -10.90, x + 6.67, -10.52, "db_" + tag)
            add(m2, x + PIN_B - 0.30, -11.30, x + PIN_B + 0.05, -10.62,
                "db_" + tag)

    for k, (tag, bit) in enumerate(cells):
        x = k * PITCH
        md = "md_" + tag
        cd = "cd_" + tag
        top.insert(pya.CellInstArray(pfet_pcell(MIR_L, W).cell_index(),
                                     pya.Trans(int(x * 1000), 0)))
        top.insert(pya.CellInstArray(pfet_pcell(CAS_L, W).cell_index(),
                                     pya.Trans(int((x + CAS_DX) * 1000), 0)))

        # PCell terminals, for the self-check and the straps below.  The
        # mirror's source is vdd now (no series switch): the cell's only
        # switching devices are the pair's two NMOS.
        reg(m1, md, x + rt_m[0], -0.01, x + rt_m[1], W + 0.01)
        reg(m1, md, x + CAS_DX + lt[0], -0.01,
            x + CAS_DX + lt[1], W + 0.01)
        reg(m1, cd, x + CAS_DX + rt_c[0], -0.01,
            x + CAS_DX + rt_c[1], W + 0.01)
        reg(m1, "vdd", x + tie[0], 0.0, x + tie[1], W)
        reg(m1, "vdd", x + lt[0], -0.01, x + lt[1], W + 0.01)
        g = gate_span(MIR_L)
        reg(poly, "vbp", x + g[0], -0.22, x + g[1], W + 0.22)
        g = gate_span(CAS_L)
        reg(poly, "vcp", x + CAS_DX + g[0], -0.22,
            x + CAS_DX + g[1], W + 0.22)

        # --- mirror drain -> cascode source, over the top (P3's bridge) ----
        add(m1, x + rt_m[0], W - 0.01, x + rt_m[1], 8.55, md)
        add(m1, x + CAS_DX + lt[0], W - 0.01,
            x + CAS_DX + lt[1], 8.55, md)
        add(m1, x + rt_m[0], 8.25, x + CAS_DX + lt[1] - 0.04, 8.55, md)

        # --- mirror source + bulk tie -> vdd -------------------------------
        add(m1, x - 0.76, -0.01, x + lt[1], 0.37, "vdd")

        # --- mirror gate -> vbp (poly -> contact -> M1 -> via1 -> M2) -----
        g = gate_span(MIR_L)
        add(poly, x + g[0], W + 0.22, x + g[1], Y_VBP_POLY, "vbp")
        add(m1, x + 0.50, 8.44, x + 1.24, 8.80, "vbp")
        top.shapes(cont).insert(box(x + 0.57, 8.51, x + 0.81, 8.75))
        top.shapes(via1).insert(box(x + 0.90, 8.50, x + 1.16, 8.76))

        # --- cascode gate -> vcp (poly riser, no contact) -----------------
        g = gate_span(CAS_L)
        add(poly, x + CAS_DX + g[0], W + 0.22,
            x + CAS_DX + g[1], Y_VCP[1], "vcp")

        # --- cascode drain -> pair tail ------------------------------------
        # The cascode's drain lands at rt_c = 1.01..1.39 (0.5 um device), so
        # the tail stub runs from there out to the pair's riser column.
        add(m1, x + CAS_DX + rt_c[0] - 0.14, -3.20,
            x + PAIR_DX - 0.08, 0.02, cd)
        if do_pair:
            draw_pair(x, tag)

        # --- vdd tie -> M3 plane (via1 - M2 patch - via2) -----------------
        top.shapes(via1).insert(box(x - 0.68, 1.02, x - 0.42, 1.28))
        add(m2, x - 0.76, 0.96, x - 0.34, 1.76, "vdd")
        top.shapes(via2).insert(box(x - 0.69, 1.40, x - 0.39, 1.70))

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

    # idump bus on M3, same span: the tail that is not on iout lands here.
    add(m3, -1.36, Y_IDUMP[0], x_b + CAS_DX + 1.30, Y_IDUMP[1], "idump")
    label(0.5, (Y_IDUMP[0] + Y_IDUMP[1]) / 2, "idump", m3_lbl)

    # vss rail: bulk ties only, so M1 is enough (no current).
    add(m1, -1.36, Y_VSS[0], x_b + CAS_DX + 1.30, Y_VSS[1], "vss")
    label(0.5, (Y_VSS[0] + Y_VSS[1]) / 2, "vss", m1_lbl)

    # ---------- replica cascode bias --------------------------------------
    # The bias branch is the cell's mirror + cascode, with the mirror diode-
    # connected (drain = gate = vbp) and the cascode diode-connected (drain =
    # gate = vcp).  16 uA injected at the vcp pad therefore sets the cells'
    # unit current.  No switch: in the dump-tail cell the tail never stops, so
    # the bias branch has nothing to reproduce (the source-switch cell needed
    # the switch here to reproduce its I*Ron degeneration).
    pcell_mir = pfet_pcell(MIR_L, W)
    pcell_cas = pfet_pcell(CAS_L, W)
    top.insert(pya.CellInstArray(pcell_mir.cell_index(),
                                 pya.Trans(int(x_b * 1000), 0)))
    top.insert(pya.CellInstArray(pcell_cas.cell_index(),
                                 pya.Trans(int((x_b + CAS_DX) * 1000), 0)))
    g = gate_span(MIR_L)
    rt = right_term(MIR_L)
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
    # Mref source + bulk tie -> vdd (the cell's mirror source is vdd too).
    add(m1, x_b - 0.76, -0.01, x_b + left_term()[1], 0.37, "vdd")
    # Mref bulk tie -> vdd plane.
    top.shapes(via1).insert(box(x_b - 0.68, 1.02, x_b - 0.42, 1.28))
    add(m2, x_b - 0.76, 0.96, x_b - 0.34, 1.76, "vdd")
    top.shapes(via2).insert(box(x_b - 0.69, 1.40, x_b - 0.39, 1.70))
    # Mcas bulk tie -> vdd, same via1/M2/via2 stack as a cell's mirror tie.
    top.shapes(via1).insert(box(x_b + CAS_DX - 0.68, 1.02,
                                x_b + CAS_DX - 0.42, 1.28))
    add(m2, x_b + CAS_DX - 0.76, 0.96, x_b + CAS_DX - 0.34, 1.76, "vdd")
    top.shapes(via2).insert(box(x_b + CAS_DX - 0.69, 1.40,
                                x_b + CAS_DX - 0.39, 1.70))

    # ---------- self-check ------------------------------------------------
    problems = []
    if do_check:
        want_dev = 4 * n_placed + 2
        want_cells = n_placed if not dbg else dbg
        want_pins = 2 * want_cells
        if len(cells) != want_cells:
            problems.append(f"{len(cells)} cells, want {want_cells}")
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
        print(f"devices    : {4 * len(cells)} + 2 replica = {want_dev} "
              f"({len(cells)} cells x [8/1 mirror, 8/0.5 cascode, "
              f"2 x 4/0.28 NMOS])")
        print(f"pins       : {2 * len(cells)} switch gates on a 3.75 um M2 "
              f"row at y={Y_PIN[0]}")
        print(f"rails      : vdd M3 plane {Y_PLANE[0]}..{Y_PLANE[1]}, "
              f"vbp M2 {Y_VBP}, vcp poly {Y_VCP}, iout M3 {Y_IOUT}, "
              f"idump M3 {Y_IDUMP}, vss M1 {Y_VSS}")
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
