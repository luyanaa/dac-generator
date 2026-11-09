#!/usr/bin/env python3
"""Linearity, binary-carry glitch and settling for the video DAC leaf.

  ./measure.py dc [build/dc.dat] [--brief]
  ./measure.py tran [build/tran.dat] [--lsb 0.0006]
  ./measure.py study [--seeds 20] [--mismatch 0.018]

`dc` and `tran` read what ngspice wrote.  `study` is the analytic version of
the dc bench over several mismatch seeds, for both decodes, so the binary
carry penalty can be compared without running 40 decks; it uses the same
per-cell error model as gen_video.py (cell selection is a linear sum, so the
two are identical at any one seed).

Endpoint fit, as in the other leaves: LSB_eff = (last - first)/(2^N - 1), so
gain error does not hide in INL.
"""
from __future__ import annotations

import argparse
import csv
import math
import random
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent


def load_cfg() -> dict:
    with open(ROOT / "video.yaml") as f:
        return yaml.safe_load(f)


def read_cols(path: Path):
    rows = []
    with open(path) as f:
        for line in f:
            parts = line.split()
            if len(parts) < 2:
                continue
            try:
                rows.append([float(p) for p in parts[:2]])
            except ValueError:
                continue
    return rows


def fit(vals, nbits: int):
    lsb = (vals[-1] - vals[0]) / (2 ** nbits - 1)
    dnl = [0.0] * len(vals)
    inl = [0.0] * len(vals)
    for i, v in enumerate(vals):
        inl[i] = (v - vals[0]) / lsb - i
        if i:
            dnl[i] = (v - vals[i - 1]) / lsb - 1.0
    return lsb, dnl, inl


def summarise(name: str, dnl, inl, brief: bool) -> None:
    if brief:
        print(f"DNL_{name} {min(dnl):+.6f} {max(dnl):+.6f}")
        print(f"INL_{name} {min(inl):+.6f} {max(inl):+.6f}")
        return
    mono = all(d >= -1.0 for d in dnl[1:])
    print(f"-- {name}")
    print(f"   DNL       : {min(dnl):+.3f} .. {max(dnl):+.3f} LSB")
    print(f"   INL       : {min(inl):+.3f} .. {max(inl):+.3f} LSB")
    print(f"   monotonic : {'yes' if mono else 'no'}")


def dc(path: Path, nbits: int, brief: bool, expect: str) -> int:
    rows = read_cols(path)
    if len(rows) != 2 ** nbits:
        print(f"error: {len(rows)} points for {nbits} bits", file=sys.stderr)
        return 2
    vals = [r[1] for r in rows]
    # A virtual-ground deck writes i(Vout) with the opposite sign convention;
    # the transfer must rise with code, so flip once and say so.
    flipped = vals[-1] < vals[0]
    if flipped:
        vals = [-v for v in vals]
    lsb, dnl, inl = fit(vals, nbits)
    if not brief:
        print(f"points       : {len(rows)}")
        print(f"LSB          : {lsb:.6g} (deck units)"
              + ("  [sign flipped]" if flipped else ""))
        print(f"endpoints    : {vals[0]:.6g} .. {vals[-1]:.6g}")
    summarise("bench", dnl, inl, brief)
    ok = max(abs(min(dnl)), abs(max(dnl))) <= 0.5 and \
        max(abs(min(inl)), abs(max(inl))) <= 1.0
    print(f"VERDICT {'PASS' if ok else 'FAIL'}  "
          f"(DNL {max(abs(min(dnl)), abs(max(dnl))):.3f} / 0.5, "
          f"INL {max(abs(min(inl)), abs(max(inl))):.3f} / 1.0 LSB)")
    out = ROOT / "build" / "inl_dnl.csv"
    with open(out, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["code", "value", "dnl", "inl"])
        for c, v in enumerate(vals):
            w.writerow([c, f"{v:.9g}", f"{dnl[c]:.6f}", f"{inl[c]:.6f}"])
    if not brief:
        print(f"wrote {out}")
    if expect == "pass":
        return 0 if ok else 1
    if expect == "fail":
        return 1 if ok else 0
    return 0


