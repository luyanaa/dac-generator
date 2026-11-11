#!/usr/bin/env python3
"""Cross-check the CDAC charge model against the full MOS circuit.

    ./xcheck_mos.py [--bits 8] [--codes 0,1,64,128,192,255] [--brief]

The behavioral model (`gen_cdac.side_top`) uses the measured 2-D small-signal
tables Cgg(Vg,Vb), Cgb(Vg,Vb) and the charge state function
Q(vg,vb)=int Cgg dvg + int Cgb(0,.) dvb.  This builds the *device-level*
equivalent - 2^N unit MOSCAPs (the same CAP_LEAF), ideal bottom-plate
switches, the top plate sampled at Vcm and then floated - runs a transient,
and compares the final top-plate voltage with the model at the same code.

`--ramps` measures Q(vg,vb) at the four corners by integrating the gate
displacement current while vg or vb is ramped, which both validates the
tables and proves the device charge is a state function (path independence).

A mismatch here means the table/integral model is not the device charge; it
is the audit's "cross-check against the full MOS SPICE circuit" step.
"""
from __future__ import annotations

import argparse
import math
import subprocess
import sys
from pathlib import Path

import gen_cdac as g

ROOT = g.ROOT
BUILD = ROOT / "build"


def die(msg: str) -> None:
    print(f"error: {msg}", file=sys.stderr)
    raise SystemExit(2)


def deck(cfg: dict, model_deck: Path, bits: int, code: int,
         tag: str = "xcheck") -> str:
    vh = float(cfg["vrefh"])
    vl = float(cfg["vrefl"])
    vcm = float(cfg["vcm"])
    vin = float(cfg.get("vin_dc", vcm))
    leaf = g.CAP_LEAF.format(wn=cfg["cu_wn_um"], wp=cfg["cu_wp_um"],
                             l=cfg["cu_l_um"])
    n = 1 << bits
    lines = [
        "* CDAC device-level charge cross-check, %d-bit code %d" % (bits, code),
        leaf,
        f".include {model_deck}",
        "Vin vin 0 %.6f" % vin,
        "Vcm vcm 0 %.6f" % vcm,
        "Vnw vnw 0 %.6f" % (2.0 * vcm),
        "Vpw vpw 0 0",
        "Rleak top 0 1e12",
        # sample 0..20 ns, convert 20.1..40 ns
        "Vph ph 0 PWL(0 1 20n 1 20.1n 0)",
        "Vphc phc 0 PWL(0 0 20n 0 20.1n 1)",
        ".model SW1 SW(Ron=1 Roff=1e12 Vt=0.5 Vh=0)",
        "St top vcm ph 0 SW1",
    ]
    idx = 0
    for k in range(bits):
        bit = (code >> k) & 1
        vref = vh if bit else vl
        for _ in range(1 << k):
            lines += [
                f"Vr{idx} vr{idx} 0 {vref:.6f}",
                f"Ss{idx} b{idx} vin ph 0 SW1",
                f"Sc{idx} b{idx} vr{idx} phc 0 SW1",
                f"Xc{idx} top b{idx} vnw vpw CDAC_CAP_UNIT",
            ]
            idx += 1
    # dummy unit: bottom held at Vcm, exactly as the model's dummy_mode=vcm
    lines += [
        f"Vrd vr{idx} 0 {vcm:.6f}",
        f"Xc{idx} top vr{idx} vnw vpw CDAC_CAP_UNIT",
        ".tran 10p 40n",
        ".control",
        "run",
        f"wrdata {BUILD / (tag + '.dat')} v(top)",
        ".endc",
        ".end",
    ]
    if idx + 1 != n:
        die(f"unit count {idx + 1} != {n}")
    return "\n".join(lines) + "\n"


def final_top(dat: Path) -> float:
    rows = []
    for ln in dat.read_text().splitlines():
        f = ln.split()
        if len(f) >= 2:
            try:
                rows.append((float(f[0]), float(f[1])))
            except ValueError:
                pass
    if not rows:
        die("no transient rows")
    return rows[-1][1]


def ramp_deck(cfg: dict, deck_path: Path, vg0: float, vb0: float,
              which: str, tag: str) -> str:
    leaf = g.CAP_LEAF.format(wn=cfg["cu_wn_um"], wp=cfg["cu_wp_um"],
                             l=cfg["cu_l_um"])
    if which == "g":
        vg = f"PWL(0 {vg0} 50n {vg0} 250n {vg0 + 1.8})"
        vb = f"{vb0}"
    else:
        vg = f"{vg0}"
        vb = f"PWL(0 {vb0} 50n {vb0} 250n {vb0 + 1.8})"
    return f"""* CDAC unit cap charge ramp, {which} at ({vg0},{vb0})
{leaf}.include {deck_path}
Vg vsh 0 {vg}
Vb fl 0 {vb}
Vnw vnw 0 {2.0 * float(cfg['vcm']):.6f}
Vpw vpw 0 0
Xc vsh fl vnw vpw CDAC_CAP_UNIT
.tran 0.5n 300n
.control
run
wrdata {BUILD / (tag + '.dat')} i(vg)
.endc
.end
"""


