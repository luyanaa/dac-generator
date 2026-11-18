#!/usr/bin/env python3
"""Full-chip (leaf) LVS: row + digital + wrapper, hierarchical.

    python3 fullchip_lvs.py

The wrapper layout is the hierarchical `dac_video_wrapper.gds` built by
`openlane/dac_video_dig/wrapper_connect.py`: the row and digital cells plus
same-layer port stubs.  Magic extracts it hierarchically (`wrapper_magic.spice`,
1023 top devices: 1022 row + 1 digital macro).  The reference is the row's
1022-device CDL (X devices in Magic's s/g/d/b pin order), the digital
gate-level netlist (stdcells as empty black boxes), and one top port `vdd`.

Netgen with `-blackbox` compares the top-level connectivity and the row; the
digital macro internals are its own LVS (Netgen, 0 differences), and the row
internals are the reference-CDL `signoff.py --stage lvs_full` (KLayout PASS).
"""
from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
OL = ROOT / "openlane" / "dac_video_dig"
BUILD = HERE / "build"
GDS = OL / "build" / "dac_video_wrapper.gds"
MAGIC_SPICE = BUILD / "wrapper_magic.spice"
REF = BUILD / "dac_video_wrapper_ref_auto.spice"
REPORT = BUILD / "fullchip_lvs.rpt"
KLAYOUT = "/usr/bin/klayout"
MAGIC = "/usr/local/bin/magic"
NETGEN = "/usr/local/bin/netgen"
MAGICRC = ROOT / "pdks" / "ihp-sg13g2" / "libs.tech" / "magic" / "ihp-sg13g2.magicrc"
DIG_SPICE = OL / "runs" / "ihp_ant" / "final" / "spice" / "dac_video_dig.spice"
N = 255


def tag(j: int) -> str:
    k = 0
    while j >= 2 ** (k + 1) - 1:
        k += 1
    return f"b{k}_{j - (2 ** k - 1)}"


def run(cmd, cwd=None, env=None, timeout=3600):
    return subprocess.run([str(c) for c in cmd], cwd=cwd, env=env,
                          capture_output=True, text=True, timeout=timeout)


def subckt_ports(name: str, lines: list[str]) -> list[str]:
    for i, l in enumerate(lines):
        if l.lower().startswith(".subckt " + name):
            out, started = [], False
            for l2 in lines[i:]:
                t = l2.strip().lower()
                if t.startswith(".subckt "):
                    out += l2.split()[2:]
                    started = True
                elif started and l2.strip().startswith("+"):
                    out += l2[1:].split()
                elif started:
                    break
            return out
    return []


def inst_tokens(lines: list[str], name: str) -> list[str]:
    for i, l in enumerate(lines):
        if l.strip().lower().startswith(name.lower() + " "):
            toks, j = [], i
            while j < len(lines):
                seg = lines[j]
                if j > i and not seg.strip().startswith("+"):
                    break
                seg = seg.strip()[len(name):] if j == i else seg.strip()[1:]
                toks += seg.split()
                j += 1
            return toks[:-1]
    return []


def make_reference() -> str:
    layout = MAGIC_SPICE.read_text().splitlines()
    lap = subckt_ports("dac_video_ihp", layout)
    ldp = subckt_ports("dac_video_dig", layout)
    lat = inst_tokens(layout, "Xdac_video_ihp_0")
    ldt = inst_tokens(layout, "Xdac_video_dig_0")
    lmap_a = dict(zip(lap, lat))
    lmap_d = dict(zip(ldp, ldt))

    ports = (["well", "vss", "vbp", "vcp", "iout", "idump"] +
             [f"d_{tag(j)}" for j in range(N)] +
             [f"db_{tag(j)}" for j in range(N)])
    ana = [".subckt dac_video_ihp " + " ".join(ports)]
    for j in range(N):
        t = tag(j)
        ana += [
            f"X{j}m well vbp md_{j} well sg13_lv_pmos w=8u l=1u",
            f"X{j}c md_{j} vcp cd_{j} well sg13_lv_pmos w=8u l=0.5u",
            f"X{j}a cd_{j} d_{t} iout vss sg13_lv_nmos w=4u l=0.28u",
            f"X{j}b cd_{j} db_{t} idump vss sg13_lv_nmos w=4u l=0.28u",
        ]
    ana += ["Xrm well vbp vbp well sg13_lv_pmos w=8u l=1u",
            "Xrc vbp vcp vcp well sg13_lv_pmos w=8u l=0.5u",
            ".ends"]
    ana = "\n".join(ana)

    dig = DIG_SPICE.read_text()
    dports = subckt_ports("dac_video_dig", dig.splitlines())

    def amap(p):
        return "vdd" if p == "well" else ("vss" if p == "vss" else lmap_a.get(p, p))

    def dmap(p):
        lp = p.lower()
        return "dvdd" if lp == "vdd" else ("vss" if lp == "vss" else lmap_d.get(p, p))

    a_conn = [amap(p) for p in ports]
    d_conn = [dmap(p) for p in dports]
    out = ["* full-chip reference: row X devices + digital gate-level",
           ana, dig,
           ".subckt dac_video_wrapper vdd",
           "Xana " + " ".join(a_conn) + " dac_video_ihp",
           "Xdig " + " ".join(d_conn) + " dac_video_dig", ".ends"]
    return "\n".join(out) + "\n"


