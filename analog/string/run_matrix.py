#!/usr/bin/env python3
"""Corner x temperature matrix for the resistor-string leaf.

    ./run_matrix.py [--pdk gf180] [--bits 8]

The DC bench is 256 bias points over ~1000 nodes, so a point costs ~0.25 s.
Default matrix: all five corners at 25 C plus tt at the temperature extremes
(7 points) unless --full is given, which runs all 15.
Results land in build/matrix.csv.
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


def run(cmd):
    return subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True)


def parse_brief(text: str) -> dict[str, tuple[float, float]]:
    out = {}
    for line in text.splitlines():
        parts = line.split()
        if len(parts) == 3 and parts[0].startswith(("DNL_", "INL_")):
            out[parts[0]] = (float(parts[1]), float(parts[2]))
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pdk", default="gf180")
    ap.add_argument("--bits", type=int, default=8)
    ap.add_argument("--full", action="store_true")
    a = ap.parse_args()

    points = ([(c, t) for c in CORNERS for t in TEMPS] if a.full
              else [(c, 25.0) for c in CORNERS] + [("tt", -40.0), ("tt", 125.0)])

    build = ROOT / "build"
    build.mkdir(exist_ok=True)
    rows = []
    for c, t in points:
        dat = build / f"dc_{c}_{int(t)}.dat"
        sp = build / f"dc_{c}_{int(t)}.spice"
        r = run([sys.executable, "gen_string.py", "--pdk", a.pdk, "--bench", "dc",
                 "--corner", c, "--temp", str(t), "--out", str(sp),
                 "--dat", str(dat)])
        if r.returncode:
            print(r.stderr)
            return 1
        r = run(["ngspice", "-b", str(sp)])
        if not dat.exists():
            print(f"ngspice failed for {c}/{t}\n{r.stdout[-500:]}{r.stderr[-800:]}")
            return 1
        r = run([sys.executable, "measure.py", "dc", str(dat), "--bits", str(a.bits),
                 "--brief"])
        v = parse_brief(r.stdout)
        dnl = v.get("DNL_tap", (float("nan"),) * 2)
        inl = v.get("INL_tap", (float("nan"),) * 2)
        rows.append((c, int(t), f"{dnl[0]:+.4f}..{dnl[1]:+.4f}",
                     f"{inl[0]:+.4f}..{inl[1]:+.4f}",
                     max(abs(dnl[0]), abs(dnl[1])), max(abs(inl[0]), abs(inl[1]))))
        print(f"{c:>3} {int(t):>4}C  DNL {rows[-1][2]:>17}  INL {rows[-1][3]:>17}")

    out = build / "matrix.csv"
    with open(out, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["corner", "temp_c", "dnl_lsb", "inl_lsb",
                    "dnl_absmax", "inl_absmax"])
        w.writerows(rows)
    print(f"\nworst |DNL| {max(r[4] for r in rows):.4f}  "
          f"worst |INL| {max(r[5] for r in rows):.4f} LSB")
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
