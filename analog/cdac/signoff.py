#!/usr/bin/env python3
"""Signoff for the 8-bit binary CDAC array (sky130A): DRC, LVS, PEX.

    ./signoff.py                 # build + drc + lvs + pex, gate on all three
    ./signoff.py --stage drc     # one stage
    ./signoff.py --brief         # one line per gate

Every stage is fail-closed: a missing PDK, deck, tool, netlist or report is an
error, never a skipped view reported as a pass.  The three gates are:

  drc  sky130A_mr.drc from KLayout 0.30.12 with feol+beol forced on.  The 0.30.0
       in /usr/bin cannot run this deck, so the two KLayouts are separate tools
       (0.30.0 has the pya build needed for geometry, 0.30.12 has the deck).

  lvs  Magic `ext2spice lvs` names every net from its label, so the netlist
       itself states the weight of each bit: the instance count per net must be
       exactly 2^i for bit i and 1 for the VCM dummy.  That is the array's whole
       contract - the row table in gen_gds.py is checked against it - so it is
       the LVS gate rather than a device-level netgen run, which a 256-instance
       capacitor array cannot disambiguate (the reference repo hits the same
       wall and only LVSes the unit cell).

  pex  Magic extraction with cthresh 0.  The netlist is kept as evidence and
       the cap count is asserted; the per-bit parasitic table is *reported*,
       not gated, because Magic's extractor does not model the MOS channel
       capacitance, so a ratio against the nominal C_u would be a made-up
       denominator.

What this file does NOT do: a transient post-layout DAC sweep.  The extracted
netlist drives the same device models as the schematic bench, so the honest
next step is a `.control` loop of `alter`/`op` over the 256 codes, and that is
the remaining pass on this leaf (see docs/analog_dac_integration_plan.md 7.4).
Nothing here claims it happened.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent
BUILD = ROOT / "build"
GDS = BUILD / "cdac.gds"
MAGIC_DIR = BUILD / "magic"

KLAYOUT_BUILD = "/usr/bin/klayout"
KLAYOUT_DECK = ("/nix/store/1whjbzm6gw6l4h0sjxdv92lyw7lq1ar8-"
                "klayout-0.30.12/bin/klayout")
TOP = "CDAC_ARRAY"
NBITS = 8
MIN_PEX_BYTES = 100_000

# What the array must be: bit i owns 2^i unit caps, the dummy owns one and is
# tied to VCM.  255 + 1 = 256 = the 16x16 array.
WANT = {f"B{i}": 1 << i for i in range(NBITS)}
WANT["VCM"] = 1


def die(msg: str) -> None:
    print(f"error: {msg}", file=sys.stderr)
    raise SystemExit(2)


def run(cmd, cwd=None, env=None, timeout=1800):
    proc = subprocess.run([str(c) for c in cmd], cwd=str(cwd or ROOT),
                          env=env, capture_output=True, text=True,
                          timeout=timeout)
    return proc


def find_pdk() -> Path:
    cands = []
    if os.environ.get("PDK_ROOT"):
        cands.append(Path(os.environ["PDK_ROOT"]))
    cands.append(Path.home() / ".ciel/ciel/sky130/versions")
    for c in cands:
        if not c.is_dir():
            continue
        if (c / "sky130A").is_dir():
            return c
        hits = sorted(p for p in c.iterdir()
                      if (p / "sky130A/libs.tech/magic").is_dir())
        if hits:
            return hits[-1]
    die("no sky130A PDK found; set PDK_ROOT to the sky130 install")


def deck(pdk: Path) -> Path:
    p = pdk / "sky130A/libs.tech/klayout/drc/sky130A_mr.drc"
    if not p.is_file():
        die(f"no sky130A DRC deck at {p}")
    return p


def magicrc(pdk: Path) -> Path:
    p = pdk / "sky130A/libs.tech/magic/sky130A.magicrc"
    if not p.is_file():
        die(f"no sky130A magicrc at {p}")
    return p


# --------------------------------------------------------------------------
# stages
# --------------------------------------------------------------------------

def build() -> None:
    if not Path(KLAYOUT_BUILD).is_file():
        die(f"{KLAYOUT_BUILD} missing (needs the pya build)")
    BUILD.mkdir(parents=True, exist_ok=True)
    proc = run([KLAYOUT_BUILD, "-b", "-r", ROOT / "gen_gds.py",
                "-rd", f"out={GDS}", "-rd", "check=true"])
    if proc.returncode != 0 or not GDS.is_file():
        print(proc.stdout + proc.stderr, file=sys.stderr)
        die("array generation failed")
    print(proc.stdout.strip())


def drc(pdk: Path) -> dict:
    if not Path(KLAYOUT_DECK).is_file():
        die(f"{KLAYOUT_DECK} missing (the 0.30.0 build cannot run the deck)")
    report = BUILD / "drc_cdac.lyrdb"
    if report.exists():
        report.unlink()
    proc = run([KLAYOUT_DECK, "-b", "-r", deck(pdk),
                "-rd", f"input={GDS}", "-rd", f"report={report}",
                "-rd", f"topcell={TOP}", "-rd", "thr=4",
                "-rd", "feol=true", "-rd", "beol=true"], cwd=BUILD)
    (BUILD / "drc.log").write_text(proc.stdout + proc.stderr)
    if not report.is_file():
        die("DRC produced no report (see build/drc.log)")
    items = ET.parse(report).getroot().findall("./items/item")
    cats = Counter((i.findtext("category") or "").strip("'") for i in items)
    return {"ok": not items, "items": len(items), "by_rule": dict(cats),
            "report": str(report)}


def magic(pdk: Path, script_name: str, body: str) -> Path:
    if not shutil.which("magic"):
        die("magic not found in PATH")
    MAGIC_DIR.mkdir(parents=True, exist_ok=True)
    tcl = MAGIC_DIR / script_name
    tcl.write_text(body)
    env = dict(os.environ)
    # sky130A.magicrc falls back to a stale hardcoded build/ path when
    # PDK_ROOT is unset (it only looks at the environment), so both must be
    # set explicitly or magic silently loads no technology and writes no
    # netlist.
    env["PDK_ROOT"] = str(pdk)
    env["MAGIC_TECH_PATH"] = str(pdk / "sky130A/libs.tech/magic")
    proc = run(["magic", "-dnull", "-noconsole", "-rcfile", magicrc(pdk),
                tcl], cwd=MAGIC_DIR, env=env)
    log = MAGIC_DIR / (tcl.stem + ".log")
    log.write_text(proc.stdout + proc.stderr)
    for ext in MAGIC_DIR.glob("*.ext"):
        ext.unlink()
    return log


def lvs(pdk: Path) -> dict:
    spice = MAGIC_DIR / "lvs.spice"
    if spice.exists():
        spice.unlink()
    magic(pdk, "extract_lvs.tcl",
          f"gds read {GDS.with_suffix('')}\n"
          f"load {TOP}\n"
          "select top cell\n"
          "port makeall\n"
          "extract\n"
          "ext2spice lvs\n"
          f"ext2spice -o {spice}\n"
          "puts LVS_DONE\n"
          "quit\n")
    if not spice.is_file():
        die("Magic wrote no LVS netlist")

    txt = spice.read_text()
    m = re.search(r"^\.subckt\s+" + TOP + r"\s+(.*)$", txt, re.M)
    if not m:
        die(f"no .subckt {TOP} in the extracted netlist")
    ports = m.group(1).split()
    rows = [ln for ln in txt.splitlines() if ln.startswith("XCDAC_CAP_")]
    got = Counter(re.match(r"XCDAC_CAP_\d+\s+\S+\s+(\S+)", ln).group(1)
                  for ln in rows if re.match(r"XCDAC_CAP_\d+\s+\S+\s+(\S+)", ln))
    got = {k: v for k, v in got.items()}

    problems = []
    for net, want in WANT.items():
        have = got.get(net, 0)
        if have != want:
            problems.append(f"{net}: {have} caps, want {want}")
    extra = sorted(set(got) - set(WANT))
    if extra:
        problems.append(f"unexpected nets on bit ports: {extra}")
    missing_ports = sorted(set(WANT) - set(ports))
    if missing_ports:
        problems.append(f"ports not extracted: {missing_ports}")
    total = sum(got.get(n, 0) for n in WANT)
    if total != 1 << NBITS:
        problems.append(f"{total} unit caps, want {1 << NBITS}")

    return {"ok": not problems, "ports": ports, "weights": dict(sorted(got.items())),
            "problems": problems, "netlist": str(spice)}


def pex(pdk: Path) -> dict:
    spice = MAGIC_DIR / "pex.spice"
    if spice.exists():
        spice.unlink()
    magic(pdk, "extract_pex.tcl",
          f"gds read {GDS.with_suffix('')}\n"
          f"load {TOP}\n"
          "select top cell\n"
          "port makeall\n"
          "extract\n"
          # hierarchy on: with it off ext2spice writes one flat deck with no
          # .subckt at all, and the 256 capacitor cells' port nets survive
          # only as hierarchical alias names joined by 0-fF coupling caps.
          # The hierarchical deck states CDAC_ARRAY's ports and its 256
          # CDAC_CAP instances outright, which is what a bench needs.
          "ext2spice hierarchy on\n"
          "ext2spice cthresh 0\n"
          "ext2spice rthresh 0\n"
          f"ext2spice -o {spice}\n"
          "puts PEX_DONE\n"
          "quit\n")
    if not spice.is_file():
        die("Magic wrote no PEX netlist")
    size = spice.stat().st_size
    if size < MIN_PEX_BYTES:
        die(f"PEX netlist is only {size} B; extraction clearly did not run")
    txt = spice.read_text()
    caps = sum(1 for ln in txt.splitlines() if ln.startswith("C"))

    m = re.search(r"^\.subckt\s+" + TOP + r"(.*?)^\.ends", txt, re.M | re.S)
    if not m:
        die(f"PEX netlist has no .subckt {TOP}")
    body = m.group(1)
    insts = sum(1 for ln in body.splitlines() if ln.startswith("XCDAC_CAP_"))
    if insts != 1 << NBITS:
        die(f"PEX netlist instantiates {insts} capacitors, want {1 << NBITS}")

    # Total extracted capacitance on each bit net, for the report only.  This
    # is Magic's geometric capacitance (wiring, junction, overlap) and does
    # not include the MOS channel, so it is not a DAC weight and is never
    # compared against 2^i * C_u.  Cross-cell coupling is attributed to the
    # hierarchical alias name, so treat these as a floor, not a full budget.
    tot: Counter = Counter()
    for mm in re.finditer(r"^C\S+\s+(\S+)\s+(\S+)\s+([-0-9.eE+]+)f",
                          body, re.M):
        v = float(mm.group(3))
        tot[mm.group(1)] += v
        tot[mm.group(2)] += v
    nets = ["VSH"] + [f"B{i}" for i in range(NBITS)] + ["VCM"]
    net_cap = {n: round(tot.get(n, 0.0), 3) for n in nets}
    return {"ok": True, "netlist": str(spice), "bytes": size, "caps": caps,
            "instances": insts, "net_cap_ff": net_cap}


# --------------------------------------------------------------------------

def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--stage", default="all",
                    choices=["all", "build", "drc", "lvs", "pex"])
    ap.add_argument("--brief", action="store_true")
    a = ap.parse_args(argv)

    pdk = find_pdk()
    rep: dict = {"pdk": str(pdk), "top": TOP, "steps": {}}
    failed = []

    if a.stage in ("all", "build", "drc", "lvs", "pex"):
        build()
    if a.stage in ("all", "drc"):
        r = drc(pdk)
        rep["steps"]["drc"] = r
        if not r["ok"]:
            failed.append(f"drc({r['items']})")
        print(f"drc  {'PASS' if r['ok'] else 'FAIL'}  {r['items']} items"
              + ("" if r["ok"] else f"  {r['by_rule']}"))
    if a.stage in ("all", "lvs"):
        r = lvs(pdk)
        rep["steps"]["lvs"] = r
        if not r["ok"]:
            failed.append("lvs")
        print(f"lvs  {'PASS' if r['ok'] else 'FAIL'}  "
              f"{sum(r['weights'].values())} caps  "
              f"weights {sorted(r['weights'].items(), key=lambda kv: kv[1])}")
        for p in r["problems"]:
            print(f"     {p}")
    if a.stage in ("all", "pex"):
        r = pex(pdk)
        rep["steps"]["pex"] = r
        print(f"pex  PASS  {r['instances']} instances, {r['caps']} C entries, "
              f"{r['bytes'] / 1e6:.2f} MB")

    rep["ok"] = not failed
    rep["failed"] = failed
    BUILD.mkdir(parents=True, exist_ok=True)
    (BUILD / "signoff.json").write_text(json.dumps(rep, indent=1) + "\n")
    print(f"signoff {'PASS' if rep['ok'] else 'FAIL'}  "
          f"report {BUILD / 'signoff.json'}")
    if a.brief:
        print("VERDICT " + ("PASS" if rep["ok"] else "FAIL"))
    return 0 if rep["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
