#!/usr/bin/env python3
"""Pre-layout benches for the 8-bit 25 MS/s video current-steering leaf.

  ./gen_video.py --bench dc   [--decode binary|unary] [--mismatch 0.018]
                              [--seed 0] [--riv 37.5] [--out build/dc.spice]
  ./gen_video.py --bench tran --from 127 --to 128 [--skew-ps 25]
                              [--edge-ps 20] [--out build/tran.spice]

Both benches are *decode* models, not device models: each of the 255 unit
cells is an ideal current source with a gain error and a finite ro, exactly
the level at which binary vs unary decoding and the major carries can be
compared.  The cell constants come from the P3 device bench (gf180, see
video.yaml), so the deck needs no PDK models and runs anywhere ngspice does.

`--decode binary` groups the cells 1/2/4/.../128 and switches a whole group
on one code bit.  `--decode unary` switches cells 0..code-1, i.e. the same
255 unit cells with a thermometer decoder, which is the control that isolates
what binary decoding itself costs.

The DC transfer is written with wrdata:
    virtual ground (--riv 0):  build/dc.dat  <- i(Vout)
    passive load  (--riv >0):  build/dc.dat  <- v(out)
measure.py fits both the same way (endpoint fit, LSB in whatever unit).

The transient bench is the glitch test: one code step, each bit slice
delayed by k*skew, finite edge, 37.5 Ohm || 2 pF.  It reports how far the
output leaves the monotonic envelope between the two codes, in LSB, and how
long it takes to settle back.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent


def load_cfg() -> dict:
    with open(ROOT / "video.yaml") as f:
        return yaml.safe_load(f)


def cell_errors(cfg: dict, sigma: float, seed: int) -> list[float]:
    """255 per-cell relative gain errors, one list for both decodes."""
    import random
    rng = random.Random(seed)
    if not sigma:
        return [0.0] * 255
    return [rng.gauss(0.0, sigma) for _ in range(255)]


def cell_bit(j: int) -> int:
    """Which binary bit owns unit cell j: 2^k cells per bit, k = 0..7."""
    for k in range(8):
        if j < (1 << (k + 1)) - 1:
            return k
    raise ValueError(j)


def dc_deck(cfg: dict, errs: list[float], decode: str, riv: float) -> str:
    iu = cfg["i_unit_ua"] * 1e-6
    ro = float(cfg["ro_unit"])
    vdd = float(cfg["vdd"])
    out = [
        f"* video current-steering, dc, decode={decode}, riv={riv}",
        f"Vdd vdd 0 {vdd}",
        "Vcode code 0 0",
    ]
    if riv:
        out.append(f"Rl out 0 {riv}")
        probe = "v(out)"
    else:
        out.append("Vout out 0 0")
        probe = "i(Vout)"

    if decode == "binary":
        for k in range(8):
            w = 1 << k
            out.append(
                f"Bsel{k} s{k} 0 V = {vdd}*(floor((v(code)+0.5)/{w})"
                f"-2*floor((v(code)+0.5)/{2 * w}))")
        for j, e in enumerate(errs):
            k = cell_bit(j)
            out.append(
                f"Bu{j} 0 out I = {iu * (1.0 + e):.12g}*v(s{k})/{vdd}"
                f" - v(out)/{ro:.12g}*v(s{k})/{vdd}")
    elif decode == "unary":
        for j, e in enumerate(errs):
            sel = f"(v(code) > {j + 0.5})"
            out.append(
                f"Bu{j} 0 out I = {iu * (1.0 + e):.12g}*{sel}"
                f" - v(out)/{ro:.12g}*{sel}")
    else:                                                     # pragma: no cover
        sys.exit(f"unknown decode {decode}")

    out += [
        ".control",
        "dc Vcode 0 255 1",
        f"wrdata {ROOT / 'build' / 'dc.dat'} {probe}",
        ".endc",
        ".end",
    ]
    return "\n".join(out) + "\n"


def tran_deck(cfg: dict, frm: int, to: int, skew_ps: float,
              edge_ps: float) -> str:
    iu = cfg["i_unit_ua"] * 1e-6
    ro = float(cfg["ro_unit"])
    vdd = float(cfg["vdd"])
    rl = float(cfg["r_load"])
    cl = float(cfg["c_load_pf"]) * 1e-12
    t0 = 200e-12
    edge = edge_ps * 1e-12
    out = [
        f"* video current-steering, tran {frm}->{to}, skew={skew_ps} ps",
        f"Vdd vdd 0 {vdd}",
        f"Rl out 0 {rl}",
        f"Cl out 0 {cl}",
    ]
    for k in range(8):
        v0 = vdd if (frm >> k) & 1 else 0.0
        v1 = vdd if (to >> k) & 1 else 0.0
        if v0 == v1:
            out.append(f"Vb{k} b{k} 0 {v0}")
            continue
        t = t0 + k * skew_ps * 1e-12
        out.append(f"Vb{k} b{k} 0 PWL(0 {v0} {t:.6g} {v0} "
                   f"{t + edge:.6g} {v1})")
    for k in range(8):
        ik = (1 << k) * iu
        rok = ro / (1 << k)
        out.append(
            f"Bb{k} 0 out I = {ik:.12g}*v(b{k})/{vdd}"
            f" - v(out)/{rok:.12g}*v(b{k})/{vdd}")
    out += [
        ".control",
        "tran 0.5p 6n",
        f"wrdata {ROOT / 'build' / 'tran.dat'} v(out)",
        ".endc",
        ".end",
    ]
    return "\n".join(out) + "\n"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--bench", choices=["dc", "tran"], default="dc")
    ap.add_argument("--decode", choices=["binary", "unary"], default="binary")
    ap.add_argument("--mismatch", type=float, default=None,
                    help="per-cell sigma; default video.yaml cell_sigma")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--riv", type=float, default=0.0,
                    help="load resistor in ohm; 0 = virtual ground")
    ap.add_argument("--from", dest="frm", type=int, default=127)
    ap.add_argument("--to", dest="to", type=int, default=128)
    ap.add_argument("--skew-ps", type=float, default=None)
    ap.add_argument("--edge-ps", type=float, default=None)
    ap.add_argument("--out", default=None)
    a = ap.parse_args(argv)

    cfg = load_cfg()
    (ROOT / "build").mkdir(exist_ok=True)
    if a.bench == "dc":
        sigma = cfg["cell_sigma"] if a.mismatch is None else a.mismatch
        errs = cell_errors(cfg, sigma, a.seed)
        text = dc_deck(cfg, errs, a.decode, a.riv)
        out = Path(a.out) if a.out else ROOT / "build" / "dc.spice"
    else:
        skew = cfg["skew_ps"] if a.skew_ps is None else a.skew_ps
        edge = cfg["edge_ps"] if a.edge_ps is None else a.edge_ps
        text = tran_deck(cfg, a.frm, a.to, skew, edge)
        out = Path(a.out) if a.out else ROOT / "build" / "tran.spice"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text)
    print(f"wrote {out}  ({len(text.splitlines())} lines)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
