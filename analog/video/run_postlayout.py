#!/usr/bin/env python3
"""Post-layout DC transfer of the 255-cell video array (gf180mcuA).

    ./run_postlayout.py            # virtual ground + 37.5 ohm load
    ./run_postlayout.py --brief

`signoff.py` builds and extracts the array but leaves the netlist as evidence.
This runs the extracted *devices* - the drawn W/L and ad/as in place - through
the full 256-code transfer, driven the way `dac_video_dig.v` drives the pair
(one bit per physical cell, bit k fanned to all 2^k cells, `d_`/`db_`
complementary), so the pre-layout model's assumptions get checked:

  * the drawn unit current, and therefore the gain, comes from the replica
    diode alone: the pair steers a constant tail, so unlike the first
    series-switch cell there is no I*Ron degeneration to reproduce in the
    bias branch.  `--selftest` moves the bias mirror's source off vdd and
    requires the bench to reject the resulting operating point;
  * with 255 identical devices and an ideal decoder the transfer must be
    monotonic and linear except for the two second-order terms: the ro
    modulation by the output swing, and the code-dependent vdd drop that the
    extracted netlist does not contain (Magic emits capacitance only, no
    metal resistance - that term stays the analytic estimate in `signoff.py`);
  * the 37.5 ohm load must be indistinguishable from a virtual ground, which
    is the leaf's claim that it needs no transimpedance stage.

Fail-closed: no netlist, or one older than the GDS, exits 2 instead of
running a stale or pre-layout deck under a post-layout name.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
BUILD = ROOT / "build"
GDS = BUILD / "video.gds"
LVS = BUILD / "magic" / "lvs.spice"
PEX = BUILD / "magic" / "pex.spice"
TOP = "dac_video_ana"


def die(msg: str, code: int = 2):
    print(f"error: {msg}", file=sys.stderr)
    raise SystemExit(code)


def load_cfg() -> dict:
    try:
        import yaml
    except ImportError:  # pragma: no cover
        die("PyYAML is required: pip install pyyaml")
    with open(ROOT / "video.yaml") as f:
        return yaml.safe_load(f)


def pdk_root() -> Path:
    base = Path(os.path.expanduser("~/.ciel/ciel/gf180mcu/versions"))
    if not base.is_dir():
        die(f"{base} not found")
    ver = sorted(p.name for p in base.iterdir() if p.is_dir())[-1]
    return base / ver / "gf180mcuA"


def models(root: Path, temp: float = 25.0) -> list[str]:
    libdir = root / "libs.tech" / "ngspice"
    lib = libdir / "sm141064.ngspice"
    if not lib.is_file():
        die(f"model library not found: {lib}")
    # The flat extraction carries `.option scale=5n`, and it is load-bearing:
    # Magic writes w=1600 l=200 in 5 nm units, and without the option those
    # are printed as metres, so the PDK's binned model lookup finds no bin and
    # ngspice reports "could not find a valid modelname".
    return [f'.lib "{lib}" typical',
            f'.include "{libdir / "design.spice"}"',
            ".option scale=5n",
            f".temp {temp}"]


def cell_bit(j: int) -> int:
    k = 0
    while j >= 2 ** (k + 1) - 1:
        k += 1
    return k


def devices(txt: str) -> list[str]:
    """The flat extraction's device lines, ready to paste at top level."""
    out = []
    for ln in txt.splitlines():
        s = ln.strip()
        if s.startswith("X") and len(s.split()) >= 6:
            out.append(s)
    return out


def net_names(devs: list[str]) -> set[str]:
    nets: set[str] = set()
    for ln in devs:
        nets.update(ln.split()[1:5])
    return nets