def tran(path: Path, lsb: float, brief: bool) -> int:
    rows = read_cols(path)
    if len(rows) < 10:
        print(f"error: {path} has {len(rows)} points", file=sys.stderr)
        return 2
    t = [r[0] for r in rows]
    v = [r[1] for r in rows]
    v0, vf = v[0], sum(v[-max(len(v) // 20, 5):]) / max(len(v) // 20, 5)
    lo, hi = min(v0, vf), max(v0, vf)
    # Glitch = how far the waveform leaves the monotonic envelope between the
    # two codes.  A single-pole settle never leaves it; a binary carry with
    # skewed bit slices does.
    glitch = max(0.0, max(v) - hi, lo - min(v))
    # Settle: last time outside +/- settle_lsb of the final value.
    tol = 0.5 * lsb
    settle = 0.0
    for ti, vi in zip(t, v):
        if abs(vi - vf) > tol:
            settle = ti
    if brief:
        print(f"GLITCH_LSB {glitch / lsb:.3f}")
        print(f"SETTLE_PS {settle * 1e12:.1f}")
        return 0
    print(f"points       : {len(rows)}")
    print(f"step         : {v0 * 1e3:+.3f} -> {vf * 1e3:+.3f} mV "
          f"({(vf - v0) / lsb:+.1f} LSB)")
    print(f"glitch       : {glitch / lsb:8.2f} LSB  "
          f"({glitch * 1e3:.2f} mV outside the monotonic envelope)")
    print(f"settle       : {settle * 1e12:8.1f} ps to +/-0.5 LSB")
    return 0


def _xfer(errs, code: int, decode: str) -> float:
    if decode == "unary":
        return sum(1.0 + e for e in errs[:code])
    total = 0.0
    for k in range(8):
        if (code >> k) & 1:
            j0 = (1 << k) - 1
            total += sum(1.0 + e for e in errs[j0:j0 + (1 << k)])
    return total


def study(seeds: int, sigma: float, brief: bool) -> int:
    rows = []
    for seed in range(seeds):
        rng = random.Random(seed)
        errs = [rng.gauss(0.0, sigma) for _ in range(255)] if sigma else \
            [0.0] * 255
        for decode in ("binary", "unary"):
            vals = [_xfer(errs, c, decode) for c in range(256)]
            _, dnl, inl = fit(vals, 8)
            rows.append({
                "seed": seed, "decode": decode,
                "dnl": max(abs(min(dnl)), abs(max(dnl))),
                "inl": max(abs(min(inl)), abs(max(inl))),
            })
    out = ROOT / "build" / "study.csv"
    with open(out, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["seed", "decode", "worst_dnl", "worst_inl"])
        for r in rows:
            w.writerow([r["seed"], r["decode"],
                        f"{r['dnl']:.6f}", f"{r['inl']:.6f}"])

    if not brief:
        print(f"-- binary vs unary decode of the same 255 unit cells "
              f"({seeds} seeds, sigma {sigma * 100:.2f} %/cell)")
        print(f"   {'decode':8s} {'worst DNL':>10s} {'worst INL':>10s} "
              f"{'DNL>0.5':>8s} {'INL>1.0':>8s}")
    for decode in ("binary", "unary"):
        sel = [r for r in rows if r["decode"] == decode]
        dnl = max(r["dnl"] for r in sel)
        inl = max(r["inl"] for r in sel)
        nd = sum(1 for r in sel if r["dnl"] > 0.5)
        ni = sum(1 for r in sel if r["inl"] > 1.0)
        if brief:
            print(f"STUDY_{decode} DNL {dnl:.6f} INL {inl:.6f} "
                  f"fail_dnl {nd} fail_inl {ni} of {seeds}")
        else:
            print(f"   {decode:8s} {dnl:10.3f} {inl:10.3f} "
                  f"{nd:5d}/{seeds:<2d} {ni:5d}/{seeds:<2d}")
    if not brief:
        print(f"wrote {out}")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("mode", choices=["dc", "tran", "study"], nargs="?",
                    default="dc")
    ap.add_argument("path", nargs="?", default=None)
    ap.add_argument("--bits", type=int, default=None)
    ap.add_argument("--lsb", type=float, default=None,
                    help="volts per LSB for the transient bench")
    ap.add_argument("--seeds", type=int, default=20)
    ap.add_argument("--mismatch", type=float, default=None)
    ap.add_argument("--expect", choices=["pass", "fail", "any"],
                    default="any", help="what this bench should prove")
    ap.add_argument("--brief", action="store_true")
    a = ap.parse_args(argv)

    cfg = load_cfg()
    nbits = a.bits or int(cfg["bits"])
    if a.mode == "dc":
        path = Path(a.path) if a.path else ROOT / "build" / "dc.dat"
        if not path.is_file():
            sys.exit(f"missing {path}")
        return dc(path, nbits, a.brief, a.expect)
    if a.mode == "tran":
        path = Path(a.path) if a.path else ROOT / "build" / "tran.dat"
        if not path.is_file():
            sys.exit(f"missing {path}")
        lsb = a.lsb if a.lsb is not None else \
            cfg["i_unit_ua"] * 1e-6 * cfg["r_load"]
        return tran(path, lsb, a.brief)
    sigma = cfg["cell_sigma"] if a.mismatch is None else a.mismatch
    return study(a.seeds, sigma, a.brief)


if __name__ == "__main__":
    sys.exit(main())
