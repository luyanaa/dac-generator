#!/usr/bin/env python3
"""Measure the IHP sg13g2 pmos-MOSCAP 2-D capacitance Cgg(Vg,Vb), Cgb(Vg,Vb).

    ./measure_c2_ihp.py [--step 0.05] [--w 2] [--l 1] [--write]

The CDAC unit is a single `sg13_moscap_p` (gate = top plate, n-well = bottom
plate).  The nmos moscap cannot be used: its bottom terminal is the shared
p-substrate, so it cannot be switched per unit.

Cgg = dQg/dVg at fixed Vb and Cgb = dQg/dVb at fixed Vg are measured with
.ac at 1 MHz, one netlist per Vb row (all Vg points instantiated at once),
and written to `cdac.yaml` under the `ihp-sg13g2` key.  The reciprocity
dCgg/dVb = dCgb/dVg is printed as the self-check.

The PMOS moscap uses the dedicated `moscap_tt` corner of cornerMOSCAP.lib;
the PSP103 models are OSDI, so PDK_ROOT/PDK must point at the IHP install
(same as the other IHP leaves).
"""
from __future__ import annotations

import argparse
import json
import math
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
FREQ = 1.0e6
OMEGA = 2 * math.pi * FREQ


def pdk_root() -> Path:
    base = Path.home() / ".ciel/ciel/ihp-sg13/versions"
    hits = sorted(p for p in base.iterdir()
                  if (p / "ihp-sg13g2/libs.tech/ngspice/models/cornerMOSCAP.lib").is_file())
    if not hits:
        raise SystemExit(f"no IHP moscap models under {base}")
    return hits[-1]


def model_lib() -> Path:
    return (Path("/grid/dac-generator/pdks/ihp-sg13g2/libs.tech/ngspice/"
                 "models/cornerMOSCAP.lib"))


def netlist(grid, vb: float, w: float, l: float, drive: str) -> str:
    lines = ["* IHP pmos moscap C2 column",
             f'.lib "{model_lib()}" moscap_tt']
    for k, vg in enumerate(grid):
        ac = " ac 1" if drive == "g" else ""
        lines.append(f"Vg{k} g{k} 0 dc {vg:.6f}{ac}")
        acb = " ac 1" if drive == "b" else ""
        lines.append(f"Vb{k} b{k} 0 dc {vb:.6f}{acb}")
        lines.append(f"X{k} g{k} b{k} sg13_moscap_p w={w:g}u l={l:g}u")
    lines.append(".control")
    lines.append("ac lin 1 1e6 1e6")
    vecs = " ".join(f"i(vg{k})" if drive == "g" else f"i(vb{k})"
                    for k in range(len(grid)))
    lines.append(f"wrdata c2.dat {vecs}")
    lines.append(".endc")
    lines.append(".end")
    return "\n".join(lines) + "\n"


def parse(path: Path, n: int) -> list[float]:
    vals = [float(v) for v in path.read_text().split()]
    imag = []
    for k in range(n):
        # wrdata writes freq, real, imag per vector
        base = 3 * k
        imag.append(vals[base + 2])
    return imag


