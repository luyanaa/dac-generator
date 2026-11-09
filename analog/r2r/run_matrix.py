#!/usr/bin/env python3
"""Run the R-2R pre-layout corner matrix and print a summary table.

    ./run_matrix.py [--pdk gf180] [--bits 8]

For every (corner, temperature) it regenerates the netlist, runs ngspice and
recomputes INL/DNL with measure.py.  Results land in build/matrix.csv.
"""
from __future__ import annotations

import argparse
import csv
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
CORNERS = ["tt", "ff", "ss", "fs", "sf"]
TEMPS = [-40.0, 25.0, 125.0]


def run(cmd: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pdk", default="gf180")
    ap.add_argument("--bits", type=int, default=8)
    a = ap.parse_args()

    build = ROOT / "build"
    build.mkdir(exist_ok=True)
    rows = []
    for c in CORNERS:
        for t in TEMPS:
            dat = build / f"dc_{c}_{int(t)}.dat"
            sp = build / f"dc_{c}_{int(t)}.spice"
            r = run([
                sys.executable, "gen_r2r.py", "--pdk", a.pdk, "--bench", "dc",
                "--corner", c, "--temp", str(t), "--out", str(sp),
                "--dat", str(dat),
            ])
            if r.returncode:
                print(r.stderr)
                return 1
            r = run(["ngspice", "-b", str(sp)])
            if not dat.exists():
                print(f"ngspice failed for {c}/{t}\n{r.stderr[-800:]}")
                return 1
            r = run([sys.executable, "measure.py", "dc", str(dat), "--bits", str(a.bits)])
            vals = {}
            for line in r.stdout.splitlines():
                if ":" in line:
                    k, v = line.split(":", 1)
                    vals[k.strip()] = v.strip()
            dnl = vals.get("DNL", "?")
            inl = vals.get("INL", "?")
            vfs = vals.get("V(full)", "?")
            rows.append((c, int(t), dnl, inl, vfs))
            print(f"{c:>3} {int(t):>4}C  DNL {dnl:>22}  INL {inl:>22}  Vfs {vfs}")

    out = build / "matrix.csv"
    with open(out, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["corner", "temp_c", "dnl_lsb", "inl_lsb", "vfs_v"])
        w.writerows(rows)
    print(f"\nwrote {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
