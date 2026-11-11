#!/usr/bin/env python3
"""Run the P5 carry on the LVS-extracted ics55 row netlist.

    python3 extracted_carry.py            # 127->128 and 0->255

`build/row_ext.cir` is the KLayout LVS extraction of `build/video_ics55.gds`
(1022 devices, 515 ports, `ICS55_LVS_COMPARE=PASS`).  The PDK models are
subcircuits, so the MOS lines are rewritten M -> X with w/l before ngspice
sees them; the array is then driven exactly like `analog/video/pdk_cell.py`
(20 ps edge, 25 ps bit skew, 16 uA on vcp, 37.5 ohm + 2 pF load).

This is the device-level extracted netlist: the layout's devices and wiring
are what is simulated, but there is no parasitic capacitance.  The Magic PEX
of the full row does not finish in a practical time (flat: >60 min, the
hierarchical form with `drc off`: >40 min), so the PEX carry is still open.
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
BUILD = HERE / "build"
MODELS = ("/grid/icsprout55-pdk/libs.tech/spice/foundry/ngspice/"
          "ICsprout_55LLULP1225_V1p1_hsp.lib")
N = 255
I_UNIT_UA = 16.0
RL = 37.5
CL_PF = 2.0
VCP_CAP_PF = 220.0
PERIOD_NS = 40.0
T0_NS = 1.0
EDGE_PS = 20.0
SKEW_PS = 25.0


def tag(j: int) -> str:
    k = 0
    while j >= 2 ** (k + 1) - 1:
        k += 1
    return f"b{k}_{j - (2 ** k - 1)}"


def convert() -> Path:
    text = (BUILD / "row_ext.cir").read_text()
    text = re.sub(r"\n\+\s*", " ", text)
    out = []
    for ln in text.splitlines():
        m = re.match(r"^M(\S+)\s+(\S+)\s+(\S+)\s+(\S+)\s+(\S+)\s+"
                     r"(NM1P2_SVT_LP|PM1P2_SVT_LP)\s+(.*)$", ln)
        if m:
            name, d, g, s, b, cls, rest = m.groups()
            kv = dict(x.split("=") for x in rest.split() if "=" in x)
            u = lambda v: v.lower()
            out.append(f"X{name} {d} {g} {s} {b} {cls.lower()} "
                       f"w={u(kv.get('W', '0'))} l={u(kv.get('L', '0'))} "
                       f"as={u(kv.get('AS', '0'))} ad={u(kv.get('AD', '0'))} "
                       f"ps={u(kv.get('PS', '0'))} pd={u(kv.get('PD', '0'))}")
        else:
            out.append(ln)
    dst = BUILD / "row_ext_x.cir"
    dst.write_text("\n".join(out) + "\n")
    return dst


def ports_of(path: Path) -> list[str]:
    lines = path.read_text().splitlines()
    for i, l in enumerate(lines):
        if l.startswith(".SUBCKT"):
            ports = l.split()[2:]
            j = i + 1
            while j < len(lines) and lines[j].startswith("+"):
                ports += lines[j].split()[1:]
                j += 1
            return ports
    raise SystemExit("no .SUBCKT in the extracted netlist")


def run(pex: Path, frm: int, to: int, kind: str) -> int:
    ports = ports_of(pex)
    dat = BUILD / f"ext_{kind}.dat"
    lines = [
        f"* extracted row {frm}->{to}",
        f'.lib "{MODELS}" tt_mos',
        "Vdd vdd 0 1.2", "Vss VSS 0 0", "Vdump idump 0 0",
        f"Rl iout 0 {RL}", f"Cl iout 0 {CL_PF}p",
        f"Cvcp vcp 0 {VCP_CAP_PF}p", "Iref vcp 0 16u",
        f'.include "{pex}"',
        "Xtop " + " ".join(ports) + " dac_video_ana",
    ]
    for j in range(N):
        t = tag(j)
        k = 0
        while j >= 2 ** (k + 1) - 1:
            k += 1
        on0 = bool((frm >> k) & 1)
        on1 = bool((to >> k) & 1)
        t0 = T0_NS * 1e-9 + k * SKEW_PS * 1e-12
        e = t0 + EDGE_PS * 1e-12
        for net, x0, x1 in ((f"d_{t}", 1.2 if on0 else 0.0, 1.2 if on1 else 0.0),
                            (f"db_{t}", 0.0 if on0 else 1.2, 0.0 if on1 else 1.2)):
            if x0 == x1:
                lines.append(f"V{net} {net} 0 {x0:g}")
            else:
                lines.append(f"V{net} {net} 0 PWL(0 {x0:g} {t0:.6g} {x0:g} "
                             f"{e:.6g} {x1:g})")
    lines += [".control", "set wr_singlescale", "set wr_vecnames",
              "tran 5e-12 50e-9", f"wrdata {dat} v(iout) v(vbp) v(vcp)",
              ".endc", ".end"]
    nl = BUILD / f"ext_{kind}.spice"
    nl.write_text("\n".join(lines) + "\n")
    r = subprocess.run(["ngspice", "-b", str(nl)], capture_output=True,
                       text=True, timeout=7200)
    (BUILD / f"ext_{kind}.log").write_text(r.stdout + r.stderr)
    if r.returncode:
        print(f"{kind}: ngspice failed ({nl})", file=sys.stderr)
        return 1
    names, rows = {}, []
    for ln in dat.read_text().splitlines():
        f = ln.split()
        if len(f) < 2:
            continue
        try:
            rows.append([float(x) for x in f])
        except ValueError:
            for i, v in enumerate(f):
                names.setdefault(v, i)
    t = [x[names["time"]] for x in rows]
    v = [x[names["v(iout)"]] for x in rows]
    lsb = I_UNIT_UA * 1e-6 * RL
    i = min(range(len(t)), key=lambda k: abs(t[k] - (T0_NS + PERIOD_NS) * 1e-9))
    print(f"  {frm:3d} -> {to:3d}: {v[i]/lsb:9.3f} LSB "
          f"(err {v[i]/lsb - to:+8.3f}) at {t[i]*1e9:.1f} ns")
    return 0


def main() -> int:
    pex = convert()
    print(f"row_ext_x.cir: {ports_of(pex).__len__()} ports")
    rc = run(pex, 127, 128, "carry")
    rc |= run(pex, 0, 255, "fs")
    return rc


if __name__ == "__main__":
    sys.exit(main())