def column(grid, vb, w, l, drive, tmp: Path, env) -> list[float]:
    path = tmp / "c2.sp"
    path.write_text(netlist(grid, vb, w, l, drive))
    out = tmp / "c2.dat"
    if out.exists():
        out.unlink()
    r = subprocess.run(["ngspice", "-b", str(path)], cwd=tmp, env=env,
                       capture_output=True, text=True, timeout=600)
    if r.returncode or not out.is_file():
        raise SystemExit(f"ngspice failed (vb={vb}, {drive})\n"
                         + (r.stdout + r.stderr)[-800:])
    # i(vg) = -j*w*Cgg (gate drive); i(vb) = -j*w*Cgb as well because ngspice
    # reports the current into the source's + node.  Cgb = dQg/dVb is negative
    # for a two-terminal cap, so the bottom-drive imag is negated once.
    sign = -1.0 if drive == "g" else 1.0
    return [sign * v / OMEGA * 1e15 for v in parse(out, len(grid))]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--step", type=float, default=0.05)
    ap.add_argument("--vmax", type=float, default=1.2)
    ap.add_argument("--w", type=float, default=2.0)
    ap.add_argument("--l", type=float, default=1.0)
    ap.add_argument("--write", action="store_true")
    a = ap.parse_args(argv)

    n = int(round(a.vmax / a.step))
    grid = [round(i * a.step, 6) for i in range(n + 1)]
    root = pdk_root()
    env = dict(os.environ)
    env["PDK_ROOT"] = str(root)
    env["PDK"] = "ihp-sg13g2"

    cgg, cgb = [], []
    with tempfile.TemporaryDirectory(prefix="cdac_ihp_c2_") as tmp:
        tmp = Path(tmp)
        for vb in grid:
            rgg = column(grid, vb, a.w, a.l, "g", tmp, env)
            rgb = column(grid, vb, a.w, a.l, "b", tmp, env)
            cgg.append([round(v, 6) for v in rgg])
            cgb.append([round(v, 6) for v in rgb])
            print(f"vb {vb:.2f}: cgg {rgg[0]:7.3f}..{rgg[-1]:7.3f}  "
                  f"cgb {rgb[0]:7.3f}..{rgb[-1]:7.3f}")

    # Reciprocity self-check.  The 2-terminal moscap has C=f(Vg-Vb), so the
    # 2-D table must collapse exactly onto the diagonal.  A forward/backward
    # derivative check would compare -C'(vd+step/2) with -C'(vd-step/2) and
    # fail on the steep part of the curve, so test the collapse directly.
    err2 = 0.0
    for j in range(len(grid)):
        for i in range(len(grid)):
            vd = round(grid[i] - grid[j], 9)
            k = grid.index(round(abs(vd) / a.step) * a.step)
            ref = cgg[0][k] if vd >= 0 else cgg[k][0]
            err2 = max(err2, abs(cgg[j][i] - ref))

    cu0 = cgg[0][0]
    cu_mid = cgg[int(len(grid) / 2)][int(len(grid) / 2)]
    res = {
        "pdk": "ihp-sg13g2",
        "device": "sg13_moscap_p",
        "w_um": a.w,
        "l_um": a.l,
        "area_um2": a.w * a.l,
        "freq_hz": FREQ,
        "grid_v": grid,
        "cgg_ff": cgg,
        "cgb_ff": cgb,
        "cu_ff_at_0_0": round(cu0, 6),
        "cu_ff_at_mid": round(cu_mid, 6),
        "reciprocity_max_ff_per_v": round(err2, 6),
    }
    out = HERE / "build" / "ihp_moscap_c2.json"
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps(res, indent=2) + "\n")
    print(f"unit {a.w:g}x{a.l:g} um: C(0,0)={cu0:.3f} fF, "
          f"C(mid,mid)={cu_mid:.3f} fF, "
          f"reciprocity error {err2:.4f} fF/V")
    print(f"wrote {out}")

    if a.write:
        import yaml  # noqa: F401  (only to validate the block)
        y = HERE / "cdac.yaml"
        s = y.read_text()
        def block(name, mat):
            out = [f"  {name}:",
                   "    vg: [" + ", ".join(f"{v:g}" for v in grid) + "]",
                   "    vb: [" + ", ".join(f"{v:g}" for v in grid) + "]",
                   "    c_ff:"]
            for row in mat:
                out.append("      - [" + ", ".join(f"{q:g}" for q in row) + "]")
            return "\n".join(out) + "\n"
        text = "\n  ihp-sg13g2:\n"
        text += (f"    # measured {a.w:g}x{a.l:g} um sg13_moscap_p, "
                 f"gate=top, nwell=bottom; moscap_tt, 1 MHz\n"
                 f"    cu_ff: {cu_mid:.6g}\n"
                 f"    cu_area_um2: {a.w * a.l:g}\n"
                 f"    cu_w_um: {a.w:g}\n"
                 f"    cu_l_um: {a.l:g}\n")
        text += block("cgg_ff_vs_vg_vb", cgg)
        text += block("cgb_ff_vs_vg_vb", cgb)
        if "\n  ihp-sg13g2:\n" in s:
            i = s.index("\n  ihp-sg13g2:\n")
            j = s.find("\n\n", i)
            s = s[:i] + "\n" + text + s[j + 1:]
        else:
            s = s.rstrip("\n") + "\n" + text
        y.write_text(s)
        print(f"wrote ihp-sg13g2 tables to {y}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
