#!/usr/bin/env python3
"""IHP sg13g2 current-steering array signoff (GDS + DRC + reference LVS).

    python3 ihp_signoff.py

The electrical pre-layout gate is `ihp_prelayout.json` (unit cell 15.92 uA,
ro 1.3 MOhm, -0.813 %/mV Vth sensitivity; DEM pre-layout with 1.8 % cells).
This script covers the layout half:

  * `gen_gds_ihp.py` builds 15 unary (8/1) + 15 binary (0.5/1) cascoded
    PMOS cells, the replica bias generator, 60 NMOS steering switches and
    the 2.75 um M2 pin row;
  * IHP KLayout DRC must report 0 items;
  * a 122-device reference CDL (2 replica + 30 mirror/cascode pairs +
    60 switches) must compare PASS.

Evidence: `build/ihp_signoff.json`, `build/csteer_ihp.gds`,
`build/csteer_ihp_drc.lyrdb`, `build/lvs_cmp/`.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

HERE = Path(__file__).resolve().parent
BUILD = HERE / "build"
PDK = Path("/grid/dac-generator/pdks/ihp-sg13g2")
KLAYOUT = Path("/usr/bin/klayout")
DRC = PDK / "libs.tech/klayout/tech/drc/ihp-sg13g2.drc"
LVS_RUNNER = PDK / "libs.tech/klayout/tech/lvs/run_lvs.py"
KLAYOUT_WRAPPER = ("#!/bin/sh\nexec env -u LD_LIBRARY_PATH "
                   "/nix/store/1whjbzm6gw6l4h0sjxdv92lyw7lq1ar8-klayout-0.30.12/bin/klayout \"$@\"\n")


def run(cmd, env=None, timeout=1800, cwd=HERE):
    return subprocess.run([str(c) for c in cmd], cwd=cwd, env=env,
                          capture_output=True, text=True, timeout=timeout)


def reference(path: Path) -> int:
    cells = [("u%d" % i, 8.0) for i in range(15)]
    for w, n in ((1, 1), (2, 2), (4, 4), (8, 8)):
        for k in range(n):
            cells.append((f"b{w}_{k}", 0.5))
    ports = ["vdd", "vss", "vbp", "vcp"]
    for tag, _ in cells:
        ports += [f"swa_{tag}", f"swb_{tag}"]
    ports += ["iout", "idump"]
    lines = [".subckt dac_csteer_ihp " + " ".join(ports)]
    # replica: diode-connected mirror + cascode, 16 uA reference into vcp
    lines.append("Mref vbp vbp vdd vdd sg13_lv_pmos L=1u W=8u")
    lines.append("Mcasb vcp vcp vbp vdd sg13_lv_pmos L=0.5u W=8u")
    for tag, w in cells:
        lines.append(f"Mm_{tag} n_{tag} vbp vdd vdd sg13_lv_pmos L=1u W={w:g}u")
        lines.append(f"Mc_{tag} cd_{tag} vcp n_{tag} vdd sg13_lv_pmos L=0.5u W={w:g}u")
        lines.append(f"Ma_{tag} iout swa_{tag} cd_{tag} vss sg13_lv_nmos L=0.28u W=4u")
        lines.append(f"Mb_{tag} idump swb_{tag} cd_{tag} vss sg13_lv_nmos L=0.28u W=4u")
    lines.append(".ends")
    path.write_text("\n".join(lines) + "\n")
    return len(lines) - 3


def main() -> int:
    BUILD.mkdir(exist_ok=True)
    env = dict(os.environ)
    gen_env = dict(env)
    gen_env["KLAYOUT_PATH"] = str(PDK / "libs.tech/klayout")

    gds = BUILD / "csteer_ihp.gds"
    p = run([KLAYOUT, "-b", "-r", "gen_gds_ihp.py",
             "-rd", f"pdkroot={PDK}", "-rd", f"out={gds}", "-rd", "check=true"],
            env=gen_env)
    (BUILD / "ihp_gen_gds.log").write_text(p.stdout + p.stderr)
    if p.returncode or not gds.is_file():
        raise SystemExit("gen_gds_ihp failed")

    rdb = BUILD / "csteer_ihp_drc.lyrdb"
    if rdb.exists():
        rdb.unlink()
    p = run([KLAYOUT, "-b", "-zz", "-r", DRC,
             "-rd", f"input={gds}", "-rd", "topcell=dac_csteer_ihp",
             "-rd", f"report={rdb}", "-rd", "no_recommended=true",
             "-rd", "run_mode=deep", "-rd", "thr=8"], timeout=1800)
    (BUILD / "ihp_drc.log").write_text(p.stdout + p.stderr)
    drc_items = (len(ET.parse(rdb).getroot().findall("./items/item"))
                 if rdb.is_file() else -1)

    ref = BUILD / "csteer_ihp_ref.cdl"
    ndev = reference(ref)
    b = BUILD / "bin"
    b.mkdir(exist_ok=True)
    w = b / "klayout"
    w.write_text(KLAYOUT_WRAPPER)
    w.chmod(0o755)
    lenv = dict(env)
    lenv["PATH"] = f"{b}:" + lenv.get("PATH", "")
    lenv["PYTHONPATH"] = "/usr/lib/klayout/pymod"
    lenv["LD_LIBRARY_PATH"] = "/usr/lib/klayout"
    run_dir = BUILD / "lvs_cmp"
    if run_dir.exists():
        shutil.rmtree(run_dir)
    p = run(["/usr/bin/python3", LVS_RUNNER, f"--layout={gds}",
             f"--netlist={ref}", "--topcell=dac_csteer_ihp",
             f"--run_dir={run_dir}", "--disable_tap_extraction",
             "--ignore_top_ports_mismatch"], env=lenv, timeout=1800)
    (BUILD / "ihp_lvs.log").write_text(p.stdout + p.stderr)
    txt = p.stdout + p.stderr
    lvs_ok = "Status           | PASS" in txt

    pre = {}
    pre_path = HERE / "ihp_prelayout.json"
    if pre_path.is_file():
        pre = json.loads(pre_path.read_text())

    res = {
        "ok": bool(drc_items == 0 and lvs_ok),
        "pdk": "ihp-sg13g2",
        "vdd": 1.2,
        "cells": {"unary": "15 x sg13_lv_pmos 8/1 mirror + 8/0.5 cascode",
                  "binary": "15 x sg13_lv_pmos 0.5/1 mirror + 0.5/0.5 cascode"},
        "switches": "60 x sg13_lv_nmos 4/0.28",
        "pin_row": "M2, 2.75 um grid, 60 control pins",
        "gds": str(gds),
        "drc_items": drc_items,
        "drc_report": str(rdb),
        "lvs_ok": lvs_ok,
        "lvs_devices": ndev,
        "reference": str(ref),
        "lvs_run_dir": str(run_dir),
        "prelayout": {
            "ok": pre.get("prelayout_ok"),
            "unit_cell": pre.get("unit_cell"),
            "dc_dem_1p8pct": pre.get("dc_dem_1p8pct"),
        },
        "logs": [str(BUILD / n) for n in
                 ("ihp_gen_gds.log", "ihp_drc.log", "ihp_lvs.log")],
    }
    (BUILD / "ihp_signoff.json").write_text(json.dumps(res, indent=2) + "\n")
    print(json.dumps(res, indent=2))
    return 0 if res["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
