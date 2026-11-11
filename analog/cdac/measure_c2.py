#!/usr/bin/env python3
"""Measure the unit MOSCAP 2-D capacitance Cgg(Vg,Vb), Cgb(Vg,Vb) (sky130).

    ./measure_c2.py [--step 0.1] [--write]

The audit's point: a 1-D C(Vtop-Vbottom) table cannot describe a 3-terminal
MOSCAP with a fixed well, because the top charge depends on both plates.
This measures the full small-signal matrix at every (Vg,Vb):

    Cgg = dQg/dVg at fixed Vb   (gate ac, bottom ac ground)
    Cgb = dQg/dVb at fixed Vg   (bottom ac, gate ac ground)

Both are stored with the sign of dQg (ngspice reports i(vg) = -j*w*C*V, so
the bottom-driven imag current is negated).  Reciprocity dCgg/dVb =
dCgb/dVg then holds on the grid to ~0.02 fF/V.

and stores both in cdac.yaml.  `CapModel` then builds the state function

    Q(vg,vb) = integral_0^vg Cgg(u,vb) du + integral_0^vb Cgb(vg,w) dw

and the charge-conservation solve uses Q and Cgg.
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
import tempfile
from pathlib import Path

import gen_cdac as g

ROOT = g.ROOT
ROW = re.compile(r"^\s*\d+\s+([-\d.eE+]+)\s+([-\d.eE+]+),\s*([-\d.eE+]+)\s*$")
FREQ = 1.0e6


def netlist(cfg: dict, deck: Path, vg: float, vb: float,
            drive: str) -> str:
    leaf = g.CAP_LEAF.format(wn=cfg["cu_wn_um"], wp=cfg["cu_wp_um"],
                             l=cfg["cu_l_um"])
    if drive == "g":
        vga, vba = "ac 1", ""
    else:
        vga, vba = "", "ac 1"
    return f"""* CDAC unit cap C2(Vg,Vb), drive {drive}
{leaf}.include {deck}
Vg vsh 0 dc {vg:.6f} {vga}
Vb fl 0 dc {vb:.6f} {vba}
Vnw vnw 0 {2.0 * float(cfg['vcm']):.6f}
Vpw vpw 0 0
Xc vsh fl vnw vpw CDAC_CAP_UNIT
.ac lin 1 {FREQ:g} {FREQ:g}
.print ac i(vg)
.end
"""


def cap(log: str, signed: bool) -> float:
    for line in log.splitlines():
        m = ROW.match(line)
        if m:
            v = float(m.group(3)) / (2 * 3.141592653589793 * FREQ) * 1e15
            # i(vg) = -j*w*C*V in ngspice: the driven-gate current is
            # negative-imaginary, and the bottom-driven one has the opposite
            # sign to dQg/dVb.
            return -v if signed else abs(v)
    raise SystemExit("no ac current row")


def measure(cfg: dict, deck: Path, vg: float, vb: float, drive: str,
            tmp: Path) -> float:
    path = tmp / "c.sp"
    path.write_text(netlist(cfg, deck, vg, vb, drive))
    r = subprocess.run(["ngspice", "-b", str(path)], cwd=tmp,
                       capture_output=True, text=True, timeout=600)
    if r.returncode:
        raise SystemExit(f"ngspice failed at {vg},{vb},{drive}")
    return cap(r.stdout + r.stderr, signed=(drive == "b"))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--step", type=float, default=0.1)
    ap.add_argument("--write", action="store_true")
    a = ap.parse_args(argv)
    cfg = g.load_cfg()
    deck = g.ensure_deck(cfg)
    vmax = float(cfg["vrefh"])
    n = int(round(vmax / a.step))
    grid = [round(i * a.step, 6) for i in range(n + 1)]
    cgg, cgb = [], []
    with tempfile.TemporaryDirectory(prefix="cdac_c2_") as tmp:
        tmp = Path(tmp)
        for vb in grid:
            rgg, rgb = [], []
            for vg in grid:
                rgg.append(round(measure(cfg, deck, vg, vb, "g", tmp), 6))
                rgb.append(round(measure(cfg, deck, vg, vb, "b", tmp), 6))
            cgg.append(rgg)
            cgb.append(rgb)
            print(f"vb {vb:.1f}: cgg {rgg[0]:.3f}..{rgg[-1]:.3f}  "
                  f"cgb {rgb[0]:.3f}..{rgb[-1]:.3f}")
    def block(name: str, mat) -> str:
        out = [f"{name}:",
               "  vg: [" + ", ".join(f"{v:g}" for v in grid) + "]",
               "  vb: [" + ", ".join(f"{v:g}" for v in grid) + "]",
               "  c_ff:"]
        for row in mat:
            out.append("    - [" + ", ".join(f"{q:g}" for q in row) + "]")
        return "\n".join(out) + "\n"
    text = block("cgg_ff_vs_vg_vb", cgg) + block("cgb_ff_vs_vg_vb", cgb)
    if a.write:
        path = ROOT / "cdac.yaml"
        s = path.read_text()
        for name in ("cgg_ff_vs_vg_vb:", "cgb_ff_vs_vg_vb:"):
            i = s.find(name)
            if i >= 0:
                j = s.find("\n\n", i)
                s = s[:i] + s[j + 1:]
        anchor = s.find("q_ffv_vs_vg_vb:")
        if anchor < 0:
            anchor = s.find("c_ff_vs_vdiff:")
        j = s.find("\n\n", anchor)
        s = s[:j + 1] + "\n" + text + s[j + 1:]
        path.write_text(s)
        print(f"wrote cgg/cgb ({len(grid)}x{len(grid)}) to {path}")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
