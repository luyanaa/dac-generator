"""Emit the schematic netlist that matches the generated ics55 row.

    python3 gen_cdl.py        # -> build/video_ics55.cdl

The CDL is the layout's netlist: 255 cells (mirror + cascode + pair) on the
same tags as the pads, plus the diode-connected replica.  It is what the
ics55 LVS deck compares against `build/video_ics55.gds`.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
N = int(os.environ.get("N_CELLS", "255"))


def tag(j):
    k = 0
    while j >= 2 ** (k + 1) - 1:
        k += 1
    return f"b{k}_{j - (2 ** k - 1)}"


def main():
    ports = ["vdd", "vbp", "vcp", "iout", "idump"]
    ports += [f"d_{tag(j)}" for j in range(N)]
    ports += [f"db_{tag(j)}" for j in range(N)]
    lines = [".subckt dac_video_ana " + " ".join(ports)]
    for j in range(N):
        t = tag(j)
        lines += [
            f"M{j}m md_{j} vbp vdd vdd pm1p2_svt_lp w=8u l=1u",
            f"M{j}c cd_{j} vcp md_{j} vdd pm1p2_svt_lp w=8u l=0.5u",
            f"M{j}a iout d_{t} cd_{j} VSS nm1p2_svt_lp w=4u l=0.28u",
            f"M{j}b idump db_{t} cd_{j} VSS nm1p2_svt_lp w=4u l=0.28u",
        ]
    lines += [
        "Mrm vbp vbp vdd vdd pm1p2_svt_lp w=8u l=1u",
        "Mrc vcp vcp vbp vdd pm1p2_svt_lp w=8u l=0.5u",
        ".ends",
    ]
    out = os.path.join(HERE, "build", "video_ics55.cdl")
    with open(out, "w") as fh:
        fh.write("\n".join(lines) + "\n")
    print(f"wrote {out}: {N} cells, {len(ports)} ports, "
          f"{4*N + 2} devices")


if __name__ == "__main__":
    sys.exit(main())
