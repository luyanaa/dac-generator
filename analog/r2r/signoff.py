#!/usr/bin/env python3
"""Signoff for the 8-bit R-2R DAC array (gf180mcuA): DRC, LVS, PEX.

    ./signoff.py                 # build + drc + lvs + pex, gate on all three
    ./signoff.py --stage drc     # one stage
    ./signoff.py --brief         # one line per gate

Every stage is fail-closed: a missing PDK, deck, tool, netlist or report is an
error, never a skipped view reported as a pass.

gf180 has no KLayout DRC deck installed, so all three gates go through Magic:

  drc  `drc check` + `drc catchup` on the top cell, then `drc count total`.
       Magic is the only gf180 rule checker present, and the rule it enforces
       here (M1.2a, 0.23 um) is the one the generator actually tripped: ra's
       right M1 terminal at 150.53 um against rb's p-tap tab at 150.67 um.

  lvs  Magic `ext2spice lvs` writes a netlist whose device parameters are the
       drawn r_length.  The gate is a graph check, not a netgen device compare:
       there is no schematic netlist for this macro, and the whole contract is
       topological (9 rows, the 1R chain, the termination 2R, 17 units of
       150 um and 8 trims of 148.36 um).  The expected graph is written below
       from the ladder definition, independently of gen_gds.py's placement
       tables, so a mistake in the generator cannot also pass the check.

  pex  Magic extraction with cthresh/rthresh 0 and hierarchy on.  The netlist
       is kept as evidence; the 25 device instances are asserted and the per-net
       geometric capacitance is reported, not gated.  Magic does not model the
       poly resistor's distributed R-C, so a post-layout ratio would need a
       model the deck does not have.

What this file does NOT do: a post-layout DC/transient sweep of the *whole*
DAC.  `--stage postlayout` runs `postlayout.py`, which reconstructs the poly
body R-C the Magic deck omits and compares a lumped against a segmented line;
that covers the ladder macro only.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent
BUILD = ROOT / "build"
GDS = BUILD / "r2r.gds"
MAGIC_DIR = BUILD / "magic"

KLAYOUT_BUILD = "/usr/bin/klayout"
TOP = "dac_r2r_ana"
NBITS = 8

# Drawn lengths (metres).  gen_gds.py passes unit_l / trim_l from r2r.yaml;
# these are the independent values the netlist must reproduce.
UNIT_L = 150.0e-6
TRIM_L = 148.36e-6

# The ladder: node i, with node 7 renamed to the external output.
NODE = {i: ("vout" if i == NBITS - 1 else f"n{i}") for i in range(NBITS)}
BITS = {f"b{i}" for i in range(NBITS)}
NODES = set(NODE.values())
PORTS = BITS | NODES | {"vss", "vout"}


def die(msg: str) -> None:
    print(f"error: {msg}", file=sys.stderr)
    raise SystemExit(2)


def run(cmd, cwd=None, env=None, timeout=1800):
    return subprocess.run([str(c) for c in cmd], cwd=str(cwd or ROOT),
                          env=env, capture_output=True, text=True,
                          timeout=timeout)


def find_pdk() -> Path:
    cands = []
    if os.environ.get("PDK_ROOT"):
        cands.append(Path(os.environ["PDK_ROOT"]))
    cands.append(Path.home() / ".ciel/ciel/gf180mcu/versions")
    for c in cands:
        if not c.is_dir():
            continue
        if (c / "gf180mcuA/libs.tech/magic").is_dir():
            return c
        hits = sorted(p for p in c.iterdir()
                      if (p / "gf180mcuA/libs.tech/magic").is_dir())
        if hits:
            return hits[-1]
    die("no gf180mcuA PDK found; set PDK_ROOT to the gf180 install")


def magicrc(pdk: Path) -> Path:
    p = pdk / "gf180mcuA/libs.tech/magic/gf180mcuA.magicrc"
    if not p.is_file():
        die(f"no gf180mcuA magicrc at {p}")
    return p


def magic_tech(pdk: Path) -> Path:
    return pdk / "gf180mcuA/libs.tech/magic"


def spice_val(tok: str) -> float:
    """SPICE engineering suffix -> float (only what the netlist emits)."""
    mult = {"t": 1e12, "g": 1e9, "meg": 1e6, "k": 1e3, "m": 1e-3,
            "u": 1e-6, "n": 1e-9, "p": 1e-12, "f": 1e-15}
    s = tok.strip().lower()
    for suf in ("meg", "t", "g", "k", "m", "u", "n", "p", "f"):
        if s.endswith(suf):
            return float(s[:-len(suf)]) * mult[suf]
    return float(s)


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


def magic(pdk: Path, script_name: str, body: str) -> Path:
    if not shutil.which("magic"):
        die("magic not found in PATH")
    MAGIC_DIR.mkdir(parents=True, exist_ok=True)
    tcl = MAGIC_DIR / script_name
    tcl.write_text(body)
    env = dict(os.environ)
    # gf180mcuA.magicrc falls back to a stale hardcoded ~/work/open-pdks build
    # path when PDK_ROOT is unset, and then loads no technology, exits 0 and
    # writes no netlist.  Both must be set explicitly.
    env["PDK_ROOT"] = str(pdk)
    env["MAGIC_TECH_PATH"] = str(magic_tech(pdk))
    proc = run(["magic", "-dnull", "-noconsole", "-rcfile", magicrc(pdk),
                tcl], cwd=MAGIC_DIR, env=env)
    log = MAGIC_DIR / (tcl.stem + ".log")
    log.write_text(proc.stdout + proc.stderr)
    for ext in MAGIC_DIR.glob("*.ext"):
        ext.unlink()
    return log


def read_top() -> str:
    return (f"gds read {GDS.with_suffix('')}\n"
            f"load {TOP}\n"
            "select top cell\n")


def drc(pdk: Path) -> dict:
    log = magic(pdk, "drc.tcl",
                read_top() +
                "drc on\n"
                "drc check\n"
                "drc catchup\n"
                "drc count total\n"
                "puts DRC_DONE\n"
                "quit\n")
    txt = log.read_text()
    if "DRC_DONE" not in txt:
        die("Magic DRC did not finish (see build/magic/drc.log)")
    hits = re.findall(r"Total DRC errors found:\s*(\d+)", txt)
    if not hits:
        die("Magic DRC produced no result line")
    items = int(hits[-1])

    by_rule: Counter = Counter()
    if items:
        # The count is known only to Python, so collect the rule breakdown in
        # a second pass with an explicit `drc find` loop.  `drc find` returns an
        # empty value in batch mode but prints the rule on the preceding line.
        log2 = magic(pdk, "drc_rules.tcl",
                     read_top() +
                     "drc on\n"
                     "drc check\n"
                     "drc catchup\n"
                     f"for {{set i 0}} {{$i < {items + 2}}} {{incr i}} {{\n"
                     "  drc find\n"
                     "}\n"
                     "puts DRC_DONE\n"
                     "quit\n")
        for rule in re.findall(r"\(([A-Za-z0-9_.]+)\)\s*$",
                               log2.read_text(), re.M):
            by_rule[rule] += 1
    return {"ok": items == 0, "items": items, "by_rule": dict(by_rule),
            "log": str(log)}


def _top_instances(txt: str):
    """Parse the top-level .subckt: (ports, [(name, nets, subckt)], body)."""
    m = re.search(r"^\.subckt\s+" + TOP + r"\s+(.*?)^\.ends", txt,
                  re.M | re.S)
    if not m:
        die(f"no .subckt {TOP} in the extracted netlist")
    header = m.group(1)
    lines = header.splitlines()
    ports = lines[0].split()
    body = "\n".join(lines[1:])
    insts = []
    for ln in lines[1:]:
        ln = ln.strip()
        if not ln.startswith("X"):
            continue
        f = ln.split()
        nets = [t for t in f[1:-1] if "=" not in t]
        insts.append((f[0], nets, f[-1]))
    return ports, insts, body


def _length_by_subckt(txt: str) -> dict:
    out = {}
    for mm in re.finditer(r"^\.subckt\s+(\S+)(.*?)^\.ends", txt, re.M | re.S):
        lm = re.search(r"r_length=(\S+)", mm.group(2))
        if lm:
            out[mm.group(1)] = spice_val(lm.group(1))
    return out


def _check_ladder(ports, insts, lens):
    """Return (problems, unit_edges, trim_edges) for the ladder."""
    problems = []
    unit, trim = [], []
    for name, nets, sub in insts:
        if sub not in lens:
            problems.append(f"{name}: unknown device subckt {sub}")
            continue
        ends = [n for n in nets if n.upper() != "VSUBS"]
        if len(ends) != 2:
            problems.append(f"{name}: {len(ends)} signal terminals, want 2")
            continue
        e = (ends[0], ends[1])
        L = lens[sub]
        if abs(L - UNIT_L) <= 1e-9:
            unit.append(e)
        elif abs(L - TRIM_L) <= 1e-9:
            trim.append(e)
        else:
            problems.append(f"{name}: r_length {L * 1e6:.3f} um is neither "
                            f"unit {UNIT_L * 1e6:.3f} nor trim {TRIM_L * 1e6:.3f}")

    if len(unit) != 17:
        problems.append(f"{len(unit)} unit resistors, want 17")
    if len(trim) != 8:
        problems.append(f"{len(trim)} trim resistors, want 8")

    missing = sorted(PORTS - set(ports))
    if missing:
        problems.append(f"ports not extracted: {missing}")

    def other(e, x):
        return e[1] if e[0] == x else e[0]

    # 2R branches: b_i -> (unit) -> mid_i -> (trim) -> N_i.
    mids = {}
    for i in range(NBITS):
        b = f"b{i}"
        inc = [e for e in unit if b in e]
        if len(inc) != 1:
            problems.append(f"{b}: {len(inc)} unit ends, want 1")
            continue
        mids[b] = other(inc[0], b)
    if len(set(mids.values())) != len(mids):
        problems.append("two bit branches share a mid node")

    used_unit, used_trim = [], []
    for i in range(NBITS):
        b = f"b{i}"
        if b not in mids:
            continue
        m = mids[b]
        inc = [e for e in trim if m in e]
        if len(inc) != 1:
            problems.append(f"mid of {b}: {len(inc)} trims, want 1")
            continue
        used_trim.append(inc[0])
        if other(inc[0], m) != NODE[i]:
            problems.append(f"{b}: trim lands on {other(inc[0], m)}, "
                            f"want {NODE[i]}")
        used_unit += [e for e in unit if b in e]

    # 1R chain N_0 - N_1 - ... - N_7.
    series = [e for e in unit if e[0] in NODES and e[1] in NODES]
    want = {frozenset((NODE[i], NODE[i + 1])) for i in range(NBITS - 1)}
    got = {frozenset(e) for e in series}
    if got != want:
        problems.append(f"1R chain is {sorted(map(sorted, got))}, "
                        f"want {sorted(map(sorted, want))}")
    used_unit += series

    # Termination 2R from N_0 to vss through one internal node.
    term = [e for e in unit if "vss" in e]
    if len(term) != 1:
        problems.append(f"{len(term)} units touch vss, want 1")
    else:
        t = other(term[0], "vss")
        inc = [e for e in unit if t in e]
        if len(inc) != 2:
            problems.append(f"termination mid: {len(inc)} units, want 2")
        else:
            nbrs = {other(e, t) for e in inc}
            if nbrs != {NODE[0], "vss"}:
                problems.append(f"termination is {sorted(nbrs)}, "
                                f"want {sorted({NODE[0], 'vss'})}")
            used_unit += inc

    # Nothing left unaccounted: catches an extra device or a wrong connection.
    if Counter(map(tuple, used_unit)) != Counter(map(tuple, unit)):
        problems.append("unit resistors not fully explained by the ladder")
    if len(used_trim) != len(set(used_trim)) or len(used_trim) != len(trim):
        problems.append("trim resistors not fully explained by the branches")

    return problems, unit, trim


def lvs(pdk: Path) -> dict:
    spice = MAGIC_DIR / "lvs.spice"
    if spice.exists():
        spice.unlink()
    magic(pdk, "extract_lvs.tcl",
          read_top() +
          "port makeall\n"
          "extract\n"
          "ext2spice lvs\n"
          f"ext2spice -o {spice}\n"
          "puts LVS_DONE\n"
          "quit\n")
    if not spice.is_file():
        die("Magic wrote no LVS netlist")
    txt = spice.read_text()
    ports, insts, _ = _top_instances(txt)
    lens = _length_by_subckt(txt)

    problems, unit, trim = _check_ladder(ports, insts, lens)

    devs = {"unit": len(unit), "trim": len(trim)}
    return {"ok": not problems, "ports": ports, "devices": devs,
            "unit_um": round(UNIT_L * 1e6, 3),
            "trim_um": round(TRIM_L * 1e6, 3),
            "problems": problems, "netlist": str(spice)}


def selftest() -> int:
    """Prove the LVS gate is not a no-op: real netlist passes, two mutations fail.

    Runs on the netlist already extracted by --stage lvs (or a full run), so it
    needs no tools of its own.
    """
    spice = MAGIC_DIR / "lvs.spice"
    if not spice.is_file():
        die("no build/magic/lvs.spice; run --stage lvs first")
    txt = spice.read_text()
    ports, insts, _ = _top_instances(txt)
    lens = _length_by_subckt(txt)

    ok = True
    problems, _, _ = _check_ladder(ports, insts, lens)
    print(f"selftest real      : {'PASS' if not problems else 'FAIL'} "
          f"({len(problems)} problems)")
    ok &= not problems

    drop = next((i for i, (_, _, sub) in enumerate(insts)
                 if sub in lens and abs(lens[sub] - UNIT_L) <= 1e-9), None)
    if drop is None:
        die("no unit resistor found in the netlist")
    mut1 = [x for i, x in enumerate(insts) if i != drop]
    p1, _, _ = _check_ladder(ports, mut1, lens)
    print(f"selftest drop-unit : {'FAIL' if p1 else 'PASS (bad!)'} "
          f"({len(p1)} problems)")
    ok &= bool(p1)

    mut2, done = [], False
    for name, nets, sub in insts:
        if (not done and sub in lens and abs(lens[sub] - TRIM_L) <= 1e-9):
            new = []
            for n in nets:
                if n.startswith("n") and n[1:].isdigit():
                    new.append("n1" if n != "n1" else "n2")
                    done = True
                else:
                    new.append(n)
            mut2.append((name, new, sub))
        else:
            mut2.append((name, nets, sub))
    p2, _, _ = _check_ladder(ports, mut2, lens)
    print(f"selftest wrong-node: {'FAIL' if p2 else 'PASS (bad!)'} "
          f"({len(p2)} problems)")
    ok &= bool(p2)

    print("selftest " + ("PASS" if ok else "FAIL"))
    return 0 if ok else 1


def pex(pdk: Path) -> dict:
    spice = MAGIC_DIR / "pex.spice"
    if spice.exists():
        spice.unlink()
    magic(pdk, "extract_pex.tcl",
          read_top() +
          "port makeall\n"
          "extract\n"
          # hierarchy on: keeps the 25 device instances as X lines in the top
          # subckt instead of flattening them into anonymous devices, so the
          # netlist states the ladder outright.
          "ext2spice hierarchy on\n"
          "ext2spice cthresh 0\n"
          "ext2spice rthresh 0\n"
          f"ext2spice -o {spice}\n"
          "puts PEX_DONE\n"
          "quit\n")
    if not spice.is_file():
        die("Magic wrote no PEX netlist")
    txt = spice.read_text()
    if "PEX_DONE" not in (MAGIC_DIR / "extract_pex.log").read_text():
        die("Magic PEX did not finish")
    ports, insts, body = _top_instances(txt)
    devs = sum(1 for _, _, sub in insts if sub.startswith("ppolyf_u"))
    if devs != 25:
        die(f"PEX netlist instantiates {devs} resistors, want 25")

    body_caps = sum(1 for ln in body.splitlines() if ln.startswith("C"))
    if body_caps == 0:
        die("PEX top subckt has no capacitance; extraction did not run")
    caps = sum(1 for ln in txt.splitlines() if ln.startswith("C"))

    tot: Counter = Counter()
    for mm in re.finditer(r"^C\S+\s+(\S+)\s+(\S+)\s+([-0-9.eE+]+[a-zA-Z]*)",
                          body, re.M):
        v = spice_val(mm.group(3))
        tot[mm.group(1)] += v
        tot[mm.group(2)] += v
    nets = ["vss", "vout"] + [f"n{i}" for i in range(NBITS - 1)] + \
        [f"b{i}" for i in range(NBITS)]
    net_cap = {n: round(tot.get(n, 0.0) * 1e15, 3) for n in nets}  # fF
    return {"ok": True, "netlist": str(spice), "bytes": spice.stat().st_size,
            "instances": devs, "caps": caps, "net_cap_ff": net_cap}


def postlayout() -> dict:
    """Run the poly R-C post-layout bench (postlayout.py) as a signoff stage.

    This is where the deck's missing resistor-body parasitics are put back:
    postlayout.py rebuilds them from the extracted geometry and the PDK model
    constants, then gates the result.  It is kept out of `all` because the
    60 us transient is minutes, not seconds, and `all` is the fast layout gate.
    """
    pl = ROOT / "postlayout.py"
    if not pl.is_file():
        die(f"no {pl}")
    proc = run([sys.executable, str(pl), "--stage", "all"], cwd=ROOT,
               timeout=7200)
    print(proc.stdout, end="")
    if proc.returncode != 0:
        print(proc.stderr, file=sys.stderr)
        die("postlayout bench failed")
    report = BUILD / "postlayout" / "postlayout.json"
    if not report.is_file():
        die("postlayout wrote no report")
    rep = json.loads(report.read_text())
    return {"ok": bool(rep.get("ok")), "report": str(report),
            "models": sorted(rep.get("models", {}))}


# --------------------------------------------------------------------------

def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--stage", default="all",
                    choices=["all", "build", "drc", "lvs", "pex",
                             "postlayout"])
    ap.add_argument("--brief", action="store_true")
    ap.add_argument("--selftest", action="store_true",
                    help="check the LVS graph gate against two mutations")
    a = ap.parse_args(argv)

    if a.selftest:
        return selftest()

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
              f"{r['devices']['unit']} unit + {r['devices']['trim']} trim "
              f"= {sum(r['devices'].values())} resistors, "
              f"{r['unit_um']}/{r['trim_um']} um")
        for p in r["problems"]:
            print(f"     {p}")
    if a.stage in ("all", "pex"):
        r = pex(pdk)
        rep["steps"]["pex"] = r
        print(f"pex  PASS  {r['instances']} instances, {r['caps']} C entries, "
              f"{r['bytes'] / 1e6:.2f} MB")
    if a.stage == "postlayout":
        r = postlayout()
        rep["steps"]["postlayout"] = r
        if not r["ok"]:
            failed.append("postlayout")
        print(f"postlayout {'PASS' if r['ok'] else 'FAIL'}  "
              f"models {', '.join(r['models'])}")

    rep["ok"] = not failed
    rep["failed"] = failed
    BUILD.mkdir(parents=True, exist_ok=True)
    (BUILD / "signoff.json").write_text(json.dumps(rep, indent=1) + "\n")
    label = "signoff" if a.stage == "all" else a.stage
    print(f"{label} {'PASS' if rep['ok'] else 'FAIL'}  "
          f"report {BUILD / 'signoff.json'}")
    if a.brief:
        print("VERDICT " + ("PASS" if rep["ok"] else "FAIL"))
    return 0 if rep["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
