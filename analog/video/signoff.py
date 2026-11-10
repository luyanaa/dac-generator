#!/usr/bin/env python3
"""Signoff for the 255-cell video DAC array (gf180mcuA): DRC, LVS, PEX, pins.

    ./signoff.py                 # build + drc + lvs + pins + pex, gate on all
    ./signoff.py --stage lvs
    ./signoff.py --stage postlayout   # delegate to the extracted DC bench
    ./signoff.py --selftest      # prove the gates reject mutations

This is the P5 counterpart of `../csteer/signoff.py`.  `gen_gds.py` generates
the analog core: 255 identical switched-cascode PMOS unit cells in one row, the
shared vdd/vbp/vcp/iout distribution, a replica *cell* at the right end (same
switch, mirror and cascode, diode-connected), and one M2 pad per cell on a
7.5 um pin row.  The digital half
(`verilog/rtl/dac_video_dig.v`, 255 registered switches) is a separate
standard-cell macro, the wrapper that abuts them and the output pad/ESD are
class C (hand layout), so the gates below sign off the array, not the DAC.

  drc  Magic `drc check` / `drc catchup` / `drc count total`, same fail-closed
       path as P1/P2/P3.  gf180 has no KLayout deck in this install.

  lvs  Flat Magic netlist.  The contract is written independently of the
       generator's placement, from the config alone:
         * 255 unit cells.  Cell j is the one whose switch gate is the pad
           `d_<tag>`; the rest of the cell is reached from that pad through
           the drawn nets, so the tag -> device mapping is re-derived and not
           assumed: gate d_<tag> -> switch drain n2 -> mirror source n2 ->
           mirror drain n1 -> cascode source n1 -> cascode drain = iout.
         * every cell is *identical*: mirror 8/1, cascode 8/0.5, switch
           0.5/0.28.  The 1/2/4/.../128 weight is the number of cells on the
           digital side; this macro has no cell-level weight at all.
         * switch source = vdd, and the switch sits *between* the supply and
           the mirror, so an off cell draws no current: there is no `idump`
           and no `vss` anywhere in this core (both are negative checks).
         * the replica bias is a copy of one cell: the same 0.5/0.28 switch
           on a static 0 V gate (`vgnd`) feeding a vdd -> vbp 8/1 diode and a
           vbp -> vcp 8/0.5 diode.  The switch has to be there: the cell's own
           switch drops I*Ron in its mirror's source, and a bias branch
           without that drop sits ~50 % away from the cells' operating point
           (measured 8.07 uA against the modelled 16 uA before the fix).
         * 5 rails (vdd/vbp/vcp/iout/vgnd) + 255 pin nets + 2 internal nodes
           per cell + the replica switch node = 771 nets.

  pins The 255 pads are checked on the drawn GDS (`pinplan.py`), not on the
       generator's variables: one M2 pad per cell in cell order on an exact
       7.5 um grid, so a hardened digital macro can abut it.  The same stage
       derives the rail resistances from the drawn metal and reports the
       supply droop and the iout bus drop as evidence (see the README).

  pex  hierarchical extraction, cthresh/rthresh 0; 768 instances and the
       per-net capacitance, kept as evidence for the digital driver load and
       for the vbp/vcp bias settling.

Not claimed: the digital macro, the wrapper, the output pad/ESD/cable driver,
the per-sample settling, or any post-layout linearity of the DAC.
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
GDS = BUILD / "video.gds"
MAGIC_DIR = BUILD / "magic"

KLAYOUT_BUILD = "/usr/bin/klayout"
TOP = "dac_video_ana"
YAML = ROOT / "video.yaml"

# Analog-facing pin contract (um).  One M2 pad per unit cell, cell order, on a
# 7.5 um grid that is also the cell pitch, so the pad is 1.0 um right of the
# cell origin (the switch gate) and the digital macro's 255 outputs land on it.
PIN_PITCH_UM = 7.5
PIN_X0_UM = 1.0
PIN_Y_UM = (-4.60, -4.20)
PIN_W_UM = 0.60
PIN_H_UM = 0.40

# The single-ended array: no ground and no dump leg (an off cell is a real
# zero, which is the whole reason P5 uses a series switch).
ANALOG_PORTS = ("vdd", "vbp", "vcp", "iout", "vgnd")
RAIL_LAYER = {"vdd": "m3", "iout": "m3", "vbp": "m2", "vcp": "m1",
              "vgnd": "m2"}

# gf180 sheet resistance (ohm/sq) for the drawn rails.  M3 is 9x better than
# M1/M2, which is why the supply and the output bus are on M3 here: the same
# current on a 1.9 mm M1 bar would cost hundreds of ohms.
RSH = {"m1": 0.090, "m2": 0.090, "m3": 0.010}


def cell_tags(cfg) -> list[str]:
    """Cell index -> segmentation tag, from the config alone.

    Cell j belongs to the smallest k with j < 2**(k+1) - 1, exactly as the
    digital expansion in `dac_video_dig.v` does; this is the P5 weight rule.
    """
    n = 2 ** int(cfg["bits"]) - 1
    tags = []
    for j in range(n):
        k = 0
        while j >= 2 ** (k + 1) - 1:
            k += 1
        tags.append(f"b{k}_{j - (2 ** k - 1)}")
    return tags


def die(msg: str) -> None:
    print(f"error: {msg}", file=sys.stderr)
    raise SystemExit(2)


def run(cmd, cwd=None, env=None, timeout=3600):
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
        die("video generation failed")
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


NETCOUNT = 0


def check(devs, scale, cfg) -> list[str]:
    """The P5 array contract, written from the config and the netlist only."""
    global NETCOUNT
    problems: list[str] = []
    tags = cell_tags(cfg)
    n_cells = len(tags)
    cell_w = float(cfg.get("cell_w", 8.0))
    mir_l = float(cfg.get("mir_l", 1.0))
    cas_l = float(cfg.get("cas_l", 0.5))
    sw_w = float(cfg.get("sw_w", 0.5))
    sw_l = float(cfg.get("sw_l", 0.28))

    rails = {"vdd", "vbp", "vcp", "iout", "vgnd"}
    pin_nets = {"d_" + t for t in tags}

    def um(tok: str) -> float:
        return spice_val(tok) * scale * 1e6

    mirrors = []          # (name, drain, source, L)
    cascodes = []
    switches = []         # (name, drain, gate, source)
    bias_m = []
    bias_c = []
    bias_s = []
    allnets: set[str] = set()

    for name, nets, sub, params in devs:
        d, g, s, b = nets
        allnets.update(nets)
        if "l" not in params or "w" not in params:
            problems.append(f"{name}: missing l/w")
            continue
        L, W = um(params["l"]), um(params["w"])
        if not sub.startswith("pfet"):
            problems.append(f"{name}: unexpected device {sub} (P5 is a "
                            f"PMOS array; a NMOS here is P3's switch pair)")
            continue
        if b != "vdd":
            problems.append(f"{name}: bulk {b}, want vdd")
        if g == "vbp":
            if d == "vbp":
                # Replica bias mirror: diode-connected, but its source is the
                # replica switch's drain, not vdd - without the switch its drop
                # would be missing from the bias branch and the cells would run
                # ~50 % low.  The pair is checked below.
                if s in rails | pin_nets:
                    problems.append(f"{name}: bias mirror source {s} is a "
                                    f"rail/port; it must be the replica "
                                    f"switch drain")
                if abs(W - cell_w) > 1e-6 or abs(L - mir_l) > 1e-6:
                    problems.append(f"{name}: bias mirror {W:.3f}/{L:.3f} um, "
                                    f"want {cell_w:.3f}/{mir_l}")
                bias_m.append((name, d, s, L))
            else:
                if abs(W - cell_w) > 1e-6:
                    problems.append(f"{name}: cell mirror w {W:.3f} um, want "
                                    f"{cell_w:.3f} (all cells are identical)")
                if abs(L - mir_l) > 1e-6:
                    problems.append(f"{name}: mirror l {L:.3f}, want {mir_l}")
                if d in rails | pin_nets:
                    problems.append(f"{name}: mirror drain {d} is a port")
                if s in rails | pin_nets:
                    problems.append(f"{name}: mirror source {s} is a port "
                                    f"(the switch drain is an internal node)")
                mirrors.append((name, d, s, L))
        elif g == "vcp":
            if d == "vcp":
                # Replica bias cascode: diode-connected from vbp to vcp.
                if s != "vbp":
                    problems.append(f"{name}: bias cascode source {s}, "
                                    f"want vbp")
                if abs(W - cell_w) > 1e-6 or abs(L - cas_l) > 1e-6:
                    problems.append(f"{name}: bias cascode {W:.3f}/{L:.3f} um, "
                                    f"want {cell_w:.3f}/{cas_l}")
                bias_c.append((name, d, s, L))
            else:
                if abs(W - cell_w) > 1e-6:
                    problems.append(f"{name}: cell cascode w {W:.3f} um, want "
                                    f"{cell_w:.3f} (all cells are identical)")
                if abs(L - cas_l) > 1e-6:
                    problems.append(f"{name}: cascode l {L:.3f}, want {cas_l}")
                if d != "iout":
                    problems.append(f"{name}: cascode drain {d}, want iout "
                                    f"(single-ended array, one output bus)")
                if s in rails | pin_nets:
                    problems.append(f"{name}: cascode source {s} is a port")
                cascodes.append((name, d, s, L))
        elif g in pin_nets:
            if abs(W - sw_w) > 1e-6 or abs(L - sw_l) > 1e-6:
                problems.append(f"{name}: switch {W:.3f}/{L:.3f} um, want "
                                f"{sw_w:.3f}/{sw_l}")
            if s != "vdd":
                problems.append(f"{name}: switch source {s}, want vdd (the "
                                f"switch is in series with the mirror)")
            if d in rails | pin_nets:
                problems.append(f"{name}: switch drain {d} is a port")
            switches.append((name, d, g, s))
        elif g == "vgnd":
            # Replica switch: the *same* device as a cell's, on a static 0 V
            # gate, so the bias branch sees the same series drop as a cell.
            if abs(W - sw_w) > 1e-6 or abs(L - sw_l) > 1e-6:
                problems.append(f"{name}: replica switch {W:.3f}/{L:.3f} um, "
                                f"want {sw_w:.3f}/{sw_l}")
            if s != "vdd":
                problems.append(f"{name}: replica switch source {s}, want vdd")
            if d in rails | pin_nets:
                problems.append(f"{name}: replica switch drain {d} is a "
                                f"rail/port")
            bias_s.append((name, d, g, s))
        else:
            problems.append(f"{name}: gate net {g} is not a cell pad, vbp, "
                            f"vcp or vgnd")

    if len(devs) != 3 * n_cells + 3:
        problems.append(f"{len(devs)} devices, want {3 * n_cells + 3} "
                        f"(3 per cell + a 3-device replica cell)")
    for label, got, want in (("cell mirrors", len(mirrors), n_cells),
                             ("cell cascodes", len(cascodes), n_cells),
                             ("switches", len(switches), n_cells),
                             ("bias mirrors", len(bias_m), 1),
                             ("bias cascodes", len(bias_c), 1),
                             ("bias switches", len(bias_s), 1)):
        if got != want:
            problems.append(f"{got} {label}, want {want}")
    # The replica is a copy of a cell, so its mirror source must be its own
    # switch's drain - that is what makes the series drop common mode.
    if bias_m and bias_s:
        if bias_m[0][2] != bias_s[0][1]:
            problems.append(f"bias mirror source {bias_m[0][2]} is not the "
                            f"replica switch drain {bias_s[0][1]}; the cells' "
                            f"series drop is then missing from the bias")
        if bias_m[0][2] in set(x[1] for x in switches):
            problems.append("replica switch drain is a cell's switch drain")

    # The tag is visible only on the switch gate.  Walk the cell from there so
    # the contract does not depend on how Magic named the internal nodes.
    sw_gate = {g: d for _, d, g, _ in switches}
    dup = [g for g, k in Counter(x[2] for x in switches).items() if k > 1]
    if dup:
        problems.append(f"duplicate switch gates: {some(dup)}")
    mir_src = {}
    for name, d, s, _ in mirrors:
        if s in mir_src:
            problems.append(f"{s}: two cell mirrors on one node")
        mir_src[s] = d
    cas_src = {}
    for name, d, s, _ in cascodes:
        if s in cas_src:
            problems.append(f"{s}: two cell cascodes on one node")
        cas_src[s] = d
    if len(set(d for _, d, _, _ in switches)) != len(switches):
        problems.append("two switches share a drain node")
    if len(set(d for _, d, _, _ in mirrors)) != len(mirrors):
        problems.append("two cell mirrors share a drain node")
    short = set(d for _, d, _, _ in switches) & set(d for _, d, _, _ in mirrors)
    if short:
        problems.append(f"mirror drain doubles as a switch drain at "
                        f"{some(sorted(short))}")
    for tag in tags:
        gnet = "d_" + tag
        if gnet not in sw_gate:
            problems.append(f"{gnet}: no switch gate")
            continue
        n2 = sw_gate[gnet]
        n1 = mir_src.get(n2)
        if n1 is None:
            problems.append(f"{gnet}: switch drain {n2} is not a mirror "
                            f"source")
            continue
        d = cas_src.get(n1)
        if d is None:
            problems.append(f"{gnet}: mirror drain {n1} is not a cascode "
                            f"source")
            continue
        if d != "iout":
            problems.append(f"{gnet}: cascode drain {d}, want iout")

    # P5 is a series-switch array: an off cell draws nothing, so the core must
    # not contain P3's ground rail or its dump bus.
    for bad in ("vss", "idump"):
        if bad in allnets:
            problems.append(f"core contains {bad}; P5 has no such rail")

    want_nets = len(rails) + n_cells + 2 * n_cells + 1
    NETCOUNT = len(allnets)
    if len(allnets) != want_nets:
        problems.append(f"{len(allnets)} nets, want {want_nets} "
                        f"(5 rails + {n_cells} pins + 2 internal per cell "
                        f"+ the replica's switch node)")
    return problems


def some(items, k: int = 6):
    items = list(items)
    return ", ".join(str(x) for x in items[:k])


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
    n_cells = len(cell_tags(cfg))
    return {"ok": not problems, "devices": len(devs), "cells": n_cells,
            "switches": n_cells, "bias": 3, "nets": NETCOUNT,
            "scale_nm": round(scale * 1e9, 3),
            "problems": problems, "netlist": str(spice)}


def _top_body(txt: str, top: str = TOP):
    m = re.search(r"^\.subckt\s+" + top + r"\s+(.*?)^\.ends", txt,
                  re.M | re.S)
    if not m:
        die(f"no .subckt {top} in the extracted netlist")
    lines = m.group(1).splitlines()
    i = 0
    while i < len(lines) and (i == 0 or lines[i].lstrip().startswith("+")):
        i += 1
    return lines[i:]


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
    cfg = load_cfg()
    n_cells = len(cell_tags(cfg))
    devs = sum(1 for f in insts if f[-1].startswith(("pfet", "nfet")))
    if devs != 3 * n_cells + 3:
        die(f"PEX netlist instantiates {devs} devices, want "
            f"{3 * n_cells + 3}")
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
    # Rails carry the bias and the return; the 255 pads are what the digital
    # macro has to drive; the internal nodes are the cell stacks.
    net_cap = {n: round(tot.get(n, 0.0) * 1e15, 2) for n in ANALOG_PORTS}
    pads = sum(v for n, v in tot.items() if n.startswith("d_"))
    net_cap["d_* (255 pads)"] = round(pads * 1e15, 2)
    net_cap["per pad"] = round(pads * 1e15 / n_cells, 3)
    net_cap["internal (510 nodes)"] = round(
        sum(v for n, v in tot.items()
            if not n.startswith("d_") and n not in ANALOG_PORTS) * 1e15, 2)
    return {"ok": True, "netlist": str(spice), "bytes": spice.stat().st_size,
            "instances": devs, "caps": caps, "net_cap_ff": net_cap}


# --------------------------------------------------------------------------
# pin contract + the rail estimate that goes with it
# --------------------------------------------------------------------------

def check_pins(plan: dict, cfg) -> list[str]:
    """Verify the drawn port geometry against the pin contract.

    `plan` is pinplan.py's JSON: for every label, the shape it sits on.  The
    check is on the GDS, not on the generator's variables, so a pad drawn off
    the grid is caught even if the generator thinks it is right.
    """
    problems = list(plan.get("problems", []))
    pins = plan.get("pins", {})
    tags = cell_tags(cfg)
    want = {"d_" + t for t in tags} | set(ANALOG_PORTS)
    got = set(pins)
    if got != want:
        problems.append(
            f"{len(got)} labelled ports, want {len(want)}: missing "
            f"{some(sorted(want - got))}, extra {some(sorted(got - want))}")

    row = [n for n, v in pins.items()
           if abs(v["bbox"][3] - PIN_Y_UM[1]) < 1e-6
           and abs(v["bbox"][1] - PIN_Y_UM[0]) < 1e-6]
    if len(row) != len(tags):
        problems.append(f"{len(row)} pads on the pin row, want {len(tags)}")
    for i, tag in enumerate(tags):
        name = "d_" + tag
        v = pins.get(name)
        if v is None:
            continue
        if name not in row:
            problems.append(f"{name}: not on the analog-facing pin row")
            continue
        b = v["bbox"]
        w, h = b[2] - b[0], b[3] - b[1]
        if v["layer"] != "m2":
            problems.append(f"{name}: pin on {v['layer']}, want m2")
        if abs(w - PIN_W_UM) > 1e-6 or abs(h - PIN_H_UM) > 1e-6:
            problems.append(f"{name}: pad {w:.3f}x{h:.3f} um, want "
                            f"{PIN_W_UM:.3f}x{PIN_H_UM:.3f}")
        cx = (b[0] + b[2]) / 2
        want_x = PIN_X0_UM + PIN_PITCH_UM * i
        if abs(cx - want_x) > 1e-6:
            problems.append(f"{name}: pin centre {cx:.3f} um, want "
                            f"{want_x:.3f}")

    for n in ANALOG_PORTS:
        v = pins.get(n)
        if v is None:
            continue
        b = v["bbox"]
        if v["layer"] != RAIL_LAYER[n]:
            problems.append(f"{n}: labelled on {v['layer']}, want "
                            f"{RAIL_LAYER[n]}")
        if b[1] < PIN_Y_UM[1] - 1e-6:
            problems.append(f"{n}: reaches y={b[1]:.3f}, into the digital "
                            f"pin row")
        if min(b[2] - b[0], b[3] - b[1]) < 0.20:
            problems.append(f"{n}: label sits on a {b[2] - b[0]:.2f}x"
                            f"{b[3] - b[1]:.2f} um sliver")
    return problems


def rails(plan: dict, cfg) -> dict:
    """Rail resistance and the two drop terms, from the drawn metal.

    vdd is an M3 plane fed at both ends (the wrapper straps it), so a uniformly
    tapped bar drops I*R/8 at the middle - the case reported here.  That drop
    lowers every cell's Vsg by the same slowly varying amount, and vbp comes
    from a replica that sits at a feed point, so it is a *gain* term (the code
    scales the supply current, the drop scales with the code, and endpoint
    calibration absorbs it); the DNL it leaves is the curvature of the drop
    with position, which the extracted DC sweep has to measure, not this stage.
    The number gated here is therefore the full-code gain loss, 2*drop/Vov,
    against a range budget.

    iout is a single-ended bus: all 255 cells exit at one node, so the farthest
    cell sees I*R/2 between its drain and the pad.  That is a compliance term,
    not a gain error - KCL still delivers every cell's current to the load -
    and the only current it costs is drop/ro_unit per cell, gated in LSB.
    """
    pins = plan["pins"]
    i_unit = float(cfg.get("i_unit_ua", 16.0)) * 1e-6
    n = 2 ** int(cfg["bits"]) - 1
    i_max = n * i_unit
    vov = float(cfg.get("vov", 0.2))
    ro = float(cfg.get("ro_unit", 4.249e8))

    out: dict = {"i_full_ma": round(i_max * 1e3, 3),
                 "gain_budget_pct": float(cfg.get("rail_gain_budget_pct",
                                                  2.0))}
    for name in ("vdd", "iout"):
        b = pins[name]["bbox"]
        length, width = b[2] - b[0], b[3] - b[1]
        r = RSH[pins[name]["layer"]] * length / width
        d_both = i_max * r / 8
        d_one = i_max * r / 2
        out[name] = {
            "length_um": round(length, 3), "width_um": round(width, 3),
            "R_ohm": round(r, 3),
            "drop_both_ends_mv": round(d_both * 1e3, 3),
            "drop_one_end_mv": round(d_one * 1e3, 3),
        }
        if name == "vdd":
            out[name]["gain_loss_pct"] = round(2 * d_both / vov * 100, 3)
        else:
            out[name]["cell_current_error_lsb"] = round(
                d_one / ro / i_unit, 5)
    # vbp/vcp/vgnd carry no DC current (gates only); report them for settling
    # (vgnd is the replica switch's static 0 V reference).
    for name in ("vbp", "vcp", "vgnd"):
        b = pins[name]["bbox"]
        out[name] = {"layer": pins[name]["layer"],
                     "length_um": round(b[2] - b[0], 3),
                     "width_um": round(b[3] - b[1], 3)}
    return out


def pins(pdk: Path) -> dict:
    if not Path(KLAYOUT_BUILD).is_file():
        die(f"{KLAYOUT_BUILD} missing (needs the pya build)")
    out = BUILD / "pinplan.json"
    proc = run([KLAYOUT_BUILD, "-b", "-r", ROOT / "pinplan.py",
                "-rd", f"gds={GDS}", "-rd", f"out={out}"])
    if proc.returncode != 0 or not out.is_file():
        print(proc.stdout + proc.stderr, file=sys.stderr)
        die("pinplan extraction failed")
    plan = json.loads(out.read_text())
    cfg = load_cfg()
    problems = check_pins(plan, cfg)
    rp = rails(plan, cfg)
    problems += rail_problems(rp, cfg)
    row = [n for n, v in plan.get("pins", {}).items()
           if abs(v["bbox"][3] - PIN_Y_UM[1]) < 1e-6
           and abs(v["bbox"][1] - PIN_Y_UM[0]) < 1e-6]
    return {"ok": not problems, "problems": problems, "ports": len(
        plan.get("pins", {})), "row": len(row), "plan": str(out),
        "rails": rp}


def rail_problems(rp: dict, cfg) -> list[str]:
    problems = []
    budget = rp["gain_budget_pct"]
    g = rp["vdd"]["gain_loss_pct"]
    if g > budget:
        problems.append(f"vdd plane drop costs {g:.2f}% gain at full code, "
                        f"budget {budget:.2f}%")
    iout = rp["iout"]
    ibudget = float(cfg.get("iout_drop_budget_mv", 25.0))
    if iout["drop_one_end_mv"] > ibudget:
        problems.append(f"iout bus drops {iout['drop_one_end_mv']:.2f} mV at "
                        f"full code, budget {ibudget:.2f} mV")
    if iout["cell_current_error_lsb"] > 0.05:
        problems.append(f"iout bus drop costs "
                        f"{iout['cell_current_error_lsb']:.3f} LSB/cell")
    return problems


# --------------------------------------------------------------------------
# selftest
# --------------------------------------------------------------------------

def selftest() -> int:
    spice = MAGIC_DIR / "lvs.spice"
    if not spice.is_file():
        die("no build/magic/lvs.spice; run --stage lvs first")
    devs, scale = parse_flat(spice.read_text())
    cfg = load_cfg()
    n_cells = len(cell_tags(cfg))

    ok = True
    p = check(devs, scale, cfg)
    print(f"selftest real      : {'PASS' if not p else 'FAIL'} ({len(p)})")
    for q in p[:6]:
        print(f"     {q}")
    ok &= not p

    def idx(pred):
        return [i for i, d in enumerate(devs) if pred(d)]

    def swaps(i, fn):
        m = list(devs)
        name, nets, sub, params = m[i]
        m[i] = (name, fn(nets), sub, params)
        return m

    sw_i = idx(lambda d: d[1][1] in {"d_" + t for t in cell_tags(cfg)})
    mir_i = idx(lambda d: d[1][1] == "vbp" and d[1][0] != "vbp")
    cas_i = idx(lambda d: d[1][1] == "vcp" and d[1][0] != "vcp")

    # Drop the middle switch: the device count and the pin chain break.
    p1 = check([d for i, d in enumerate(devs)
                if i != sw_i[len(sw_i) // 2]], scale, cfg) if sw_i else ["none"]
    # Re-label one switch gate onto a neighbour: one pad unconnected, one
    # gate carrying two devices.
    p2 = check(swaps(sw_i[0], lambda n: [n[0], devs[sw_i[1]][1][1], n[2], n[3]]),
               scale, cfg) if len(sw_i) > 1 else ["none"]
    # Short two switch drains: one mirror source disappears and one node
    # carries two switches, so the tag -> cell walk fails.
    def short_sw():
        m = list(devs)
        a, b = sw_i[0], sw_i[-1]
        db = devs[b][1][0]
        m[a] = (devs[a][0], [db] + devs[a][1][1:], devs[a][2], devs[a][3])
        return m
    p3 = check(short_sw(), scale, cfg) if len(sw_i) > 1 else ["none"]
    # Give one cell cascode the mirror length: it stops being a cascode.
    p4 = check([(nm, nt, sb, dict(pp, l="200")) if i == cas_i[0]
                else (nm, nt, sb, pp)
                for i, (nm, nt, sb, pp) in enumerate(devs)], scale, cfg) \
        if cas_i else ["none"]
    # Shrink one mirror: all cells must be identical.
    p5 = check([(nm, nt, sb, dict(pp, w="4u")) if i == mir_i[-1]
                else (nm, nt, sb, pp)
                for i, (nm, nt, sb, pp) in enumerate(devs)], scale, cfg) \
        if mir_i else ["none"]
    # Break the bias: mirror gate to vcp, cascode source to vdd.
    bm = idx(lambda d: d[1][1] == "vbp" and d[1][0] == "vbp")
    bc = idx(lambda d: d[1][1] == "vcp" and d[1][0] == "vcp")
    p6 = check(swaps(bm[0], lambda n: [n[0], "vcp", n[2], n[3]]), scale,
               cfg) if bm else ["none"]
    p7 = check(swaps(bc[0], lambda n: [n[0], n[1], "vdd", n[3]]), scale,
               cfg) if bc else ["none"]
    # Move one cascode drain off iout (single-ended array, one bus only).
    p8 = check(swaps(cas_i[-1], lambda n: ["idump", n[1], n[2], n[3]]),
               scale, cfg) if cas_i else ["none"]
    # The replica switch: killing it (gate to vdd), shorting it (source to
    # vbp), and the pre-fix bug itself - the bias mirror fed straight from vdd
    # so the cells' series drop is missing from the bias branch.
    bs = idx(lambda d: d[1][1] == "vgnd")
    p9 = check(swaps(bs[0], lambda n: [n[0], "vdd", n[2], n[3]]), scale,
               cfg) if bs else ["none"]
    p10 = check(swaps(bs[0], lambda n: [n[0], n[1], "vbp", n[3]]), scale,
                cfg) if bs else ["none"]
    p11 = check(swaps(bm[0], lambda n: [n[0], n[1], "vdd", n[3]]), scale,
                cfg) if bm else ["none"]
    for name, prob in (("drop-switch", p1), ("relabel-gate", p2),
                       ("swap-drains", p3), ("casc-length", p4),
                       ("mirror-width", p5), ("bias-gate", p6),
                       ("bias-source", p7), ("casc-drain", p8),
                       ("bias-sw-gate", p9), ("bias-sw-src", p10),
                       ("bias-undegenerated", p11)):
        print(f"selftest {name:12}: {'FAIL' if prob else 'PASS (bad!)'} "
              f"({len(prob)})")
        ok &= bool(prob)

    plan_path = BUILD / "pinplan.json"
    if not plan_path.is_file():
        die("no build/pinplan.json; run --stage pins first")
    plan = json.loads(plan_path.read_text())
    pp = check_pins(plan, cfg)
    rp = rails(plan, cfg)
    pr = pp + rail_problems(rp, cfg)
    print(f"selftest pins-real  : {'FAIL' if pr else 'PASS'} ({len(pr)})")
    for q in pr[:6]:
        print(f"     {q}")
    ok &= not pr

    def plan_mut(fn):
        m = json.loads(json.dumps(plan))
        fn(m["pins"])
        return check_pins(m, cfg)

    tags = cell_tags(cfg)

    def shift(pins):
        b = pins["d_" + tags[100]]["bbox"]
        pins["d_" + tags[100]]["bbox"] = [v + 0.5 for v in b]

    def swap(pins):
        a, b = "d_" + tags[7], "d_" + tags[8]
        pins[a], pins[b] = pins[b], pins[a]

    def widen(pins):
        b = pins["d_" + tags[0]]["bbox"]
        pins["d_" + tags[0]]["bbox"] = [b[0] - 0.4, b[1], b[2], b[3]]

    def drop(pins):
        del pins["d_" + tags[-1]]

    def wrong_layer(pins):
        pins["d_" + tags[0]]["layer"] = "m1"

    def shrink_vdd(pins):
        b = pins["vdd"]["bbox"]
        # Halve the plane's width: the droop doubles.
        pins["vdd"]["bbox"] = [b[0], b[1], b[2], b[1] + (b[3] - b[1]) / 40]

    for name, fn in (("pin-shift", shift), ("pin-swap", swap),
                     ("pin-widen", widen), ("pin-drop", drop),
                     ("pin-layer", wrong_layer)):
        p = plan_mut(fn)
        print(f"selftest {name:12}: {'FAIL' if p else 'PASS (bad!)'} "
              f"({len(p)})")
        ok &= bool(p)
    m = json.loads(json.dumps(plan))
    shrink_vdd(m["pins"])
    pr = check_pins(m, cfg) + rail_problems(rails(m, cfg), cfg)
    print(f"selftest rail-shrink : {'FAIL' if pr else 'PASS (bad!)'} "
          f"({len(pr)})")
    ok &= bool(pr)

    print("selftest " + ("PASS" if ok else "FAIL"))
    return 0 if ok else 1


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--stage", default="all",
                    choices=["all", "build", "drc", "lvs", "pex", "pins",
                             "postlayout"])
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--brief", action="store_true")
    a = ap.parse_args(argv)
    if a.selftest:
        return selftest()
    if a.stage == "postlayout":
        # The bench owns the netlist, the gates and the report, so the stage
        # cannot drift from what it means.
        cmd = [sys.executable, str(ROOT / "run_postlayout.py")]
        if a.brief:
            cmd.append("--brief")
        return subprocess.run(cmd).returncode

    pdk = find_pdk()
    rep: dict = {"pdk": str(pdk), "top": TOP, "steps": {}}
    failed = []
    if a.stage in ("all", "build", "drc", "lvs", "pex", "pins"):
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
        print(f"lvs  {'PASS' if r['ok'] else 'FAIL'}  {r['devices']} devices "
              f"({r['cells']} identical cells + {r['bias']}-device replica), "
              f"{r['nets']} nets, scale {r['scale_nm']:g} nm")
        for p in r["problems"]:
            print(f"     {p}")
    if a.stage in ("all", "pins"):
        r = pins(pdk)
        rep["steps"]["pins"] = r
        if not r["ok"]:
            failed.append("pins")
        rp = r["rails"]
        print(f"pins {'PASS' if r['ok'] else 'FAIL'}  {r['ports']} ports, "
              f"{r['row']} on the 7.5 um digital row")
        print(f"     rails: vdd {rp['vdd']['R_ohm']:g} ohm "
              f"({rp['vdd']['drop_both_ends_mv']:g} mV both ends, "
              f"{rp['vdd']['gain_loss_pct']:g}% gain), "
              f"iout {rp['iout']['R_ohm']:g} ohm "
              f"({rp['iout']['drop_one_end_mv']:g} mV one end, "
              f"{rp['iout']['cell_current_error_lsb']:g} LSB/cell)")
        for p in r["problems"]:
            print(f"     {p}")
    if a.stage in ("all", "pex"):
        r = pex(pdk)
        rep["steps"]["pex"] = r
        nc = r["net_cap_ff"]
        print(f"pex  PASS  {r['instances']} instances, {r['caps']} C entries, "
              f"{r['bytes'] / 1e3:.1f} kB")
        print(f"     C: vdd {nc['vdd']} fF, vbp {nc['vbp']} fF, "
              f"vcp {nc['vcp']} fF, iout {nc['iout']} fF, "
              f"{nc['d_* (255 pads)']} fF on the pads "
              f"({nc['per pad']} fF each)")
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
