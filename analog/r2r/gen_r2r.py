#!/usr/bin/env python3
"""Generate the pre-layout SPICE netlist for the R-2R DAC leaf.

The netlist is a *schematic-level* (no parasitics) description built only from
PDK devices, so it exercises the same on-resistance and temperature behaviour
as the layout will.  Two benches are emitted:

  dc    -- all 2^N codes in one DC sweep, for INL/DNL
  tran  -- a staircase of selected code transitions, for settling

Usage:
    ./gen_r2r.py --pdk gf180 --bench dc   [--out build/r2r_dc.spice]
    ./gen_r2r.py --pdk gf180 --bench tran [--out build/r2r_tran.spice]

The PDK paths are resolved from $PDK_ROOT (default: the newest installed
ciel version) unless --pdk-root is given.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent

# Per-instance resistor mismatch is applied as a multiplicative length error.
# gf180 reports mis_r = 0 in the SPICE model, so Monte Carlo cannot move a
# resistor ratio; this explicit perturbation is the only way to bound INL.
_MIS = {"sigma": 0.0, "rng": None}


def load_cfg():
    try:
        import yaml
    except ImportError:  # pragma: no cover
        sys.exit("PyYAML is required: pip install pyyaml")
    with open(ROOT / "r2r.yaml") as f:
        return yaml.safe_load(f)


def pdk_root(cfg, pdk: str, override: str | None) -> Path:
    if override:
        return Path(override)
    if pdk == "gf180":
        fam, name = "gf180mcu", "gf180mcuA"
    elif pdk == "sky130":
        fam, name = "sky130", "sky130A"
    else:
        sys.exit(f"unsupported pdk {pdk}")
    base = Path(os.path.expanduser(f"~/.ciel/ciel/{fam}/versions"))
    if not base.is_dir():
        sys.exit(f"{base} not found; pass --pdk-root")
    ver = sorted(p.name for p in base.iterdir() if p.is_dir())[-1]
    return base / ver / name


def models(cfg, pdk: str, root: Path, corner: str, temp: float) -> str:
    p = cfg["pdk"][pdk]
    libdir = root / "libs.tech" / "ngspice"
    lib = libdir / p["model_lib"]
    if not lib.is_file():
        sys.exit(f"model library not found: {lib}")
    if pdk == "gf180":
        mos = {"tt": "typical", "ff": "ff", "ss": "ss", "fs": "fs", "sf": "sf"}[corner]
        res = {"tt": "res_typical", "ff": "res_ff", "ss": "res_ss",
               "fs": "res_typical", "sf": "res_typical"}[corner]
        libs = [mos, res]
    else:
        libs = ["tt"] if corner == "tt" else [corner]
    lines = [f'.lib "{lib}" ' + s for s in libs]
    if p["design_file"]:
        lines.append(f'.include "{libdir / p["design_file"]}"')
    lines.append(f".temp {temp}")
    return "\n".join(lines)


def unit_geom(cfg, pdk: str) -> tuple[float, float]:
    p = cfg["pdk"][pdk]
    return float(p.get("unit_l", cfg["unit_l"])), float(p.get("trim_l", cfg["trim_l"]))


def res(cfg, pdk: str, name: str, a: str, b: str, gnd: str, length: float) -> str:
    p = cfg["pdk"][pdk]
    if _MIS["sigma"]:
        length *= 1.0 + _MIS["rng"].gauss(0.0, _MIS["sigma"])
    return (
        f"X{name} {a} {b} {gnd} {p['res_subckt']} "
        f"{p['res_w_param']}={cfg['unit_w']}u {p['res_l_param']}={length}u"
    )


def ladder(cfg, pdk: str) -> list[str]:
    """R-2R core.  n[bits-1] is the output node; n[0] is the LSB node."""
    n = int(cfg["bits"])
    unit, trim = unit_geom(cfg, pdk)
    gnd = "vss"
    out: list[str] = [f"* R-2R ladder: {n} bits, unit W={cfg['unit_w']}u L={unit}u"]

    def node(i: int) -> str:
        return "vout" if i == n - 1 else f"n{i}"

    # Series 1R between adjacent nodes, MSB-first.  The MSB node is the output,
    # so only bits-1 series resistors are needed.
    for i in range(n - 1, 0, -1):
        out.append(res(cfg, pdk, f"rs{i}", node(i), node(i - 1), gnd, unit))

    # 2R branch per bit: unit (driver side) + trimmed unit (node side).
    for i in range(n):
        out.append(res(cfg, pdk, f"ra{i}", f"d{i}", f"m{i}", gnd, unit))
        out.append(res(cfg, pdk, f"rb{i}", f"m{i}", node(i), gnd, trim))

    # LSB termination 2R to ground.
    out.append(res(cfg, pdk, "rta", "n0", "mt", gnd, unit))
    out.append(res(cfg, pdk, "rtb", "mt", gnd, gnd, trim))
    return out


def drivers(cfg, pdk: str) -> list[str]:
    p = cfg["pdk"][pdk]
    n = int(cfg["bits"])
    out = ["* bit drivers: non-inverting CMOS buffer, one per bit"]
    out += [
        ".subckt inv a y vdd vss",
        f"Xp y a vdd vdd {p['pfet']} w={cfg['drv_wp']}u l={cfg['drv_l']}u",
        f"Xn y a vss vss {p['nfet']} w={cfg['drv_wn']}u l={cfg['drv_l']}u",
        ".ends inv",
        ".subckt buf a y vdd vss",
        "X1 a t vdd vss inv",
        "X2 t y vdd vss inv",
        ".ends buf",
    ]
    for i in range(n):
        out.append(f"Xd{i} b{i} d{i} vdd vss buf")
    return out


def bench_dc(cfg, pdk: str, dat: str | None = None) -> str:
    n = int(cfg["bits"])
    vdd = cfg["vdd"]
    out = ["* bench: DC sweep of all codes (one bias point per code)"]
    out.append(f"Vdd vdd 0 {vdd}")
    out.append("Vss vss 0 0")
    out.append("Vcode code 0 0")
    # Binary slice of the swept code; integer arithmetic only.
    for i in range(n):
        out.append(
            f"Bb{i} b{i} 0 V = {vdd}*(floor((v(code)+0.5)/{2**i})"
            f"-2*floor((v(code)+0.5)/{2**(i+1)}))"
        )
    out.append(".control")
    out.append("set wr_singlescale")
    out.append("set wr_vecnames")
    out.append(f"dc Vcode 0 {2**n - 1} 1")
    out.append(f"wrdata {dat or 'build/dc.dat'} v(code) v(vout)")
    out.append(".endc")
    return "\n".join(out)


def bench_tran(cfg, pdk: str, dat: str | None = None) -> str:
    n = int(cfg["bits"])
    vdd = cfg["vdd"]
    # Transitions that stress the ladder: LSB, mid major carry, MSB, full.
    steps = [0, 1, 2, 3, 127, 128, 254, 255, 0]
    step_us = 5.0
    ramp_ns = 10.0
    out = ["* bench: staircase transient for settling"]
    out.append(f"Vdd vdd 0 {vdd}")
    out.append("Vss vss 0 0")
    # Staircase: hold each code, then a 1 ns edge before the next step, so the
    # bit sources only switch at the edges instead of sliding through every
    # intermediate integer during a slow ramp.
    pts = [f"0 {steps[0]}"]
    for k in range(1, len(steps)):
        t0 = k * step_us * 1e3
        pts.append(f"{t0 - ramp_ns:.1f}n {steps[k-1]}")
        pts.append(f"{t0:.1f}n {steps[k]}")
    out.append("Vcode code 0 PWL(" + " ".join(pts) + ")")
    for i in range(n):
        out.append(
            f"Bb{i} b{i} 0 V = {vdd}*(floor((v(code)+0.5)/{2**i})"
            f"-2*floor((v(code)+0.5)/{2**(i+1)}))"
        )
    out.append(f"Rload vout 0 {cfg['load_r']}")
    out.append(f"Cload vout 0 {cfg['load_c_pf']}p")
    out.append(".control")
    out.append("set wr_singlescale")
    out.append("set wr_vecnames")
    out.append(f"tran 2n {len(steps) * step_us}u")
    out.append(f"wrdata {dat or 'build/tran.dat'} v(vout) v(code)")
    out.append(".endc")
    return "\n".join(out)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pdk", default="gf180", choices=["gf180", "sky130"])
    ap.add_argument("--bench", default="dc", choices=["dc", "tran"])
    ap.add_argument("--pdk-root", default=None)
    ap.add_argument("--corner", default="tt", choices=["tt", "ff", "ss", "fs", "sf"])
    ap.add_argument("--temp", type=float, default=25.0)
    ap.add_argument("--out", default=None)
    ap.add_argument("--dat", default=None)
    ap.add_argument("--mismatch", type=float, default=0.0,
                    help="per-unit resistor length sigma (relative)")
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--force", action="store_true",
                    help="emit a deck even if the PDK's models are known-bad")
    a = ap.parse_args()

    cfg = load_cfg()
    pdk_cfg = cfg["pdk"][a.pdk]
    if pdk_cfg.get("models_ok") is False and not a.force:
        sys.exit(f"error: {a.pdk} pre-layout models are not usable here:\n"
                 f"       {pdk_cfg.get('models_blocker', 'unknown blocker')}\n"
                 f"       geometry lives in r2r.yaml/README; use --force only "
                 f"to emit a deck you will not trust.")
    if a.mismatch:
        import random
        _MIS["sigma"] = a.mismatch
        _MIS["rng"] = random.Random(a.seed)
    root = pdk_root(cfg, a.pdk, a.pdk_root)
    (ROOT / "build").mkdir(exist_ok=True)

    lines = [
        f"* R-2R DAC, {cfg['bits']} bit, {a.pdk}, {a.bench} bench",
        "* Generated by analog/r2r/gen_r2r.py -- do not edit.",
        models(cfg, a.pdk, root, a.corner, a.temp),
        f".param vdd={cfg['vdd']}",
        "",
        *drivers(cfg, a.pdk),
        "",
        *ladder(cfg, a.pdk),
        "",
        (bench_dc if a.bench == "dc" else bench_tran)(cfg, a.pdk, a.dat),
        ".end",
        "",
    ]
    text = "\n".join(lines)
    out = Path(a.out) if a.out else ROOT / "build" / f"r2r_{a.bench}.spice"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text)
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
