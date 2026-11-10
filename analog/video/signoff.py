#!/usr/bin/env python3
"""Signoff for the 255-cell video DAC array (gf180mcuA): DRC, LVS, PEX, pins.

    ./signoff.py                 # build + drc + lvs + pins + pex, gate on all
    ./signoff.py --stage lvs
    ./signoff.py --stage postlayout   # delegate to the extracted DC bench
    ./signoff.py --stage mm           # delegate to the mismatch Monte Carlo
    ./signoff.py --stage tran         # delegate to the carry transient
    ./signoff.py --selftest      # prove the gates reject mutations

This is the P5 counterpart of `../csteer/signoff.py`.  `gen_gds.py` generates
the analog core: 255 identical dump-tail unit cells in one row, the shared
vdd/vss/vbp/vcp/iout/idump distribution, a replica *bias* at the right end
(the cell's mirror and cascode, diode-connected) and **two** M2 pads per cell
on a 3.75 um grid.  The digital half (`verilog/rtl/dac_video_dig.v`) is a
separate standard-cell macro, the wrapper that abuts them and the output
pad/ESD are class C (hand layout), so the gates below sign off the array, not
the DAC.

  drc  Magic `drc check` / `drc catchup` / `drc count total`, same fail-closed
       path as P1/P2/P3.  gf180 has no KLayout deck in this install.

  lvs  Flat Magic netlist.  The contract is written independently of the
       generator's placement, from the config alone:
         * 255 unit cells, each 4 devices: an 8/1 PMOS mirror (source vdd,
           gate vbp), an 8/0.5 PMOS cascode (gate vcp) and a 4/0.28 NMOS pair
           whose shared source is the cascode's drain.  The pair's gates are
           the two pads `d_<tag>` (drain iout) and `db_<tag>` (drain idump),
           so the tail current always flows and is steered, not switched.
         * every cell is identical; the 1/2/4/.../128 weight is the number of
           cells on the digital side, so this macro has no cell-level weight.
         * the tag lives on the pads only: the contract walks pad -> NMOS ->
           shared tail -> cascode -> mirror -> vdd, re-deriving the cell from
           the drawn nets instead of trusting Magic's node names.
         * the replica bias is the cell's mirror+cascode, diode-connected
           (vbp -> vcp), with 16 uA sinked at vcp.  No switch: in this cell
           the tail never stops, so the bias branch has no drop to reproduce.
         * 6 rails (vdd/vss/vbp/vcp/iout/idump) + 510 pad nets + 2 internal
           nodes per cell = 1026 nets.
         * negative checks: no `vgnd`/`n_ref` (the old series-switch ports),
           no PMOS with a pad gate, no NMOS source on a rail.

  pins The 510 pads are checked on the drawn GDS (`pinplan.py`), not on the
       generator's variables: two M2 pads per cell in cell order on an exact
       3.75 um grid, so a hardened 510-output digital macro can abut it.  The
       same stage derives the rail resistances from the drawn metal and
       reports the supply droop and the iout/idump bus drops as evidence.

  pex  hierarchical extraction, cthresh/rthresh 0; 1022 instances and the
       per-net capacitance, kept as evidence for the digital driver load and
       for the vbp/vcp bias settling.

  postlayout / mm / tran  delegated to `run_postlayout.py` (extracted
       256-code dc transfer), `run_mismatch_pex.py` (static mismatch Monte
       Carlo with per-device `delvto`/`mulu0` drawn from the PDK area law) and
       `run_transient_pex.py` (carry transient on the extracted netlist with
       its capacitance).  They own their netlist, gates and report, so the
       stage name cannot drift from what ran.

Not claimed: the digital macro, the wrapper, the output pad/ESD/cable driver.
The array's own post-layout linearity is `mm`'s job (static mismatch only);
`tran` runs the carries with the wrapper's 100 pF on vcp but has no envelope
and no cable driver.
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

# Analog-facing pin contract (um).  Two M2 pads per unit cell - the steering
# pair's `d_` (iout) and `db_` (idump) gates - in cell order, on a 3.75 um
# grid inside the 7.5 um cell pitch, so a hardened digital macro with 510
# outputs abuts the row directly.
PIN_PITCH_UM = 3.75
PIN_X0_UM = 2.25
PIN_Y_UM = (-11.60, -11.20)
PIN_W_UM = 0.60
PIN_H_UM = 0.40

# The dump-tail array: the tail current always flows, steered to `iout` or
# `idump` by the pair, so the core has a ground (bulk) rail and a dump bus.
ANALOG_PORTS = ("vdd", "vss", "vbp", "vcp", "iout", "idump")
RAIL_LAYER = {"vdd": "m3", "iout": "m3", "idump": "m3", "vbp": "m2",
              "vcp": "m1", "vss": "m1"}

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
    """The P5 dump-tail array contract, from the config and the netlist only.

    Every cell is redrawn by the generator, so the contract is a *walk* from
    the two pads: pad pair -> two NMOS gates -> their shared source (the tail)
    -> the cascode's drain -> the cascode's source -> the mirror's drain -> the
    mirror's source on vdd.  Nothing about the cell is assumed beyond the
    config's device sizes.
    """
    global NETCOUNT
    problems: list[str] = []
    tags = cell_tags(cfg)
    n_cells = len(tags)
    cell_w = float(cfg.get("cell_w", 8.0))
    mir_l = float(cfg.get("mir_l", 1.0))
    cas_l = float(cfg.get("cas_l", 0.5))
    pair_w = float(cfg.get("pair_w", 4.0))
    pair_l = float(cfg.get("pair_l", 0.28))

    rails = {"vdd", "vss", "vbp", "vcp", "iout", "idump"}
    pin_nets = {"d_" + t for t in tags} | {"db_" + t for t in tags}

    def um(tok: str) -> float:
        return spice_val(tok) * scale * 1e6

    mirrors = []       # (name, drain, source)
    cascodes = []      # (name, drain, source)
    switches = []      # (name, drain, gate, source)
    bias_m: list = []
    bias_c: list = []
    allnets: set[str] = set()

    for name, nets, sub, params in devs:
        d, g, s, b = nets
        allnets.update(nets)
        if "l" not in params or "w" not in params:
            problems.append(f"{name}: missing l/w")
            continue
        L, W = um(params["l"]), um(params["w"])
        if sub.startswith("pfet"):
            if b != "vdd":
                problems.append(f"{name}: pfet bulk {b}, want vdd")
            if g == "vbp":
                if d == "vbp":
                    # Bias mirror: diode-connected, source on vdd.
                    if s != "vdd":
                        problems.append(f"{name}: replica mirror source {s}, "
                                        f"want vdd")
                    if abs(W - cell_w) > 1e-6 or abs(L - mir_l) > 1e-6:
                        problems.append(f"{name}: replica mirror "
                                        f"{W:.3f}/{L:.3f} um, want "
                                        f"{cell_w:.3f}/{mir_l}")
                    bias_m.append((name, d, s))
                else:
                    if s != "vdd":
                        problems.append(f"{name}: mirror source {s}, want vdd "
                                        f"(this cell has no series switch)")
                    if d in rails | pin_nets:
                        problems.append(f"{name}: mirror drain {d} is a "
                                        f"rail/port")
                    if abs(W - cell_w) > 1e-6:
                        problems.append(f"{name}: cell mirror w {W:.3f} um, "
                                        f"want {cell_w:.3f} (all cells are "
                                        f"identical)")
                    if abs(L - mir_l) > 1e-6:
                        problems.append(f"{name}: mirror l {L:.3f}, want "
                                        f"{mir_l}")
                    mirrors.append((name, d, s))
            elif g == "vcp":
                if d == "vcp":
                    if s != "vbp":
                        problems.append(f"{name}: replica cascode source {s}, "
                                        f"want vbp")
                    if abs(W - cell_w) > 1e-6 or abs(L - cas_l) > 1e-6:
                        problems.append(f"{name}: replica cascode "
                                        f"{W:.3f}/{L:.3f} um, want "
                                        f"{cell_w:.3f}/{cas_l}")
                    bias_c.append((name, d, s))
                else:
                    if d in rails | pin_nets:
                        problems.append(f"{name}: cascode drain {d} is a "
                                        f"rail/port (the tail is internal)")
                    if s in rails | pin_nets:
                        problems.append(f"{name}: cascode source {s} is a "
                                        f"rail/port")
                    if abs(W - cell_w) > 1e-6 or abs(L - cas_l) > 1e-6:
                        problems.append(f"{name}: cell cascode "
                                        f"{W:.3f}/{L:.3f} um, want "
                                        f"{cell_w:.3f}/{cas_l}")
                    cascodes.append((name, d, s))
            else:
                problems.append(f"{name}: pfet gate {g} is neither vbp nor "
                                f"vcp - this cell has no PMOS switch")
        elif sub.startswith("nfet"):
            if b != "vss":
                problems.append(f"{name}: nfet bulk {b}, want vss")
            if g not in pin_nets:
                problems.append(f"{name}: nfet gate {g} is not a cell pad")
            if d not in ("iout", "idump"):
                problems.append(f"{name}: nfet drain {d}, want iout or idump")
            if s in rails | pin_nets:
                problems.append(f"{name}: nfet source {s} is a rail/port - "
                                f"the pair's tail must be the cascode drain")
            if abs(W - pair_w) > 1e-6 or abs(L - pair_l) > 1e-6:
                problems.append(f"{name}: pair switch {W:.3f}/{L:.3f} um, "
                                f"want {pair_w:.3f}/{pair_l}")
            switches.append((name, d, g, s))
        else:
            problems.append(f"{name}: unexpected device {sub}")

    want = 4 * n_cells + 2
    if len(devs) != want:
        problems.append(f"{len(devs)} devices, want {want} "
                        f"(4 per cell + a 2-device replica)")
    for label, got, want_n in (("cell mirrors", len(mirrors), n_cells),
                               ("cell cascodes", len(cascodes), n_cells),
                               ("pair switches", len(switches), 2 * n_cells),
                               ("bias mirrors", len(bias_m), 1),
                               ("bias cascodes", len(bias_c), 1)):
        if got != want_n:
            problems.append(f"{got} {label}, want {want_n}")

    # The replica is the cell's current source only: mirror source on vdd and
    # cascode source on vbp, with no switch (the tail never stops).
    if bias_m and bias_m[0][2] != "vdd":
        problems.append("replica mirror source is not vdd")
    if bias_c and bias_c[0][2] != "vbp":
        problems.append("replica cascode source is not vbp")

    # Walk each cell from its pad pair.  The tag lives on the pads only, so
    # nothing here depends on how Magic named the internal nodes.
    gate = {g: (d, s) for _, d, g, s in switches}
    dup = [g for g, k in Counter(x[2] for x in switches).items() if k > 1]
    if dup:
        problems.append(f"duplicate switch gates: {some(dup)}")
    cas_of: dict[str, str] = {}
    for _, d, s in cascodes:
        if d in cas_of:
            problems.append(f"{d}: two cell cascodes on one tail")
        cas_of[d] = s
    mir_of: dict[str, str] = {}
    for _, d, s in mirrors:
        if d in mir_of:
            problems.append(f"{d}: two cell mirrors on one drain")
        mir_of[d] = s
    for tag in tags:
        a, bb = "d_" + tag, "db_" + tag
        if a not in gate or bb not in gate:
            problems.append(f"{tag}: a pad has no switch gate")
            continue
        da, sa = gate[a]
        dbb, sbb = gate[bb]
        if da != "iout":
            problems.append(f"{a}: drain {da}, want iout")
        if dbb != "idump":
            problems.append(f"{bb}: drain {dbb}, want idump")
        if sa != sbb:
            problems.append(f"{tag}: the pair's sources differ "
                            f"({sa} vs {sbb})")
            continue
        if sa not in cas_of:
            problems.append(f"{tag}: tail {sa} is not a cascode drain")
            continue
        md = cas_of[sa]
        if md not in mir_of:
            problems.append(f"{tag}: cascode source {md} is not a mirror "
                            f"drain")
            continue
        if mir_of[md] != "vdd":
            problems.append(f"{tag}: mirror source {mir_of[md]}, want vdd")

    # The series-switch cell's two extra ports must be gone.
    for bad in ("vgnd", "n_ref"):
        if bad in allnets:
            problems.append(f"core contains {bad} (the series-switch "
                            f"replica's gate/source)")

    want_nets = len(rails) + len(pin_nets) + 2 * n_cells
    NETCOUNT = len(allnets)
    if len(allnets) != want_nets:
        problems.append(f"{len(allnets)} nets, want {want_nets} "
                        f"(6 rails + {len(pin_nets)} pads + 2 internal per "
                        f"cell)")
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
            "switches": 2 * n_cells, "bias": 2, "nets": NETCOUNT,
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
    if devs != 4 * n_cells + 2:
        die(f"PEX netlist instantiates {devs} devices, want "
            f"{4 * n_cells + 2}")
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
    pads = sum(v for n, v in tot.items()
               if n.startswith("d_") or n.startswith("db_"))
    net_cap["d_*/db_* (510 pads)"] = round(pads * 1e15, 2)
    net_cap["per pad"] = round(pads * 1e15 / (2 * n_cells), 3)
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
    want = ({"d_" + t for t in tags} | {"db_" + t for t in tags}
            | set(ANALOG_PORTS))
    got = set(pins)
    if got != want:
        problems.append(
            f"{len(got)} labelled ports, want {len(want)}: missing "
            f"{some(sorted(want - got))}, extra {some(sorted(got - want))}")

    row = [n for n, v in pins.items()
           if abs(v["bbox"][3] - PIN_Y_UM[1]) < 1e-6
           and abs(v["bbox"][1] - PIN_Y_UM[0]) < 1e-6]
    if len(row) != 2 * len(tags):
        problems.append(f"{len(row)} pads on the pin row, want {2 * len(tags)}")
    for i, tag in enumerate(tags):
        for j, name in enumerate(("d_" + tag, "db_" + tag)):
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
            want_x = PIN_X0_UM + PIN_PITCH_UM * (2 * i + j)
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
    for name in ("vdd", "iout", "idump"):
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
    # vbp/vcp/vss carry no DC current (gates and bulk ties only); report them
    # for settling and for the pair's bulk reference.
    for name in ("vbp", "vcp", "vss"):
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

    pads = ({"d_" + t for t in cell_tags(cfg)}
            | {"db_" + t for t in cell_tags(cfg)})
    sw_i = idx(lambda d: d[1][1] in pads)
    mir_i = idx(lambda d: d[1][1] == "vbp" and d[1][0] != "vbp")
    cas_i = idx(lambda d: d[1][1] == "vcp" and d[1][0] != "vcp")
    bm = idx(lambda d: d[1][1] == "vbp" and d[1][0] == "vbp")
    bc = idx(lambda d: d[1][1] == "vcp" and d[1][0] == "vcp")

    def drop(i, lst):
        return [d for k, d in enumerate(lst) if k != i]

    # Drop one pair switch: the device count and the pad walk break.
    p1 = check(drop(sw_i[len(sw_i) // 2], devs), scale, cfg) if sw_i else ["none"]
    # Re-label one switch gate onto its neighbour's pad: one pad unconnected,
    # one gate carrying two devices.
    p2 = check(swaps(sw_i[0], lambda n: [n[0], devs[sw_i[1]][1][1], n[2], n[3]]),
               scale, cfg) if len(sw_i) > 1 else ["none"]
    # Move a `d_` switch's drain to idump (the pair's two drains are fixed).
    p3 = check(swaps(sw_i[0], lambda n: ["idump", n[1], n[2], n[3]]),
               scale, cfg) if sw_i else ["none"]
    # Move its source onto a rail: the tail must be the cascode drain.
    p4 = check(swaps(sw_i[0], lambda n: [n[0], n[1], "iout", n[3]]),
               scale, cfg) if sw_i else ["none"]
    # Give one cell cascode the mirror length.
    p5 = check([(nm, nt, sb, dict(pp, l="200")) if i == cas_i[0]
                else (nm, nt, sb, pp)
                for i, (nm, nt, sb, pp) in enumerate(devs)], scale, cfg) \
        if cas_i else ["none"]
    # Shrink one mirror: all cells must be identical.
    p6 = check([(nm, nt, sb, dict(pp, w="4u")) if i == mir_i[-1]
                else (nm, nt, sb, pp)
                for i, (nm, nt, sb, pp) in enumerate(devs)], scale, cfg) \
        if mir_i else ["none"]
    # Break the bias: mirror gate to vcp, cascode source to vdd.
    p7 = check(swaps(bm[0], lambda n: [n[0], "vcp", n[2], n[3]]), scale,
               cfg) if bm else ["none"]
    p8 = check(swaps(bc[0], lambda n: [n[0], n[1], "vdd", n[3]]), scale,
               cfg) if bc else ["none"]
    # Put one cell's tail on the dump bus instead of the cascode.
    p9 = check(swaps(cas_i[-1], lambda n: ["idump", n[1], n[2], n[3]]),
               scale, cfg) if cas_i else ["none"]
    # Drop the replica cascode: the bias loop loses its diode.
    p10 = check(drop(bc[0], devs), scale, cfg) if bc else ["none"]
    # Put a PMOS gate on a pad: that is the old series-switch cell.
    p11 = check(swaps(mir_i[0], lambda n: [n[0], sorted(pads)[0], n[2], n[3]]),
                scale, cfg) if mir_i else ["none"]
    # Nfet bulk off vss.
    p12 = check(swaps(sw_i[0], lambda n: [n[0], n[1], n[2], "vdd"]),
                scale, cfg) if sw_i else ["none"]
    for name, prob in (("drop-switch", p1), ("relabel-gate", p2),
                       ("pair-drain", p3), ("pair-source", p4),
                       ("casc-length", p5), ("mirror-width", p6),
                       ("bias-gate", p7), ("bias-source", p8),
                       ("tail-off-bus", p9), ("drop-bias-casc", p10),
                       ("pmos-on-pad", p11), ("nfet-bulk", p12)):
        print(f"selftest {name:14}: {'FAIL' if prob else 'PASS (bad!)'} "
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
                             "postlayout", "mm", "tran"])
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--brief", action="store_true")
    a = ap.parse_args(argv)
    if a.selftest:
        return selftest()
    if a.stage in ("postlayout", "mm", "tran"):
        # Each bench owns the netlist, the gates and the report, so a stage
        # cannot drift from what it means.
        script = {"postlayout": "run_postlayout.py",
                  "mm": "run_mismatch_pex.py",
                  "tran": "run_transient_pex.py"}[a.stage]
        cmd = [sys.executable, str(ROOT / script)]
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
              f"{r['row']} on the 3.75 um digital row")
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
              f"idump {nc['idump']} fF, vss {nc['vss']} fF, "
              f"{nc['d_*/db_* (510 pads)']} fF on the pads "
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
