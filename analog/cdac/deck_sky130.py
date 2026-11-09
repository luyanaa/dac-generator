#!/usr/bin/env python3
"""Flatten the sky130 ngspice corner tree into one self-contained deck.

Why: ``sky130.lib.spice`` uses nested relative ``.include`` paths that only
resolve from inside the PDK tree, and the flattened device files reference
mismatch parameters in a scope ngspice does not populate.  Flattening once, in
order, into a single file fixes both:

  * every include is resolved relative to the file that contains it;
  * ``.param`` lines and the ``.model`` that uses them end up in one scope;
  * parameters the models reference but no corner file defines (the LOD
    ``*_diff`` terms, zero in the nominal case) are declared once as 0
    instead of failing the substitution.

This is a vendored, sky130-only copy of the flattener in
``../saradc_auto/gen/analog/deck.py`` (which also carries an ICsprout 55 nm
Xyce path and an unconditional ``hspice_expr`` import; neither is needed
here).  The output is a run artifact: it is not checked in and not a PDK copy.

    ./deck_sky130.py --corner-index $PDK/libs.tech/ngspice/corners/tt.spice \
        --out build/sky130_tt.spice
"""
from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path

INCLUDE = re.compile(r'^\s*\.include\s+"?([^"\s]+)"?', re.I)
PARAM_ALL = re.compile(r"^\s*\.param\s+(.+)$", re.I)
BRACED = re.compile(r"\{([^}]*)\}")
IDENT = re.compile(r"\bsky130_fd_pr__[A-Za-z0-9_]+")

# Includes that make up the digital/analog 1.8 V core.  The CDAC uses only
# nfet_01v8 / pfet_01v8 plus their mismatch corners.
WANTED = ["nfet_01v8__tt", "nfet_01v8__mismatch",
          "pfet_01v8__tt", "pfet_01v8__mismatch"]


def expand(path: str) -> str:
    return os.path.expandvars(os.path.expanduser(path))


def _read(path: str) -> str:
    with open(expand(path), encoding="utf-8", errors="replace") as fh:
        return fh.read()


def _resolve(ref: str, base: str) -> str:
    ref = ref.strip().strip('"')
    if not os.path.isabs(ref):
        ref = os.path.normpath(os.path.join(base, ref))
    return ref


def collect(path, lines, wanted=None, depth=0, seen=None):
    """Recursively inline a spice file, optionally filtering includes."""
    if depth > 12:
        raise SystemExit(f"include recursion too deep at {path}")
    seen = seen or set()
    real = os.path.realpath(expand(path))
    if real in seen:
        return
    seen.add(real)
    base = os.path.dirname(expand(path))
    for raw in _read(path).splitlines():
        inc = INCLUDE.match(raw)
        if inc:
            sub = _resolve(inc.group(1), base)
            if wanted and not any(w in os.path.basename(sub) for w in wanted):
                continue
            collect(sub, lines, wanted, depth + 1, seen)
            continue
        # .lib/.endl sections only exist for the top-level corner selector.
        if re.match(r"^\s*\.(lib|endl)\b", raw, re.I):
            continue
        lines.append(raw)


def declared_params(text: str) -> set[str]:
    names: set[str] = set()
    for line in text.splitlines():
        for chunk in PARAM_ALL.findall(line):
            for part in chunk.split():
                if "=" in part:
                    names.add(part.split("=", 1)[0].strip())
    return names


def referenced_params(text: str) -> set[str]:
    names: set[str] = set()
    for expr in BRACED.findall(text):
        names.update(IDENT.findall(expr))
    return names


def build(corner_index: str, out_path: str, wanted=None,
          temperature: float = 27.0) -> dict:
    wanted = WANTED if wanted is None else wanted
    lines = [f"* flattened sky130 deck, corner {os.path.basename(corner_index)}",
             f".options tnom={temperature:g} temp={temperature:g}"]
    collect(corner_index, lines, wanted=list(wanted))

    text = "\n".join(lines)
    missing = sorted(referenced_params(text) - declared_params(text))

    header = [".param mc_mm_switch=0", ".param mc_pr_switch=0"]
    header += [f".param {name}=0" for name in missing]

    os.makedirs(os.path.dirname(os.path.abspath(expand(out_path))),
                exist_ok=True)
    with open(expand(out_path), "w", encoding="utf-8") as fh:
        fh.write("\n".join(header) + "\n")
        fh.write(text + "\n")
    return {"path": out_path, "zeroed": missing,
            "bytes": os.path.getsize(expand(out_path)),
            "lines": len(text.splitlines())}


def find_corner(pdk_root: str, corner: str) -> Path:
    p = Path(pdk_root) / "sky130A/libs.tech/ngspice/corners" / f"{corner}.spice"
    if not p.is_file():
        raise SystemExit(f"missing corner file {p}")
    return p


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--corner-index", help=".../libs.tech/ngspice/corners/tt.spice")
    ap.add_argument("--pdk-root", default=os.environ.get("PDK_ROOT"),
                    help="sky130 version dir (parent of sky130A)")
    ap.add_argument("--corner", default="tt")
    ap.add_argument("--out", required=True)
    ap.add_argument("--temperature", type=float, default=27.0)
    a = ap.parse_args(argv)

    corner = a.corner_index
    if not corner:
        if not a.pdk_root:
            ap.error("--corner-index or --pdk-root is required")
        corner = str(find_corner(a.pdk_root, a.corner))
    info = build(corner, a.out, temperature=a.temperature)
    print(f"{info['path']}: {info['bytes']} bytes, {info['lines']} lines, "
          f"{len(info['zeroed'])} undefined params set to 0")
    for name in info["zeroed"]:
        print(f"  zeroed {name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
