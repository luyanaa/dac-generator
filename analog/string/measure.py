#!/usr/bin/env python3
"""Compute INL/DNL and settling from the resistor-string ngspice benches.

  ./measure.py dc   [build/dc.dat]    -> INL/DNL, writes build/inl_dnl.csv
  ./measure.py tran [build/tran.dat]  -> per-step settling to 0.5 LSB

The DC file has four columns (sweep, code, tap, buffered output).  Linearity is
reported for both the raw tap and the follower output, so the tree's
code-dependent on-resistance can be separated from the buffer.

Endpoint-fit LSB, as in the reference designs: the code span is normalised to
2^N-1, DNL = step/LSB - 1, INL = deviation from the endpoint straight line.
"""
from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def read_cols(path: Path):
    rows = []
    with open(path) as f:
        for line in f:
            parts = line.split()
            if len(parts) < 3:
                continue
            try:
                rows.append([float(p) for p in parts])
            except ValueError:
                continue
    return rows


def fit(vals, nbits: int):
    vmin, vmax = vals[0], vals[-1]
    lsb = (vmax - vmin) / (2 ** nbits - 1)
    dnl = [0.0] * len(vals)
    inl = [0.0] * len(vals)
    for i, v in enumerate(vals):
        inl[i] = (v - vmin) / lsb - i
        if i:
            dnl[i] = (v - vals[i - 1]) / lsb - 1
    return vmin, vmax, lsb, dnl, inl


def measure_dc(path: Path, nbits: int, brief: bool = False) -> int:
    rows = read_cols(path)
    if len(rows) != 2 ** nbits:
        print(f"warning: {len(rows)} points for {nbits} bits", file=sys.stderr)
    code = [int(round(r[1])) for r in rows]
    sig = {"tap": [r[2] for r in rows], "vout": [r[-1] for r in rows]}

    out = ROOT / "build" / "inl_dnl.csv"
    with open(out, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["code", "tap", "vout", "dnl_tap", "inl_tap",
                    "dnl_vout", "inl_vout"])
        stats = {}
        for name, vals in sig.items():
            vmin, vmax, lsb, dnl, inl = fit(vals, nbits)
            stats[name] = (vmin, vmax, lsb, dnl, inl)
        for i in range(len(rows)):
            w.writerow([code[i]] + [f"{sig[k][i]:.9f}" for k in sig]
                       + [f"{stats['tap'][3][i]:.6f}", f"{stats['tap'][4][i]:.6f}",
                          f"{stats['vout'][3][i]:.6f}", f"{stats['vout'][4][i]:.6f}"])

    if brief:
        for name in sig:
            _, _, _, dnl, inl = stats[name]
            print(f"DNL_{name} {min(dnl):+.6f} {max(dnl):+.6f}")
            print(f"INL_{name} {min(inl):+.6f} {max(inl):+.6f}")
        return 0

    print(f"points       : {len(rows)}")
    for name in sig:
        vmin, vmax, lsb, dnl, inl = stats[name]
        print(f"-- {name}")
        print(f"   V(0)      : {vmin:.6f} V")
        print(f"   V(full)   : {vmax:.6f} V")
        print(f"   LSB       : {lsb*1e3:.6f} mV")
        print(f"   DNL       : {min(dnl):+.3f} .. {max(dnl):+.3f} LSB")
        print(f"   INL       : {min(inl):+.3f} .. {max(inl):+.3f} LSB")
        print(f"   monotonic : {'yes' if all(d >= -1.0 for d in dnl[1:]) else 'no'}")
    print(f"wrote {out}")
    return 0


def measure_tran(path: Path, nbits: int, step_us: float = 10.0) -> int:
    rows = read_cols(path)
    if not rows:
        print("error: empty tran data", file=sys.stderr)
        return 1
    t = [r[0] for r in rows]
    vtap = [r[1] for r in rows]
    vout = [r[2] for r in rows]
    code = [r[3] for r in rows]
    lsb = 3.3 / (2 ** nbits - 1)
    tol = 0.5 * lsb
    step = step_us * 1e-6
    t_end = t[-1]

    print(f"{'t_us':>8} {'tap_ns':>10} {'vout_ns':>10} {'final_V':>10} {'code':>5}")
    k = 0
    while (k + 1) * step <= t_end + 1e-12:
        t0, t1 = k * step, (k + 1) * step
        tail = [i for i in range(len(t)) if t0 + 0.5 * step <= t[i] < t1 - 0.01 * step]
        if not tail:
            k += 1
            continue
        row = [f"{t0*1e6:8.2f}"]
        for sig in (vtap, vout):
            vf = sig[tail[-1]]
            cross = None
            for i in reversed(range(len(t))):
                if t[i] <= t0:
                    break
                if t[i] >= t1 - 0.01 * step:
                    continue
                if abs(sig[i] - vf) > tol:
                    cross = t[min(i + 1, len(t) - 1)] - t0
                    break
            row.append(f"{(0.0 if cross is None else cross)*1e9:10.1f}")
        row += [f"{vout[tail[-1]]:10.4f}", f"{round(code[tail[-1]]):5d}"]
        print(" ".join(row))
        k += 1
    return 0


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=["dc", "tran"])
    ap.add_argument("path", nargs="?", default=None)
    ap.add_argument("--bits", type=int, default=8)
    ap.add_argument("--brief", action="store_true",
                    help="machine-readable DNL/INL lines only")
    a = ap.parse_args()
    p = Path(a.path) if a.path else ROOT / "build" / f"{a.mode}.dat"
    if not p.is_file():
        sys.exit(f"missing {p}")
    if a.mode == "dc":
        sys.exit(measure_dc(p, a.bits, a.brief))
    sys.exit(measure_tran(p, a.bits))


if __name__ == "__main__":
    main()