def wrdata(path: Path) -> tuple[dict[str, int], list[list[float]]]:
    """Parse wrdata output: the vector-name header plus the numeric rows.

    `set wr_vecnames` writes the names, so the columns are looked up by name
    instead of assumed: with `wr_singlescale` the sweep is column 0 and the
    first requested vector is column 1, which is easy to get wrong.
    """
    names, rows = {}, []
    for ln in path.read_text().splitlines():
        f = ln.split()
        if len(f) < 2:
            continue
        try:
            rows.append([float(v) for v in f])
        except ValueError:
            if not names:
                names = {v: i for i, v in enumerate(f)}
    return names, rows


def ngspice(netlist: Path, timeout: int = 3600) -> None:
    r = subprocess.run(["ngspice", "-b", str(netlist)], capture_output=True,
                       text=True, timeout=timeout)
    txt = r.stdout + r.stderr
    if r.returncode or "Error!" in txt:
        tail = "\n".join(l for l in txt.splitlines()
                         if "rror" in l or "singular" in l)[-1500:]
        die(f"ngspice failed on {netlist.name}\n{tail}")


def drive(cfg) -> list[str]:
    """The 510 gate drives, from the same cell->bit rule as the RTL.

    The pair steers the tail: `d_<tag>` high puts the cell's 16 uA on `iout`,
    `db_<tag>` is its complement.  A cell that is on therefore has its NMOS
    gate at vdd and its dump switch at 0.
    """
    vdd = float(cfg["vdd"])
    n = 2 ** int(cfg["bits"]) - 1
    lines = []
    for j in range(n):
        k = cell_bit(j)
        w = 2 ** k
        bit = (f"(floor(v(code)/{w})-2*floor(v(code)/{2 * w}))")
        tag = f"b{k}_{j - (2 ** k - 1)}"
        lines.append(f"Bd_{tag} d_{tag} 0 V = {vdd:.3f}*{bit}")
        lines.append(f"Bdb_{tag} db_{tag} 0 V = {vdd:.3f}*(1-{bit})")
    return lines


