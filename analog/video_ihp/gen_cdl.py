#!/usr/bin/env python3
"""Emit the schematic netlist that matches the generated IHP row.

    python3 gen_cdl.py        # -> build/video_ihp.cdl

The IHP row (gen_gds.py) is 255 dump-tail cells plus the diode-connected
replica.  Each cell is a pmos mirror (8/1), a pmos cascode (8/0.5) and two
nmos switches (4/0.28); the replica is the mirror+cascode pair with its drain
and gate tied to vbp/vcp.  The CDL uses the same `b{k}_{i}` pad tags as the
layout, so the PDK `run_lvs.py` comparison can match every gate net.
"""
from __future__ import annotations

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
N = int(os.environ.get("N_CELLS", "255"))


def tag(j: int) -> str:
    k = 0
    while j >= 2 ** (k + 1) - 1:
        k += 1
    return f"b{k}_{j - (2 ** k - 1)}"


def main() -> int:
    ports = ["vdd", "vss", "vbp", "vcp", "iout", "idump"]
    ports += [f"d_{tag(j)}" for j in range(N)]
    ports += [f"db_{tag(j)}" for j in range(N)]
    lines = [".subckt dac_video_ihp " + " ".join(ports)]
    for j in range(N):
        t = tag(j)
        lines += [
            f"M{j}m md_{j} vbp vdd vdd sg13_lv_pmos w=8u l=1u",
            f"M{j}c cd_{j} vcp md_{j} vdd sg13_lv_pmos w=8u l=0.5u",
            f"M{j}a iout d_{t} cd_{j} vss sg13_lv_nmos w=4u l=0.28u",
            f"M{j}b idump db_{t} cd_{j} vss sg13_lv_nmos w=4u l=0.28u",
        ]
    lines += [
        "Mrm vbp vbp vdd vdd sg13_lv_pmos w=8u l=1u",
        "Mrc vcp vcp vbp vdd sg13_lv_pmos w=8u l=0.5u",
        ".ends",
    ]
    out = os.path.join(HERE, "build", "video_ihp.cdl")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w") as fh:
        fh.write("\n".join(lines) + "\n")
    print(f"wrote {out}: {N} cells, {len(ports)} ports, "
          f"{4 * N + 2} devices")
    return 0


if __name__ == "__main__":
    sys.exit(main())
