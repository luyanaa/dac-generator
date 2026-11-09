#!/usr/bin/env python3
"""Pre-layout benches for the unit-current-steering DAC leaf.

Two benches:

  dc    -- all 2^N codes at a fixed DEM pointer.  Cells are ideal current
           sources with a per-cell gain error and a finite output resistance,
           which is the right level for a linearity/DEM study: the switching
           and segmentation are what is being verified, not the MOS I-V.
  cell  -- one unit cell built from PDK devices (cascoded PMOS mirror).  Gives
           the output resistance and the dI/I sensitivity to a Vth offset that
           the dc bench takes as inputs.

Usage:
    ./gen_csteer.py --bench dc   [--pointer 0] [--mismatch 0.018]
    ./gen_csteer.py --bench cell

The per-cell errors are written to build/cells.json so measure.py can compute
the DEM-averaged linearity from exactly the same numbers.
"""
from __future__ import annotations

import argparse
import json
import os
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def load_cfg():
    try:
        import yaml
    except ImportError:  # pragma: no cover
        sys.exit("PyYAML is required: pip install pyyaml")
    with open(ROOT / "csteer.yaml") as f:
        return yaml.safe_load(f)


def pdk_root(cfg, pdk: str, override: str | None) -> Path:
    if override:
        return Path(override)
    fam = {"gf180": ("gf180mcu", "gf180mcuA"),
           "sky130": ("sky130", "sky130A")}.get(pdk)
    if fam is None:
        sys.exit(f"unsupported pdk {pdk}")
    base = Path(os.path.expanduser(f"~/.ciel/ciel/{fam[0]}/versions"))
    if not base.is_dir():
        sys.exit(f"{base} not found; pass --pdk-root")
    ver = sorted(p.name for p in base.iterdir() if p.is_dir())[-1]
    return base / ver / fam[1]


def models(cfg, pdk: str, root: Path, temp: float, corner: str = "tt") -> str:
    p = cfg["pdk"][pdk]
    libdir = root / "libs.tech" / "ngspice"
    lib = libdir / p["model_lib"]
    if not lib.is_file():
        sys.exit(f"model library not found: {lib}")
    if pdk == "gf180":
        libs = ["typical"] if corner == "tt" else [corner]
    else:
        libs = ["tt"] if corner == "tt" else [corner]
    lines = [f'.lib "{lib}" ' + s for s in libs]
    if p.get("design_file"):
        lines.append(f'.include "{libdir / p["design_file"]}"')
    lines.append(f".temp {temp}")
    return "\n".join(lines)


def cells(cfg, mismatch: float, seed: int, pointer: int) -> tuple[list[str], dict]:
    """Ideal current cells with gain error and finite ro.

    There are 15 unary cells, so DWA has 15 pointer states (not 16): the cell
    at distance d from the pointer is selected when d is below the number of
    active unary cells.  With `pointer` fixed the distance is a constant, so
    the switch predicate is one comparison per cell.
    """
    nu = int(cfg["unary_bits"])
    nb = int(cfg["binary_bits"])
    n_unary = 2 ** nu - 1
    i_lsb = cfg["i_lsb_ua"] * 1e-6
    i_unit = cfg["i_unit_ua"] * 1e-6
    ro_u = cfg["ro_unit"]
    vdd = cfg["vdd"]
    rng = random.Random(seed)
    errs = {"unary": [], "binary": [], "sigma": mismatch, "pointer": pointer}

    out = [
        f"* {n_unary} unary cells of {i_unit*1e6:.3g} uA + {nb} binary cells",
        "* B-source cell: I = Icell*(1+e)*sel - v(out)/ro*sel",
        f"Bnu nu 0 V = floor((v(code)+0.5)/{2**nb})",
    ]
    for j in range(n_unary):
        e = rng.gauss(0.0, mismatch) if mismatch else 0.0
        errs["unary"].append(e)
        d = (j - pointer) % n_unary
        # selected iff d < n_unary_active, i.e. nu > d + 0.5
        out.append(f"Bsu{j} su{j} 0 V = {vdd}*(v(nu) > {d + 0.5})")
        i = i_unit * (1.0 + e)
        out.append(
            f"Bu{j} 0 out I = ({i:.12g}*v(su{j})/{vdd})"
            f" - (v(out)/{ro_u}*v(su{j})/{vdd})")

    for k in range(nb):
        w = 2 ** k
        ro_b = ro_u / w
        sig = mismatch * (w ** 0.5) if (mismatch and cfg["binary_sigma_scale"]) else mismatch
        e = rng.gauss(0.0, sig) if mismatch else 0.0
        errs["binary"].append(e)
        out.append(
            f"Bs{k} sb{k} 0 V = {vdd}*(floor((v(code)+0.5)/{w})"
            f"-2*floor((v(code)+0.5)/{2*w}))")
        i = i_lsb * w * (1.0 + e)
        out.append(
            f"Bb{k} 0 out I = ({i:.12g}*v(sb{k})/{vdd})"
            f" - (v(out)/{ro_b}*v(sb{k})/{vdd})")

    return out, errs


