#!/usr/bin/env python3
"""Wrapper bias check: 16.03 uA from a 1.66 kohm rppd resistor.

    python3 wrapper_bias.py            # DC + carry transient
    python3 wrapper_bias.py --dc       # operating point only

The row is the extracted `build/pex.spice` (1022 devices + 8421 caps).  The
row's `iref` input is a current **sink** from vcp to ground; the wrapper uses
a `rppd` resistor from vcp to ground instead of an ideal current source.  The
diode-connected replica self-biases at vcp ~26.7 mV, so the resistor value is
only vcp/16.032uA = 1.66 kohm (6.4 squares at W=1 um), not the 73 kohm a
vdd-to-vcp source would need.  The 470 pF/100 pF decoupling and the 37.5 ohm
+ 2 pF output load are the wrapper components.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import signoff as so

HERE = Path(__file__).resolve().parent
BUILD = HERE / "build"
VDD = so.VDD
IREF = so.IREF_UA * 1e-6
RL = 37.5
RREF = 1660.0  # ohm; 1660/260 = 6.38 rppd squares


def body() -> list[str]:
    return [ln for ln in (BUILD / "pex.spice").read_text().splitlines()
            if not ln.strip().startswith((".subckt", ".ends"))]


def head(lib: Path) -> list[str]:
    return (["* wrapper bias: vcp->ground rppd resistor + 470/100 pF",
             f'.lib "{lib}" mos_tt'] + body() +
            [f"Vdd vdd 0 {VDD:g}", "Vss vss 0 0",
             f"Rref vcp 0 {RREF:.1f}", "Cvcp vcp 0 470p",
             "Cvbp vbp 0 100p", "Vdump idump 0 0",
             f"Rl iout 0 {RL}", "Cl iout 0 2p"])


def gates(code: int) -> list[str]:
    out = []
    for j, t in enumerate(so.cell_tags()):
        on = (code >> so.cell_bit(j)) & 1
        out += [f"Vd_{t} d_{t} 0 {VDD if on else 0}",
                f"Vdb_{t} db_{t} 0 {0 if on else VDD}"]
    return out


def run_deck(path: Path) -> subprocess.CompletedProcess:
    pdk = so.find_pdk()
    env = dict(os.environ)
    env["PDK_ROOT"] = str(pdk.parent)
    env["PDK"] = pdk.name
    return subprocess.run(["ngspice", "-b", str(path)], cwd=BUILD, env=env,
                          capture_output=True, text=True, timeout=7200)


def grab(txt: str, name: str) -> float:
    m = re.search(rf"{name}\s*=\s*([-+0-9.eE]+)", txt, re.I)
    if not m:
        raise SystemExit(f"ngspice produced no {name}")
    return float(m.group(1))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dc", action="store_true")
    a = ap.parse_args(argv)
    lib = so.find_pdk() / "libs.tech/ngspice/models/cornerMOSlv.lib"

    op_deck = head(lib) + gates(255) + [
        ".op", ".control", "run", "print i(Vdd)",
        "print v(iout) v(vbp) v(vcp)", ".endc", ".end"]
    op_path = BUILD / "wrapper_bias_dc.spice"
    op_path.write_text("\n".join(op_deck) + "\n")
    r = run_deck(op_path)
    (BUILD / "wrapper_bias_dc.log").write_text(r.stdout + r.stderr)
    if r.returncode:
        print(r.stdout[-2000:]); print(r.stderr[-2000:]); return 1
    txt = r.stdout + r.stderr
    i_vdd = abs(grab(txt, r"i\(vdd\)"))
    iout = grab(txt, r"v\(iout\)")
    vbp = grab(txt, r"v\(vbp\)")
    vcp = grab(txt, r"v\(vcp\)")
    res = {
        "rref_ohm": RREF,
        "rppd_squares": RREF / 260.0,
        "i_vdd_mA": round(i_vdd * 1e3, 4),
        "i_cell_uA": round(i_vdd / 255.0 * 1e6, 3),
        "vcp_V": round(vcp, 6),
        "vbp_V": round(vbp, 6),
        "iout_mV": round(iout * 1e3, 4),
        "code": 255,
        "log": str(BUILD / "wrapper_bias_dc.log"),
    }
    res["ok"] = (abs(i_vdd * 1e3 - 4.087) < 0.03
                 and 0.0 < vcp < 0.1 and 0.55 < vbp < 0.75
                 and abs(iout * 1e3 - 153.3) < 1.0)
    if a.dc:
        (BUILD / "wrapper_bias.json").write_text(json.dumps(res, indent=2) + "\n")
        print(json.dumps(res, indent=2))
        return 0 if res["ok"] else 1

    tr = head(lib)
    t0, edge, skew = 1e-9, 20e-12, 25e-12
    for j, t in enumerate(so.cell_tags()):
        k = so.cell_bit(j)
        g0 = VDD if (127 >> k) & 1 else 0.0
        g1 = VDD if (128 >> k) & 1 else 0.0
        tt = t0 + k * skew
        tr += [f"Vd_{t} d_{t} 0 PWL(0 {g0} {tt} {g0} {tt + edge} {g1})",
               f"Vdb_{t} db_{t} 0 PWL(0 {VDD - g0} {tt} {VDD - g0} "
               f"{tt + edge} {VDD - g1})"]
    tr += [".tran 5p 40n", ".control", "run",
           f"wrdata {BUILD/'wrapper_carry.dat'} v(iout) v(vbp) v(vcp)",
           ".endc", ".end"]
    tr_path = BUILD / "wrapper_carry.spice"
    tr_path.write_text("\n".join(tr) + "\n")
    r = run_deck(tr_path)
    (BUILD / "wrapper_carry.log").write_text(r.stdout + r.stderr)
    if r.returncode:
        print(r.stdout[-2000:]); print(r.stderr[-2000:]); return 1
    # Compare the 40 ns value with a separate code-128 operating point (the
    # .op above is code 255).  The PWL starts at 127, so the first transient
    # sample is one LSB below the target and is not the reference.
    op128 = head(lib) + gates(128) + [
        ".op", ".control", "run", "print v(iout) v(vbp) v(vcp)",
        ".endc", ".end"]
    p128 = BUILD / "wrapper_bias_128.spice"
    p128.write_text("\n".join(op128) + "\n")
    r128 = run_deck(p128)
    (BUILD / "wrapper_bias_128.log").write_text(r128.stdout + r128.stderr)
    if r128.returncode:
        print(r128.stdout[-2000:]); print(r128.stderr[-2000:]); return 1
    txt128 = r128.stdout + r128.stderr
    iout0 = grab(txt128, r"v\(iout\)")
    vbp0 = grab(txt128, r"v\(vbp\)")
    vcp0 = grab(txt128, r"v\(vcp\)")
    rows = []
    for ln in (BUILD / "wrapper_carry.dat").read_text().splitlines():
        f = ln.split()
        if len(f) >= 6:
            try:
                rows.append([float(v) for v in f[:6]])
            except ValueError:
                pass
    if not rows:
        raise SystemExit("no wrapper_carry.dat samples")
    # wrdata: t, iout, t, vbp, t, vcp
    t, iout_end, vbp_end, vcp_end = (rows[-1][0], rows[-1][1],
                                     rows[-1][3], rows[-1][5])
    lsb = IREF * RL
    settle = abs(iout_end - iout0) / lsb
    res["carry"] = {
        "t_ns": round(t * 1e9, 3),
        "iout_mV": round(iout_end * 1e3, 4),
        "iout_dc_mV": round(iout0 * 1e3, 4),
        "settle_lsb": round(settle, 4),
        "vbp_mV_drift": round((vbp_end - vbp0) * 1e3, 4),
        "vcp_mV_drift": round((vcp_end - vcp0) * 1e3, 4),
        "log": str(BUILD / "wrapper_carry.log"),
    }
    res["ok"] = res["ok"] and settle < 0.5
    (BUILD / "wrapper_bias.json").write_text(json.dumps(res, indent=2) + "\n")
    print(json.dumps(res, indent=2))
    return 0 if res["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
