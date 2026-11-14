#!/usr/bin/env python3
"""8-cell PEX from the KLayout LVS netlist + Magic net capacitances.

The Magic device extraction still loses the cascode drain, so this path uses
the KLayout LVS extraction for the devices/connectivity (lower layers are
known-good) and stamps the named-net capacitances from the Magic .ext onto
the same nets.  Compare codes 0/1/3/7 against the CDL.
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
PORTS = (["d_b0_0", "d_b1_0", "d_b1_1", "d_b2_0", "d_b2_1", "d_b2_2",
          "d_b2_3", "d_b3_0", "db_b0_0", "db_b1_0", "db_b1_1", "db_b2_0",
          "db_b2_1", "db_b2_2", "db_b2_3", "db_b3_0", "idump", "iout",
          "vbp", "vcp", "vdd"])


def tag(j):
    k = 0
    while j >= 2 ** (k + 1) - 1:
        k += 1
    return k, f"b{k}_{j - (2 ** k - 1)}"


def prep():
    src = BUILD / "block8_ext.cir"
    if not src.is_file():
        sys.exit(f"missing {src}")
    text = src.read_text()
    text = re.sub(r"\n\+\s*", " ", text)
    out = []
    for line in text.splitlines():
        m = re.match(r"^M(\S+)\s+(\S+)\s+(\S+)\s+(\S+)\s+(\S+)\s+"
                     r"(NM1P2_SVT_LP|PM1P2_SVT_LP)\s+(.*)$", line)
        if m:
            name, d, g, ss, b, model, rest = m.groups()
            kv = dict(x.split("=") for x in rest.split() if "=" in x)
            u = lambda v: v.lower()
            out.append(f"X{name} {d} {g} {ss} {b} {model.lower()} "
                       f"w={u(kv.get('W','0'))} l={u(kv.get('L','0'))}")
        else:
            out.append(line)
    # named-net caps from the Magic .ext (the internal a_* nets are not
    # mapped; the gate/bias/output caps dominate this comparison)
    caps = []
    for line in (BUILD / "block8_pex2.spice").read_text().splitlines():
        m = re.match(r"^C(\S+)\s+(\S+)\s+SUB\s+([\d.eE+-]+)f", line)
        if m and m.group(2) in PORTS:
            caps.append(f"C{m.group(1)} {m.group(2)} 0 {m.group(3)}f")
    dst = BUILD / "block8_klayout_pex.cir"
    dst.write_text("\n".join(out + caps) + "\n")
    return dst


def ports_of(path):
    lines = Path(path).read_text().splitlines()
    for i, line in enumerate(lines):
        if line.lower().startswith(".subckt"):
            ports = line.split()[2:]
            j = i + 1
            while j < len(lines) and lines[j].startswith("+"):
                ports += lines[j].split()[1:]
                j += 1
            return ports
    sys.exit(f"no .subckt in {path}")


def deck(pex, code, kind):
    lines = [f"* block8 {kind} code {code}",
             f'.lib "{MODELS}" tt_mos',
             f"Vdd vdd 0 {VDD:g}", "Vss VSS 0 0", "Vsub SUB 0 0",
             "Vdump idump 0 0", f"Rl iout 0 {RL:g}",
             f"Cl iout 0 {CL*1e12:g}p",
             f"Cvcp vcp 0 {VCP_CAP*1e12:g}p",
             f"Iref vcp 0 {IREF*1e6:g}u"]
    if kind == "pex":
        lines.append(f'.include "{pex}"')
        lines.append("Xtop " + " ".join(ports_of(pex)) + " dac_video_ana")
    else:
        src = BUILD / "video_ics55.cdl"
        sim = BUILD / "video_ics55_sim.cdl"
        sim.write_text("\n".join(("X" + ln[1:]) if ln.startswith("M") else ln
                                 for ln in src.read_text().splitlines()) + "\n")
        lines.append(f'.include "{sim}"')
        lines.append("Xtop " + " ".join(ports_of(src)) + " dac_video_ana")
    for j in range(N):
        k, t = tag(j)
        on = bool((code >> k) & 1)
        lines.append(f"Vd_{t} d_{t} 0 {VDD if on else 0:g}")
        lines.append(f"Vdb_{t} db_{t} 0 {0 if on else VDD:g}")
    dat = BUILD / f"block8k_{kind}_{code}.dat"
    lines += [".control", "set wr_singlescale", "set wr_vecnames",
              "tran 10e-12 45e-9", f"wrdata {dat} v(iout)", ".endc", ".end"]
    nl = BUILD / f"block8k_{kind}_{code}.spice"
    nl.write_text("\n".join(lines) + "\n")
    return nl


def settled(dat):
    rows, names = [], {}
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
    pex = prep()
    lsb = IREF * RL
    worst = 0.0
    print(f"{'code':>4} {'PEX (LSB)':>10} {'CDL (LSB)':>10} {'delta':>8}")
    for code in (0, 1, 3, 7):
        out = {}
        for kind in ("pex", "cdl"):
            nl = deck(pex, code, kind)
            r = subprocess.run(["ngspice", "-b", str(nl)],
                               capture_output=True, text=True, timeout=1800)
            (BUILD / f"block8k_{kind}_{code}.log").write_text(
                r.stdout + r.stderr)
            if r.returncode:
                sys.exit(f"ngspice failed: {nl}")
            out[kind] = settled(BUILD / f"block8k_{kind}_{code}.dat") / lsb
        d = out["pex"] - out["cdl"]
        worst = max(worst, abs(d))
        print(f"{code:4d} {out['pex']:10.4f} {out['cdl']:10.4f} {d:+8.4f}")
    print(f"worst |PEX - CDL| = {worst:.4f} LSB")
    return 0 if worst < 0.1 else 1


if __name__ == "__main__":
    sys.exit(main())
