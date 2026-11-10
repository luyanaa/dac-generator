#!/usr/bin/env python3
r"""Generate the unit-current-source array for the current-steering DAC (P3).

This is the reusable *device* generator for P3: 30 cascoded-PMOS cells (15
unary at 16 LSB, 15 binary at 1 LSB each), placed in one row with the bias and
supply rails that the array shares.  It does not draw transistor geometry:
every device is the PDK `pfet` PCell, and the script only adds the M1/poly
straps and the terminal pads.

The 1/2/4/8 binary weight is the *cell count* on each gate net, not the device
width: all 15 binary cells are identical 0.5/1 um devices, which is what the
digital macro drives (`swa_b8[7:0]` fans one register bit to eight cells).

What it does not contain (class C, hand layout, see README):

  * the switch matrix (30 cells -> 255 codes, DEM rotation wires),
  * the cascode bias generator (vbp/vcp are brought out as rails),
  * the I-V output resistor and the differential wrapper.

Cell (all dimensions um).  Two devices side by side, mirror on the left and
cascode on the right, sharing one M1 node in the middle:

      vdd rail (y=-1.25)
        |          |          |
      [mir]------[cas]        |
        |          |           |
       vbp        vcp       out pad (y=9.0..9.4)
      poly rail  poly rail

  * the mirror drain and the cascode source are joined by an M1 bridge *above*
    the devices (y=8.25..8.55): the cascode's own n-well tie sits between them
    and cannot be crossed at device level, so the bridge goes over the top.
  * both n-well ties are the vdd net and are stubbed down to the vdd rail.
  * mirror gates go to the lower poly rail (vbp, y=8.5..8.85), cascode gates to
    the upper one (vcp, y=9.45..9.85).  The lower rail is notched around each
    cascode gate extension: a poly rail that crossed one would short vbp to vcp.
  * every cell gets its own cascode-drain pad `cd_<tag>` at y=9.0..9.4; the
    steering switches pick the tail off that pad on M2.  The tag carries the
    segmentation (`u7`, `b8_3`), so LVS re-derives the weighting from the
    netlist.

Usage (KLayout's interpreter, not system python3):
    klayout -b -r gen_gds.py [-rd out=build/csteer.gds] [-rd check=true]
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pya

HERE = Path(__file__).resolve().parent

# --- pfet PCell geometry at ld=0.44 (probed from the PDK PCell, um) ---------
LD = 0.44
MIR_L = 1.0
CAS_L = 0.5
W = 8.0
CAS_DX = 2.98            # cascode origin; comp gap 0.34 (DF.3a wants 0.28)
PITCH = 5.5              # cell pitch; 0.72 clear of the next cell's tie

M1 = (34, 0)
M1_LABEL = (34, 10)
VIA1 = (35, 0)
M2 = (36, 0)
M2_LABEL = (36, 10)
POLY = (30, 0)
POLY_LABEL = (30, 10)
CONTACT = (33, 0)

# rails
Y_VDD = (-1.40, -1.10)
Y_RB_A = (8.45, 8.85)    # vbp
Y_RB_B = (9.45, 9.85)    # vcp
Y_PAD = (9.00, 9.40)
Y_STRAP = (9.05, 9.35)


def left_term():
    return (-0.01, 0.37)


def right_term(l):
    return (0.51 + l, 0.89 + l)


def gate_span(l):
    return (0.44, 0.44 + l)


def tie_span():
    return (-0.76, -0.32)


def load_cfg():
    try:
        import yaml
    except ImportError:  # pragma: no cover
        sys.exit("PyYAML is required: pip install pyyaml")
    with open(HERE / "csteer.yaml") as f:
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

    out_path = opt("out", str(HERE / "build" / "csteer.gds"))
    do_check = str(opt("check", "false")).lower() in ("1", "true", "yes")
    cfg = load_cfg()
    n_unary = 2 ** int(cfg["unary_bits"]) - 1
    unary_w = 2 ** int(cfg["binary_bits"]) - 1          # 15 unit cells in binary
    bins = [2 ** i for i in range(int(cfg["binary_bits"]))]  # 1,2,4,8

    root = Path(opt("pdkroot") or pdk_root())
    libdir = root / "libs.tech" / "klayout" / "tech" / "pymacros"
    if str(libdir) not in sys.path:
        sys.path.insert(0, str(libdir))
    from klayout_api_cells import gf180mcu_klayoutapi  # noqa: E402

    lib = gf180mcu_klayoutapi()
    ly = pya.Layout()
    ly.dbu = 0.001
    top = ly.create_cell("dac_csteer_ana")
    m1 = ly.layer(*M1)
    m1_lbl = ly.layer(*M1_LABEL)
    via1 = ly.layer(*VIA1)
    m2 = ly.layer(*M2)
    m2_lbl = ly.layer(*M2_LABEL)
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

    def add_reg(layer, region, net):
        # Shapes.insert does not take a Region: insert each merged polygon.
        for poly in region.each_merged():
            top.shapes(layer).insert(poly)
        regions.setdefault((layer, net), pya.Region()).insert(region)

    def label(x, y, name, layer=m1_lbl):
        top.shapes(layer).insert(
            pya.Text(name, pya.Trans(int(round(x * 1000)), int(round(y * 1000)))))

    # ---------- cells -----------------------------------------------------
    cells = [("U%d" % i, 1) for i in range(n_unary)]
    idx = n_unary
    bin_blocks = []
    for w in bins:
        start = idx
        for k in range(w):
            cells.append(("B%d_%d" % (w, k), w))
            idx += 1
        bin_blocks.append((w, start, idx - 1))

    dbg = int(opt("dbg_cells", 0))
    if dbg:
        cells = cells[:dbg]
        bin_blocks = [b for b in bin_blocks if b[2] < dbg]

    # Cell width carries the weight: one unary cell is the full 16 LSB device,
    # every binary cell is a single 1 LSB device and the 1/2/4/8 weight is the
    # *number* of cells on that gate net, not a wider device.  That keeps all
    # 15 binary cells identical (better matching) and is exactly what the
    # digital macro drives (see dac_csteer_dig.v).
    i_unit = float(cfg.get("i_unit_ua", 16.0))
    i_lsb = float(cfg.get("i_lsb_ua", 1.0))
    w_bin = W * i_lsb / i_unit

    pcell_cache: dict[tuple[float, float], object] = {}

    def pfet_pcell(l, w):
        key = (round(l, 6), round(w, 6))
        if key not in pcell_cache:
            pcell_cache[key] = ly.create_cell(
                "pfet", lib.name(),
                {"l": l, "w": w, "ld": LD, "nf": 1,
                 "bulk": "Bulk Tie", "volt": "3.3V"})
        return pcell_cache[key]

    gate_ext_cas = []
    out_pads = {}
    cd_pads = []

    for k, (name, wgt) in enumerate(cells):
        x = k * PITCH
        # The cascode drain leaves the cell through the pad at the top and is
        # now the switch tail (cd), not an output.  The net name carries the
        # cell's segmentation tag, so LVS can re-derive the 1-2-4-8 weighting
        # from the netlist alone.
        tag = name.lower()
        out_net = "cd_" + tag
        wc = W if tag.startswith("u") else w_bin
        top.insert(pya.CellInstArray(pfet_pcell(MIR_L, wc).cell_index(),
                                     pya.Trans(int(x * 1000), 0)))
        top.insert(pya.CellInstArray(pfet_pcell(CAS_L, wc).cell_index(),
                                     pya.Trans(int((x + CAS_DX) * 1000), 0)))
        # PCell terminal geometry, for the self-check only.
        lt = left_term()
        rt_m = right_term(MIR_L)
        rt_c = right_term(CAS_L)
        tie = tie_span()
        regions.setdefault((m1, "vdd"), pya.Region()).insert(
            box(x + lt[0], -0.01, x + lt[1], wc + 0.01))      # mirror source
        regions.setdefault((m1, "vdd"), pya.Region()).insert(
            box(x + tie[0], 0.0, x + tie[1], wc))             # mirror tie
        regions.setdefault((m1, "vdd"), pya.Region()).insert(
            box(x + CAS_DX + tie[0], 0.0, x + CAS_DX + tie[1], wc))
        node = "n_" + tag
        regions.setdefault((m1, node), pya.Region()).insert(
            box(x + rt_m[0], -0.01, x + rt_m[1], wc + 0.01))  # mirror drain
        regions.setdefault((m1, node), pya.Region()).insert(
            box(x + CAS_DX + lt[0], -0.01, x + CAS_DX + lt[1], wc + 0.01))
        g = gate_span(MIR_L)
        regions.setdefault((poly, "vbp"), pya.Region()).insert(
            box(x + g[0], -0.22, x + g[1], wc + 0.22))
        g = gate_span(CAS_L)
        regions.setdefault((poly, "vcp"), pya.Region()).insert(
            box(x + CAS_DX + g[0], -0.22, x + CAS_DX + g[1], wc + 0.22))

        # --- straps -------------------------------------------------------
        add(m1, x - 0.01, Y_VDD[0], x + 0.37, -0.01, "vdd")          # source
        add(m1, x - 0.76, Y_VDD[0], x - 0.32, 0.0, "vdd")            # tie
        add(m1, x + CAS_DX - 0.76, Y_VDD[0], x + CAS_DX - 0.32, 0.0, "vdd")

        add(m1, x + rt_m[0], wc + 0.01, x + rt_m[1], 8.55, node)     # riser
        add(m1, x + CAS_DX + lt[0], wc + 0.01,
            x + CAS_DX + lt[1], 8.55, node)                           # cas riser
        add(m1, x + rt_m[0], 8.25, x + CAS_DX + 0.33, 8.55, node)    # bridge
        add(m1, x + CAS_DX + rt_c[0], wc + 0.01,
            x + CAS_DX + rt_c[1], Y_PAD[0], out_net)                 # out riser
        add(m1, x + CAS_DX + rt_c[0], Y_PAD[0],
            x + CAS_DX + rt_c[1], Y_PAD[1], out_net)                 # out pad
        cd_pads.append((tag, x))
        label(x + CAS_DX + rt_c[0] + 0.1, (Y_PAD[0] + Y_PAD[1]) / 2,
              out_net)

        g = gate_span(MIR_L)
        add(poly, x + g[0], wc + 0.22, x + g[1], Y_RB_A[1], "vbp")
        # vbp pickup, mirror gate -> poly contact -> M1 pad -> via1 -> M2 rail.
        # Both bias rails cannot live on poly: the cascode gate extension has
        # to cross the mirror-gate rail band, so vbp is carried on metal2 and
        # only lands on the gate poly per cell.
        add(m1, x + 0.50, 8.44, x + 1.24, 8.80, "vbp")
        top.shapes(cont).insert(box(x + 0.58, 8.52, x + 0.80, 8.74))
        top.shapes(via1).insert(box(x + 0.90, 8.50, x + 1.16, 8.76))
        g = gate_span(CAS_L)
        add(poly, x + CAS_DX + g[0], wc + 0.22,
            x + CAS_DX + g[1], Y_RB_B[1], "vcp")
        gate_ext_cas.append((x + CAS_DX + g[0], x + CAS_DX + g[1]))

    x_last = (len(cells) - 1) * PITCH
    # The replica bias generator sits to the right of the vcp pad.
    x_b = x_last + 6.5
    pcell_mir = pfet_pcell(MIR_L, W)
    pcell_cas = pfet_pcell(CAS_L, W)

    # ---------- shared rails ---------------------------------------------
    add(m1, -0.76, Y_VDD[0], x_b + 1.0, Y_VDD[1], "vdd")
    label(0.0, (Y_VDD[0] + Y_VDD[1]) / 2, "vdd")

    # vbp rail on metal2.  It crosses the cascode gate extensions and the
    # output risers (both on M1) without a via, so it is one net end to end;
    # each cell reaches it through its own contact/via1 stack.
    add(m2, -1.36, 8.44, x_b + CAS_DX + 1.24, 8.80, "vbp")
    label(x_last / 2, 8.62, "vbp", m2_lbl)

    # vcp rail: straight bar, nothing else rises through its band.
    add_reg(poly, pya.Region(box(gate_ext_cas[0][0], Y_RB_B[0],
                                 gate_ext_cas[-1][1], Y_RB_B[1])), "vcp")
    # The vcp pad goes to the right of the last output pad, not above it:
    # overhead would break M1.2a against the pad (0.05 um).
    xc = x_last + CAS_DX + 1.39 + 0.30
    add(poly, gate_ext_cas[-1][1], Y_RB_B[0],
        x_b + CAS_DX + 1.40, Y_RB_B[1], "vcp")
    top.shapes(cont).insert(box(xc + 0.09, 9.53, xc + 0.31, 9.75))
    add(m1, xc, 9.45, xc + 0.6, 10.05, "vcp")
    label(xc + 0.3, 9.75, "vcp")

    # ---------- replica cascode bias -------------------------------------
    # One 16 uA reference injected at the vcp pad drives the stack
    #   Mref (8/1)   vdd -> vbp, gate = drain = vbp
    #   Mcas (8/0.5) vbp -> vcp, gate = drain = vcp
    # so vbp is the mirror gate and vcp one cascode Vgs below it: exactly the
    # bias the 30 cells use.  No extra pad, the vcp pad is the iref node.
    top.insert(pya.CellInstArray(pcell_mir.cell_index(),
                                 pya.Trans(int(x_b * 1000), 0)))
    top.insert(pya.CellInstArray(pcell_cas.cell_index(),
                                 pya.Trans(int((x_b + CAS_DX) * 1000), 0)))
    # Mref: source and bulk to vdd, gate+drain to vbp.  Use the same pickup
    # as a mirror cell (poly riser -> contact -> M1 pad -> via1), kept above
    # the source terminal so the M1 pad cannot crowd it.
    g = gate_span(MIR_L)                      # 0.44..1.44 for the 8/1 device
    rt = right_term(MIR_L)                    # 1.51..1.89
    add(m1, x_b - 0.01, Y_VDD[0], x_b + 0.37, -0.01, "vdd")
    add(m1, x_b - 0.76, Y_VDD[0], x_b - 0.32, 0.0, "vdd")
    add(poly, x_b + g[0], W + 0.22, x_b + g[1], Y_RB_A[1], "vbp")
    add(m1, x_b + 0.50, 8.44, x_b + rt[1], 8.80, "vbp")
    top.shapes(cont).insert(box(x_b + 0.58, 8.52, x_b + 0.80, 8.74))
    add(m1, x_b + rt[0], 8.01, x_b + rt[1], 8.44, "vbp")
    top.shapes(via1).insert(box(x_b + 0.90, 8.50, x_b + 1.16, 8.76))
    # Mcas: source to vbp, bulk to vdd, gate+drain to vcp
    g = gate_span(CAS_L)                      # 0.44..0.94 for the 8/0.5 device
    rt = right_term(CAS_L)                    # 0.79..1.17
    add(m1, x_b + CAS_DX - 0.01, 8.01, x_b + CAS_DX + 0.37, 8.80, "vbp")
    top.shapes(via1).insert(box(x_b + CAS_DX + 0.05, 8.46,
                                x_b + CAS_DX + 0.31, 8.72))
    add(m1, x_b + CAS_DX - 0.76, Y_VDD[0], x_b + CAS_DX - 0.32, 0.0, "vdd")
    add(poly, x_b + CAS_DX + g[0], W + 0.22,
        x_b + CAS_DX + g[1], Y_RB_B[1], "vcp")
    add(m1, x_b + CAS_DX + 0.50, Y_RB_B[0],
        x_b + CAS_DX + rt[1] + 0.35, 10.05, "vcp")
    top.shapes(cont).insert(box(x_b + CAS_DX + 0.58, 9.53,
                                x_b + CAS_DX + 0.80, 9.75))
    add(m1, x_b + CAS_DX + rt[0], 8.01,
        x_b + CAS_DX + rt[1], Y_RB_B[0], "vcp")
    label(x_b + CAS_DX + rt[1] + 0.1, 9.75, "vcp")

    # ---------- steering switches ----------------------------------------
    # One differential NMOS pair per cell, folded into two rows above the
    # current sources: row A steers the cell into `iout`, row B into `idump`.
    # Both rows take their tail from the same cascode drain (cd_<tag>), which is
    # picked off the output pad, carried up on M2 and fanned into the two
    # source strips.  Each switch gate is brought out on its own M2 pad; the
    # complementary drive is the digital macro's job.
    #
    # Rotated nfet (W along x), origin (X, Y), W=4 L=0.28:
    #   comp        X-4.0 .. X       , Y      .. Y+1.16
    #   src M1      X-4.0 .. X       , Y-0.01 .. Y+0.37
    #   drain M1    X-4.0 .. X       , Y+0.79 .. Y+1.17
    #   gate poly   X-4.22 .. X+0.22 , Y+0.44 .. Y+0.72
    #   bulk tie    X-4.0 .. X       , Y-0.76 .. Y-0.32
    # The gate paddle starts at x+0.62: it overlaps the last 0.10 of the gate
    # poly (so the two shapes really merge) and still keeps 0.12 to the active
    # edge (PL.5a wants 0.10).
    sw_l = float(cfg.get("sw_l", 0.28))
    sw_w = float(cfg.get("sw_w", 4.0))
    pcell_n = ly.create_cell("nfet", lib.name(),
                             {"l": sw_l, "w": sw_w, "ld": LD, "nf": 1,
                              "bulk": "Bulk Tie", "volt": "3.3V"})
    y_a, y_b = 12.0, 16.0
    y_iout = y_a + 1.17
    y_idump = y_b + 1.17
    y_ctrl_a, y_ctrl_b = 18.00, 18.75

    def nfet(X, Y, tag, row, gate):
        top.insert(pya.CellInstArray(
            pcell_n.cell_index(),
            pya.Trans(pya.Trans.R90, int(round(X * 1000)),
                      int(round(Y * 1000)))))
        regions.setdefault((m1, "cd_" + tag), pya.Region()).insert(
            box(X - 4.0, Y - 0.01, X, Y + 0.37))
        regions.setdefault((m1, row), pya.Region()).insert(
            box(X - 4.0, Y + 0.79, X, Y + 1.17))
        regions.setdefault((poly, gate), pya.Region()).insert(
            box(X - 4.22, Y + 0.44, X + 0.22, Y + 0.72))
        regions.setdefault((m1, "vss"), pya.Region()).insert(
            box(X - 4.0, Y - 0.76, X, Y - 0.32))

    # iout / idump buses: M1 bars that merge with every drain strip.  The 0.02
    # of overlap is enough because the extractor merges overlapping metal; the
    # LVS gate then proves every switch drain really landed on its bus.
    add(m1, -0.76, y_iout - 0.02, x_b + 1.0, y_iout + 0.30, "iout")
    label(0.5, y_iout + 0.14, "iout")
    add(m1, -0.76, y_idump - 0.02, x_b + 1.0, y_idump + 0.30, "idump")
    label(0.5, y_idump + 0.14, "idump")
    # Bulk-tie rails: one M1 bar per row, strapped together on M2 at the far
    # right (needs 0.06 of M2 around each via1).
    add(m1, -0.76, y_a - 0.78, x_b + 1.0, y_a - 0.30, "vss")
    add(m1, -0.76, y_b - 0.78, x_b + 1.0, y_b - 0.30, "vss")
    label(0.5, y_a - 0.54, "vss")
    xs = x_last + 2.33
    add(m2, xs, y_a - 0.76, xs + 0.40, y_b - 0.32, "vss")
    top.shapes(via1).insert(box(xs + 0.07, y_a - 0.70,
                                xs + 0.33, y_a - 0.44))
    top.shapes(via1).insert(box(xs + 0.07, y_b - 0.64,
                                xs + 0.33, y_b - 0.38))

    for tag, x in cd_pads:
        X = x + 0.5
        swa, swb = "swa_" + tag, "swb_" + tag
        nfet(X, y_a, tag, "iout", swa)
        nfet(X, y_b, tag, "idump", swb)

        # cd: output pad -> M1 riser clear of the vbp M2 rail -> via1 ->
        # M2 up and left -> vertical drop between the two gates -> via1 into
        # each source strip.  Every via1 gets 0.06 of metal on all sides.
        add(m1, x + 3.99, Y_PAD[0], x + 4.37, 10.12, "cd_" + tag)
        top.shapes(via1).insert(box(x + 4.05, 9.80, x + 4.31, 10.06))
        add(m2, x + 3.99, 9.74, x + 4.37, 10.30, "cd_" + tag)
        add(m2, x + 0.06, 10.00, x + 4.37, 10.30, "cd_" + tag)
        add(m2, x + 0.06, 10.00, x + 0.44, y_a + 0.05, "cd_" + tag)
        top.shapes(via1).insert(box(x + 0.12, y_a + 0.05,
                                    x + 0.38, y_a + 0.31))
        add(m2, x + 0.06, y_a + 0.05, x + 0.44, y_b + 0.37, "cd_" + tag)
        top.shapes(via1).insert(box(x + 0.12, y_b + 0.05,
                                    x + 0.38, y_b + 0.31))

        # Row A gate: poly paddle -> contact -> M1 landing -> via1 -> M2
        # riser to the control pad.  The riser is the pad's only layer, so
        # the digital macro connects on M2.
        add(poly, x + 0.62, y_a + 0.34, x + 1.26, y_a + 0.82, "swa_" + tag)
        top.shapes(cont).insert(box(x + 0.86, y_a + 0.46,
                                    x + 1.08, y_a + 0.68))
        add(m1, x + 0.80, y_a + 0.40, x + 1.20, y_a + 0.80, "swa_" + tag)
        top.shapes(via1).insert(box(x + 0.87, y_a + 0.48,
                                    x + 1.13, y_a + 0.74))
        add(m2, x + 0.80, y_a + 0.42, x + 1.20, y_ctrl_a + 0.35, "swa_" + tag)
        label(x + 1.00, y_ctrl_a + 0.17, "swa_" + tag, m2_lbl)

        # Row B gate: the same y band is blocked by the next cell's gate poly
        # (it starts at x+1.78), so the poly climbs over the idump bus and
        # takes its contact in the clear band above it.  That also lets the
        # two M2 risers keep 0.28 of spacing.
        add(poly, x + 0.62, y_b + 0.44, x + 1.00, 18.14, "swb_" + tag)
        add(poly, x + 0.62, 17.74, x + 1.90, 18.14, "swb_" + tag)
        top.shapes(cont).insert(box(x + 1.60, 17.82, x + 1.82, 18.04))
        add(m1, x + 1.53, 17.75, x + 1.93, 18.15, "swb_" + tag)
        top.shapes(via1).insert(box(x + 1.60, 17.81, x + 1.86, 18.07))
        add(m2, x + 1.53, 17.75, x + 1.93, y_ctrl_b + 0.35, "swb_" + tag)
        label(x + 1.73, y_ctrl_b + 0.17, "swb_" + tag, m2_lbl)

    # ---------- self-check ------------------------------------------------
    problems = []
    if do_check:
        # two PFETs per cell, plus the two-device replica bias generator,
        # plus the two steering NFETs per cell
        want_dev = 2 * len(cells) + 2
        want_sw = 2 * len(cells)
        want_cells = dbg if dbg else n_unary + unary_w
        if len(cells) != want_cells:
            problems.append(f"{len(cells)} unit cells, want {n_unary + unary_w}")
        # different nets must not touch on the same layer
        keys = sorted(regions, key=lambda k: (k[0], k[1]))
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
              f"({len(cells)} cascode pairs + replica bias) + "
              f"{want_sw} nfet switches")
        print(f"cell widths: unary {W:.3f} um, binary {w_bin:.3f} um "
              f"({len(cells) - n_unary} binary cells at 1 LSB each)")
        print(f"terminals  : iout/idump buses, vss, "
              f"{want_sw} switch gates, 3 bias rails, iref on vcp")
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
