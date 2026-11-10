#!/usr/bin/env python3
"""Signoff for the unit-current-source array (gf180mcuA): DRC, LVS, PEX.

    ./signoff.py                 # build + drc + lvs + pex, gate on all three
    ./signoff.py --stage drc
    ./signoff.py --selftest      # prove the LVS gate rejects mutations

This is the P3 counterpart of `../string/signoff.py`.  Only the *device array*
is generated (`gen_gds.py`): 30 cascoded-PMOS unit cells with shared vdd/vbp/
vcp rails and per-output pads, plus the two-device replica cascode bias
generator at the right end.  The switch matrix, the I-V resistor and the
differential wrapper stay class C (hand layout), so the gates below sign off
the current-source macro with its bias, not the whole DAC, and they say so.

  drc  Magic `drc check` / `drc catchup` / `drc count total`, same fail-closed
       path as P1/P2.  gf180 has no KLayout deck in this install.

  lvs  Flat Magic netlist.  The contract is written independently of the
       generator's placement: 30 unit cells (one mirror + one cascode each),
       every mirror s=vdd/g=vbp/d=internal, every cascode s=internal/g=vcp/
       d=output, bulk=vdd, 30 internal nodes, and the 4+4 segmentation's output
       fan-out (1 unary device per oU*, and 1/2/4/8 devices on oB1/oB2/oB4/oB8).
       Plus the replica bias: one 8/1 diode vdd->vbp and one 8/0.5 diode
       vbp->vcp, so vcp sits one cascode Vgs below the mirror gate.

  pex  hierarchical extraction, cthresh/rthresh 0; 62 instances and the per-net
       geometric capacitance, kept as evidence.

Not claimed: the switches, bias, output resistor, post-layout linearity.
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
GDS = BUILD / "csteer.gds"
MAGIC_DIR = BUILD / "magic"

KLAYOUT_BUILD = "/usr/bin/klayout"
TOP = "dac_csteer_ana"
YAML = ROOT / "csteer.yaml"

# Device geometry the generator is expected to produce (um).
EXPECTED_W_UM = 8.0
MIR_L_UM = 1.0
CAS_L_UM = 0.5


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


def load_cfg() -> dict:
    try:
        import yaml
    except ImportError:  # pragma: no cover
        die("PyYAML is required: pip install pyyaml")
    with open(YAML) as f:
        return yaml.safe_load(f)


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
        die("csteer generation failed")
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


def parse_flat(txt: str):
    """Return (devices, scale_m).

    Devices are `Xname d g s b subckt [k=v ...]` in Magic's mirror terminal
    order (d, g, s, b).  `.option scale=5n` gives the length/width unit.
    """
    scale = 5e-9
    m = re.search(r"^\.option\s+scale=(\S+)", txt, re.M)
    if m:
        scale = spice_val(m.group(1))
    devs = []
    for ln in txt.splitlines():
        s = ln.strip()
        if not s.startswith("X"):
            continue
        f = s.split()
        if len(f) < 6:
            continue
        params = dict(t.split("=", 1) for t in f[6:] if "=" in t)
        devs.append((f[0], f[1:5], f[5], params))
    return devs, scale


def check(devs, scale, cfg) -> list[str]:
    problems: list[str] = []
    ub = int(cfg.get("unary_bits", 4))
    bb = int(cfg.get("binary_bits", 4))
    n_unary = 2 ** ub - 1
    weights = [2 ** i for i in range(bb)]
    n_cells = n_unary + sum(weights)

    out_ports = {f"oU{i}" for i in range(n_unary)} | {f"oB{w}" for w in weights}
    ports = {"vdd", "vbp", "vcp"} | out_ports

    def um(tok: str) -> float:
        return spice_val(tok) * scale * 1e6

    mirrors = []   # (name, d, s, L)
    cascodes = []  # (name, d, s, L)
    bias_mirrors = []
    bias_cascodes = []
    allnets: set[str] = set()
    for name, nets, sub, params in devs:
        d, g, s, b = nets
        allnets.update(nets)
        if not sub.startswith("pfet"):
            problems.append(f"{name}: unexpected device {sub}")
            continue
        if "l" not in params or "w" not in params:
            problems.append(f"{name}: missing l/w")
            continue
        L, W = um(params["l"]), um(params["w"])
        if abs(W - EXPECTED_W_UM) > 1e-6:
            problems.append(f"{name}: w {W:.3f} um, want {EXPECTED_W_UM:.3f}")
        if b != "vdd":
            problems.append(f"{name}: bulk {b}, want vdd")
        if g == "vbp" and d == "vbp":
            # Replica bias mirror: diode-connected from vdd to vbp.
            if abs(L - MIR_L_UM) > 1e-6:
                problems.append(f"{name}: bias mirror l {L:.3f}, want {MIR_L_UM}")
            if s != "vdd":
                problems.append(f"{name}: bias mirror source {s}, want vdd")
            bias_mirrors.append((name, d, s, L))
        elif g == "vcp" and d == "vcp":
            # Replica bias cascode: diode-connected from vbp to vcp.  Its
            # source must be vbp, i.e. the mirror diode it stacks on.
            if abs(L - CAS_L_UM) > 1e-6:
                problems.append(f"{name}: bias cascode l {L:.3f}, want {CAS_L_UM}")
            if s != "vbp":
                problems.append(f"{name}: bias cascode source {s}, want vbp")
            bias_cascodes.append((name, d, s, L))
        elif g == "vbp":
            if abs(L - MIR_L_UM) > 1e-6:
                problems.append(f"{name}: mirror l {L:.3f}, want {MIR_L_UM}")
            if s != "vdd":
                problems.append(f"{name}: mirror source {s}, want vdd")
            if d in ports:
                problems.append(f"{name}: mirror drain {d} is a port")
            mirrors.append((name, d, s, L))
        elif g == "vcp":
            if abs(L - CAS_L_UM) > 1e-6:
                problems.append(f"{name}: cascode l {L:.3f}, want {CAS_L_UM}")
            if s in ports:
                problems.append(f"{name}: cascode source {s} is a port")
            if d not in out_ports:
                problems.append(f"{name}: cascode drain {d} not an output")
            cascodes.append((name, d, s, L))
        else:
            problems.append(f"{name}: gate net {g}, want vbp or vcp")

    if len(devs) != 2 * n_cells + 2:
        problems.append(f"{len(devs)} devices, want {2 * n_cells + 2} "
                        f"(2 per cell + replica bias)")
    if len(mirrors) != n_cells:
        problems.append(f"{len(mirrors)} mirrors, want {n_cells}")
    if len(cascodes) != n_cells:
        problems.append(f"{len(cascodes)} cascodes, want {n_cells}")
    if len(bias_mirrors) != 1:
        problems.append(f"{len(bias_mirrors)} bias mirrors, want 1")
    if len(bias_cascodes) != 1:
        problems.append(f"{len(bias_cascodes)} bias cascodes, want 1")

    m_int = Counter(d for _, d, _, _ in mirrors)
    c_int = Counter(s for _, _, s, _ in cascodes)
    if set(m_int) != set(c_int):
        only_m = sorted(set(m_int) - set(c_int))
        only_c = sorted(set(c_int) - set(m_int))
        problems.append(f"internal nodes differ: mirror-only {only_m}, "
                        f"cascode-only {only_c}")
    for n, k in m_int.items():
        if k != 1:
            problems.append(f"{n}: {k} mirror drains")
    for n, k in c_int.items():
        if k != 1:
            problems.append(f"{n}: {k} cascode sources")
    if len(m_int) != n_cells:
        problems.append(f"{len(m_int)} internal nodes, want {n_cells}")

    fan = Counter(d for _, d, _, _ in cascodes)
    for i in range(n_unary):
        if fan.get(f"oU{i}", 0) != 1:
            problems.append(f"oU{i}: {fan.get(f'oU{i}', 0)} devices, want 1")
    for w in weights:
        if fan.get(f"oB{w}", 0) != w:
            problems.append(f"oB{w}: {fan.get(f'oB{w}', 0)} devices, want {w}")

    want_nets = 3 + n_cells + n_unary + len(weights)
    if len(allnets) != want_nets:
        problems.append(f"{len(allnets)} nets, want {want_nets}")

    return problems


def lvs(pdk: Path) -> dict:
    spice = MAGIC_DIR / "lvs.spice"
    if spice.exists():
        spice.unlink()
    magic(pdk, "extract_lvs.tcl",
          read_top() +
          "port makeall\n"
          "extract\n"
          "ext2spice hierarchy off\n"
          "ext2spice subcircuits off\n"
          f"ext2spice -o {spice}\n"
          "puts LVS_DONE\n"
          "quit\n")
    if not spice.is_file():
        die("Magic wrote no LVS netlist")
    devs, scale = parse_flat(spice.read_text())
    cfg = load_cfg()
    problems = check(devs, scale, cfg)
    ub = int(cfg.get("unary_bits", 4))
    bb = int(cfg.get("binary_bits", 4))
    n_cells = 2 ** ub - 1 + sum(2 ** i for i in range(bb))
    return {"ok": not problems, "devices": len(devs), "cells": n_cells,
            "bias": 2, "scale_nm": round(scale * 1e9, 3),
            "problems": problems, "netlist": str(spice)}


def _top_body(txt: str):
    m = re.search(r"^\.subckt\s+" + TOP + r"\s+(.*?)^\.ends", txt,
                  re.M | re.S)
    if not m:
        die(f"no .subckt {TOP} in the extracted netlist")
    lines = m.group(1).splitlines()
    i = 0
    while i < len(lines) and (i == 0 or lines[i].lstrip().startswith("+")):
        i += 1
    return lines[i:]


def selftest() -> int:
    spice = MAGIC_DIR / "lvs.spice"
    if not spice.is_file():
        die("no build/magic/lvs.spice; run --stage lvs first")
    devs, scale = parse_flat(spice.read_text())
    cfg = load_cfg()
    ub = int(cfg.get("unary_bits", 4))
    n_unary = 2 ** ub - 1

    ok = True
    p = check(devs, scale, cfg)
    print(f"selftest real      : {'PASS' if not p else 'FAIL'} ({len(p)})")
    ok &= not p

    # Drop the middle mirror: the cell count and the internal-node match break.
    # Cell mirrors only (g=vbp, d!=vbp); the bias mirror is a separate class.
    mir_idx = [i for i, d in enumerate(devs)
               if d[1][1] == "vbp" and d[1][0] != "vbp"]
    if not mir_idx:
        die("no vbp-gated devices in the extracted netlist")
    drop = [d for i, d in enumerate(devs) if i != mir_idx[len(mir_idx) // 2]]
    p1 = check(drop, scale, cfg)
    print(f"selftest drop-unit : {'FAIL' if p1 else 'PASS (bad!)'} ({len(p1)})")
    ok &= bool(p1)

    # Move one mirror gate to vcp: it becomes a wrong-length "cascode".
    i = mir_idx[0]
    name, nets, sub, params = devs[i]
    mut = list(devs)
    mut[i] = (name, [nets[0], "vcp", nets[2], nets[3]], sub, params)
    p2 = check(mut, scale, cfg)
    print(f"selftest swap-gate : {'FAIL' if p2 else 'PASS (bad!)'} ({len(p2)})")
    ok &= bool(p2)

    # Short two outputs: oU0's cascode is renamed onto oU1.
    cas_idx = [i for i, d in enumerate(devs) if d[1][1] == "vcp"]
    done = False
    mut2 = list(devs)
    for i in cas_idx:
        name, nets, sub, params = mut2[i]
        if nets[0] == "oU0":
            mut2[i] = (name, ["oU1", nets[1], nets[2], nets[3]], sub, params)
            done = True
            break
    if not done:
        p3 = ["oU0 not found"]
    else:
        p3 = check(mut2, scale, cfg)
    print(f"selftest short-out : {'FAIL' if p3 else 'PASS (bad!)'} ({len(p3)})")
    ok &= bool(p3)

    # Bias diode stack: break the mirror diode and lift the cascode's source
    # off vbp.  Both must be rejected on the bias class checks alone.
    bm = [i for i, d in enumerate(devs)
          if d[1][1] == "vbp" and d[1][0] == "vbp"]
    bc = [i for i, d in enumerate(devs)
          if d[1][1] == "vcp" and d[1][0] == "vcp"]
    if bm and bc:
        mut3 = list(devs)
        name, nets, sub, params = mut3[bm[0]]
        mut3[bm[0]] = (name, [nets[0], "vcp", nets[2], nets[3]], sub, params)
        p4 = check(mut3, scale, cfg)
        mut4 = list(devs)
        name, nets, sub, params = mut4[bc[0]]
        mut4[bc[0]] = (name, [nets[0], nets[1], "vdd", nets[3]], sub, params)
        p5 = check(mut4, scale, cfg)
    else:
        p4 = p5 = ["no bias devices found"]
    print(f"selftest bias-gate : {'FAIL' if p4 else 'PASS (bad!)'} ({len(p4)})")
    ok &= bool(p4)
    print(f"selftest bias-src  : {'FAIL' if p5 else 'PASS (bad!)'} ({len(p5)})")
    ok &= bool(p5)

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
    body = _top_body(txt)
    insts = [ln.split() for ln in body if ln.strip().startswith("X")]
    devs = sum(1 for f in insts if f[-1].startswith("pfet"))
    if devs != 62:
        die(f"PEX netlist instantiates {devs} devices, want 62")
    caps = sum(1 for ln in body if ln.strip().startswith("C"))
    if caps == 0:
        die("PEX top subckt has no capacitance; extraction did not run")
    tot = Counter()
    for ln in body:
        mm = re.match(r"^C\S+\s+(\S+)\s+(\S+)\s+([-0-9.eE+]+[a-zA-Z]*)", ln)
        if not mm:
            continue
        v = spice_val(mm.group(3))
        tot[mm.group(1)] += v
        tot[mm.group(2)] += v
    cfg = load_cfg()
    ub = int(cfg.get("unary_bits", 4))
    bb = int(cfg.get("binary_bits", 4))
    names = ["vdd", "vbp", "vcp"]
    names += [f"oU{i}" for i in range(2 ** ub - 1)]
    names += [f"oB{w}" for w in (2 ** i for i in range(bb))]
    net_cap = {n: round(tot.get(n, 0.0) * 1e15, 3) for n in names}
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
        print(f"lvs  {'PASS' if r['ok'] else 'FAIL'}  {r['devices']} devices, "
              f"{r['cells']} cells, scale {r['scale_nm']:g} nm")
        for p in r["problems"]:
            print(f"     {p}")
    if a.stage in ("all", "pex"):
        r = pex(pdk)
        rep["steps"]["pex"] = r
        print(f"pex  PASS  {r['instances']} instances, {r['caps']} C entries, "
              f"{r['bytes'] / 1e3:.1f} kB")
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
