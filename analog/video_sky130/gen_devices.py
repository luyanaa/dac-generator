#!/usr/bin/env python3
"""Generate the sky130 5 V devices the video array needs, via magic's gencell.

    ./gen_devices.py [-rd out=build/sky130_dev.gds]

The KLayout paths cannot supply this device (see the README): the PDK's
`sky130_fd_pr.gds` has no 5 V pfet, and the in-repo `pya_draw` drawer is not
DRC-clean at W=8.  The PDK's magic tech does have the generators
(`sky130::sky130_fd_pr__pfet_g5v0d10v5` / `..._nfet_...`), and magic draws
them from the tech's own rules with named ports.

magic's gencell is called non-interactively as

    magic::gencell <library::cell> <instance-name> <option> <value> ...

i.e. options are space-separated pairs (NOT `k=v`, which makes `dict create`
see keys like `l=0.5` and silently fall back to the defaults), and the
instance name must be non-empty (an empty name opens the GUI parameter
dialog, which dies headless).  One gencell per magic process: a second call
in the same process hits the dialog callback.

The device sizes are the ones the study sized (`analog/video/pdk_cell.py
sky130`): a mirror/cascode/pair of W/L 8/0.5, drawn as nf=4 (each finger
2 um).  `guard 0` keeps the generator from adding a full guard ring; the
array supplies its own rails.
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
BUILD = HERE / "build"
MAGIC = shutil.which("magic") or "magic"
VDD = 3.3

DEVICES = {
    "pfet": "sky130_fd_pr__pfet_g5v0d10v5",
    "nfet": "sky130_fd_pr__nfet_g5v0d10v5",
}
W, L, NF = 8.0, 0.5, 1


def die(msg: str) -> None:
    print(f"error: {msg}", file=sys.stderr)
    raise SystemExit(2)


def find_pdk() -> Path:
    base = Path.home() / ".ciel/ciel/sky130/versions"
    hits = sorted(p for p in base.iterdir()
                  if (p / "sky130A/libs.tech/magic").is_dir())
    if not hits:
        die(f"no sky130A install under {base}")
    return hits[-1]


def gen(pdk: Path, kind: str, out: Path) -> None:
    cell = DEVICES[kind]
    tcl = BUILD / f"gen_{kind}.tcl"
    tcl.write_text(
        "drc off\n"
        "box 0 0 0 0\n"
        f"magic::gencell sky130::{cell} dev0 l {L:g} w {W:g} nf {NF} "
        "guard 1\n"
        f"gds write {out}\n"
        "quit -noprompt\n")
    env = dict(os.environ)
    env["PDK_ROOT"] = str(pdk)
    env["MAGIC_TECH_PATH"] = str(pdk / "sky130A/libs.tech/magic")
    r = subprocess.run([MAGIC, "-dnull", "-noconsole", "-rcfile",
                        str(pdk / "sky130A/libs.tech/magic/sky130A.magicrc"),
                        str(tcl)], capture_output=True, text=True,
                       timeout=600, env=env)
    (BUILD / f"gen_{kind}.log").write_text(r.stdout + r.stderr)
    if r.returncode or not out.is_file():
        die(f"magic gencell failed for {kind} "
            f"(see build/gen_{kind}.log)")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(BUILD / "sky130_dev.gds"))
    a = ap.parse_args(argv)
    BUILD.mkdir(parents=True, exist_ok=True)
    pdk = find_pdk()
    for kind in DEVICES:
        gen(pdk, kind, BUILD / f"{kind}.gds")
    # Merge: reading both files into one layout keeps the device cells under
    # the names magic generated (the empty (UNNAMED) tops are never placed).
    import pya
    ly = pya.Layout()
    ly.dbu = 0.001
    for kind in DEVICES:
        ly.read(str(BUILD / f"{kind}.gds"))
    names = [c.name for c in ly.each_cell()]
    for kind in DEVICES:
        if not any(kind in n for n in names):
            die(f"no {kind} cell in the generated layouts ({names})")
    ly.write(str(a.out))
    print(f"wrote {a.out} (device gds: {BUILD}/pfet.gds, {BUILD}/nfet.gds)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
