#!/usr/bin/env python3
"""IHP sg13g2 binary-CDAC signoff: unit C, model gate, array DRC and LVS.

    python3 ihp_signoff.py

Gates:
  * unit C(V): `build/ihp_moscap_c2.json` from `measure_c2_ihp.py` must exist
    (the measured `sg13_moscap_p` 2-D table); the moscap backend is a study,
    not the signoff cap, because its bias dependence gives +/-27 LSB INL;
  * electrical: `gen_cdac.py --bench model --cap mim --pdk ihp-sg13g2`
    (10 Pelgrom seeds) then `measure.py --cap mim` must print VERDICT PASS;
  * layout: 256 `cmim` units, IHP KLayout DRC 0 and the 9-entry reference
    CDL (m=128..1) LVS PASS.
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
PDK = Path("/grid/dac-generator/pdks/ihp-sg13g2")
KLAYOUT = Path("/usr/bin/klayout")
DRC = PDK / "libs.tech/klayout/tech/drc/ihp-sg13g2.drc"
LVS_RUNNER = PDK / "libs.tech/klayout/tech/lvs/run_lvs.py"
KLAYOUT_WRAPPER = ("#!/bin/sh\nexec env -u LD_LIBRARY_PATH "
                   "/nix/store/1whjbzm6gw6l4h0sjxdv92lyw7lq1ar8-klayout-0.30.12/bin/klayout \"$@\"\n")


def run(cmd, env=None, timeout=1800):
    return subprocess.run([str(c) for c in cmd], cwd=HERE, env=env,
                          capture_output=True, text=True, timeout=timeout)


def main() -> int:
    BUILD.mkdir(exist_ok=True)
    env = dict(os.environ)
    env["PDK_ROOT"] = str(Path.home() /
                          ".ciel/ciel/ihp-sg13/versions")
    hits = sorted((Path.home() / ".ciel/ciel/ihp-sg13/versions").glob(
        "*/ihp-sg13g2/libs.tech/ngspice/models/cornerMOSCAP.lib"))
    if hits:
        env["PDK_ROOT"] = str(hits[-1].parents[4])
    env["PDK"] = "ihp-sg13g2"

    unit = BUILD / "ihp_moscap_c2.json"
    unit_ok = unit.is_file()

    # electrical: flat-MIM model gate (the moscap is recorded as a study)
    p = run([sys.executable, "gen_cdac.py", "--bench", "model", "--cap", "mim",
             "--pdk", "ihp-sg13g2", "--seeds", "10"])
    (BUILD / "ihp_model_mim.log").write_text(p.stdout + p.stderr)
    if p.returncode:
        raise SystemExit("gen_cdac mim failed")
    p = run([sys.executable, "measure.py", "--cap", "mim", "--brief"])
    (BUILD / "ihp_measure_mim.log").write_text(p.stdout + p.stderr)
    gate_ok = "VERDICT_mim PASS" in p.stdout
    dnl = [float(x) for x in re.findall(r"DNL_mim ([-+0-9.eE]+) ([-+0-9.eE]+)",
                                        p.stdout)[0]]
    inl = [float(x) for x in re.findall(r"INL_mim ([-+0-9.eE]+) ([-+0-9.eE]+)",
                                        p.stdout)[0]]
    fs = float(re.findall(r"FS_mim ([-+0-9.eE]+)", p.stdout)[0])
    meta = json.loads((BUILD / "model_mim.json").read_text())

    # moscap study (measured bias dependence)
    p = run([sys.executable, "gen_cdac.py", "--bench", "model", "--cap",
             "moscap", "--pdk", "ihp-sg13g2", "--mismatch", "0.0234",
             "--seeds", "1"])
    (BUILD / "ihp_model_moscap.log").write_text(p.stdout + p.stderr)
    mm = json.loads((BUILD / "model_moscap.json").read_text())

    # layout
    gds = BUILD / "cdac_ihp.gds"
    gen_env = dict(env)
    gen_env["KLAYOUT_PATH"] = str(PDK / "libs.tech/klayout")
    p = run([KLAYOUT, "-b", "-r", "gen_gds_ihp.py", "-rd", f"pdkroot={PDK}",
             "-rd", f"out={gds}", "-rd", "check=true"], env=gen_env)
    (BUILD / "ihp_gen_gds.log").write_text(p.stdout + p.stderr)
    if p.returncode or not gds.is_file():
        raise SystemExit("gen_gds_ihp failed")
    rdb = BUILD / "cdac_ihp_drc.lyrdb"
    if rdb.exists():
        rdb.unlink()
    p = run([KLAYOUT, "-b", "-zz", "-r", DRC, "-rd", f"input={gds}",
             "-rd", "topcell=dac_cdac_ihp", "-rd", f"report={rdb}",
             "-rd", "no_recommended=true", "-rd", "run_mode=deep",
             "-rd", "thr=8"])
    (BUILD / "ihp_drc.log").write_text(p.stdout + p.stderr)
    drc_items = (len(ET.parse(rdb).getroot().findall("./items/item"))
                 if rdb.is_file() else -1)

    ref = BUILD / "cdac_ihp_ref.cdl"
    ports = [f"B{i}" for i in range(8)] + ["VCM", "VSH"]
    lines = [".subckt dac_cdac_ihp " + " ".join(ports)]
    for bits, m in ((7, 128), (6, 64), (5, 32), (4, 16), (3, 8), (2, 4),
                    (1, 2), (0, 1)):
        lines.append(f"C_b{bits} VSH B{bits} cap_cmim w=6.99u l=6.99u m={m}")
    lines.append("C_dummy VSH VCM cap_cmim w=6.99u l=6.99u m=1")
    lines.append(".ends")
    ref.write_text("\n".join(lines) + "\n")

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
             f"--netlist={ref}", "--topcell=dac_cdac_ihp",
             f"--run_dir={run_dir}"], env=lenv)
    (BUILD / "ihp_lvs.log").write_text(p.stdout + p.stderr)
    lvs_ok = "Status           | PASS" in (p.stdout + p.stderr)

    res = {
        "ok": bool(unit_ok and gate_ok and drc_items == 0 and lvs_ok),
        "pdk": "ihp-sg13g2",
        "unit_moscap": {
            "measured": unit_ok,
            "table": str(unit),
            "device": "sg13_moscap_p 2x1 um",
            "cu_ff_at_0V": 6.24413,
        },
        "signoff_cap": {
            "backend": "cmim 7x7 um",
            "cu_ff": meta["budget"]["c_unit_ff"],
            "c_tot_ff": meta["budget"]["c_tot_ff"],
            "dnl_lsb": dnl, "inl_lsb": inl,
            "fs_max_hz": fs,
            "gate": "PASS" if gate_ok else "FAIL",
            "seeds": 10,
            "sigma_rel": meta["sigma_rel"],
        },
        "moscap_study": {
            "dnl_lsb": mm["dnl"], "inl_lsb": mm["inl"],
            "note": "bias-dependent moscap; recorded as a study, not the gate",
        },
        "layout": {
            "units": 256,
            "gds": str(gds),
            "drc_items": drc_items,
            "drc_report": str(rdb),
            "lvs_ok": lvs_ok,
            "reference": str(ref),
            "lvs_run_dir": str(run_dir),
        },
        "logs": [str(BUILD / n) for n in
                 ("ihp_model_mim.log", "ihp_measure_mim.log",
                  "ihp_gen_gds.log", "ihp_drc.log", "ihp_lvs.log")],
    }
    (BUILD / "ihp_signoff.json").write_text(json.dumps(res, indent=2) + "\n")
    print(json.dumps(res, indent=2))
    return 0 if res["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
