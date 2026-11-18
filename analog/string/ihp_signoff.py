#!/usr/bin/env python3
"""IHP sg13g2 resistor-string pre-layout + GDS signoff.

    python3 ihp_signoff.py

The pre-layout benches use the 4 kOhm rppd unit (L=30.769 um, W=2 um) and the
1.2 V sg13_lv transmission-gate tree; the settling bench uses `--rtg 100`
(ideal 100 ohm switches) because the full 510-device MOS tree is too slow for
a 90 us staircase.  The layout is the 255-unit string only; the TG tree and
follower remain class-C hand layout, exactly as in the gf180 leaf.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

HERE = Path(__file__).resolve().parent
BUILD = HERE / "build"
PDK = "ihp-sg13g2"
LOCAL_PDK = Path("/grid/dac-generator/pdks/ihp-sg13g2")
KLAYOUT = Path("/usr/bin/klayout")
DECK = LOCAL_PDK / "libs.tech/klayout/tech/drc/ihp-sg13g2.drc"
LVS_RUNNER = LOCAL_PDK / "libs.tech/klayout/tech/lvs/run_lvs.py"


def root() -> Path:
    base = Path.home() / ".ciel/ciel/ihp-sg13/versions"
    hits = sorted(p for p in base.iterdir()
                  if (p / "ihp-sg13g2/libs.tech/ngspice/models/cornerMOSlv.lib").is_file())
    if not hits:
        raise SystemExit(f"no IHP ngspice models under {base}")
    return hits[-1]


def run(cmd, env=None, timeout=2400):
    return subprocess.run([str(c) for c in cmd], cwd=HERE, env=env,
                          capture_output=True, text=True, timeout=timeout)


def parse_measure(txt: str) -> dict:
    # measure.py prints one block per signal; use the vout block.
    blocks = re.split(r"--\s+(\w+)\s*\n", txt)
    out = {}
    for i in range(1, len(blocks) - 1, 2):
        name, body = blocks[i], blocks[i + 1]
        dnl = re.search(r"DNL\s*:\s*([-+0-9.]+)\s*\.\.\s*([-+0-9.]+)", body)
        inl = re.search(r"INL\s*:\s*([-+0-9.]+)\s*\.\.\s*([-+0-9.]+)", body)
        mono = re.search(r"monotonic\s*:\s*(\w+)", body)
        if dnl:
            out[name] = {"dnl": [float(dnl.group(1)), float(dnl.group(2))],
                         "inl": [float(inl.group(1)), float(inl.group(2))] if inl else None,
                         "monotonic": (mono.group(1) == "yes") if mono else None}
    return out


def main() -> int:
    r = root()
    env = dict(os.environ)
    env["PDK_ROOT"] = str(r)
    env["PDK"] = PDK
    BUILD.mkdir(exist_ok=True)

    # pre-layout DC with the MOS TG tree
    p = run([sys.executable, "gen_string.py", "--pdk", PDK, "--bench", "dc"])
    (BUILD / "ihp_gen_dc.log").write_text(p.stdout + p.stderr)
    if p.returncode:
        raise SystemExit("gen_string dc failed")
    p = run(["ngspice", "-b", "build/string_dc.spice"], env=env)
    (BUILD / "ihp_dc.log").write_text(p.stdout + p.stderr)
    if p.returncode:
        raise SystemExit("ngspice dc failed")
    p = run([sys.executable, "measure.py", "dc"], env=env)
    (BUILD / "ihp_measure_dc.log").write_text(p.stdout + p.stderr)
    pre = parse_measure(p.stdout)
    vout = pre.get("vout", {})
    dc_ok = (vout.get("dnl") and max(abs(x) for x in vout["dnl"]) <= 0.5
             and vout.get("inl") and max(abs(x) for x in vout["inl"]) <= 1.0
             and vout.get("monotonic") is True)

    # fast settling with ideal 100 ohm switches
    p = run([sys.executable, "gen_string.py", "--pdk", PDK, "--bench", "tran",
             "--rtg", "100", "--dat", "build/tran_4k.dat"])
    (BUILD / "ihp_gen_tran.log").write_text(p.stdout + p.stderr)
    if p.returncode:
        raise SystemExit("gen_string tran failed")
    p = run(["ngspice", "-b", "build/string_tran.spice"], env=env, timeout=1800)
    (BUILD / "ihp_tran.log").write_text(p.stdout + p.stderr)
    if p.returncode:
        raise SystemExit("ngspice tran failed")
    p = run([sys.executable, "measure.py", "tran", "build/tran_4k.dat",
             "--vdd", "1.2"], env=env)
    (BUILD / "ihp_measure_tran.log").write_text(p.stdout + p.stderr)
    settles = [float(m.group(1)) for m in
               re.finditer(r"^\s*\d+\.\d+\s+(\d+\.\d+)", p.stdout, re.M)]
    tran_ok = bool(settles) and max(settles) <= 2000.0

    # GDS + DRC
    gds = BUILD / "string_ihp4k.gds"
    genenv = dict(os.environ)
    genenv["KLAYOUT_PATH"] = str(LOCAL_PDK / "libs.tech/klayout")
    p = run([KLAYOUT, "-b", "-r", "gen_gds_ihp.py",
             "-rd", f"pdkroot={LOCAL_PDK}", "-rd", f"out={gds}",
             "-rd", "check=true"], env=genenv)
    (BUILD / "ihp_gen_gds.log").write_text(p.stdout + p.stderr)
    if p.returncode:
        raise SystemExit("gen_gds_ihp failed")
    rdb = BUILD / "string_ihp4k_drc.lyrdb"
    if rdb.exists():
        rdb.unlink()
    p = run([KLAYOUT, "-b", "-zz", "-r", DECK,
             "-rd", f"input={gds}", "-rd", "topcell=dac_string_ihp",
             "-rd", f"report={rdb}", "-rd", "no_recommended=true",
             "-rd", "run_mode=deep", "-rd", "thr=8"], timeout=1800)
    (BUILD / "ihp_drc.log").write_text(p.stdout + p.stderr)
    drc_items = len(ET.parse(rdb).getroot().findall("./items/item")) if rdb.is_file() else -1

    # reference 255-unit string
    ports = ["vss"] + [f"t{i}" for i in range(1, 255)] + ["vref"]
    ref = BUILD / "string_ihp_ref.cdl"
    lines = [".subckt dac_string_ihp " + " ".join(ports)]
    for i in range(255):
        a = "vss" if i == 0 else f"t{i}"
        b = "vref" if i == 254 else f"t{i+1}"
        lines.append(f"R{i} {a} {b} sub rppd w=2u l=32.07u ps=0u b=0 m=1")
    lines.append(".ends")
    ref.write_text("\n".join(lines) + "\n")
    # KLayout LVS env
    b = BUILD / "bin"
    b.mkdir(exist_ok=True)
    w = b / "klayout"
    w.write_text("#!/bin/sh\nexec env -u LD_LIBRARY_PATH "
                 "/nix/store/1whjbzm6gw6l4h0sjxdv92lyw7lq1ar8-klayout-0.30.12/bin/klayout \"$@\"\n")
    w.chmod(0o755)
    lenv = dict(os.environ)
    lenv["PATH"] = f"{b}:" + lenv.get("PATH", "")
    lenv["PYTHONPATH"] = "/usr/lib/klayout/pymod"
    lenv["LD_LIBRARY_PATH"] = "/usr/lib/klayout"
    run_dir = BUILD / "lvs_ihp"
    if run_dir.exists():
        shutil.rmtree(run_dir)
    p = run(["/usr/bin/python3", LVS_RUNNER, f"--layout={gds}",
             f"--netlist={ref}", "--topcell=dac_string_ihp",
             f"--run_dir={run_dir}", "--disable_tap_extraction"],
            env=lenv, timeout=1800)
    (BUILD / "ihp_lvs.log").write_text(p.stdout + p.stderr)
    lvs_ok = "Status           | PASS" in (p.stdout + p.stderr)

    res = {
        "ok": bool(dc_ok and tran_ok and drc_items == 0 and lvs_ok),
        "pdk": PDK, "vdd": 1.2, "bits": 8,
        "unit": "rppd W=2u L=30.769u (4 kOhm nominal; layout PCell 4.004k)",
        "prelayout": pre,
        "settle_ns": settles,
        "worst_settle_ns": max(settles) if settles else None,
        "gds": str(gds), "drc_items": drc_items,
        "lvs_ok": lvs_ok, "reference": str(ref),
        "logs": [str(BUILD / n) for n in
                 ("ihp_dc.log", "ihp_measure_dc.log", "ihp_tran.log",
                  "ihp_measure_tran.log", "ihp_drc.log", "ihp_lvs.log")],
    }
    (BUILD / "ihp_signoff.json").write_text(json.dumps(res, indent=2) + "\n")
    print(json.dumps(res, indent=2))
    return 0 if res["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
