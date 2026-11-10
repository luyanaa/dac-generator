#!/usr/bin/env python3
"""Post-layout check of the current-steering core (gf180mcuA).

    ./run_postlayout.py            # dc + transient on the extracted core
    ./run_postlayout.py --brief

This closes the loop the layout opens: `signoff.py` builds the 30-cell array
with its replica cascode bias and 60 steering switches and extracts it, but
until here the PEX netlist was evidence only.  The script instantiates the
hierarchical extraction of the whole core (122 devices plus the 1022 coupling
capacitors) and re-runs the two switch measurements of `run_switch.py` against
the same gates, so pre- and post-layout numbers are comparable:

  dc    one cell's pair swept over the control voltage, every other cell parked
        on `idump`: dc sum error, Ron, output compliance.

  tran  the same make-before-break edge the pre-layout bench uses: integrated
        event charge error on `iout`, pair charge error, peak displacement and
        settling to +-0.5 LSB.

  code  0..255 with all 60 gates driven the way the digital macro drives them:
        full scale, the unary step, DNL/INL and monotonicity on the extracted
        core.  This is the gate that a mis-sized binary field cannot pass.

The difference to the pre-layout bench is exactly the layout: the switching
node now carries its extracted tail capacitance instead of a guessed 10 fF,
and `iout`/`idump` carry the extracted bus plus all 60 switch drain caps.

Fail-closed: with no `build/magic/pex.spice`, or a PEX older than the GDS it
came from, this exits 2 instead of running a stale or pre-layout netlist under
a post-layout name.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

from gen_csteer import load_cfg, models, pdk_root
from run_switch import QSUM_MAX, Q_MAX, RON_MAX, SETTLE_MAX

ROOT = Path(__file__).resolve().parent
BUILD = ROOT / "build"
PEX = BUILD / "magic" / "pex.spice"
TOP = "dac_csteer_ana"


def die(msg: str, code: int = 2):
    print(f"error: {msg}", file=sys.stderr)
    raise SystemExit(code)


def ports(pex: Path) -> list[str]:
    txt = pex.read_text()
    m = re.search(r"^\.subckt\s+" + TOP + r"\s+(.*?)(?=^[.X])", txt,
                  re.M | re.S)
    if not m:
        die(f"no .subckt {TOP} in {pex}")
    return m.group(1).replace("+", " ").split()


def wrdata(path: Path) -> list[list[float]]:
    rows = []
    for ln in path.read_text().splitlines():
        f = ln.split()
        if len(f) < 2:
            continue
        try:
            rows.append([float(v) for v in f])
        except ValueError:
            continue
    return rows


def ngspice(netlist: Path) -> None:
    r = subprocess.run(["ngspice", "-b", str(netlist)], capture_output=True,
                       text=True)
    txt = r.stdout + r.stderr
    if r.returncode or "Error!" in txt:
        tail = "\n".join(l for l in txt.splitlines()
                         if "rror" in l or "singular" in l)[-1500:]
        die(f"ngspice failed on {netlist.name}\n{tail}")


def netlist_head(cfg, pdk: str, root: Path, pex: Path, pts: list[str]) -> list[str]:
    return [
        f"* post-layout: {TOP} from {pex.name}",
        models(cfg, pdk, root, 25.0, "tt"),
        f'.include "{pex}"',
        "Vdd vdd 0 %.3f" % cfg["vdd"],
        "Vss vss 0 0",
        "Iref vcp 0 %gu" % float(cfg["i_unit_ua"]),
        "Xcore " + " ".join(pts) + f" {TOP}",
    ]


def park(lines: list[str], pts: list[str], drive: str,
         vdd: float) -> list[str]:
    """Every switch off `drive`: row A on for iout, row B on for idump."""
    for p in pts:
        if p.startswith("swa_"):
            lines.append(f"V{p} {p} 0 {vdd if drive == 'iout' else 0.0:.3f}")
        elif p.startswith("swb_"):
            lines.append(f"V{p} {p} 0 {vdd if drive == 'idump' else 0.0:.3f}")
    return lines


def bench_dc(cfg, pdk: str, root: Path, pts: list[str]) -> dict:
    out = BUILD / "post_dc.dat"
    vdd = float(cfg["vdd"])
    lines = [l for l in park(netlist_head(cfg, pdk, root, PEX, pts), pts,
                             "idump", vdd)
             if not l.startswith(("Vswa_u0", "Vswb_u0"))]
    lines += [
        # cell u0 is the one under test: row A ramps up while row B ramps down
        # through a behavioural source, so the pair is always legal.
        "Vswp swa_u0 0 0",
        f"Bswb_u0 swb_u0 0 V = {vdd:.3f} - v(swa_u0)",
        "Vmi iout 0 0",
        "Vmn idump 0 0",
        ".control", "set wr_singlescale", "set wr_vecnames",
        f"dc Vswp 0 {vdd} 0.01",
        f"wrdata {out} v(swa_u0) i(Vmi) i(Vmn) v(cd_u0)",
        ".endc", ".end",
    ]
    nl = BUILD / "post_dc.spice"
    nl.write_text("\n".join(lines) + "\n")
    ngspice(nl)
    dcs = wrdata(out)
    if len(dcs) < 10:
        die("dc sweep produced no data")

    # Columns: scale, swa_u0, i(iout), i(idump), v(cd_u0).  The iout/idump
    # sources are 0 V, so i() is the current the buses collect.  The other 29
    # cells are parked, so only u0's share moves over the sweep: its full
    # current is the iout rise, and the pair sum must stay at that total.
    iout0, idump0 = dcs[0][2], dcs[0][3]
    icell = dcs[-1][2] - iout0
    if icell <= 0:
        die(f"u0 delivered {icell * 1e6:.3f} uA; did the sweep park it?")
    tot0 = iout0 + idump0
    sum_err = max(abs(r[2] + r[3] - tot0) for r in dcs) / icell
    on = dcs[-1]
    ron = on[4] / (on[2] - iout0) if on[2] > iout0 else float("inf")

    # Output compliance: hold the drive fully on one side and lift the bus.
    out2 = BUILD / "post_comp.dat"
    lines = [l for l in park(netlist_head(cfg, pdk, root, PEX, pts), pts,
                             "idump", vdd)
             if not l.startswith(("Vswa_u0", "Vswb_u0"))]
    lines += [
        f"Vswp swa_u0 0 {vdd}",
        "Vswn swb_u0 0 0",
        "Vmi iout 0 0",
        "Vmn idump 0 0",
        ".control", "set wr_singlescale", "set wr_vecnames",
        "dc Vmi 0 2.5 0.02",
        f"wrdata {out2} v(iout) i(Vmi) v(cd_u0)",
        ".endc", ".end",
    ]
    nl2 = BUILD / "post_comp.spice"
    nl2.write_text("\n".join(lines) + "\n")
    ngspice(nl2)
    comp = wrdata(out2)
    comp_v = 0.0
    for r in comp:
        if abs(r[2] - icell) <= 0.01 * icell:
            comp_v = max(comp_v, r[1])

    return {"icell": icell, "sum_err": sum_err, "ron": ron,
            "compliance": comp_v, "sweep": str(out)}


def bench_tran(cfg, pdk: str, root: Path, pts: list[str]) -> dict:
    out = BUILD / "post_tran.dat"
    vdd = float(cfg["vdd"])
    edge = float(cfg["sw_edge_ns"])
    skew = float(cfg["sw_skew_ns"])
    t0, t1 = 10.0, 50.0

    def pulse(lo, hi, delay=0.0):
        return (f"PWL(0 {lo} {t0 + delay}n {lo} {t0 + delay + edge}n {hi} "
                f"{t1}n {hi} {t1 + edge}n {lo} {t1 + edge + 1}n {lo})")

    # Park every cell except u0 on idump, then flip u0 from idump to iout.
    lines = [l for l in park(netlist_head(cfg, pdk, root, PEX, pts), pts,
                             "idump", vdd)
             if not l.startswith(("Vswa_u0", "Vswb_u0"))]
    lines += [
        f"Vswa_u0 swa_u0 0 {pulse(0.0, vdd)}",
        f"Vswb_u0 swb_u0 0 {pulse(vdd, 0.0, skew)}",
        "Vmi iout 0 0",
        "Vmn idump 0 0",
        ".control", "set wr_singlescale", "set wr_vecnames",
        "tran 0.005n 70n",
        f"wrdata {out} v(swa_u0) v(swb_u0) v(cd_u0) i(Vmi) i(Vmn)",
        ".endc", ".end",
    ]
    nl = BUILD / "post_tran.spice"
    nl.write_text("\n".join(lines) + "\n")
    ngspice(nl)
    trn = wrdata(out)
    if len(trn) < 100:
        die("transient produced no data")

    dcs = wrdata(BUILD / "post_dc.dat")
    iout0 = dcs[0][2]
    icell = dcs[-1][2] - iout0

    # Same metric as run_switch.py, on u0's share of the buses: the other 29
    # cells are parked, so subtract their constant contribution and integrate
    # the deviation from an ideal step at the gate midpoint.
    iout_park, tot_park = trn[0][4], trn[0][4] + trn[0][5]
    ts = 10.0e-9 + 0.5 * edge * 1e-9
    q = qsum = peak = cd_exc = 0.0
    for i in range(1, len(trn)):
        t = trn[i][0]
        dt = t - trn[i - 1][0]
        if 9.5e-9 <= t <= 11.5e-9:
            iu = trn[i][4] - iout_park
            ideal = icell if t >= ts else 0.0
            q += (iu - ideal) * dt
            # The pair total at t=0 already contains u0's full cell current,
            # so its deviation from that baseline is the pair charge error.
            qsum += (trn[i][4] + trn[i][5] - tot_park) * dt
            peak = max(peak, iu)
            cd_exc = max(cd_exc, abs(trn[i][3]))
        if t > 11.5e-9:
            break
    last_bad = None
    for r in trn:
        if 10.2e-9 <= r[0] <= 45e-9 and abs(r[4] - iout_park - icell) > 0.5e-6:
            last_bad = r[0]
    settle = 0.0 if last_bad is None else last_bad - 10.2e-9
    return {"q": q, "qsum": qsum, "peak": peak, "cd_exc": cd_exc,
            "settle": settle, "sweep": str(out)}


def bench_transfer(cfg, pdk: str, root: Path, pts: list[str],
                   r_series: float = 0.0) -> dict:
    """All 256 codes on the extracted core: the DAC transfer curve.

    This is the check the layout did not have: every switch gate is driven the
    way `dac_csteer_dig` drives it (thermometer on the MSBs, one register bit
    fanned to all cells of a binary weight), the output is a virtual ground,
    and the code is swept end to end.  The DWA pointer only permutes which
    unary cell is on, so it cannot change the sum and the bench uses pointer 0.

    `r_series` puts that resistance between `iout` and the 0 V source, i.e. it
    models a passive I-V of that input impedance.  Run it at 1 kOhm to show
    that the leaf does not need an opamp transimpedance stage.
    """
    tag = "gnd" if not r_series else f"{r_series:.0f}"
    out = BUILD / f"post_transfer_{tag}.dat"
    vdd = float(cfg["vdd"])
    ub = int(cfg["unary_bits"])
    bb = int(cfg["binary_bits"])
    bits = int(cfg["bits"])

    conds: dict[str, str] = {}
    for j in range(2 ** ub - 1):
        conds[f"u{j}"] = f"(floor(v(code)/{2 ** bb}) > {j + 0.5})"
    for k in range(bb):
        w = 2 ** k
        bit = f"(floor(v(code)/{w})-2*floor(v(code)/{2 * w}))"
        for i in range(w):
            conds[f"b{w}_{i}"] = f"({bit} > 0.5)"

    lines = netlist_head(cfg, pdk, root, PEX, pts)
    lines.append("Vcode code 0 0")
    want = {p for p in pts if p.startswith(("swa_", "swb_"))}
    got = {pfx + t for t in conds for pfx in ("swa_", "swb_")}
    if got != want:
        die(f"transfer drive covers {len(got)} gates, netlist has {len(want)}")
    for tag, cond in conds.items():
        lines.append(f"Bswa_{tag} swa_{tag} 0 V = {vdd:.3f}*{cond}")
        lines.append(f"Bswb_{tag} swb_{tag} 0 V = {vdd:.3f}*(1-{cond})")
    if r_series:
        lines += [f"Rz iout nz {r_series:.6g}", "Vz nz 0 0",
                  "Vmn idump 0 0"]
        probe = "i(Vz)"
    else:
        lines += ["Vmi iout 0 0", "Vmn idump 0 0"]
        probe = "i(Vmi)"
    lines += [
        ".control", "set wr_singlescale", "set wr_vecnames",
        f"dc Vcode 0 {2 ** bits - 1} 1",
        f"wrdata {out} v(code) {probe} i(Vmn)",
        ".endc", ".end",
    ]
    nl = BUILD / f"post_transfer_{tag}.spice"
    nl.write_text("\n".join(lines) + "\n")
    ngspice(nl)
    rows = wrdata(out)
    if len(rows) < 2 ** bits:
        die(f"transfer sweep produced {len(rows)} rows, want {2 ** bits}")

    # iout, the I-V input node.  With a series R the current is read at the 0 V
    # source behind it, so take the magnitude (the direction depends on the
    # source orientation, the DAC current does not).
    i = [abs(r[2]) if r_series else r[2] for r in rows]
    i0 = i[0]
    fs = i[-1] - i0
    if fs <= 0:
        die(f"full scale {fs * 1e6:.3f} uA; is the output grounded?")
    lsb = fs / (2 ** bits - 1)
    steps = [i[c] - i[c - 1] for c in range(1, len(i))]
    dnl = max(abs(s / lsb - 1.0) for s in steps)
    inl = max(abs((i[c] - i0) / lsb - c) for c in range(len(i)))
    bad = [c for c, s in enumerate(steps, 1) if s < -0.05 * lsb]
    return {"fs": fs, "lsb": lsb, "dnl": dnl, "inl": inl,
            "nonmono": len(bad), "first_bad": bad[:5],
            "unary_step": (i[2 ** bb] - i0) / lsb,
            "sweep": str(out)}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--brief", action="store_true")
    ap.add_argument("--pdk", default="gf180", choices=["gf180", "sky130"])
    a = ap.parse_args(argv)
    if a.pdk != "gf180":
        die("post-layout extraction exists for gf180 only", 2)
    if not PEX.is_file():
        die(f"no {PEX.relative_to(ROOT)}; build and extract first "
            f"(./signoff.py --stage pex)")
    gds = BUILD / "csteer.gds"
    if gds.is_file() and gds.stat().st_mtime > PEX.stat().st_mtime:
        die(f"stale {PEX.name}: {gds.name} is newer; re-extract with "
            f"./signoff.py --stage pex")

    cfg = load_cfg()
    root = pdk_root(cfg, a.pdk, None)
    pts = ports(PEX)

    dc = bench_dc(cfg, a.pdk, root, pts)
    tr = bench_tran(cfg, a.pdk, root, pts)
    tf = bench_transfer(cfg, a.pdk, root, pts)
    tf1k = bench_transfer(cfg, a.pdk, root, pts, r_series=1000.0)
    want_fs = (2 ** int(cfg["bits"]) - 1) * float(cfg["i_lsb_ua"])

    checks = [
        ("dc sum error", dc["sum_err"] < 0.01,
         f"{dc['sum_err'] * 100:.3f} %"),
        ("switch Ron", dc["ron"] < RON_MAX, f"{dc['ron']:.0f} ohm"),
        ("output compliance", dc["compliance"] > 1.5,
         f"{dc['compliance']:.2f} V"),
        ("event charge error", abs(tr["q"]) < Q_MAX,
         f"{tr['q'] * 1e15:.1f} fC"),
        ("pair charge error", abs(tr["qsum"]) < QSUM_MAX,
         f"{tr['qsum'] * 1e15:.1f} fC"),
        ("settle to 0.5 LSB", tr["settle"] < SETTLE_MAX,
         f"{tr['settle'] * 1e12:.0f} ps"),
        ("full scale", abs(tf["fs"] * 1e6 - want_fs) < 0.05 * want_fs,
         f"{tf['fs'] * 1e6:.1f} uA"),
        ("unary step 16 LSB", abs(tf["unary_step"] - 16.0) < 1.0,
         f"{tf['unary_step']:.2f} LSB"),
        ("transfer DNL", tf["dnl"] < 0.5, f"{tf['dnl']:.3f} LSB"),
        ("transfer INL", tf["inl"] < 1.0, f"{tf['inl']:.3f} LSB"),
        ("monotonic", tf["nonmono"] == 0, f"{tf['nonmono']} bad steps"),
        # A 1 kOhm passive I-V is the cheapest termination the leaf can use;
        # it must be indistinguishable from the virtual ground.  This is the
        # check that a 1000x cell-ro error would fail.
        ("passive 1 kOhm I-V",
         abs(tf1k["inl"] - tf["inl"]) < 0.05
         and abs(tf1k["fs"] - tf["fs"]) < 0.005 * tf["fs"],
         f"INL {tf1k['inl']:.3f} / FS {tf1k['fs'] * 1e6:.1f} uA"),
    ]
    ok = True
    if not a.brief:
        print(f"post-layout core ({PEX.name}, {len(pts)} ports, "
              f"Icell {dc['icell'] * 1e6:.3f} uA)")
        print(f"  peak displacement   : {tr['peak'] * 1e6:.1f} uA")
        print(f"  cascode drain swing : {tr['cd_exc'] * 1e3:.1f} mV")
        print(f"  transfer            : FS {tf['fs'] * 1e6:.1f} uA "
              f"(want {want_fs:.1f}), LSB {tf['lsb'] * 1e6:.3f} uA, "
              f"unary step {tf['unary_step']:.2f} LSB")
        print(f"  1 kOhm passive I-V  : INL {tf1k['inl']:.3f} LSB, "
              f"FS {tf1k['fs'] * 1e6:.1f} uA "
              f"(virtual ground {tf['inl']:.3f} LSB)")
    for name, good, val in checks:
        ok &= good
        if a.brief:
            print(f"{name:22} {val:>12}  {'ok' if good else 'FAIL'}")
        else:
            print(f"  {name:20}: {val:>12}  {'ok' if good else 'FAIL'}")
    print(f"post-layout {'PASS' if ok else 'FAIL'}")
    (BUILD / "postlayout.json").write_text(json.dumps(
        {"ok": ok, "pdk": a.pdk, "pex": str(PEX), "ports": len(pts),
         "dc": dc, "tran": tr, "transfer": tf, "termination_1k": tf1k},
        indent=1) + "\n")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
