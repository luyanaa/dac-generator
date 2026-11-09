#!/usr/bin/env python3
"""Signoff for the 8-bit resistor-string array (gf180mcuA): DRC, LVS, PEX.

    ./signoff.py                 # build + drc + lvs + pex, gate on all three
    ./signoff.py --stage drc
    ./signoff.py --selftest      # prove the LVS gate rejects mutations

This is the P2 counterpart of `../../r2r/signoff.py`.  The P2 leaf has two
parts, and only one of them is generated: the 255-unit string is a device
array (`gen_gds.py`), while the 255-transmission-gate tree and the output
follower are class C.  So the gates below sign off the *string macro*, not the
whole DAC, and they say so.

  drc  Magic `drc check` / `drc catchup` / `drc count total`, same fail-closed
       path as P1.  gf180 has no KLayout deck in this install.

  lvs  Magic-extracted netlist.  The contract is a 255-edge series chain from
       `vss` to `vref` with taps `t1..t254` in ascending order, every device a
       single 5.714 um unit.  The expected chain is written independently of
       gen_gds.py's pitch table.

  pex  hierarchical extraction, cthresh/rthresh 0; 255 instances and the per-net
       geometric capacitance, kept as evidence.

Not claimed: the TG tree, the follower, post-layout linearity.
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
GDS = BUILD / "string.gds"
MAGIC_DIR = BUILD / "magic"

KLAYOUT_BUILD = "/usr/bin/klayout"
TOP = "dac_string_ana"
NBITS = 8
NUNITS = 2 ** NBITS - 1
UNIT_L = 5.714e-6
UNIT_W = 2.0e-6

TAPS = [f"t{i}" for i in range(1, NUNITS)]
PORTS = {"vss", "vref"} | set(TAPS)


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
    die("no gf180mcuA PDK found; set PDK_ROOT")


def magicrc(pdk: Path) -> Path:
    p = pdk / "gf180mcuA/libs.tech/magic/gf180mcuA.magicrc"
    if not p.is_file():
        die(f"no gf180mcuA magicrc at {p}")
    return p


def magic_tech(pdk: Path) -> Path:
    return pdk / "gf180mcuA/libs.tech/magic"


def spice_val(tok: str) -> float:
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
        die("string generation failed")
    print(proc.stdout.strip())


def magic(pdk: Path, script_name: str, body: str) -> Path:
    if not shutil.which("magic"):
        die("magic not found in PATH")
    MAGIC_DIR.mkdir(parents=True, exist_ok=True)
    tcl = MAGIC_DIR / script_name
    tcl.write_text(body)
    env = dict(os.environ)
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
    return {"ok": items == 0, "items": items, "log": str(log)}


def _top_instances(txt: str):
    m = re.search(r"^\.subckt\s+" + TOP + r"\s+(.*?)^\.ends", txt,
                  re.M | re.S)
    if not m:
        die(f"no .subckt {TOP} in the extracted netlist")
    lines = m.group(1).splitlines()
    # Magic wraps long port lists onto `+ ...` continuation lines.
    i = 0
    hdr = []
    while i < len(lines) and (i == 0 or lines[i].lstrip().startswith("+")):
        hdr.append(lines[i])
        i += 1
    ports = " ".join(hdr).replace("+", " ").split()
    body = "\n".join(lines[i:])
    insts = []
    for ln in lines[i:]:
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


def _dev_blocks(txt: str) -> dict:
    out = {}
    for m in re.finditer(r"^\.subckt\s+(\S+)\s+(.*?)^\.ends", txt,
                         re.M | re.S):
        lines = m.group(2).splitlines()
        out[m.group(1)] = (lines[0].split() if lines else [], lines[1:])
    return out


def _bulk_pos(blocks: dict, sub: str) -> int | None:
    """Instance position of the bulk terminal, from the device's own X0 line.

    Magic connects the resistor's p-tap to whatever net the layout uses.  In
    the R-2R that was the unlabelled `VSUBS`; here the p-tap bus is labelled
    `vss`, so filtering by name would leave three terminals.  Resolve the
    position instead, using the model's (p, n, b) order.
    """
    if sub not in blocks:
        return None
    ports, body = blocks[sub]
    for ln in body:
        if ln.strip().startswith("X0 "):
            f = ln.split()
            bnode = f[3]
            if bnode in ports:
                return ports.index(bnode)
    return None


def _check_chain(ports, insts, lens, blocks):
    """Return (problems, edges).  Every device is a 2-terminal unit resistor."""
    problems = []
    edges = []
    for name, nets, sub in insts:
        if sub not in lens:
            problems.append(f"{name}: unknown device subckt {sub}")
            continue
        bi = _bulk_pos(blocks, sub)
        ends = [n for i, n in enumerate(nets) if i != bi]
        if len(ends) != 2:
            problems.append(f"{name}: {len(ends)} signal terminals, want 2")
            continue
        L = lens[sub]
        if abs(L - UNIT_L) > 1e-9:
            problems.append(f"{name}: r_length {L * 1e6:.3f} um, "
                            f"want {UNIT_L * 1e6:.3f}")
        edges.append(tuple(ends))

    if len(edges) != NUNITS:
        problems.append(f"{len(edges)} resistors, want {NUNITS}")

    missing = sorted(PORTS - set(ports))
    if missing:
        problems.append(f"ports not extracted: {missing}")

    # Series chain from vss to vref through every tap in order.
    adj: dict[str, list[str]] = {}
    for a, b in edges:
        adj.setdefault(a, []).append(b)
        adj.setdefault(b, []).append(a)
    for n, nb in adj.items():
        if len(nb) > 2:
            problems.append(f"{n}: {len(nb)} neighbours (not a simple chain)")

    want_internal = TAPS
    if "vss" not in adj or "vref" not in adj:
        problems.append("chain endpoints vss/vref missing")
        return problems, edges

    path, prev, cur = ["vss"], None, "vss"
    seen = {"vss"}
    while cur != "vref" and len(path) <= NUNITS + 1:
        nxt = [n for n in adj.get(cur, []) if n != prev and n not in seen]
        if not nxt:
            problems.append(f"chain stops at {cur}")
            break
        if len(nxt) > 1:
            problems.append(f"chain branches at {cur}: {nxt}")
        cur = nxt[0]
        path.append(cur)
        seen.add(cur)
        prev = path[-2]
    if path[-1] != "vref":
        problems.append(f"chain ends at {path[-1]}, want vref")
    if len(path) != NUNITS + 1:
        problems.append(f"chain has {len(path) - 1} edges, want {NUNITS}")
    internal = path[1:-1]
    if internal != want_internal:
        problems.append("tap order is not t1..t254 along the chain")
    unused = set(adj) - set(path)
    if unused:
        problems.append(f"nodes not on the chain: {sorted(unused)}")
    return problems, edges


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
    blocks = _dev_blocks(txt)
    problems, edges = _check_chain(ports, insts, lens, blocks)
    return {"ok": not problems, "ports": len(ports), "devices": len(edges),
            "unit_um": round(UNIT_L * 1e6, 3), "problems": problems,
            "netlist": str(spice)}


def selftest() -> int:
    spice = MAGIC_DIR / "lvs.spice"
    if not spice.is_file():
        die("no build/magic/lvs.spice; run --stage lvs first")
    txt = spice.read_text()
    ports, insts, _ = _top_instances(txt)
    lens = _length_by_subckt(txt)
    blocks = _dev_blocks(txt)
    ok = True
    p, _ = _check_chain(ports, insts, lens, blocks)
    print(f"selftest real      : {'PASS' if not p else 'FAIL'} ({len(p)})")
    ok &= not p

    drop = insts[:NUNITS // 2] + insts[NUNITS // 2 + 1:]
    p1, _ = _check_chain(ports, drop, lens, blocks)
    print(f"selftest drop-unit : {'FAIL' if p1 else 'PASS (bad!)'} ({len(p1)})")
    ok &= bool(p1)

    mut, done = [], False
    for name, nets, sub in insts:
        if not done and "t100" in nets:
            new = [("t101" if n == "t100" else n) for n in nets]
            mut.append((name, new, sub))
            done = True
        else:
            mut.append((name, nets, sub))
    if not done:
        die("no t100 in the extracted netlist")
    p2, _ = _check_chain(ports, mut, lens, blocks)
    print(f"selftest swap-tap  : {'FAIL' if p2 else 'PASS (bad!)'} ({len(p2)})")
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
          "ext2spice hierarchy on\n"
          "ext2spice cthresh 0\n"
          "ext2spice rthresh 0\n"
          f"ext2spice -o {spice}\n"
          "puts PEX_DONE\n"
          "quit\n")
    if not spice.is_file():
        die("Magic wrote no PEX netlist")
    txt = spice.read_text()
    ports, insts, body = _top_instances(txt)
    devs = sum(1 for _, _, sub in insts if sub.startswith("ppolyf_u"))
    if devs != NUNITS:
        die(f"PEX netlist instantiates {devs} resistors, want {NUNITS}")
    caps = sum(1 for ln in body.splitlines() if ln.startswith("C"))
    if caps == 0:
        die("PEX top subckt has no capacitance; extraction did not run")
    tot = Counter()
    for mm in re.finditer(r"^C\S+\s+(\S+)\s+(\S+)\s+([-0-9.eE+]+[a-zA-Z]*)",
                          body, re.M):
        v = spice_val(mm.group(3))
        tot[mm.group(1)] += v
        tot[mm.group(2)] += v
    nets = ["vss", "vref"] + TAPS
    net_cap = {n: round(tot.get(n, 0.0) * 1e15, 3) for n in nets}
    return {"ok": True, "netlist": str(spice), "bytes": spice.stat().st_size,
            "instances": devs, "caps": caps, "net_cap_ff": net_cap}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--stage", default="all",
                    choices=["all", "build", "drc", "lvs", "pex"])
    ap.add_argument("--selftest", action="store_true")
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
        print(f"drc  {'PASS' if r['ok'] else 'FAIL'}  {r['items']} items")
    if a.stage in ("all", "lvs"):
        r = lvs(pdk)
        rep["steps"]["lvs"] = r
        if not r["ok"]:
            failed.append("lvs")
        print(f"lvs  {'PASS' if r['ok'] else 'FAIL'}  {r['devices']} units "
              f"({r['unit_um']} um), {r['ports']} ports")
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
    label = "signoff" if a.stage == "all" else a.stage
    print(f"{label} {'PASS' if rep['ok'] else 'FAIL'}  "
          f"report {BUILD / 'signoff.json'}")
    return 0 if rep["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
