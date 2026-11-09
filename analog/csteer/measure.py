#!/usr/bin/env python3
"""Static linearity and DEM statistics for the current-steering DAC leaf.

  ./measure.py dc [build/dc.dat]            bench fit (one fixed DEM pointer)
  ./measure.py dc --cells build/cells.json  also the analytic DEM study
  ./measure.py dc --brief                   machine-readable summary

Three linearity views are reported:

  bench      the ngspice transfer exactly as simulated at pointer 0, so it
             includes the injected per-cell gain errors.  Into a virtual
             ground the cell ro does not matter; with --riv it does.
  dem_mean   mean over all 2^unary_bits-1 DEM pointer positions.  With DWA
             every unary cell is selected n-of-15 times for a code with n
             active unary cells, so the first-order unary gain error cancels
             and what is left is the mean unary gain plus the binary errors.
  dem_worst  worst of the 15 pointer positions.  This is the INL/DNL a scope
             sees on any single sample, and it is what mismatch really costs.

  dem_rms    standard deviation over the pointer positions, in LSB: the
             first-order shaped mismatch noise that DEM converts the static
             unary error into.

Endpoint fit, as in the resistor leaves.  The analytic model is the same
ideal-cell model as the dc bench (current sources with a gain error), so the
two must agree at pointer 0 -- that equality is the cross-check.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def read_cols(path: Path):
    rows = []
    with open(path) as f:
        for line in f:
            parts = line.split()
            if len(parts) < 2:
                continue
            try:
                rows.append([float(p) for p in parts])
            except ValueError:
                continue
    return rows


def fit(vals, nbits: int):
    """Endpoint fit.  Returns (lsb, dnl, inl) with DNL/INL in LSB."""
    vmin, vmax = vals[0], vals[-1]
    lsb = (vmax - vmin) / (2 ** nbits - 1)
    dnl = [0.0] * len(vals)
    inl = [0.0] * len(vals)
    for i, v in enumerate(vals):
        inl[i] = (v - vmin) / lsb - i
        if i:
            dnl[i] = (v - vals[i - 1]) / lsb - 1.0
    return lsb, dnl, inl


def load_cfg():
    try:
        import yaml
    except ImportError:  # pragma: no cover
        return {}
    with open(ROOT / "csteer.yaml") as f:
        return yaml.safe_load(f)


def transfer_lsb(code: int, cfg: dict, errs: dict, pointer: int) -> float:
    """Modelled output in nominal LSB units, identical to the dc bench."""
    nu = int(cfg.get("unary_bits", 4))
    nb = int(cfg.get("binary_bits", 4))
    n_unary = 2 ** nu - 1
    n_active = code >> nb
    total = 0.0
    for j in range(n_unary):
        d = (j - pointer) % n_unary
        if d < n_active:
            total += 2 ** nu * (1.0 + errs["unary"][j])
    for k in range(nb):
        if (code >> k) & 1:
            total += 2 ** k * (1.0 + errs["binary"][k])
    return total


def dem_study(cfg: dict, errs: dict):
    bits = int(cfg.get("bits", 8))
    n_ptr = 2 ** int(cfg.get("unary_bits", 4)) - 1   # 15 unary cells
    ncode = 2 ** bits
    per_ptr = []
    for p in range(n_ptr):
        per_ptr.append([transfer_lsb(c, cfg, errs, p) for c in range(ncode)])
    mean = [sum(per_ptr[p][c] for p in range(n_ptr)) / n_ptr
            for c in range(ncode)]
    rms = []
    worst_hi = [0.0] * ncode
    worst_lo = [0.0] * ncode
    for c in range(ncode):
        vals = [per_ptr[p][c] for p in range(n_ptr)]
        rms.append(math.sqrt(sum((v - mean[c]) ** 2 for v in vals) / n_ptr))
        worst_hi[c] = max(vals) - mean[c]
        worst_lo[c] = min(vals) - mean[c]

    _, dnl_mean, inl_mean = fit(mean, bits)
    # worst pointer: INL/DNL of each pointer's own endpoint fit, then extremes.
    inl_hi = [0.0] * ncode
    inl_lo = [0.0] * ncode
    dnl_hi = [0.0] * ncode
    dnl_lo = [0.0] * ncode
    for p in range(n_ptr):
        _, dnl, inl = fit(per_ptr[p], bits)
        for c in range(ncode):
            inl_hi[c] = max(inl_hi[c], inl[c])
            inl_lo[c] = min(inl_lo[c], inl[c])
            dnl_hi[c] = max(dnl_hi[c], dnl[c])
            dnl_lo[c] = min(dnl_lo[c], dnl[c])
    return {
        "mean": mean, "rms": rms,
        "dnl_mean": dnl_mean, "inl_mean": inl_mean,
        "inl_hi": inl_hi, "inl_lo": inl_lo,
        "dnl_hi": dnl_hi, "dnl_lo": dnl_lo,
        "worst_hi": worst_hi, "worst_lo": worst_lo,
    }


def summarise(name: str, dnl, inl, brief: bool) -> None:
    if brief:
        print(f"DNL_{name} {min(dnl):+.6f} {max(dnl):+.6f}")
        print(f"INL_{name} {min(inl):+.6f} {max(inl):+.6f}")
    else:
        mono = all(d >= -1.0 for d in dnl[1:])
        print(f"-- {name}")
        print(f"   DNL       : {min(dnl):+.3f} .. {max(dnl):+.3f} LSB")
        print(f"   INL       : {min(inl):+.3f} .. {max(inl):+.3f} LSB")
        print(f"   monotonic : {'yes' if mono else 'no'}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=["dc"], nargs="?", default="dc")
    ap.add_argument("path", nargs="?", default=None)
    ap.add_argument("--bits", type=int, default=None)
    ap.add_argument("--cells", default=None)
    ap.add_argument("--brief", action="store_true")
    ap.add_argument("--no-dem", action="store_true",
                    help="bench only; skip the ideal-cell DEM study")
    a = ap.parse_args()

    cfg = load_cfg()
    nbits = a.bits or int(cfg.get("bits", 8))
    path = Path(a.path) if a.path else ROOT / "build" / "dc.dat"
    if not path.is_file():
        sys.exit(f"missing {path}")

    rows = read_cols(path)
    if len(rows) != 2 ** nbits:
        print(f"warning: {len(rows)} points for {nbits} bits", file=sys.stderr)
    vals = [r[-1] for r in rows]
    lsb, dnl, inl = fit(vals, nbits)
    if not a.brief:
        print(f"points       : {len(rows)}")
        print(f"LSB          : {lsb*1e6:.6f} uA" if "_riv" not in path.name
              else f"LSB          : {lsb*1e3:.6f} mV")
    summarise("bench", dnl, inl, a.brief)

    if a.no_dem:
        return
    cells_path = Path(a.cells) if a.cells else ROOT / "build" / "cells.json"
    if not cells_path.is_file():
        if not a.brief:
            print(f"note: {cells_path} missing, skipping the DEM study")
        return
    errs = json.loads(cells_path.read_text())
    if not errs.get("sigma"):
        if not a.brief:
            print("note: cells.json has sigma=0, skipping the DEM study")
        return
    st = dem_study(cfg, errs)
    summarise("dem_mean", st["dnl_mean"], st["inl_mean"], a.brief)
    dnl_w = (min(st["dnl_lo"]), max(st["dnl_hi"]))
    inl_w = (min(st["inl_lo"]), max(st["inl_hi"]))
    if a.brief:
        print(f"DNL_dem_worst {dnl_w[0]:+.6f} {dnl_w[1]:+.6f}")
        print(f"INL_dem_worst {inl_w[0]:+.6f} {inl_w[1]:+.6f}")
    else:
        print(f"-- dem_worst (any single sample, 15 pointers)")
        print(f"   DNL       : {dnl_w[0]:+.3f} .. {dnl_w[1]:+.3f} LSB")
        print(f"   INL       : {inl_w[0]:+.3f} .. {inl_w[1]:+.3f} LSB")
    rms_peak = max(st["rms"])
    rms_rms = math.sqrt(sum(v * v for v in st["rms"]) / len(st["rms"]))
    if a.brief:
        print(f"DEM_RMS_LSB {rms_rms:.6f} {rms_peak:.6f}")
    else:
        print(f"-- dem_noise")
        print(f"   rms over codes : {rms_rms*1e3:.2f} mLSB")
        print(f"   worst code rms  : {rms_peak*1e3:.2f} mLSB")

    out = ROOT / "build" / "inl_dnl.csv"
    with open(out, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["code", "bench", "inl_bench", "dnl_bench",
                    "dem_mean", "inl_dem_mean", "dnl_dem_mean",
                    "dem_min", "dem_max", "dem_rms"])
        for c in range(len(rows)):
            lo = st["mean"][c] + st["worst_lo"][c]
            hi = st["mean"][c] + st["worst_hi"][c]
            w.writerow([c, f"{vals[c]:.9g}", f"{inl[c]:.6f}", f"{dnl[c]:.6f}",
                        f"{st['mean'][c]:.9g}", f"{st['inl_mean'][c]:.6f}",
                        f"{st['dnl_mean'][c]:.6f}", f"{lo:.9g}", f"{hi:.9g}",
                        f"{st['rms'][c]:.6f}"])
    if not a.brief:
        print(f"wrote {out}")


if __name__ == "__main__":
    main()
