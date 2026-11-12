#!/usr/bin/env python3
"""Generate the DEF pin template for the video current-steering digital half.

    ./gen_pin_template.py --pdk sky130 [--out pin_template_sky130.def]

Why a template instead of the automatic pin placer: the analog leaf is a row
of 255 cells on a 7.5 um pitch whose d_/db_ pads sit on an exact 3.75 um grid
at x = 2.25 + j*3.75, y = -18.0 (sky130) / -10.0 (gf180, ihp).  The digital
macro has to land its 510 outputs on that same grid, one pin per analog pad,
otherwise the wrapper needs 510 jogs and the abutment channel is not
straight.

`Odb.CustomIOPlacement` distributes pins evenly over the edge *on the routing
track grid*, which for sky130 met2 is 0.46 um: 3.75 is not a multiple of it,
so an automatic placement can never reproduce the analog pitch (it lands on
3.68 or 4.14 um and drifts by tens of microns across the row).  A DEF
template is applied verbatim by `Odb.ApplyDEFTemplate`, so the pins land on
the analog grid exactly.

The order along the row is the analog pad order: pad 2k is d_<k>, pad 2k+1 is
db_<k>, so the template lists dout[0], dout_n[0], dout[1], dout_n[1], ...
The control pins go on the north edge, out of the abutment channel.
"""
from __future__ import annotations

import argparse
import sys

N_CELLS = 255
PITCH = 7.5
PIN_A = 2.25          # d_<k> pad centre inside cell k
PIN_B = 6.00          # db_<k> pad centre
PAD_W = 0.60          # pad width (both directions)
DIE_W = N_CELLS * PITCH           # 1912.5
DIE_H = 80.0
DBU = 1000            # DEF database units per micron (sky130/gf180/ihp)
GRID = 5              # manufacturing grid, in DBU (0.005 um on all three)

LAYER = {
    "sky130": "met2",
    "gf180": "Metal2",
    "ihp130": "Metal2",
}


def u(v: float) -> int:
    return int(round(v * DBU / GRID)) * GRID


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pdk", default="sky130", choices=sorted(LAYER))
    ap.add_argument("--out", default=None)
    ap.add_argument("--die-h", type=float, default=DIE_H)
    ap.add_argument("--bits", type=int, default=8,
                    help="code width: 7 = sky130 thermometer, 8 = binary")
    ap.add_argument("--order", default=None,
                    help="also write an IO_PIN_ORDER_CFG file here")
    a = ap.parse_args(argv)
    layer = LAYER[a.pdk]
    out = a.out or f"pin_template_{a.pdk}.def"
    lines = [
        "VERSION 5.8 ;",
        "DIVIDERCHAR \"/\" ;",
        "BUSBITCHARS \"[]\" ;",
        f"DESIGN dac_video_dig ;",
        f"UNITS DISTANCE MICRONS {DBU} ;",
        f"DIEAREA ( 0 0 ) ( {u(DIE_W)} {u(a.die_h)} ) ;",
    ]
    pins = []
    # 510 outputs: analog pad order d0, db0, d1, db1, ...
    for k in range(N_CELLS):
        for suffix, net, x in (("", f"dout[{k}]", k * PITCH + PIN_A),
                               ("_n", f"dout_n[{k}]", k * PITCH + PIN_B)):
            # DEF pin geometry is *relative* to the placement point: a
            # rectangle that also carried the absolute x would be shifted
            # twice by odb (it applies PLACED to the box).  Keep the box
            # centred on the origin and put the absolute position in PLACED.
            pins.append(
                f"    - {net} + NET {net} + DIRECTION OUTPUT + USE SIGNAL\n"
                f"      + PORT\n"
                f"        + LAYER {layer} ( {u(-PAD_W / 2)} 0 ) "
                f"( {u(PAD_W / 2)} {u(PAD_W)} )\n"
                f"        + PLACED ( {u(x)} 0 ) N ;")
    # control pins on the north edge, evenly spaced
    ctrl = [("clk", "INPUT"), ("rst_n", "INPUT"), ("stb", "INPUT"),
            ("valid", "OUTPUT"), ("ready", "OUTPUT")]
    ctrl += [(f"code[{i}]", "INPUT") for i in range(a.bits)]
    step = DIE_W / (len(ctrl) + 1)
    for i, (net, direction) in enumerate(ctrl):
        x = step * (i + 1)
        y = a.die_h - PAD_W
        pins.append(
            f"    - {net} + NET {net} + DIRECTION {direction} + USE SIGNAL\n"
            f"      + PORT\n"
            f"        + LAYER {layer} ( {u(-PAD_W / 2)} {u(-PAD_W / 2)} ) "
            f"( {u(PAD_W / 2)} {u(PAD_W / 2)} )\n"
            f"        + PLACED ( {u(x)} {u(a.die_h)} ) N ;")
    lines.append(f"PINS {len(pins)} ;")
    lines += pins
    lines.append("END PINS")
    lines.append("END DESIGN")
    text = "\n".join(lines) + "\n"
    if a.order:
        # Fallback for flows that cannot ingest a DEF template: same pin
        # order, on the routing track grid.  @min_distance 3.45 um gives 8
        # tracks (3.68 um) per pin, the closest the sky130 met2 grid allows
        # to the analog 3.75 um pitch.
        # Entries are regexes and are re-sorted per side: @bit_major gives
        # bit-major order, so dout[k] then dout_n[k] interleave exactly like
        # the analog pads.  Brackets must be escaped for the regex match.
        order = ["#S", "@min_distance = 3.45", "@bit_major"]
        for k in range(N_CELLS):
            order.append(f"dout\\[{k}\\]")
            order.append(f"dout_n\\[{k}\\]")
        order.append("#N")
        for net, _ in ctrl:
            order.append(net.replace("[", "\\[").replace("]", "\\]"))
        with open(a.order, "w") as fh:
            fh.write("\n".join(order) + "\n")
        print(f"wrote {a.order}: {2 * N_CELLS} pins in analog pad order + "
              f"{len(ctrl)} control pins")
    if out == "-":
        sys.stdout.write(text)
    else:
        with open(out, "w") as fh:
            fh.write(text)
        print(f"wrote {out}: {2 * N_CELLS} array pins on {layer} at "
              f"x=2.25+{PITCH/2:g}*j, {len(ctrl)} control pins on the north edge")
    return 0


if __name__ == "__main__":
    sys.exit(main())
