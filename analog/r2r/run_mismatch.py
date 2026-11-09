#!/usr/bin/env python3
"""Per-unit resistor mismatch sweep for the R-2R leaf.

gf180's ppolyf_u model has mis_r = 0, so ngspice Monte Carlo cannot move a
resistor ratio.  This applies an explicit per-instance length error instead
and reports the worst INL/DNL over N seeds.

    ./run_mismatch.py --sigma 0.002 --seeds 20
"""
from __future__ import annotations

import argparse
import statistics
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def run(cmd):
    return subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pdk", default="gf180")
    ap.add_argument("--bits", type=int, default=8)
    ap.add_argument("--sigma", type=float, default=0.002)
    ap.add_argument("--seeds", type=int, default=20)
    ap.add_argument("--corner", default="tt")
    ap.add_argument("--temp", type=float, default=25.0)
    a = ap.parse_args()

    build = ROOT / "build"
    build.mkdir(exist_ok=True)
    inls, dnls = [], []
    for seed in range(1, a.seeds + 1):
        sp = build / f"mm_{seed}.spice"
        dat = build / f"mm_{seed}.dat"
        r = run([sys.executable, "gen_r2r.py", "--pdk", a.pdk, "--bench", "dc",
                 "--corner", a.corner, "--temp", str(a.temp),
                 "--mismatch", str(a.sigma), "--seed", str(seed),
                 "--out", str(sp), "--dat", str(dat)])
        if r.returncode:
            print(r.stderr)
            return 1
        r = run(["ngspice", "-b", str(sp)])
        if not dat.exists():
            print(f"ngspice failed seed {seed}")
            return 1
        r = run([sys.executable, "measure.py", "dc", str(dat), "--bits", str(a.bits)])
        for line in r.stdout.splitlines():
            if line.startswith("DNL"):
                lo, hi = line.split(":", 1)[1].replace("LSB", "").split("..")
                dnls.append(max(abs(float(lo)), abs(float(hi))))
            elif line.startswith("INL"):
                lo, hi = line.split(":", 1)[1].replace("LSB", "").split("..")
                inls.append(max(abs(float(lo)), abs(float(hi))))
        print(f"seed {seed:3d}  |DNL|max {dnls[-1]:.3f}  |INL|max {inls[-1]:.3f}")

    print(f"\nsigma = {a.sigma*100:.2f} %/unit, {a.seeds} seeds, {a.corner}/{a.temp:.0f} C")
    print(f"worst |DNL| = {max(dnls):.3f} LSB  (mean {statistics.mean(dnls):.3f})")
    print(f"worst |INL| = {max(inls):.3f} LSB  (mean {statistics.mean(inls):.3f})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