def transfer(cfg, root: Path, devs: list[str], r_series: float,
             tag: str) -> dict:
    vdd = float(cfg["vdd"])
    n_code = 2 ** int(cfg["bits"])
    out = BUILD / f"post_transfer_{tag}.dat"
    lines = [f"* post-layout DC transfer, {tag}",
             *models(root),
             *devs,
             f"Vdd vdd 0 {vdd:.3f}",
             "Vss vss 0 0",
             # The dump bus returns to ground (a tail that is not on iout).
             "Vdump idump 0 0",
             "Iref vcp 0 %gu" % float(cfg["i_unit_ua"]),
             "Vcode code 0 0",
             *drive(cfg)]
    if r_series:
        lines += [f"Rz iout nz {r_series:.6g}", "Vz nz 0 0"]
        probe = "i(Vz)"
    else:
        lines += ["Vmi iout 0 0"]
        probe = "i(Vmi)"
    lines += [".control", "set wr_singlescale", "set wr_vecnames",
              f"dc Vcode 0 {n_code - 1} 1",
              f"wrdata {out} v(code) {probe} v(vbp) v(vcp) i(Vdd)",
              ".endc", ".end"]
    nl = BUILD / f"post_transfer_{tag}.spice"
    nl.write_text("\n".join(lines) + "\n")
    ngspice(nl)
    names, rows = wrdata(out)
    if len(rows) < n_code:
        die(f"transfer sweep produced {len(rows)} rows, want {n_code}")
    for want in ("i(Vz)" if r_series else "i(Vmi)", "v(vbp)", "v(vcp)",
                 "i(Vdd)"):
        if want not in names:
            die(f"wrdata has no {want} column ({sorted(names)})")
    ci = names["i(Vz)" if r_series else "i(Vmi)"]
    cvb, cvc, cid = names["v(vbp)"], names["v(vcp)"], names["i(Vdd)"]

    i = [abs(r[ci]) for r in rows]
    i0 = i[0]
    fs = i[-1] - i0
    if fs <= 0:
        die(f"full scale {fs * 1e6:.3f} uA; is the output grounded?")
    lsb = fs / (n_code - 1)
    steps = [i[c] - i[c - 1] for c in range(1, len(i))]
    dnl = max(abs(s / lsb - 1.0) for s in steps)
    inl = max(abs((i[c] - i0) / lsb - c) for c in range(len(i)))
    bad = [c for c, s in enumerate(steps, 1) if s < -0.05 * lsb]
    return {"fs": fs, "lsb": lsb, "dnl": dnl, "inl": inl,
            "nonmono": len(bad), "first_bad": bad[:5],
            "i_full_supply_ma": abs(rows[-1][cid]) * 1e3,
            "vbp": rows[-1][cvb], "vcp": rows[-1][cvc],
            "sweep": str(out)}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--brief", action="store_true")
    ap.add_argument("--riv", type=float, default=37.5,
                    help="load resistance at iout (0 = virtual ground)")
    ap.add_argument("--selftest", action="store_true",
                    help="re-run with the bias mirror's source off vdd "
                         "(an operating point the gate must reject)")
    a = ap.parse_args(argv)

    if not LVS.is_file():
        die(f"no {LVS.relative_to(ROOT)}; extract first "
            f"(./signoff.py --stage lvs)")
    if GDS.is_file() and GDS.stat().st_mtime > LVS.stat().st_mtime:
        die(f"stale {LVS.name}: {GDS.name} is newer; re-extract with "
            f"./signoff.py --stage lvs")
    if not PEX.is_file():
        die(f"no {PEX.relative_to(ROOT)}; run ./signoff.py --stage pex")

    cfg = load_cfg()
    root = pdk_root()
    txt = LVS.read_text()
    devs = devices(txt)
    nets = net_names(devs)
    n_cells = 2 ** int(cfg["bits"]) - 1
    if len(devs) != 4 * n_cells + 2:
        die(f"netlist has {len(devs)} devices, want {4 * n_cells + 2}")
    tags = [f"b{cell_bit(j)}_{j - (2 ** cell_bit(j) - 1)}"
            for j in range(n_cells)]
    want = ({"d_" + t for t in tags} | {"db_" + t for t in tags})
    got = {p for p in nets if p.startswith("d_") or p.startswith("db_")}
    if got != want:
        die(f"netlist exposes {len(got)} pads, want {len(want)}")
    for rail in ("vdd", "vss", "vbp", "vcp", "iout", "idump"):
        if rail not in nets:
            die(f"netlist has no {rail}")
    if "vgnd" in nets:
        die("netlist has vgnd; this is the old series-switch cell")
    pts = sorted(nets)

    i_unit = float(cfg["i_unit_ua"])
    gnd = transfer(cfg, root, devs, 0.0, "gnd")
    rl = transfer(cfg, root, devs, a.riv, f"{a.riv:.0f}") \
        if a.riv else gnd
    want_fs = n_cells * i_unit          # uA
    drawn = gnd["fs"] / n_cells         # A
    gain_shift = drawn * 1e6 / i_unit - 1.0

    if a.riv:
        load_ok = (abs(rl["inl"] - gnd["inl"]) < 0.05
                   and abs(rl["fs"] - gnd["fs"]) < 0.01 * gnd["fs"])
        load_val = f"INL {rl['inl']:.3f} / FS {rl['fs'] * 1e6:.1f} uA"
    else:
        load_ok, load_val = True, "skipped"

    checks = [
        ("full scale", abs(gnd["fs"] * 1e6 - want_fs) < 0.6 * want_fs,
         f"{gnd['fs'] * 1e6:.1f} uA vs {want_fs:.1f}"),
        # The replica diode sets the unit current, so the drawn current must
        # land on the reference; 5 % covers the yaml's 16.0 uA rounding.  A
        # bias mirror whose source is not vdd lands far away and `--selftest`
        # requires that to fail.
        ("drawn unit current", abs(gain_shift) < 0.05,
         f"{drawn * 1e6:.3f} uA ({gain_shift * 100:+.1f} % vs model)"),
        ("transfer DNL", gnd["dnl"] < 0.5, f"{gnd['dnl']:.3f} LSB"),
        ("transfer INL", gnd["inl"] < 0.5, f"{gnd['inl']:.3f} LSB"),
        ("monotonic", gnd["nonmono"] == 0, f"{gnd['nonmono']} bad steps"),
        # The bias must sit where a cascoded mirror needs it: vbp one mirror
        # Vsg below vdd, vcp one cascode Vsg below vbp.
        ("bias stack", 1.2 < gnd["vbp"] < float(cfg["vdd"]) - 0.3
         and 0.15 < gnd["vcp"] < gnd["vbp"] - 0.2,
         f"vbp {gnd['vbp']:.3f} V, vcp {gnd['vcp']:.3f} V"),
        # The leaf's claim: a 37.5 ohm resistor is a sufficient termination.
        ("37.5 ohm load", load_ok, load_val),
    ]
    ok = True
    if not a.brief:
        print(f"post-layout array ({LVS.name}, {len(devs)} devices, "
              f"{len(pts)} ports)")
        print(f"  virtual ground      : FS {gnd['fs'] * 1e6:.1f} uA, "
              f"LSB {gnd['lsb'] * 1e6:.3f} uA, "
              f"Icell {drawn * 1e6:.3f} uA")
        print(f"  full-code supply    : {gnd['i_full_supply_ma']:.3f} mA")
        if a.riv:
            print(f"  {a.riv:g} ohm load       : FS {rl['fs'] * 1e6:.1f} uA, "
                  f"INL {rl['inl']:.3f} LSB (virtual ground "
                  f"{gnd['inl']:.3f})")
    for name, good, val in checks:
        ok &= good
        print(f"  {name:20}: {val:>28}  {'ok' if good else 'FAIL'}")
    print(f"post-layout {'PASS' if ok else 'FAIL'}")
    (BUILD / "postlayout.json").write_text(json.dumps(
        {"ok": ok, "netlist": str(LVS), "devices": len(devs),
         "ports": len(pts), "i_unit_drawn_ua": drawn * 1e6,
         "gain_shift_pct": gain_shift * 100,
         "virtual_ground": gnd, "load": rl}, indent=1) + "\n")
    if a.selftest:
        return selftest(cfg, root, devs, ok)
    return 0 if ok else 1


