#!/usr/bin/env python3
"""Compare the 8-cell Magic PEX netlist with the 8-cell schematic CDL.

    python3 block8_pex.py

The 8-cell block is the first 8 columns of the row (3 bits + the first cell
of bit 3 held off).  Magic PEX is run with the experimental tech copy whose
CT/V1 contact areas and poly/FET connection are fixed; this script drives
the named gate nets (`d_b0_0` ...), the 16 uA reference, the 37.5 ohm / 2 pF
load and compares the settled output of the PEX with the CDL at codes 0..7.
"""
import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
BUILD = HERE / "build"
MODELS = ("/grid/icsprout55-pdk/libs.tech/spice/foundry/ngspice/"
          "ICsprout_55LLULP1225_V1p1_hsp.lib")
N = 8
VDD = 1.2
IREF = 16e-6
RL = 37.5
CL = 2e-12
VCP_CAP = 220e-12


def tag(j):
    k = 0
    while j >= 2 ** (k + 1) - 1:
        k += 1
    return k, f"b{k}_{j - (2 ** k - 1)}"


def prep_pex():
    src = BUILD / "block8_pex2.spice"
    if not src.is_file():
        sys.exit(f"missing {src}; run the Magic extraction first")
    text = src.read_text()
    text = re.sub(r"\b(w_\S+?)#", "vdd", text)
    # The PEX writes M devices with the model name; the PDK models are
    # subcircuits, so convert to X with w/l in um.
    out = []
    pat = re.compile(r"^M(\S+)\s+(\S+)\s+(\S+)\s+(\S+)\s+(\S+)\s+"
                     r"((?:nm|pm)\S+)\s+w=([\d.]+)\s+l=([\d.]+)")
    for line in text.splitlines():
        line = re.sub(r"\s+\*\*FLOATING.*$", "", line)
        m = pat.match(line)
        if m:
            name, d, g, ss, b, model, w, l = m.groups()
            out.append(f"X{name} {d} {g} {ss} {b} {model} w={w}u l={l}u")
        elif line.startswith("+"):
            continue
        else:
            out.append(line)
    text = "\n".join(out) + "\n"
    dst = BUILD / "block8_pex2_tb.spice"
    dst.write_text(text)
    return dst


def deck(pex: Path, code: int, kind: str) -> Path:
    lines = [
        f"* 8-cell {kind} code {code}",
        f'.lib "{MODELS}" tt_mos',
        f"Vdd vdd 0 {VDD:g}",
        "Vss VSS 0 0",
        "Vsub SUB 0 0",
        "Vdump idump 0 0",
        f"Rl iout 0 {RL:g}",
        f"Cl iout 0 {CL*1e12:g}p",
        f"Cvcp vcp 0 {VCP_CAP*1e12:g}p",
        f"Iref vcp 0 {IREF*1e6:g}u",
    ]
    if kind == "pex":
        lines.append(f'.include "{pex}"')
    else:
        src = BUILD / "video_ics55.cdl"
        sim = BUILD / "video_ics55_sim.cdl"
        sim.write_text("\n".join(
            ("X" + ln[1:]) if ln.startswith("M") else ln
            for ln in src.read_text().splitlines()) + "\n")
        lines.append(f'.include "{sim}"')
        ports = (["vdd", "vbp", "vcp", "iout", "idump"] +
                 [f"d_{tag(j)[1]}" for j in range(N)] +
                 [f"db_{tag(j)[1]}" for j in range(N)])
        lines.append("Xtop " + " ".join(ports) + " dac_video_ana")
    for j in range(N):
        k, t = tag(j)
        on = bool((code >> k) & 1)
        lines.append(f"Vd_{t} d_{t} 0 {VDD if on else 0:g}")
        lines.append(f"Vdb_{t} db_{t} 0 {0 if on else VDD:g}")
    dat = BUILD / f"block8_{kind}_{code}.dat"
    lines += [".control", "set wr_singlescale", "set wr_vecnames",
              "tran 10e-12 45e-9", f"wrdata {dat} v(iout)", ".endc", ".end"]
    nl = BUILD / f"block8_{kind}_{code}.spice"
    nl.write_text("\n".join(lines) + "\n")
    return nl


def settled(dat: Path) -> float:
    rows = []
    names = {}
    for line in dat.read_text().splitlines():
        f = line.split()
        if len(f) < 2:
            continue
        try:
            rows.append([float(x) for x in f])
        except ValueError:
            for i, v in enumerate(f):
                names.setdefault(v, i)
    t = [r[names["time"]] for r in rows]
    v = [r[names["v(iout)"]] for r in rows]
    i = min(range(len(t)), key=lambda k: abs(t[k] - 41e-9))
    return v[i]


def main():
    pex = prep_pex()
    lsb = IREF * RL
    worst = 0.0
    print(f"{'code':>4} {'PEX (LSB)':>10} {'CDL (LSB)':>10} {'delta':>8}")
    for code in (0, 1, 3, 7):
        out = {}
        for kind in ("pex", "cdl"):
            nl = deck(pex if kind == "pex" else None, code, kind)
            r = subprocess.run(["ngspice", "-b", str(nl)],
                               capture_output=True, text=True, timeout=1800)
            (BUILD / f"block8_{kind}_{code}.log").write_text(
                r.stdout + r.stderr)
            if r.returncode:
                sys.exit(f"ngspice failed: {nl}")
            out[kind] = settled(BUILD / f"block8_{kind}_{code}.dat") / lsb
        d = out["pex"] - out["cdl"]
        worst = max(worst, abs(d))
        print(f"{code:4d} {out['pex']:10.4f} {out['cdl']:10.4f} "
              f"{d:+8.4f}")
    print(f"worst |PEX - CDL| = {worst:.4f} LSB")
    return 0 if worst < 0.1 else 1


if __name__ == "__main__":
    sys.exit(main())
