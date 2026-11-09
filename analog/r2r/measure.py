#!/usr/bin/env python3
"""Compute INL/DNL and settling from the R-2R ngspice benches.

  ./measure.py dc   [build/dc.dat]    -> prints INL/DNL, writes build/inl_dnl.csv
  ./measure.py tran [build/tran.dat]  -> prints per-step settling to 0.5 LSB

Definitions follow the reference designs: endpoint-fit LSB (the code span is
normalised to 2^N-1), DNL = step/LSB - 1, INL = deviation from the straight
line through the two endpoints.
"""
from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def read_wrdata(path: Path):
    rows = []
    with open(path) as f:
        for line in f:
            parts = line.split()
            if len(parts) >= 3:
                try:
                    rows.append((float(parts[0]), float(parts[1]), float(parts[2])))
                except ValueError:
                    continue
    return rows


def measure_dc(path: Path, nbits: int) -> int:
    rows = read_wrdata(path)
    code = [int(round(r[1])) for r in rows]
    vout = [r[2] for r in rows]
    if len(vout) != 2**nbits:
        print(f"warning: {len(vout)} points for {nbits} bits", file=sys.stderr)

    vmin, vmax = vout[0], vout[-1]
    lsb = (vmax - vmin) / (2**nbits - 1)
    if lsb <= 0:
        print("error: non-monotonic endpoints", file=sys.stderr)
        return 1

    dnl = [0.0] * len(vout)
    inl = [0.0] * len(vout)
    for i, v in enumerate(vout):
        inl[i] = (v - vmin) / lsb - i
        if i:
            dnl[i] = (v - vout[i - 1]) / lsb - 1

    out = ROOT / "build" / "inl_dnl.csv"
    with open(out, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["code", "vout", "dnl_lsb", "inl_lsb"])
        for i in range(len(vout)):
            w.writerow([i, f"{vout[i]:.9f}", f"{dnl[i]:.6f}", f"{inl[i]:.6f}"])

    print(f"points       : {len(vout)}")
    print(f"V(0)         : {vmin:.6f} V")
    print(f"V(full)      : {vmax:.6f} V")
    print(f"LSB          : {lsb*1e3:.6f} mV")
    print(f"DNL          : {min(dnl):+.3f} .. {max(dnl):+.3f} LSB")
    print(f"INL          : {min(inl):+.3f} .. {max(inl):+.3f} LSB")
    print(f"monotonic    : {'yes' if all(d >= -1.0 for d in dnl) else 'no'}")
    print(f"wrote {out}")
    return 0


def measure_tran(path: Path, nbits: int, step_us: float = 5.0) -> int:
    rows = read_wrdata(path)
    if not rows:
        print("error: empty tran data", file=sys.stderr)
        return 1
    t = [r[0] for r in rows]
    v = [r[1] for r in rows]
    code = [r[2] for r in rows]
    lsb = 3.3 / 2**nbits
    tol = 0.5 * lsb
    t_end = t[-1]
    step = step_us * 1e-6

    print(f"{'t_us':>8} {'settle_ns':>11} {'final_V':>10} {'code':>5}")
    k = 0
    while (k + 1) * step <= t_end + 1e-12:
        t0 = k * step
        t1 = (k + 1) * step
        # Final value from the settled tail of the window (past the edge ramp).
        tail = [i for i in range(len(t)) if t0 + 0.5 * step <= t[i] < t1 - 0.01 * step]
        if not tail:
            k += 1
            continue
        vf = v[tail[-1]]
        # Settling is measured from the nominal edge time t0.
        cross = None
        for i in reversed(range(len(t))):
            if t[i] <= t0:
                break
            if t[i] >= t1 - 0.01 * step:
                continue
            if abs(v[i] - vf) > tol:
                cross = t[min(i + 1, len(t) - 1)] - t0
                break
        settle = 0.0 if cross is None else cross
        print(f"{t0*1e6:8.2f} {settle*1e9:11.1f} {vf:10.4f} {round(code[tail[-1]]):5d}")
        k += 1
    return 0


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=["dc", "tran"])
    ap.add_argument("path", nargs="?", default=None)
    ap.add_argument("--bits", type=int, default=8)
    a = ap.parse_args()
    p = Path(a.path) if a.path else ROOT / "build" / f"{a.mode}.dat"
    if not p.is_file():
        sys.exit(f"missing {p}")
    sys.exit(measure_dc(p, a.bits) if a.mode == "dc" else measure_tran(p, a.bits))


if __name__ == "__main__":
    main()
