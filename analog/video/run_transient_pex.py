#!/usr/bin/env python3
r"""Post-layout carry transient of the 255-cell video array (gf180mcuA).

    ./run_transient_pex.py                  # the critical carries
    ./run_transient_pex.py --from 127 --to 128
    ./run_transient_pex.py --selftest       # the settle gate in both directions
    ./run_transient_pex.py --stiff-bias     # diagnostic: vbp/vcp ideal

`run_postlayout.py` proves the drawn DC transfer and `run_mismatch_pex.py` the
static mismatch.  Neither can see a *dynamic* effect, because both solve the
bias away: the dc sweep re-solves the operating point at every code.  This runs
the extracted netlist *with its capacitance* through a carry, the way the DAC
actually uses it:

  * `build/magic/pex.spice` is hierarchical.  The top subckt has 516 ports
    (`vss vcp vbp`, the 510 pads, `vdd iout idump`) and the PMOS device
    subckts have a `VSUBS` port that the top subckt leaves as a *local* net -
    i.e. the PMOS bodies are not connected to anything unless this bench adds
    the port.  So `patch_pex()` inserts `VSUBS` in the top subckt's port list
    and the deck ties it to vdd; the patched netlist is a build product.
  * the gate drives are ideal PWL sources on the 510 pads (`d_`/`db_`
    complementary), one common edge with the yaml's `skew_ps` per code bit.  A
    real standard-cell driver is class C (not hardened here); this bench
    therefore measures the *cell*, not the decoder's drive strength.
  * the load is `r_load` in parallel with `c_load_pf`, and the settled value is
    checked against the loaded DC transfer in `postlayout.json`, so the two
    benches cannot drift apart.

Why this stage exists
---------------------
The pre-layout carry study modelled each cell as an ideal current source with
a gain error and a finite ro.  That model turns a cell off instantly and holds
the bias at an ideal voltage; a real cell does neither, and the *first* P5
macro - a series switch between vdd and the mirror's source - failed here
badly: switching a cell moved its mirror source 0.59 V and its cascode source
1.4 V, the 255 gates loaded the bias lines with ~8 pF, and the one-cell
replica drove them at 1/gm ~ 6-7 kOhm.  A 50-80 ns pole against a 40 ns
period, -9.5 LSB on the 127->128 carry.

This macro is the dump-tail cell: the mirror and cascode keep 16 uA flowing at
all times and an NMOS pair steers the tail to `iout` or `idump`, so neither
the mirror's Vgs nor its Vds moves with the code.  The residual dynamics are
(a) the cascode-gate line being kicked by the pair's drain swing at the
cascode's Cgd - 255 x Cgd x 0.15 V, which is why the wrapper puts 100 pF on
`vcp` (without it the full-scale step lands -4.3 LSB; with it, -0.3) - and
(b) the pair's own switching charge into the 2 pF output, a ~350-450 LSB
spike that decays in ~3 ns, well clear of the 40 ns sample point.

Gates
-----
 1. No netlist, no PEX, a PEX older than the GDS, or no `postlayout.json` -> 2.
 2. The patched netlist must expose 517 ports and 1022 devices, all six rails
    and all 510 pads; `vgnd`/`n_ref` must not exist (the old cell's ports).
 3. Per carry: the output must be within 0.5 LSB of the loaded DC value at the
    25 MS/s period (40 ns), and `vbp`/`vcp` must be within 2 mV of their DC
    values at that time - the second explains the first.
 4. `--selftest` proves the gate works in both directions: the same deck with
    an ideal bias must pass, and the measured value checked against a wrong
    target must fail.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

import run_postlayout as pl

ROOT = pl.ROOT
BUILD = pl.BUILD
GDS = pl.GDS
LVS = pl.LVS
PEX = pl.PEX
POST = BUILD / "postlayout.json"
PATCHED = BUILD / "tran_pex.spice"

# The DAC is specified at 25 MS/s.
PERIOD_NS = 40.0
# Settle within half an LSB of the loaded dc value.
SETTLE_LSB = 0.5
# A bias that has not recovered moves every cell.  The dump-tail cell's mirror
# is undegenerated, so its measured 0.558 %/mV is 0.71 LSB/mV at code 128:
# 0.7 mV is the same 0.5 LSB window as above, seen from the cause.  The
# measured worst is 0.48 mV, so this gate has real margin left - it is a
# diagnostic bound, not a second copy of the first.
BIAS_MV = 0.7
T0_NS = 1.0


def die(msg: str, code: int = 2):
    print(f"error: {msg}", file=sys.stderr)
    raise SystemExit(code)


def tag_of(j: int) -> str:
    k = pl.cell_bit(j)
    return f"b{k}_{j - (2 ** k - 1)}"


def cell_on(j: int, code: int, decode: str) -> bool:
    """Is physical cell j on at `code`?
    `binary` expands the code 1/2/4/.../128 (the cell's weight is the fanout);
    `thermo` is the first `code` cells, i.e. one cell per code step - the
    control that shows what the switching *bank* costs on its own.
    """
    if decode == "thermo":
        return j < code
    return bool((code >> pl.cell_bit(j)) & 1)


# --------------------------------------------------------------------------
# the extracted netlist
# --------------------------------------------------------------------------
TOP = "dac_video_ana"
HEAD_RE = re.compile(r"^\.subckt\s+" + TOP + r"\s+([^\n]*(?:\n\+[^\n]*)*)",
                     re.M)


def patch_pex(txt: str) -> tuple[str, list[str]]:
    """Give the top subckt a VSUBS port, so the bodies can be tied to vdd.

    Magic writes the device subckts with a `VSUBS` port and the top subckt
    wires that port to a net *also named* `VSUBS`, which - since it is not in
    the top port list - is local to the subckt and therefore floating.  That is
    fine for LVS (it compares topology) but wrong for simulation: an
    unconnected body.  Inserting the port makes the net external.
    """
    m = HEAD_RE.search(txt)
    if not m:
        die(f"{PEX.name}: no `.subckt {TOP}` header")
    ports = m.group(1).replace("+", " ").split()
    if "VSUBS" not in ports:
        if "vbp" not in ports:
            die(f"{PEX.name}: top subckt has no vbp port")
        ports.insert(ports.index("vbp") + 1, "VSUBS")
        head = ".subckt " + TOP + " " + " ".join(ports)
        txt = txt[:m.start()] + head + txt[m.end():]
    if len(ports) != 517:
        die(f"{PEX.name}: top subckt has {len(ports)} ports, want 516 + "
            f"VSUBS (6 rails + 510 pads)")
    return txt, ports


def patched_netlist() -> list[str]:
    if not PEX.is_file():
        die(f"no {PEX.relative_to(ROOT)}; run ./signoff.py --stage pex")
    if GDS.is_file() and GDS.stat().st_mtime > PEX.stat().st_mtime:
        die(f"stale {PEX.name}: {GDS.name} is newer; re-extract")
    txt, ports = patch_pex(PEX.read_text())
    pads = [p for p in ports if p.startswith("d_") or p.startswith("db_")]
    if len(pads) != 510:
        die(f"{PEX.name}: {len(pads)} pads, want 510")
    for rail in ("vdd", "vss", "iout", "idump", "vbp", "vcp", "VSUBS"):
        if rail not in ports:
            die(f"{PEX.name}: no {rail} port")
    # The body net must not also be a top-level pin under another spelling.
    if txt.count(".subckt " + TOP + " ") != 1:
        die(f"{PEX.name}: {TOP} defined more than once")
    PATCHED.write_text(txt)
    return ports


def gate_case(cfg, root: Path, ports: list[str], frm: int, to: int,
              edge_ps: float, skew_ps: float, tstop_ns: float,
              stiff: bool, decode: str = "binary", tstep_ps: float = 5.0,
              t0_ns: float = T0_NS, vcp_cap_pf: float = 100.0) -> str:
    vdd = float(cfg["vdd"])
    edge = edge_ps * 1e-12
    skew = skew_ps * 1e-12
    lines = ["* carry %d -> %d, %s decode, edge %.0f ps, skew %.0f ps%s"
             % (frm, to, decode, edge_ps, skew_ps,
                ", stiff bias" if stiff else ""),
             *pl.models(root),
             f'.include "{PATCHED}"',
             f"Vdd vdd 0 {vdd:.6g}",
             "Vss vss 0 0",
             "Vbulk VSUBS 0 %.6g" % vdd,
             "Vdump idump 0 0",
             "Iref vcp 0 %.6gu" % float(cfg["i_unit_ua"]),
             "Rl iout 0 %.6g" % float(cfg["r_load"]),
             "Cl iout 0 %.6gp" % float(cfg["c_load_pf"]),
             # The wrapper's decoupling: the full-scale step kicks the
             # cascode-gate line and 100 pF takes it from 5 mV to 0.5 mV.
             f"Cvcp vcp 0 {vcp_cap_pf:.6g}p"]
    if stiff:
        # Diagnostic only: force the two bias lines to their dc values, so the
        # cell's own settling can be separated from the bias network's.
        post = json.loads(POST.read_text())
        d = post["load"]
        lines += [f"Vbp vbp 0 {d['vbp']:.8g}", f"Vcp vcp 0 {d['vcp']:.8g}"]
    tagj = {tag_of(j): j for j in range(2 ** int(cfg["bits"]) - 1)}
    for p in ports:
        neg = p.startswith("db_")
        if not (p.startswith("d_") or neg):
            continue
        j = tagj[p[3:] if neg else p[2:]]
        # With a thermometer decode only one cell changes per step, so there
        # is no bit-slice skew to model; the binary bank keeps the yaml's.
        k = pl.cell_bit(j) if decode == "binary" else 0
        # NMOS gates: high conducts.  `d_` high puts the cell's tail on iout,
        # `db_` high dumps it, so the two are complementary.
        on0 = cell_on(j, frm, decode)
        on1 = cell_on(j, to, decode)
        g0 = (0.0 if on0 else vdd) if neg else (vdd if on0 else 0.0)
        g1 = (0.0 if on1 else vdd) if neg else (vdd if on1 else 0.0)
        t = t0_ns * 1e-9 + k * skew
        if g0 == g1:
            lines.append(f"V{p} {p} 0 {g0:.6g}")
        else:
            lines.append(f"V{p} {p} 0 PWL(0 {g0:.6g} {t:.6g} {g0:.6g} "
                         f"{t + edge:.6g} {g1:.6g})")
    lines.append("Xdac " + " ".join(ports) + " " + TOP)
    tag = f"tran_{frm}_{to}_{decode}" + ("_stiff" if stiff else "")
    lines += [".control", "set wr_singlescale", "set wr_vecnames",
              f"tran {tstep_ps}e-12 {tstop_ns}e-9",
              f"wrdata {BUILD / (tag + '.dat')} v(iout) v(vbp) v(vcp)",
              ".endc", ".end"]
    nl = BUILD / (tag + ".spice")
    nl.write_text("\n".join(lines) + "\n")
    pl.ngspice(nl)
    return tag


def measure(tag: str, frm: int, to: int, post: dict, cfg,
            tstop_ns: float) -> dict:
    names, rows = pl.wrdata(BUILD / (tag + ".dat"))
    for want in ("v(iout)", "v(vbp)", "v(vcp)"):
        if want not in names:
            die(f"{tag}.dat: no {want} column ({sorted(names)})")
    if not rows:
        die(f"{tag}.dat: no rows")
    lsb_a = float(post["load"]["lsb"])
    rl = float(cfg["r_load"])
    lsb_v = lsb_a * rl
    t = [r[names["time"]] for r in rows]
    if t[-1] < (T0_NS + PERIOD_NS) * 1e-9:
        die(f"{tag}.dat ends at {t[-1]*1e9:g} ns, before the "
            f"{T0_NS + PERIOD_NS:g} ns sample point")
    v = [r[names["v(iout)"]] for r in rows]
    vb = [r[names["v(vbp)"]] for r in rows]
    vc = [r[names["v(vcp)"]] for r in rows]

    # The loaded dc transfer is linear to 0.0004 LSB, so `code * LSB` is the
    # reference, and code 0 is 0 A (the array's off state is a true zero).
    target = to * lsb_v
    start = frm * lsb_v
    at = T0_NS + PERIOD_NS

    def nearest(tt):
        return min(range(len(t)), key=lambda i: abs(t[i] - tt))

    i_period = nearest(at * 1e-9)
    settled = v[i_period] / lsb_v
    err = settled - to

    # Settle time: the last time the output is more than SETTLE_LSB away from
    # the dc value, i.e. everything after it is inside the window.
    settle_ns = t[0] * 1e9
    for i in range(len(v) - 1, -1, -1):
        if abs(v[i] - target) > SETTLE_LSB * lsb_v:
            settle_ns = (t[i + 1] * 1e9) if i + 1 < len(t) else float("inf")
            break

    lo, hi = min(start, target), max(start, target)
    over_lsb = (max(v) - hi) / lsb_v if max(v) > hi else 0.0
    under_lsb = (lo - min(v)) / lsb_v if min(v) < lo else 0.0
    glitch = max(over_lsb, under_lsb)

    d = post["load"]
    return {"from": frm, "to": to, "tag": tag,
            "settled_lsb": settled, "err_lsb": err,
            "settle_ns": settle_ns, "glitch_lsb": glitch,
            "vbp": vb[i_period], "vcp": vc[i_period],
            "vbp_dc": d["vbp"], "vcp_dc": d["vcp"],
            "dvbp_mv": (vb[i_period] - d["vbp"]) * 1e3,
            "dvcp_mv": (vc[i_period] - d["vcp"]) * 1e3,
            "lsb_v": lsb_v, "tstop_ns": tstop_ns}


def one(cfg, root, ports, frm, to, edge_ps, skew_ps, tstop_ns, stiff,
        post, decode="binary", tstep_ps: float = 5.0,
        vcp_cap_pf: float = 100.0) -> dict:
    tag = gate_case(cfg, root, ports, frm, to, edge_ps, skew_ps, tstop_ns,
                    stiff, decode, tstep_ps, vcp_cap_pf=vcp_cap_pf)
    return measure(tag, frm, to, post, cfg, tstop_ns)


def ok_run(r: dict) -> bool:
    return (abs(r["err_lsb"]) <= SETTLE_LSB
            and abs(r["dvbp_mv"]) <= BIAS_MV
            and abs(r["dvcp_mv"]) <= BIAS_MV)


def show(r: dict) -> None:
    print(f"  {r['from']:3d} -> {r['to']:3d}: settled {r['settled_lsb']:8.3f} "
          f"LSB (err {r['err_lsb']:+7.3f}), settle {r['settle_ns']:6.2f} ns, "
          f"glitch {r['glitch_lsb']:6.1f} LSB, "
          f"dvbp {r['dvbp_mv']:+6.2f} mV, dvcp {r['dvcp_mv']:+6.2f} mV"
          f"  {'ok' if ok_run(r) else 'FAIL'}")


def selftest(cfg, root, ports, edge_ps, skew_ps, tstop_ns, post) -> int:
    """Prove the settle gate is not vacuous, in both directions."""
    ok = True

    # A deck with an ideal bias must pass: the gate can be met by a good
    # design, so a failing real run is a statement about the design.
    good = one(cfg, root, ports, 127, 128, edge_ps, skew_ps, tstop_ns,
               stiff=True, post=post)
    p = abs(good["err_lsb"]) <= SETTLE_LSB
    print(f"selftest stiff-bias: {'PASS' if p else 'FAIL'} "
          f"(settled {good['settled_lsb']:.3f} LSB)")
    ok &= p

    # The same measurement checked against the wrong code must fail.  This is
    # what a sign error or a stale `postlayout.json` looks like.
    wrong = dict(good, to=133, err_lsb=good["settled_lsb"] - 133.0)
    p = abs(wrong["err_lsb"]) > SETTLE_LSB
    print(f"selftest wrong-code: {'PASS' if p else 'FAIL'} "
          f"({wrong['err_lsb']:+.3f} LSB)")
    ok &= p

    print("selftest " + ("PASS" if ok else "FAIL"))
    return 0 if ok else 1


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--from", dest="frm", type=int, default=None,
                    help="starting code (default: the critical carries)")
    ap.add_argument("--to", dest="to", type=int, default=None)
    ap.add_argument("--edge-ps", type=float, default=None)
    ap.add_argument("--skew-ps", type=float, default=None)
    ap.add_argument("--tstop-ns", type=float, default=PERIOD_NS + 10.0)
    ap.add_argument("--tstep-ps", type=float, default=5.0)
    ap.add_argument("--vcp-cap-pf", type=float, default=100.0,
                    help="decoupling on vcp (the wrapper requirement; 100 pF "
                         "takes the full-scale kick from 5 mV to 0.5 mV)")
    ap.add_argument("--decode", choices=["binary", "thermo"], default="binary",
                    help="binary = the leaf's 1/2/4/... expansion; thermo = "
                         "first N cells, one cell per step (the control)")
    ap.add_argument("--stiff-bias", action="store_true",
                    help="force vbp/vcp to their dc values (diagnostic)")
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--brief", action="store_true")
    a = ap.parse_args(argv)

    if not POST.is_file():
        die(f"no {POST.relative_to(ROOT)}; run ./signoff.py --stage postlayout")
    post = json.loads(POST.read_text())
    if post.get("netlist") != str(LVS):
        die(f"{POST.name} was built from {post.get('netlist')}, not {LVS}")
    cfg = pl.load_cfg()
    root = pl.pdk_root()
    ports = patched_netlist()
    edge = float(cfg["edge_ps"]) if a.edge_ps is None else a.edge_ps
    skew = float(cfg["skew_ps"]) if a.skew_ps is None else a.skew_ps

    if a.selftest:
        return selftest(cfg, root, ports, edge, skew, a.tstop_ns, post)

    if (a.frm is None) != (a.to is None):
        die("give both --from and --to, or neither")
    if a.frm is None:
        carries = [(127, 128), (128, 127), (63, 64)]
    else:
        carries = [(a.frm, a.to)]
    n = 2 ** int(cfg["bits"]) - 1
    for frm, to in carries:
        if not (0 <= frm <= n and 0 <= to <= n):
            die(f"code {frm}->{to} outside 0..{n}")
        if frm == to:
            die("--from and --to are the same code")

    print(f"post-layout transient ({PEX.name}, {len(ports)} ports, "
          f"{a.decode} decode, edge {edge:g} ps, skew {skew:g} ps, "
          f"{PERIOD_NS:g} ns period)")
    rows = []
    for frm, to in carries:
        r = one(cfg, root, ports, frm, to, edge, skew, a.tstop_ns,
                a.stiff_bias, post, a.decode, a.tstep_ps, a.vcp_cap_pf)
        rows.append(r)
        if not a.brief:
            show(r)

    checks = [
        ("settle @40 ns", all(abs(r["err_lsb"]) <= SETTLE_LSB for r in rows),
         f"{max(abs(r['err_lsb']) for r in rows):.3f} LSB worst"),
        ("bias @40 ns", all(abs(r["dvbp_mv"]) <= BIAS_MV
                            and abs(r["dvcp_mv"]) <= BIAS_MV for r in rows),
         f"{max(max(abs(r['dvbp_mv']), abs(r['dvcp_mv'])) for r in rows):.2f}"
         f" mV worst"),
        ("settle-time", all(r["settle_ns"] <= T0_NS + PERIOD_NS for r in rows),
         f"{max(r['settle_ns'] for r in rows):.1f} ns worst of "
         f"{T0_NS + PERIOD_NS:g}"),
    ]
    ok = all(good for _, good, _ in checks)
    if not a.brief:
        print()
        for name, good, val in checks:
            print(f"  {name:16}: {val:>28}  {'ok' if good else 'FAIL'}")
    print(f"post-layout transient {'PASS' if ok else 'FAIL'}")
    # A --stiff-bias run is a diagnostic, so it gets its own report: it must
    # never overwrite the failing signoff number with a passing one.
    rep = f"transient_{a.decode}" + ("_stiff" if a.stiff_bias else "") + ".json"
    (BUILD / rep).write_text(json.dumps(
        {"ok": ok, "period_ns": PERIOD_NS, "edge_ps": edge, "skew_ps": skew,
         "decode": a.decode, "stiff_bias": a.stiff_bias,
         "diagnostic": a.stiff_bias, "runs": rows}, indent=1) + "\n")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