def selftest(cfg, root: Path, devs: list[str], good_ok: bool) -> int:
    """Re-run with the bias mirror's source moved off vdd.

    The cell's current is set by the replica's diode (mirror + cascode), so a
    bias mirror whose source is not vdd is a different operating point and the
    unit current must move far outside the 16 uA the leaf is built on.  The
    gate must notice - if this passes, the bench is not measuring the bias it
    claims to.
    """
    n_cells = 2 ** int(cfg["bits"]) - 1
    mut = []
    hit = 0
    for ln in devs:
        f = ln.split()
        if f[2] == "vbp" and f[1] == "vbp":
            hit += 1
            ln = " ".join([f[0], f[1], f[2], "vcp", f[4]] + f[5:])
        mut.append(ln)
    print()
    print(f"selftest nominal      : {'PASS' if good_ok else 'FAIL (bad!)'}")
    if hit != 1:
        print(f"selftest bad-bias      : cannot run ({hit} bias mirrors found)")
        return 1
    r = transfer(cfg, root, mut, 0.0, "selftest")
    drawn = r["fs"] / n_cells * 1e6
    shift = drawn / float(cfg["i_unit_ua"]) - 1.0
    bad = abs(shift) > 0.10
    print(f"selftest bad-bias      : drawn {drawn:.3f} uA "
          f"({shift * 100:+.1f} % vs model) "
          f"{'rejected' if bad else 'PASS (bad!)'}")
    ok = good_ok and bad
    print("selftest " + ("PASS" if ok else "FAIL"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