def main() -> int:
    # 1. wrapper GDS (cell-level, no flatten)
    env = dict(os.environ)
    env["DIG_GDS"] = str(OL / "runs" / "ihp_ant" / "final" / "gds" / "dac_video_dig.gds")
    p = run([KLAYOUT, "-b", "-r", OL / "wrapper_connect.py", "-z"], env=env)
    (BUILD / "wrapper_connect.log").write_text(p.stdout + p.stderr)
    if p.returncode or not GDS.is_file():
        raise SystemExit("wrapper_connect.py failed")
    # 2. Magic hierarchical extraction
    tcl = BUILD / "extract_wrapper_auto.tcl"
    tcl.write_text(
        f'gds read {GDS}\nload dac_video_wrapper -dereference\n'
        f'cd {BUILD / "wrapper_magic"}\n'
        "extract do local\nextract no capacitance\nextract no coupling\n"
        "extract no resistance\nextract no adjust\nextract unique all\n"
        "extract\next2spice lvs\n"
        f'ext2spice -o {MAGIC_SPICE} dac_video_wrapper.ext\n'
        "puts WRAPPER_EXTRACT_DONE\nquit\n")
    (BUILD / "wrapper_magic").mkdir(exist_ok=True)
    p = run([MAGIC, "-dnull", "-noconsole", "-rcfile", MAGICRC, tcl])
    (BUILD / "fullchip_magic.log").write_text(p.stdout + p.stderr)
    if p.returncode or not MAGIC_SPICE.is_file():
        raise SystemExit("Magic extraction failed")
    # 3. add the one top-level port to the extracted top cell
    s = MAGIC_SPICE.read_text()
    s = s.replace(".subckt dac_video_wrapper\n",
                  ".subckt dac_video_wrapper vdd\n", 1)
    (BUILD / "wrapper_magic_vdd.spice").write_text(s)
    # 4. reference and Netgen
    REF.write_text(make_reference())
    lvs = BUILD / "netgen_fullchip.lvs"
    lvs.write_text(
        f"set circuit1 [readnet spice {BUILD / 'wrapper_magic_vdd.spice'}]\n"
        f"set circuit2 [readnet spice {REF}]\n"
        f'lvs "$circuit1 dac_video_wrapper" "$circuit2 dac_video_wrapper" '
        f"/dev/null {REPORT} -blackbox -json\n")
    p = run([NETGEN, "-batch", "source", lvs])
    (BUILD / "fullchip_netgen.log").write_text(p.stdout + p.stderr)
    text = p.stdout + p.stderr
    ok = "Circuits match uniquely" in text
    ds = re.findall(r"Circuit 1 contains (\d+) devices", text)
    ns = re.findall(r"Circuit 1 contains (\d+) nets", text)
    res = {"ok": ok,
           "devices": int(ds[-1]) if ds else None,
           "nets": int(ns[-1]) if ns else None,
           "topcell": "dac_video_wrapper",
           "gds": str(GDS),
           "extracted": str(MAGIC_SPICE),
           "reference": str(REF),
           "report": str(REPORT),
           "log": str(BUILD / "fullchip_netgen.log")}
    (BUILD / "fullchip_lvs.json").write_text(json.dumps(res, indent=2) + "\n")
    print(json.dumps(res, indent=2))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
