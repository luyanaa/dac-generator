#!/usr/bin/env python3
"""Spec gate for the binary CDAC leaf.

Reads the artifacts `gen_cdac.py --bench model` just wrote for one capacitor
backend and decides whether that backend meets the SAR target:

    ./measure.py --cap mim              gate: DNL/INL/fs/monotonicity
    ./measure.py --cap moscap --expect study
                                        report only, record why it fails
    ./measure.py --cap const --expect control
                                        the exactness self-check

Why this is a gate and not a table: the CDAC result is not "the model ran".
The measured sky130 moscap is bias dependent (2.67 -> 5.02 fF over the range
the array applies), so an 8-bit full-scale array built from it is *not*
linear no matter how good the mismatch is.  A backend either meets the target
or the regression says so and exits non-zero; there is no "close enough".

Targets come from the reference SAR spec (../saradc_auto,
gen/spec/examples/sar8_sky130.json): 8 bit, 1.8 V differential, 1 MS/s,
dnl_target_lsb 0.5.  The INL target (1.0 LSB) is this leaf's own, the
reference spec sets only DNL.
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent

DNL_TARGET = 0.5      # LSB, from the reference SAR spec
INL_TARGET = 1.0      # LSB, this leaf's target (not in the reference spec)
FS_TARGET = 1.0e6     # Hz, from the reference SAR spec


def load(cap: str):
    csv_path = ROOT / "build" / f"model_{cap}.csv"
    json_path = ROOT / "build" / f"model_{cap}.json"
    if not csv_path.is_file() or not json_path.is_file():
        raise SystemExit(
            f"error: {csv_path.name}/{json_path.name} missing; "
            f"run `./gen_cdac.py --bench model --cap {cap}` first")
    rows = []
    with open(csv_path) as fh:
        for row in csv.DictReader(fh):
            rows.append({"code": int(row["code"]), "vd": float(row["vd_v"]),
                         "inl": float(row["inl_lsb"]),
                         "dnl": float(row["dnl_lsb"])})
    return rows, json.loads(json_path.read_text())


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--cap", default="moscap",
                    choices=["moscap", "mim", "const"])
    ap.add_argument("--expect", default="spec",
                    choices=["spec", "study", "control"],
                    help="spec: gate; study: report a backend known to fail; "
                         "control: require exact linearity")
    ap.add_argument("--brief", action="store_true")
    a = ap.parse_args(argv)

    rows, meta = load(a.cap)
    nu = 1 << int(meta["bits"])
    if len(rows) != nu:
        raise SystemExit(f"error: {len(rows)} codes in the artifact, need {nu}")

    span = rows[-1]["vd"] - rows[0]["vd"]
    lsb = span / (nu - 1)
    dnl = [r["dnl"] for r in rows[1:]]
    inl = [r["inl"] for r in rows]
    worst_dnl = max(abs(min(dnl)), abs(max(dnl)))
    worst_inl = max(abs(min(inl)), abs(max(inl)))
    monotonic = all(d >= -1.0 for d in dnl)
    fs = float(meta["budget"]["fs_max_hz"])
    ct = float(meta["budget"]["c_tot_ff"])
    sigma = float(meta["sigma_rel"]) * 100.0

    # The spec check is always evaluated: a study backend must report FAIL,
    # not be excused from the numbers.  `--expect` only decides the exit code.
    fails = []
    if worst_dnl > DNL_TARGET:
        fails.append(f"DNL {worst_dnl:.3f} > {DNL_TARGET} LSB")
    if worst_inl > INL_TARGET:
        fails.append(f"INL {worst_inl:.3f} > {INL_TARGET} LSB")
    if not monotonic:
        fails.append("not monotonic")
    if fs < FS_TARGET:
        fails.append(f"fs_max {fs/1e6:.2f} < {FS_TARGET/1e6:g} MS/s")
    if a.expect == "control" and (worst_dnl > 1e-9 or worst_inl > 1e-9):
        fails.append("control backend is not exactly linear")

    if a.brief:
        print(f"DNL_{a.cap} {min(dnl):+.6f} {max(dnl):+.6f}")
        print(f"INL_{a.cap} {min(inl):+.6f} {max(inl):+.6f}")
        print(f"FS_{a.cap} {fs:.6g}")
        print(f"VERDICT_{a.cap} {'PASS' if not fails else 'FAIL'}")
        return 0 if not fails else 1

    print(f"-- CDAC {int(meta['bits'])} bit, backend {a.cap}, "
          f"dummy {meta['dummy_mode']}")
    print(f"   C_total   : {ct:.1f} fF   sigma_C/C {sigma:.4f} %/unit")
    print(f"   span      : {span:.4f} V   LSB {lsb*1e3:.4f} mV")
    print(f"   DNL       : {min(dnl):+.3f} .. {max(dnl):+.3f} LSB "
          f"(target {DNL_TARGET})")
    print(f"   INL       : {min(inl):+.3f} .. {max(inl):+.3f} LSB "
          f"(target {INL_TARGET})")
    print(f"   monotonic : {'yes' if monotonic else 'no'}")
    print(f"   fs_max    : {fs/1e6:.2f} MS/s (target {FS_TARGET/1e6:g})")
    if worst_inl > 1.0:
        # Report the shape, not just the number: an even-symmetric bow like
        # this is the C(V) parabola, not mismatch (mismatch is a random walk).
        pts = [0, nu // 8, nu // 4, 3 * nu // 8, nu // 2]
        print("   INL@code  : " + " ".join(f"{c}:{rows[c]['inl']:+.2f}"
                                           for c in pts))

    if fails:
        print(f"   VERDICT   : FAIL ({'; '.join(fails)})")
        if a.expect == "study":
            print("   note      : recorded study, not a design; this backend "
                  "is expected to fail at full scale")
            return 0
        return 1
    print("   VERDICT   : PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