def ramps(cfg: dict) -> int:
    """Validate the 2-D tables and path independence with device ramps."""
    deck_path = g.ensure_deck(cfg)
    cap = g.CapModel(cfg, "moscap")
    # all ramps start at 0 in the ramped coordinate and stay inside 0..1.8 V
    pts = [(0.0, 0.0, "g"), (0.0, 1.8, "g"),
           (0.0, 0.0, "b"), (1.8, 0.0, "b"),
           (0.0, 0.9, "g"), (0.9, 0.0, "b")]
    got = {}
    for vg0, vb0, which in pts:
        tag = f"ramp_{which}_{vg0:g}_{vb0:g}".replace(".", "p")
        (BUILD / (tag + ".sp")).write_text(
            ramp_deck(cfg, deck_path, vg0, vb0, which, tag))
        r = subprocess.run(["ngspice", "-b", str(BUILD / (tag + ".sp"))],
                           cwd=BUILD, capture_output=True, text=True,
                           timeout=1800)
        (BUILD / (tag + ".log")).write_text(r.stdout + r.stderr)
        if r.returncode:
            die(f"ngspice failed for ramp {which} at ({vg0},{vb0})")
        rows = []
        for ln in (BUILD / (tag + ".dat")).read_text().splitlines():
            f = ln.split()
            if len(f) >= 2:
                try:
                    rows.append((float(f[0]), float(f[1])))
                except ValueError:
                    pass
        q = 0.0
        for (t0, i0), (t1, i1) in zip(rows, rows[1:]):
            if t1 > 50e-9 and t0 < 250e-9:
                q += 0.5 * (i0 + i1) * (t1 - t0)
        got[(vg0, vb0, which)] = -q * 1e15
    print("-- device charge ramps (fC)")
    worst = 0.0
    for (vg0, vb0, which), v in sorted(got.items()):
        if which == "g":
            m = cap.charge(1.8, vb0) - cap.charge(0.0, vb0)
        else:
            m = cap.charge(vg0, 1.8) - cap.charge(vg0, 0.0)
        d = m - v
        worst = max(worst, abs(d))
        print(f"   {'Vg' if which == 'g' else 'Vb'} 0->1.8 at "
              f"({vg0:.1f},{vb0:.1f}): device {v:+.4f}  model {m:+.4f}  "
              f"delta {d:+.4f} fC")
    a = got[(0.0, 0.0, "b")] + got[(0.0, 1.8, "g")]
    b = got[(0.0, 0.0, "g")] + got[(1.8, 0.0, "b")]
    print(f"-- path independence: vb->vg {a:+.4f}  vg->vb {b:+.4f}  "
          f"difference {a - b:+.4f} fC")
    print(f"worst |model - device| = {worst:.4f} fC")
    return 0 if worst < 0.05 and abs(a - b) < 0.05 else 1


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--bits", type=int, default=8)
    ap.add_argument("--codes", default="0,1,64,128,192,255")
    ap.add_argument("--brief", action="store_true")
    ap.add_argument("--ramps", action="store_true",
                    help="validate Q(vg,vb) with device charge ramps")
    a = ap.parse_args(argv)
    cfg = g.load_cfg()
    if a.ramps:
        return ramps(cfg)
    cap = g.CapModel(cfg, "moscap")
    model_deck = g.ensure_deck(cfg)
    vh, vl, vcm = float(cfg["vrefh"]), float(cfg["vrefl"]), float(cfg["vcm"])
    vin = float(cfg.get("vin_dc", vcm))
    factors = [1.0] * (1 << a.bits)
    lsb = (vh - vl) / (1 << a.bits)
    codes = [int(c) for c in a.codes.split(",") if c != ""]
    worst = 0.0
    for code in codes:
        tag = f"xcheck_{a.bits}_{code}"
        net = deck(cfg, model_deck, a.bits, code, tag)
        (BUILD / (tag + ".sp")).write_text(net)
        r = subprocess.run(["ngspice", "-b", str(BUILD / (tag + ".sp"))],
                           cwd=BUILD, capture_output=True, text=True,
                           timeout=1800)
        (BUILD / (tag + ".log")).write_text(r.stdout + r.stderr)
        if r.returncode:
            die(f"ngspice failed for code {code} (build/{tag}.log)")
        vsp = final_top(BUILD / (tag + ".dat"))
        vmod, _ = g.side_top(cfg, cap, code, False, factors, a.bits,
                             vh, vl, vcm, vin, str(cfg.get("dummy_mode", "vcm")),
                             float(cfg["vrefl"]))
        d = (vsp - vmod) * 1e3
        worst = max(worst, abs(d))
        if a.brief:
            print(f"code {code:3d}: mos {vsp:.6f} V  model {vmod:.6f} V  "
                  f"delta {d:+.3f} mV ({d/1e3/lsb:+.4f} LSB)")
        else:
            print(f"-- code {code}")
            print(f"   MOS   : {vsp:.6f} V")
            print(f"   model : {vmod:.6f} V")
            print(f"   delta : {d:+.3f} mV = {d/1e3/lsb:+.4f} LSB")
    print(f"worst |delta| = {worst:.3f} mV = {worst/1e3/lsb:.4f} LSB")
    return 0


if __name__ == "__main__":
    sys.exit(main())
