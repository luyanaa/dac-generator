#!/usr/bin/env python3
"""Per-cell gain-mismatch sweep for the current-steering leaf.

gf180's models are not statistical in this ngspice build, so mismatch is the
explicit Pelgrom estimate in csteer.yaml (1.8 % per unit cell).  This runs the
dc bench over N seeds and reports the worst and mean linearity, both at a
fixed pointer (what the hardware does without DEM) and averaged over the DEM
pointer positions (what DEM recovers).

    ./run_mismatch.py --sigma 0.018 --seeds 10
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


def parse_brief(text: str):
    out = {}
    for line in text.splitlines():
        parts = line.split()
        if not parts:
            continue
        if parts[0].startswith(("DNL_", "INL_")) and len(parts) == 3:
            out[parts[0]] = (float(parts[1]), float(parts[2]))
        elif parts[0] == "DEM_RMS_LSB" and len(parts) == 3:
            out["DEM_RMS"] = (float(parts[1]), float(parts[2]))
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pdk", default="gf180", choices=["gf180", "sky130"])
    ap.add_argument("--sigma", type=float, default=0.018)
    ap.add_argument("--seeds", type=int, default=10)
    ap.add_argument("--corner", default="tt")
    ap.add_argument("--temp", type=float, default=25.0)
    a = ap.parse_args()

    keys = ["DNL_bench", "INL_bench", "DNL_dem_mean", "INL_dem_mean",
            "DNL_dem_worst", "INL_dem_worst", "DEM_RMS"]
    allres = {k: [] for k in keys}
    print(f"{'seed':>4} {'DNL_b':>8} {'INL_b':>8} {'DNL_dm':>8} "
          f"{'INL_dm':>8} {'INL_dw':>8} {'rms':>7}")
    for seed in range(1, a.seeds + 1):
        r = run([sys.executable, "gen_csteer.py", "--pdk", a.pdk, "--bench", "dc",
                 "--mismatch", str(a.sigma), "--seed", str(seed),
                 "--corner", a.corner, "--temp", str(a.temp)])
        if r.returncode:
            sys.exit(f"gen failed: {r.stderr.strip()}")
        r = run(["ngspice", "-b", str(ROOT / "build" / "csteer_dc.spice")])
        if r.returncode:
            sys.exit("ngspice failed")
        r = run([sys.executable, "measure.py", "dc", "--brief"])
        if r.returncode:
            sys.exit(f"measure failed: {r.stderr.strip()}")
        res = parse_brief(r.stdout)
        for k in keys:
            allres[k].append(res[k])
        inl_b = max(abs(v) for v in res["INL_bench"])
        inl_dm = max(abs(v) for v in res["INL_dem_mean"])
        inl_dw = max(abs(v) for v in res["INL_dem_worst"])
        print(f"{seed:>4} {res['DNL_bench'][0]:>+8.3f} {inl_b:>8.3f} "
              f"{res['DNL_dem_mean'][0]:>+8.3f} {inl_dm:>8.3f} "
              f"{inl_dw:>8.3f} {res['DEM_RMS'][1]*1e3:>7.1f}")

    print("\nsummary (worst of the extremes over seeds; rms in LSB)")
    for k in ("DNL_bench", "DNL_dem_mean", "DNL_dem_worst"):
        lo = min(v[0] for v in allres[k])
        hi = max(v[1] for v in allres[k])
        print(f"  {k:<14}: {lo:+.3f} .. {hi:+.3f}")
    for k in ("INL_bench", "INL_dem_mean", "INL_dem_worst"):
        w = max(max(abs(x) for x in v) for v in allres[k])
        mean_w = statistics.mean(max(abs(x) for x in v) for v in allres[k])
        print(f"  {k:<14}: worst {w:.3f}, mean {mean_w:.3f}")
    rms = [v[1] for v in allres["DEM_RMS"]]
    print(f"  DEM_RMS (peak code): worst {max(rms):.3f}, "
          f"mean {statistics.mean(rms):.3f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
