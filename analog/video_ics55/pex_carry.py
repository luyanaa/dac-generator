#!/usr/bin/env python3
"""Run the P5 carry on the Magic-extracted ics55 row.

    python3 pex_carry.py [--from 127] [--to 128] [--kind carry]

The PDK's magic tech extracts area/perimeter capacitance with
`ext2spice cthresh 0` (the KLayout RCX ruleset is what is missing).  This
script takes `build/row_pex.spice`, ties the extracted well nodes to vdd,
injects the 16 uA reference on vcp, and drives the 510 gate pads with the
same 20 ps edge / 25 ps skew as `analog/video/pdk_cell.py`.
"""
from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
BUILD = HERE / "build"
MODELS = ("/grid/icsprout55-pdk/libs.tech/spice/foundry/ngspice/"
          "ICsprout_55LLULP1225_V1p1_hsp.lib")
N = 255
I_UNIT_UA = 16.0
RL = 37.5
CL_PF = 2.0
VCP_CAP_PF = 220.0
PERIOD_NS = 40.0
T0_NS = 1.0
EDGE_PS = 20.0
SKEW_PS = 25.0
SETTLE_LSB = 0.5


def tag(j: int) -> str:
    k = 0
    while j >= 2 ** (k + 1) - 1:
        k += 1
    return f"b{k}_{j - (2 ** k - 1)}"


def prep_pex() -> Path:
    src = BUILD / "row_pex.spice"
    if not src.is_file():
        sys.exit(f"missing {src}; run the magic extraction first")
    text = src.read_text()
    # tie the extracted well nodes to vdd (the pcell has no well tap)
    wells = set(re.findall(r"\b(w_\S+?)#", text))
    for w in sorted(wells, key=len, reverse=True):
        text = text.replace(w + "#", "vdd")
    # the reference current is injected on vcp (the iref pad has no label)
    text = text.replace(".ends", "Iref vcp 0 16u\n.ends", 1)
    out = BUILD / "row_pex_tb.spice"
    out.write_text(text)
    print(f"  wells tied: {len(wells)}")
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--from", dest="frm", type=int, default=127)
    ap.add_argument("--to", type=int, default=128)
    ap.add_argument("--kind", default="carry")
    a = ap.parse_args()
    pex = prep_pex()
    dat = BUILD / f"pex_{a.kind}_{a.frm}_{a.to}.dat"
    lines = [
        f"* ics55 PEX {a.kind} {a.frm}->{a.to}",
        f'.lib "{MODELS}" tt_mos',
        "Vdd vdd 0 1.2",
        "Vss vss 0 0",
        "Vsub SUB 0 0",
        "Vdump idump 0 0",
        f"Rl iout 0 {RL}",
        f"Cl iout 0 {CL_PF}p",
        f"Cvcp vcp 0 {VCP_CAP_PF}p",
        f'.include "{pex}"',
        "Xtop " + " ".join(
            [f"d_{tag(j)}" for j in range(N)] +
            [f"db_{tag(j)}" for j in range(N)] +
            ["vdd", "vss", "iout", "idump", "vbp", "vcp"]) + " dac_video_ana",
    ]
    # port order must match the extracted .subckt; read it instead
    sub = re.search(r"^\.subckt dac_video_ana\s+(.*?)(?=^\S|\Z)",
                    pex.read_text(), re.S | re.M)
    ports = sub.group(1).replace("+", " ").split()
    lines[-1] = "Xtop " + " ".join(ports) + " dac_video_ana"
    for j in range(N):
        t = tag(j)
        k = 0
        while j >= 2 ** (k + 1) - 1:
            k += 1
        on0 = bool((a.frm >> k) & 1)
        on1 = bool((a.to >> k) & 1)
        t0 = T0_NS * 1e-9 + k * SKEW_PS * 1e-12
        e = t0 + EDGE_PS * 1e-12
        for net, x0, x1 in ((f"d_{t}", 1.2 if on0 else 0.0,
                             1.2 if on1 else 0.0),
                            (f"db_{t}", 0.0 if on0 else 1.2,
                             0.0 if on1 else 1.2)):
            if x0 == x1:
                lines.append(f"V{net} {net} 0 {x0:g}")
            else:
                lines.append(f"V{net} {net} 0 PWL(0 {x0:g} {t0:.6g} {x0:g} "
                             f"{e:.6g} {x1:g})")
    lines += [".control", "set wr_singlescale", "set wr_vecnames",
              "tran 5e-12 50e-9", f"wrdata {dat} v(iout) v(vbp) v(vcp)",
              ".endc", ".end"]
    nl = BUILD / f"pex_{a.kind}_{a.frm}_{a.to}.spice"
    nl.write_text("\n".join(lines) + "\n")
    r = subprocess.run(["ngspice", "-b", str(nl)], capture_output=True,
                       text=True, timeout=7200)
    (BUILD / f"pex_{a.kind}_{a.frm}_{a.to}.log").write_text(
        r.stdout + r.stderr)
    if r.returncode:
        sys.exit(f"ngspice failed ({nl})")
    names, rows = {}, []
    for ln in dat.read_text().splitlines():
        f = ln.split()
        if len(f) < 2:
            continue
        try:
            rows.append([float(v) for v in f])
        except ValueError:
            for i, v in enumerate(f):
                names.setdefault(v, i)
    t = [x[names["time"]] for x in rows]
    v = [x[names["v(iout)"]] for x in rows]
    lsb = I_UNIT_UA * 1e-6 * RL
    at = (T0_NS + PERIOD_NS) * 1e-9
    i = min(range(len(t)), key=lambda k: abs(t[k] - at))
    settled = v[i] / lsb
    print(f"{a.frm} -> {a.to}: {settled:.3f} LSB "
          f"(err {settled - a.to:+.3f}) at {t[i]*1e9:.1f} ns, "
          f"{len(rows)} rows")
    return 0


if __name__ == "__main__":
    sys.exit(main())
