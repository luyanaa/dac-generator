#!/usr/bin/env python3
"""Generate the pre-layout SPICE netlist for the resistor-string DAC leaf.

Schematic-level only: 255 PDK poly units in series and 255 transmission gates
arranged as an 8-level binary tree, so the same on-resistance and temperature
behaviour as the layout is exercised.  Two benches:

  dc    -- all 2^N codes in one DC sweep, for INL/DNL (tree included)
  tran  -- staircase of code transitions, for settling

Usage:
    ./gen_string.py --pdk gf180 --bench dc   [--out build/string_dc.spice]
    ./gen_string.py --pdk gf180 --bench tran [--out build/string_tran.spice]

Options of note:
    --rtg OHM    replace the MOS tree with fixed series resistors of OHM each
                 (switch-resistance sensitivity sweep, no devices needed)
    --mismatch S per-unit length sigma, applied explicitly
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent

_MIS = {"sigma": 0.0, "rng": None}


def load_cfg():
    try:
        import yaml
    except ImportError:  # pragma: no cover
        sys.exit("PyYAML is required: pip install pyyaml")
    with open(ROOT / "string.yaml") as f:
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
    if p.get("design_file"):
        lines.append(f'.include "{libdir / p["design_file"]}"')
    lines.append(f".temp {temp}")
    return "\n".join(lines)


def unit_l(cfg, pdk: str) -> float:
    p = cfg["pdk"][pdk]
    return float(p.get("unit_l", cfg["unit_l"]))


def jitter(length: float) -> float:
    if not _MIS["sigma"]:
        return length
    return length * (1.0 + _MIS["rng"].gauss(0.0, _MIS["sigma"]))


def res(cfg, pdk: str, name: str, a: str, b: str, gnd: str, length: float) -> str:
    p = cfg["pdk"][pdk]
    return (f"X{name} {a} {b} {gnd} {p['res_subckt']} "
            f"{p['res_w_param']}={cfg['unit_w']}u "
            f"{p['res_l_param']}={jitter(length):.6f}u")


def tree(cfg, pdk: str, rtg: float | None) -> list[str]:
    """255 units + an 8-level binary TG tree.  Tap k is at k * Ru."""
    bits = int(cfg["bits"])
    n_taps = 2 ** bits
    u = unit_l(cfg, pdk)
    p = cfg["pdk"][pdk]
    out = [f"* string: {n_taps - 1} units of W={cfg['unit_w']}u L={u}u",
           "Vref vref 0 {vref}", "Vbot vss 0 0"]

    # The string itself: tap k sits below unit k; the top tap is vref.
    taps = ["vss"] + [f"t{k}" for k in range(1, n_taps - 1)] + ["vref"]
    for k in range(n_taps - 1):
        out.append(res(cfg, pdk, f"rs{k}", taps[k + 1], taps[k], "vss", u))

    if rtg is None:
        out += [
            "* transmission gate (3.3 V devices, uniform at every level)",
            ".subckt tg a b c cn vdd vss",
            f"Xn a c b vss {p['nfet']} w={cfg['tg_wn']}u l={cfg['tg_l']}u",
            f"Xp a cn b vdd {p['pfet']} w={cfg['tg_wp']}u l={cfg['tg_l']}u",
            ".ends tg",
        ]

    nodes = taps
    tg_idx = 0
    for lvl in range(bits):
        new = []
        for k in range(len(nodes) // 2):
            mid = f"out" if (lvl == bits - 1 and k == 0) else f"n{lvl}_{k}"
            a, b = nodes[2 * k], nodes[2 * k + 1]
            if rtg is None:
                # bit = 0 selects the lower tap of the pair
                out.append(f"Xt{tg_idx} {a} {mid} bn{lvl} b{lvl} vdd vss tg")
                out.append(f"Xt{tg_idx + 1} {b} {mid} b{lvl} bn{lvl} vdd vss tg")
            else:
                # Behavioural switch: conductance rtg when the control is on,
                # zero when off.  A plain resistor would short the pair.
                on = f"bn{lvl}"
                on2 = f"b{lvl}"
                out.append(
                    f"Bt{tg_idx} {a} {mid} I = (v({a})-v({mid}))*{1.0/rtg:.9g}"
                    f"*v({on})/{cfg['vdd']}")
                out.append(
                    f"Bt{tg_idx + 1} {b} {mid} I = (v({b})-v({mid}))*{1.0/rtg:.9g}"
                    f"*v({on2})/{cfg['vdd']}")
            tg_idx += 2
            new.append(mid)
        nodes = new
    assert len(nodes) == 1, len(nodes)
    return out


def bench_dc(cfg, pdk: str, dat: str | None = None) -> str:
    bits = int(cfg["bits"])
    vdd = cfg["vdd"]
    out = ["* bench: DC sweep of all codes (one bias point per code)"]
    out.append(f"Vdd vdd 0 {vdd}")
    out.append("Vcode code 0 0")
    for i in range(bits):
        out.append(
            f"Bb{i} b{i} 0 V = {vdd}*(floor((v(code)+0.5)/{2**i})"
            f"-2*floor((v(code)+0.5)/{2**(i+1)}))"
        )
        out.append(f"Bbn{i} bn{i} 0 V = {vdd}-v(b{i})")
    # Ideal unity-gain follower: separates string/tree error from the buffer.
    out.append(f"Ebuf vout 0 out 0 {cfg['buf_gain']}")
    out.append(f"Rout vout 0 {cfg['load_r']}")
    out.append(".control")
    out.append("set wr_singlescale")
    out.append("set wr_vecnames")
    out.append(f"dc Vcode 0 {2**bits - 1} 1")
    out.append(f"wrdata {dat or 'build/dc.dat'} v(code) v(out) v(vout)")
    out.append(".endc")
    return "\n".join(out)


def bench_tran(cfg, pdk: str, dat: str | None = None) -> str:
    bits = int(cfg["bits"])
    vdd = cfg["vdd"]
    n = 2 ** bits - 1
    steps = [0, 1, 2, 3, 127, 128, 129, 254, 255, 0]
    step_us = 10.0
    ramp_ns = 20.0
    out = ["* bench: staircase transient for settling"]
    out.append(f"Vdd vdd 0 {vdd}")
    pts = [f"0 {steps[0]}"]
    for k in range(1, len(steps)):
        t0 = k * step_us * 1e3
        pts.append(f"{t0 - ramp_ns:.1f}n {steps[k-1]}")
        pts.append(f"{t0:.1f}n {steps[k]}")
    out.append("Vcode code 0 PWL(" + " ".join(pts) + ")")
    for i in range(bits):
        out.append(
            f"Bb{i} b{i} 0 V = {vdd}*(floor((v(code)+0.5)/{2**i})"
            f"-2*floor((v(code)+0.5)/{2**(i+1)}))"
        )
        out.append(f"Bbn{i} bn{i} 0 V = {vdd}-v(b{i})")
    out.append(f"Ebuf vout 0 out 0 {cfg['buf_gain']}")
    out.append(f"Rbuf vout out {cfg['buf_rout']}")
    out.append(f"Cload vout 0 {cfg['load_c_pf']}p")
    out.append(f"Rload vout 0 {cfg['load_r']}")
    out.append(f"Ctap out 0 {cfg.get('tap_c_pf', 0.06)}p")
    out.append(".control")
    out.append("set wr_singlescale")
    out.append("set wr_vecnames")
    out.append("option reltol=1e-3 vntol=1e-7 abstol=1e-13")
    out.append(f"tran 20n {len(steps) * step_us}u")
    out.append(f"wrdata {dat or 'build/tran.dat'} v(out) v(vout) v(code)")
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
    ap.add_argument("--rtg", type=float, default=None,
                    help="model each tree switch as a fixed resistor instead")
    ap.add_argument("--mismatch", type=float, default=0.0)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--unit-l", type=float, default=None,
                    help="override the string unit length (um)")
    ap.add_argument("--tg-wn", type=float, default=None)
    ap.add_argument("--tg-wp", type=float, default=None)
    a = ap.parse_args()

    cfg = load_cfg()
    if a.unit_l:
        cfg["unit_l"] = a.unit_l
        cfg["pdk"][a.pdk].pop("unit_l", None)
    if a.tg_wn:
        cfg["tg_wn"] = a.tg_wn
    if a.tg_wp:
        cfg["tg_wp"] = a.tg_wp
    pdk_cfg = cfg["pdk"][a.pdk]
    if pdk_cfg.get("models_ok") is False and not a.force:
        sys.exit(f"error: {a.pdk} pre-layout models are not usable here:\n"
                 f"       {pdk_cfg.get('models_blocker', 'unknown blocker')}")
    if a.mismatch:
        import random
        _MIS["sigma"] = a.mismatch
        _MIS["rng"] = random.Random(a.seed)

    root = pdk_root(cfg, a.pdk, a.pdk_root)
    (ROOT / "build").mkdir(exist_ok=True)

    lines = [
        f"* Resistor-string DAC, {cfg['bits']} bit, {a.pdk}, {a.bench} bench",
        "* Generated by analog/string/gen_string.py -- do not edit.",
        models(cfg, a.pdk, root, a.corner, a.temp),
        f".param vdd={cfg['vdd']}",
        f".param vref={cfg['vref']}",
        "",
        *tree(cfg, a.pdk, a.rtg),
        "",
        (bench_dc if a.bench == "dc" else bench_tran)(cfg, a.pdk, a.dat),
        ".end",
        "",
    ]
    text = "\n".join(lines)
    out = Path(a.out) if a.out else ROOT / "build" / f"string_{a.bench}.spice"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text)
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
