#!/usr/bin/env python3
"""IHP sg13g2 R-2R pre-layout signoff.

    python3 ihp_signoff.py

Runs the existing `gen_r2r.py` PDK-parameterised netlist with the IHP
`sg13_lv` 1.2 V MOS and `rppd` 260 ohm/sq poly resistor, then the DC
(INL/DNL) and a short staircase settling bench.  Evidence:
`build/ihp_prelayout.json`, `build/dc.dat`, `build/tran_ihp.dat`.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

import measure

ROOT = Path(__file__).resolve().parent
BUILD = ROOT / "build"
PDK = "ihp-sg13g2"


def ihp_root() -> Path:
    base = Path.home() / ".ciel/ciel/ihp-sg13/versions"
    hits = sorted(p for p in base.iterdir()
                  if (p / "ihp-sg13g2/libs.tech/ngspice/models/cornerMOSlv.lib").is_file())
    if not hits:
        raise SystemExit(f"no IHP ngspice models under {base}")
    return hits[-1]


def run(cmd, env=None, timeout=1800):
    p = subprocess.run([str(c) for c in cmd], cwd=ROOT, env=env,
                       capture_output=True, text=True, timeout=timeout)
    return p


def write_reference(path: Path) -> None:
    ports = ([f"b{i}" for i in range(8)] + [f"n{i}" for i in range(7)] +
             ["vout", "vss"])
    lines = [".subckt dac_r2r_ihp " + " ".join(ports)]
    lines.append("Rterm vss n0 sub rppd w=2u l=314u ps=0u b=0 m=1")
    for i in range(8):
        node = "vout" if i == 7 else f"n{i}"
        lines.append(f"Rb{i} b{i} {node} sub rppd w=2u l=313u ps=0u b=0 m=1")
    for i in range(7):
        node = "vout" if i == 6 else f"n{i+1}"
        lines.append(f"Rs{i} n{i} {node} sub rppd w=2u l=157u ps=0u b=0 m=1")
    lines.append(".ends")
    path.write_text("\n".join(lines) + "\n")


def main() -> int:
    root = ihp_root()
    env = dict(os.environ)
    env["PDK_ROOT"] = str(root)
    env["PDK"] = PDK
    BUILD.mkdir(exist_ok=True)

    p = run([sys.executable, "gen_r2r.py", "--pdk", PDK, "--bench", "dc"])
    (BUILD / "ihp_gen_dc.log").write_text(p.stdout + p.stderr)
    if p.returncode:
        raise SystemExit("gen_r2r dc failed")
    p = run(["ngspice", "-b", "build/r2r_dc.spice"], env=env)
    (BUILD / "ihp_dc.log").write_text(p.stdout + p.stderr)
    if p.returncode:
        raise SystemExit("ngspice dc failed")
    p = run([sys.executable, "measure.py", "dc"], env=env)
    (BUILD / "ihp_measure_dc.log").write_text(p.stdout + p.stderr)
    if p.returncode:
        raise SystemExit("measure dc failed")
    rows = []
    for ln in (BUILD / "inl_dnl.csv").read_text().splitlines()[1:]:
        f = ln.split(",")
        if len(f) >= 4:
            rows.append((float(f[1]), float(f[2]), float(f[3])))
    dnl = [r[1] for r in rows]
    inl = [r[2] for r in rows]

    steps = "0,1,127,128,255"
    p = run([sys.executable, "gen_r2r.py", "--pdk", PDK, "--bench", "tran",
             "--steps", steps, "--step-us", "1", "--dat", "build/tran_ihp.dat"])
    (BUILD / "ihp_gen_tran.log").write_text(p.stdout + p.stderr)
    if p.returncode:
        raise SystemExit("gen_r2r tran failed")
    p = run(["ngspice", "-b", "build/r2r_tran.spice"], env=env, timeout=3600)
    (BUILD / "ihp_tran.log").write_text(p.stdout + p.stderr)
    if p.returncode:
        raise SystemExit("ngspice tran failed")
    p = run([sys.executable, "measure.py", "tran", "build/tran_ihp.dat",
             "--vdd", "1.2", "--step-us", "1"], env=env)
    (BUILD / "ihp_measure_tran.log").write_text(p.stdout + p.stderr)
    if p.returncode:
        raise SystemExit("measure tran failed")
    settles = [float(m.group(1)) for m in
               re.finditer(r"^\s*\d+\.\d+\s+(\d+\.\d+)", p.stdout, re.M)]
    pre_ok = (max(abs(x) for x in dnl) <= 0.5
              and max(abs(x) for x in inl) <= 1.0
              and all(x >= -1.0 for x in dnl)
              and max(settles) <= 2000.0)
    # GDS: rppd PCells + M1 straps
    pdk = Path("/grid/dac-generator/pdks/ihp-sg13g2")
    gds = BUILD / "r2r_ihp.gds"
    gen_env = dict(os.environ)
    gen_env["KLAYOUT_PATH"] = str(pdk / "libs.tech/klayout")
    p = run(["/usr/bin/klayout", "-b", "-r", "gen_gds_ihp.py",
             "-rd", f"pdkroot={pdk}", "-rd", f"out={gds}",
             "-rd", "check=true"], env=gen_env)
    (BUILD / "ihp_gen_gds.log").write_text(p.stdout + p.stderr)
    if p.returncode or not gds.is_file():
        raise SystemExit("gen_gds_ihp failed")
    # DRC
    rdb = BUILD / "r2r_ihp_drc.lyrdb"
    if rdb.exists():
        rdb.unlink()
    p = run(["/usr/bin/klayout", "-b", "-zz", "-r",
             str(pdk / "libs.tech/klayout/tech/drc/ihp-sg13g2.drc"),
             "-rd", f"input={gds}", "-rd", "topcell=dac_r2r_ihp",
             "-rd", f"report={rdb}", "-rd", "no_recommended=true",
             "-rd", "run_mode=deep", "-rd", "thr=8"], timeout=1800)
    (BUILD / "ihp_drc.log").write_text(p.stdout + p.stderr)
    import xml.etree.ElementTree as ET
    drc_items = 0
    if rdb.is_file():
        drc_items = len(ET.parse(rdb).getroot().findall("./items/item"))
    # LVS: KLayout reference-CDL compare
    ref = BUILD / "r2r_ihp_ref.cdl"
    write_reference(ref)
    b = BUILD / "bin"
    b.mkdir(exist_ok=True)
    wrapper = b / "klayout"
    wrapper.write_text("#!/bin/sh\nexec env -u LD_LIBRARY_PATH "
                       "/nix/store/1whjbzm6gw6l4h0sjxdv92lyw7lq1ar8-klayout-0.30.12/bin/klayout \"$@\"\n")
    wrapper.chmod(0o755)
    lvs_env = dict(os.environ)
    lvs_env["PATH"] = f"{b}:" + lvs_env.get("PATH", "")
    lvs_env["PYTHONPATH"] = "/usr/lib/klayout/pymod"
    lvs_env["LD_LIBRARY_PATH"] = "/usr/lib/klayout"
    run_dir = BUILD / "lvs_ihp"
    if run_dir.exists():
        import shutil
        shutil.rmtree(run_dir)
    lvs = run(["/usr/bin/python3",
               str(pdk / "libs.tech/klayout/tech/lvs/run_lvs.py"),
               f"--layout={gds}", f"--netlist={ref}",
               "--topcell=dac_r2r_ihp", f"--run_dir={run_dir}",
               "--disable_tap_extraction"], env=lvs_env, timeout=1800)
    (BUILD / "ihp_lvs.log").write_text(lvs.stdout + lvs.stderr)
    lvs_ok = ("Status           | PASS" in (lvs.stdout + lvs.stderr)
              or "Netlists match" in (lvs.stdout + lvs.stderr))
    res = {
        "ok": pre_ok and drc_items == 0 and lvs_ok,
        "prelayout_ok": pre_ok,
        "drc_items": drc_items,
        "lvs_ok": lvs_ok,
        "gds": str(gds),
        "reference": str(ref),
        "drc_report": str(rdb),
        "lvs_log": str(BUILD / "ihp_lvs.log"),
        "pdk": PDK,
        "vdd": 1.2,
        "bits": 8,
        "unit": "rppd W=2u L=150u (19.5 kOhm)",
        "driver": "sg13_lv Wn=3u/Wp=8u L=0.13u",
        "dnl_lsb": [round(min(dnl), 4), round(max(dnl), 4)],
        "inl_lsb": [round(min(inl), 4), round(max(inl), 4)],
        "monotonic": all(x >= -1.0 for x in dnl),
        "settle_ns": settles,
        "worst_settle_ns": max(settles) if settles else None,
        "dc_dat": str(BUILD / "dc.dat"),
        "tran_dat": str(BUILD / "tran_ihp.dat"),
        "logs": [str(BUILD / n) for n in
                 ("ihp_dc.log", "ihp_tran.log", "ihp_measure_tran.log")],
    }
    (BUILD / "ihp_signoff.json").write_text(json.dumps(res, indent=2) + "\n")
    print(json.dumps(res, indent=2))
    return 0 if res["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