def bench_dc(cfg, dat: str, pointer: int, mismatch: float, seed: int,
             riv: float = 0.0) -> tuple[str, dict]:
    """Virtual-ground bench by default; `riv` switches to a passive I-V.

    A current DAC is characterised into 0 V, which is what an opamp I-V
    presents.  With a passive resistor the cell output conductance becomes a
    code-dependent gain error, so both are useful and both are reported.
    """
    bits = int(cfg["bits"])
    vdd = cfg["vdd"]
    body, errs = cells(cfg, mismatch, seed, pointer)
    out = ["* bench: DC sweep of all codes at a fixed DEM pointer",
           f"Vdd vdd 0 {vdd}", "Vcode code 0 0", ""]
    out += body
    out.append("")
    if riv:
        out.append(f"* passive I-V: the ro term now loads the output")
        out.append(f"Riv out 0 {riv}")
        probe = "v(out)"
    else:
        out.append("* virtual ground: i(Vout) is the output current")
        out.append("Vout out 0 0")
        probe = "i(Vout)"
    out += [".control", "set wr_singlescale", "set wr_vecnames",
            f"dc Vcode 0 {2**bits - 1} 1",
            f"wrdata {dat} v(code) {probe}", ".endc"]
    return "\n".join(out), errs


def bench_cell(cfg, pdk: str, dat: str, voff: float) -> str:
    """One unit cell: cascoded PMOS mirror, plus its bias branches."""
    p = cfg["pdk"][pdk]
    vdd = cfg["vdd"]
    w, l = cfg["cell_w"], cfg["cell_l"]
    cw, cl = cfg["casc_w"], cfg["casc_l"]
    i_u = cfg["i_unit_ua"]
    return "\n".join([
        "* unit current cell with a cascoded PMOS mirror (bias network not included)",
        f"Vdd vdd 0 {vdd}",
        "* mirror bias: Iref into a diode-connected device sets Vbp",
        f"Iref vbp 0 {i_u}u",
        f"M1 vbp vbp vdd vdd {p['pfet']} w={w}u l={l}u",
        "* cascode gate bias: ideal source here; the production cell needs a",
        "* wide-swing cascode bias generator (see README, class-C layout note).",
        "* vcp = 1.5 V leaves the mirror device in saturation at 16 uA.",
        "Vcp vcp 0 1.5",
        "* the cell under test, with an optional Vth offset in the gate lead",
        f"Voff vbp2 vbp dc {voff}",
        f"Mcell n1 vbp2 vdd vdd {p['pfet']} w={w}u l={l}u",
        f"Mcasc out vcp n1 vdd {p['pfet']} w={cw}u l={cl}u",
        "* sweep the output node; the flat part of I(Vout) gives ro",
        "Vout out 0 0",
        ".control",
        "set wr_singlescale",
        "set wr_vecnames",
        "dc Vout 30m 3.2 10m",
        f"wrdata {dat} v(out) i(Vout)",
        ".endc",
        ".end",
    ])


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pdk", default="gf180", choices=["gf180", "sky130"])
    ap.add_argument("--bench", default="dc", choices=["dc", "cell"])
    ap.add_argument("--pdk-root", default=None)
    ap.add_argument("--temp", type=float, default=25.0)
    ap.add_argument("--corner", default="tt")
    ap.add_argument("--pointer", type=int, default=0)
    ap.add_argument("--mismatch", type=float, default=0.0)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--voff", type=float, default=0.0)
    ap.add_argument("--out", default=None)
    ap.add_argument("--dat", default=None)
    ap.add_argument("--riv", type=float, default=0.0,
                    help="terminate into a resistor instead of virtual ground")
    ap.add_argument("--force", action="store_true")
    a = ap.parse_args()

    cfg = load_cfg()
    pdk_cfg = cfg["pdk"][a.pdk]
    if pdk_cfg.get("models_ok") is False and not a.force:
        sys.exit(f"error: {a.pdk} pre-layout models are not usable here:\n"
                 f"       {pdk_cfg.get('models_blocker', 'unknown blocker')}")

    root = pdk_root(cfg, a.pdk, a.pdk_root)
    (ROOT / "build").mkdir(exist_ok=True)
    dat = str(Path(a.dat) if a.dat else ROOT / "build" / f"{a.bench}.dat")

    if a.bench == "dc":
        body, errs = bench_dc(cfg, dat, a.pointer, a.mismatch, a.seed, a.riv)
        text = "\n".join([
            f"* Current-steering DAC, {cfg['bits']} bit, {a.pdk}, dc bench",
            "* Generated by analog/csteer/gen_csteer.py -- do not edit.",
            models(cfg, a.pdk, root, a.temp, a.corner),
            body, ".end", ""])
        (ROOT / "build" / "cells.json").write_text(
            json.dumps(errs, indent=1) + "\n")
    else:
        text = "\n".join([
            f"* Current-steering unit cell, {a.pdk}, device bench",
            "* Generated by analog/csteer/gen_csteer.py -- do not edit.",
            models(cfg, a.pdk, root, a.temp, a.corner),
            bench_cell(cfg, a.pdk, dat, a.voff), ""])

    out = Path(a.out) if a.out else ROOT / "build" / f"csteer_{a.bench}.spice"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text)
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
