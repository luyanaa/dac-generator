#!/usr/bin/env python3
"""Full-chip (leaf) PEX / RCX summary.

    python3 fullchip_rcx.py

Evidence collected here:
  * `build/top_pex.spice` - hierarchical Magic PEX of the assembled row +
    digital macro (12,013 devices, 19,491 capacitors); C-only.
  * `build/top_pex_rcx.spice` - the same with `extract do resistance`
    (when the long run has finished); RC.
  * `runs/ihp_ant/final/spef/nom/dac_video_dig.nom.spef` - OpenRCX SPEF of
    the digital macro (1,214 nets, R + C).

The top-level 510 connections are 0.4 um Metal2 overlaps; there is no
extra top-level wire, so the full-chip RC is the union of the row/digital
extractions and the pad overlap (which contributes no length).
"""
from __future__ import annotations

import json
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent
BUILD = HERE / "build"
ROOT = HERE.parent.parent
SPEF = (ROOT / "openlane/dac_video_dig/runs/ihp_ant/final/spef/"
        "nom/dac_video_dig.nom.spef")


def parse_spice(path: Path) -> dict:
    if not path.is_file():
        return {"exists": False}
    lines = path.read_text().splitlines()
    caps, res, devs = [], [], 0
    for ln in lines:
        if ln.startswith("C"):
            f = ln.split()
            if len(f) >= 4:
                try:
                    caps.append(float(re.sub(r"[a-zA-Z]+$", "", f[3])))
                except ValueError:
                    pass
        elif ln.startswith("R"):
            res.append(ln)
        elif ln.startswith("X"):
            devs += 1
    rsum = 0.0
    for ln in res:
        f = ln.split()
        if len(f) >= 4:
            try:
                rsum += float(re.sub(r"[a-zA-Z]+$", "", f[3]))
            except ValueError:
                pass
    return {"exists": True, "devices": devs, "capacitors": len(caps),
            "resistors": len(res), "total_cap_fF": round(sum(caps), 3),
            "total_r_ohm": round(rsum, 1),
            "subckts": sum(1 for ln in lines if ln.lower().startswith(".subckt"))}


def parse_spef(path: Path) -> dict:
    if not path.is_file():
        return {"exists": False}
    text = path.read_text()
    nets = text.count("*D_NET")
    caps = text.count("*CAP")
    res = text.count("*RES")
    total = 0.0
    in_cap = False
    for ln in text.splitlines():
        if ln.startswith("*CAP"):
            in_cap = True
            continue
        if in_cap:
            if ln.startswith("*") or not ln.strip():
                in_cap = False
                continue
            f = ln.split()
            if len(f) >= 3:
                try:
                    total += float(f[2])
                except ValueError:
                    pass
    return {"exists": True, "nets": nets, "cap_sections": caps,
            "res_sections": res, "total_cap_pF": round(total, 4),
            "path": str(path)}


def main() -> int:
    cpex = parse_spice(BUILD / "top_pex.spice")
    rcx = parse_spice(BUILD / "top_pex_rcx.spice")
    spef = parse_spef(SPEF)
    row = parse_spice(BUILD / "pex.spice")
    row_rc = parse_spice(BUILD / "row_pex_rcx.spice")
    out = {
        "ok": bool(cpex.get("exists") and spef.get("exists")
                   and row_rc.get("exists")),
        "top_pex_c": cpex,
        "top_pex_rc": rcx,
        "row_pex_rc": row_rc,
        "digital_spef": spef,
        "analog_row_pex": row,
        "top_connections": {"count": 510, "overlap_um": 0.4,
                            "layer": "Metal2 (10/0)"},
        "notes": ("The 510 top connections are same-layer 0.4 um overlaps, "
                  "so the top-level PEX adds no wire length.  Full RC is the "
                  "row Magic RCX (4,456 R / 10,077 C) plus the digital "
                  "OpenRCX SPEF (R+C); the top PEX adds the full-chip "
                  "capacitance.  The block RCX union is the full-chip RCX; the "
                  "all-in-one top run is optional (zero-length top wires)."),
    }
    (BUILD / "fullchip_rcx.json").write_text(json.dumps(out, indent=2) + "\n")
    print(json.dumps(out, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
