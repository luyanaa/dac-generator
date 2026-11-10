#!/usr/bin/env python3
"""Device bench for the current-steering unit cell.

Runs the cascoded PMOS cell over corners/temperature, fits

    I_cell  at Vout = 0        (the cell the dc bench models as ideal)
    ro      over the flat window 0.05-1.0 V

and, at tt/25 C, sweeps a gate-referred Vth offset to get the dI/I
sensitivity.  That sensitivity times the Pelgrom sigma_VT is the per-cell
gain sigma the dc bench injects, so the two benches are tied together:

    sigma_I/I = (dI/I per mV) * sigma_VT

    ./run_cell.py             default 7-point matrix + sensitivity
    ./run_cell.py --full      all 15 corner/temperature points
    ./run_cell.py --brief     machine-readable lines only
"""
from __future__ import annotations

import argparse
import csv
import statistics
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
CORNERS = ["tt", "ff", "ss", "fs", "sf"]
TEMPS = [-40.0, 25.0, 125.0]


def run(cmd):
    return subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True)


def read_iv(path: Path):
    rows = []
    for line in path.read_text().splitlines():
        p = line.split()
        if len(p) < 2:
            continue
        try:
            rows.append((float(p[0]), float(p[-1])))
        except ValueError:
            continue
    return rows


def fit(rows):
    if not rows:
        return None
    i0 = rows[0][1]
    seg = [(v, i) for v, i in rows if 0.05 <= v <= 1.0]
    n = len(seg)
    sv = sum(v for v, _ in seg)
    si = sum(i for _, i in seg)
    svv = sum(v * v for v, _ in seg)
    svi = sum(v * i for v, i in seg)
    b = (n * svi - sv * si) / (n * svv - sv * sv)
    ro = -1.0 / b if b else float("inf")
    return i0, ro


def bench_cell(corner: str, temp: float, voff: float = 0.0, pdk: str = "gf180"):
    tag = f"{corner}_{int(temp)}" + (f"_v{int(voff*1000)}" if voff else "")
    dat = ROOT / "build" / f"cell_{tag}.dat"
    out = ROOT / "build" / f"csteer_cell_{tag}.spice"
    r = run([sys.executable, "gen_csteer.py", "--pdk", pdk, "--bench", "cell",
             "--corner", corner, "--temp", str(temp), "--voff", str(voff),
             "--dat", str(dat), "--out", str(out)])
    if r.returncode:
        sys.exit(f"gen failed ({corner},{temp}): {r.stderr.strip()}")
    r = run(["ngspice", "-b", str(out)])
    if r.returncode:
        sys.exit(f"ngspice failed ({corner},{temp})")
    return fit(read_iv(dat))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pdk", default="gf180", choices=["gf180", "sky130"])
    ap.add_argument("--full", action="store_true")
    ap.add_argument("--brief", action="store_true")
    a = ap.parse_args()

    points = ([(c, t) for c in CORNERS for t in TEMPS] if a.full
              else [(c, 25.0) for c in CORNERS] + [("tt", -40.0), ("tt", 125.0)])
    rows = []
    for c, t in points:
        f = bench_cell(c, t, pdk=a.pdk)
        if f is None:
            sys.exit(f"no data for {c}/{t}")
        rows.append((c, t, f[0], f[1]))
        if a.brief:
            print(f"CELL {c} {t:+.0f} {f[0]*1e6:.4f} {f[1]/1e6:.1f}")
        else:
            print(f"{c:>2} {t:+6.0f}C  I={f[0]*1e6:8.4f} uA  "
                  f"ro={f[1]/1e6:8.1f} MOhm")

    # Vth sensitivity at tt/25 C
    base = None
    sens = []
    for voff in (0.0, 0.005, 0.010, 0.020):
        f = bench_cell("tt", 25.0, voff, pdk=a.pdk)
        if voff == 0.0:
            base = f[0]
            continue
        d = (f[0] - base) / abs(base)
        sens.append(d / (voff * 1e3))
        if a.brief:
            print(f"SENS {voff*1e3:.0f} {d*100:+.3f} {d/(voff*1e3)*100:+.4f}")
        else:
            print(f"voff={voff*1e3:>4.0f} mV  dI/I={d*100:+7.3f}%  "
                  f"{d/(voff*1e3)*100:+.4f} %/mV")

    mean_sens = statistics.mean(sens)
    if a.brief:
        print(f"SENS_MEAN {mean_sens*100:.4f}")
    else:
        print(f"mean sensitivity: {mean_sens*100:+.4f} %/mV")

    out = ROOT / "build" / "cell_matrix.csv"
    with open(out, "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["corner", "temp_C", "i_cell_uA", "ro_MOhm", "sens_pct_per_mV"])
        for c, t, i, ro in rows:
            w.writerow([c, t, f"{i*1e6:.4f}", f"{ro/1e6:.1f}", ""])
        w.writerow(["tt", 25.0, "", "", f"{mean_sens*100:.4f}"])
    if not a.brief:
        print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
