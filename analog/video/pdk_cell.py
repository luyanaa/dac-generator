#!/usr/bin/env python3
"""Device-level dump-tail cell study across the PDKs this repo has data for.

    ./pdk_cell.py --list
    ./pdk_cell.py sky130
    ./pdk_cell.py ihp-sg13g2
    ./pdk_cell.py ics55        # 1.2 V core, foundry/ngspice model tree

The P5 method is: the mirror and cascode keep the unit current flowing and an
NMOS pair steers it, so the mirror's Vgs and Vds never move with the code.
This script applies it to a PDK without its layout: 255 cells plus the
diode-connected replica, the same 37.5 ohm / 2 pF output, a 20 ps edge and the
25 ps bit skew, and it gates

  * the drawn unit current (the replica sets it, so this checks the netlist),
  * the 127->128 carry and the 0->255 full-scale step at the 40 ns period,
  * the bias excursion at that instant.

It is a *cell* study, not a signoff of a macro: no parasitics, no layout.  The
device sizes in PDKS below are the ones that fit the supply; the report prints
the operating point so a different PDK can be sized the same way.
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
BUILD = ROOT / "build"

# w/l are in um for sky130's subckts and in metres (written `Nu`) for the IHP
# PSP103 subckt; the format string is per PDK so neither is guessed.
PDKS: dict[str, dict] = {
    "sky130": {
        # The 1.8 V logic PMOS cannot stack two diodes at 16 uA in 1.8 V
        # (measured: the replica's vcp is driven negative), so the cell uses
        # the 5 V thick-oxide devices at 3.3 V - the same supply and the same
        # sizes as the gf180 macro.
        "vdd": 3.3,
        "root": "~/.ciel/ciel/sky130/versions/*/sky130A",
        "lib": "{root}/libs.tech/ngspice/sky130.lib.spice",
        "section": "tt",
        "pfet": "sky130_fd_pr__pfet_g5v0d10v5",
        "nfet": "sky130_fd_pr__nfet_g5v0d10v5",
        "fmt": "{n} {d} {g} {s} {b} {m} w={w:g} l={l:g}",
        "mir": (8.0, 0.5), "cas": (8.0, 0.5), "pair": (16.0, 0.5),
        "vcp_cap_pf": 100.0,
        "env": {},
    },
    "ihp-sg13g2": {
        "vdd": 1.8,
        "root": "~/.ciel/ciel/ihp-sg13/versions/*/ihp-sg13g2",
        "lib": "{root}/libs.tech/ngspice/models/cornerMOSlv.lib",
        "section": "mos_tt",
        "pfet": "sg13_lv_pmos",
        "nfet": "sg13_lv_nmos",
        "fmt": "{n} {d} {g} {s} {b} {m} w={w:g}u l={l:g}u",
        # The PSP103 models are OSDI; the PDK's .spiceinit loads them only
        # when PDK_ROOT/PDK point at this install (see `env` below).
        "env": {"PDK": "ihp-sg13g2"},
        "pdk_root_env": True,
        "mir": (8.0, 1.0), "cas": (8.0, 0.5), "pair": (4.0, 0.28),
        "vcp_cap_pf": 220.0,
        # "series": replica mirror + diode cascode, vcp = Vdd - 2*Vsg.
        # "wide-swing": mirror copy + triode NMOS, vcp = I*Ron (positive at
        # low Vdd); the cell cascodes still use cfg["cas"].
        "bias": "series", "nbias": (0.5, 1.0),
    },
    "ics55": {
        # The PDK ships a foundry ngspice variant (foundry/ngspice); its
        # wrapper defaults mismod=0, so a plain op is deterministic.  The top
        # .lib carries .option scale=0.9, which the wrapper's lef/wef
        # expressions also apply - use the top lib, not the wrapper directly.
        "vdd": 1.2,
        "root": "/grid/icsprout55-pdk",
        "lib": ("{root}/libs.tech/spice/foundry/ngspice/"
                "ICsprout_55LLULP1225_V1p1_hsp.lib"),
        "section": "tt_mos",
        "pfet": "pm1p2_svt_lp",
        "nfet": "nm1p2_svt_lp",
        "fmt": "{n} {d} {g} {s} {b} {m} w={w:g}u l={l:g}u",
        "env": {},
        "mir": (8.0, 1.0), "cas": (8.0, 0.5), "pair": (4.0, 0.28),
        "vcp_cap_pf": 220.0,
        # "series": replica mirror + diode cascode, vcp = Vdd - 2*Vsg.
        # "wide-swing": mirror copy + triode NMOS, vcp = I*Ron (positive at
        # low Vdd); the cell cascodes still use cfg["cas"].
        "bias": "series", "nbias": (0.5, 1.0),
    },
}

I_UNIT_UA = 16.0
PERIOD_NS = 40.0
T0_NS = 1.0
EDGE_PS = 20.0
SKEW_PS = 25.0
RL = 37.5
CL_PF = 2.0
SETTLE_LSB = 0.5
BIAS_MV = 0.7
N = 255


def die(msg: str, code: int = 2):
    print(f"error: {msg}", file=sys.stderr)
    raise SystemExit(code)


def root_of(cfg: dict) -> Path:
    pat = os.path.expanduser(cfg["root"])
    hits = sorted(glob.glob(pat))
    if not hits:
        die(f"PDK not found: {pat}")
    return Path(hits[-1])


def tag(j: int) -> str:
    k = 0
    while j >= 2 ** (k + 1) - 1:
        k += 1
    return f"b{k}_{j - (2 ** k - 1)}"


def deck(cfg: dict, root: Path, name: str, frm: int, to: int,
         op_only: bool = False) -> Path:
    vdd = float(cfg["vdd"])
    lib = cfg["lib"].format(root=root)
    dat = BUILD / f"pdk_{cfg['name']}_{name}.dat"
    op = BUILD / f"pdk_{cfg['name']}_{name}_op.dat"
    bias = cfg.get("bias", "series")
    iref_node = "vbp" if bias == "wide-swing" else "vcp"
    lines = [f"* {cfg['name']} dump-tail cell, {frm}->{to}",
             f'.lib "{lib}" {cfg["section"]}',
             f"Vdd vdd 0 {vdd:g}",
             "Vss vss 0 0",
             "Vdump idump 0 0",
             f"Iref {iref_node} 0 {I_UNIT_UA:g}u",
             f"Rl iout 0 {RL:g}",
             f"Cl iout 0 {CL_PF:g}p",
             f"Cvcp vcp 0 {cfg['vcp_cap_pf']:g}p"]

    fmt = cfg["fmt"]

    def cell(name_, tagj):
        return [
            fmt.format(n=name_ + "m", d=f"md_{tagj}", g="vbp", s="vdd",
                       b="vdd", m=cfg["pfet"], w=cfg["mir"][0],
                       l=cfg["mir"][1]),
            fmt.format(n=name_ + "c", d=f"cd_{tagj}", g="vcp",
                       s=f"md_{tagj}", b="vdd", m=cfg["pfet"],
                       w=cfg["cas"][0], l=cfg["cas"][1]),
            fmt.format(n=name_ + "a", d="iout", g=f"d_{tagj}",
                       s=f"cd_{tagj}", b="vss", m=cfg["nfet"],
                       w=cfg["pair"][0], l=cfg["pair"][1]),
            fmt.format(n=name_ + "b", d="idump", g=f"db_{tagj}",
                       s=f"cd_{tagj}", b="vss", m=cfg["nfet"],
                       w=cfg["pair"][0], l=cfg["pair"][1]),
        ]

    for j in range(N):
        lines += cell(f"X{j}_", tag(j))
    # Replica bias.
    lines.append(fmt.format(n="Xrm", d="vbp", g="vbp", s="vdd", b="vdd",
                            m=cfg["pfet"], w=cfg["mir"][0],
                            l=cfg["mir"][1]))
    if bias == "wide-swing":
        # Bias branch: vcp = Vdd - Vsg(mirror copy) - I*Ron(triode); the
        # triode gate is at Vdd, so vcp stays positive below 1.2 V.
        lines.append(fmt.format(n="Xrc", d="vcp", g="vbp", s="vdd", b="vdd",
                                m=cfg["pfet"], w=cfg["mir"][0],
                                l=cfg["mir"][1]))
        lines.append(fmt.format(n="Xrn", d="vcp", g="vdd", s="vss", b="vss",
                                m=cfg["nfet"], w=cfg["nbias"][0],
                                l=cfg["nbias"][1]))
        # Replica mirror + cascode, loaded by a 16 uA sink.  Without this
        # the replica no longer sets the cell's mirror drain: setting vcp
        # independently left md at 0.649 V instead of vbp=0.613 V and the
        # channel-length modulation produced 6 LSB of code-dependent error.
        lines.append(fmt.format(n="Xrm2", d="md_rep", g="vbp", s="vdd",
                                b="vdd", m=cfg["pfet"], w=cfg["mir"][0],
                                l=cfg["mir"][1]))
        lines.append(fmt.format(n="Xrca", d="cd_rep", g="vcp", s="md_rep",
                                b="vdd", m=cfg["pfet"], w=cfg["cas"][0],
                                l=cfg["cas"][1]))
        lines.append(f"Isink cd_rep 0 {I_UNIT_UA:g}u")
    else:
        lines.append(fmt.format(n="Xrc", d="vcp", g="vcp", s="vbp", b="vdd",
                                m=cfg["pfet"], w=cfg["cas"][0],
                                l=cfg["cas"][1]))
    for j in range(N):
        t = tag(j)
        k = 0
        while j >= 2 ** (k + 1) - 1:
            k += 1
        on0 = bool((frm >> k) & 1)
        on1 = bool((to >> k) & 1)
        t0 = T0_NS * 1e-9 + k * SKEW_PS * 1e-12
        e = t0 + EDGE_PS * 1e-12
        for net, a, bb in (("d_" + t, vdd if on0 else 0.0,
                            vdd if on1 else 0.0),
                           ("db_" + t, 0.0 if on0 else vdd,
                            0.0 if on1 else vdd)):
            if a == bb:
                lines.append(f"V{net} {net} 0 {a:g}")
            else:
                lines.append(f"V{net} {net} 0 PWL(0 {a:g} {t0:.6g} {a:g} "
                             f"{e:.6g} {bb:g})")
    # Start the tails low: with weak devices the all-off solution is also
    # self-consistent (the pair's source floats to vdd and the pair is off).
    # A nodeset is only an initial guess - the solve still has to satisfy KCL.
    for j in range(N):
        t = tag(j)
        lines.append(f".nodeset v(md_{t})={vdd - 0.45:g} "
                     f"v(cd_{t})={vdd - 0.60:g}")
    ctl = [".control", "set wr_singlescale", "set wr_vecnames", "op",
           f"wrdata {op} v(iout) v(vbp) v(vcp) v(md_b0_0) v(cd_b0_0)"]
    if not op_only:
        ctl += ["tran 5e-12 50e-9",
                f"wrdata {dat} v(iout) v(vbp) v(vcp)"]
    ctl += [".endc", ".end"]
    lines += ctl
    out = BUILD / f"pdk_{cfg['name']}_{name}.spice"
    out.write_text("\n".join(lines) + "\n")
    return out


def ngspice(nl: Path, cfg: dict, root: Path) -> None:
    env = dict(os.environ)
    env.update({k: str(v).format(root=root) for k, v in cfg["env"].items()})
    if cfg.get("pdk_root_env"):
        env["PDK_ROOT"] = str(root.parent)
    r = subprocess.run(["ngspice", "-b", str(nl)], capture_output=True,
                       text=True, timeout=3600, env=env)
    txt = r.stdout + r.stderr
    if r.returncode or "Error!" in txt or "could not find a valid" in txt:
        tail = "\n".join(l for l in txt.splitlines()
                         if "rror" in l or "modelname" in l
                         or "singular" in l)[-900:]
        die(f"ngspice failed on {nl.name}\n{tail}")


def wrdata(path: Path):
    names, rows = {}, []
    for ln in path.read_text().splitlines():
        f = ln.split()
        if len(f) < 2:
            continue
        try:
            rows.append([float(v) for v in f])
        except ValueError:
            for i, v in enumerate(f):
                names.setdefault(v, i)
    return names, rows


def run(cfg: dict, root: Path, frm: int, to: int, kind: str,
        op_only: bool = False) -> dict:
    nl = deck(cfg, root, f"{kind}_{frm}_{to}", frm, to, op_only)
    ngspice(nl, cfg, root)
    opname, opr = wrdata(BUILD / f"pdk_{cfg['name']}_{kind}_{frm}_{to}_op.dat")
    op = {k: opr[-1][i] for k, i in opname.items() if k != "time"} \
        if opr else {}
    if op_only:
        return {"from": frm, "to": to, "op": op}
    names, rows = wrdata(BUILD / f"pdk_{cfg['name']}_{kind}_{frm}_{to}.dat")
    if not rows:
        die(f"{kind}_{frm}_{to}.dat: no rows")
    t = [r[names["time"]] for r in rows]
    v = [r[names["v(iout)"]] for r in rows]
    vb = [r[names["v(vbp)"]] for r in rows]
    vc = [r[names["v(vcp)"]] for r in rows]
    lsb_v = I_UNIT_UA * 1e-6 * RL
    at = (T0_NS + PERIOD_NS) * 1e-9
    i41 = min(range(len(t)), key=lambda i: abs(t[i] - at))
    settled = v[i41] / lsb_v
    err = settled - to
    settle = None
    target = to * lsb_v
    for i in range(len(v) - 1, -1, -1):
        if abs(v[i] - target) > SETTLE_LSB * lsb_v:
            settle = t[i + 1] * 1e9 if i + 1 < len(t) else None
            break
    return {"from": frm, "to": to, "settled_lsb": settled, "err_lsb": err,
            "settle_ns": settle, "vbp": vb[i41], "vcp": vc[i41],
            "vbp_dc": op.get("v(vbp)"), "vcp_dc": op.get("v(vcp)"),
            "op": op}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("pdk", nargs="?")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--brief", action="store_true")
    ap.add_argument("--op-only", action="store_true",
                    help="solve the operating point and stop (sizing loop)")
    ap.add_argument("--all", action="store_true",
                    help="run every PDK that is not blocked")
    ap.add_argument("--vdd", type=float, default=None,
                    help="override the supply (supply/corner sweep)")
    ap.add_argument("--corner", default=None,
                    help="model corner (ics55: tt/ff/ss; default: the entry's "
                         "section)")
    ap.add_argument("--bias", choices=["series", "wide-swing"], default=None,
                    help="replica bias topology (default: the entry's bias)")
    ap.add_argument("--nbias", default=None,
                    help="wide-swing triode NMOS W,L in um (e.g. 0.5,1.0)")
    ap.add_argument("--mir", default=None,
                    help="mirror W,L in um (sizing experiment)")
    ap.add_argument("--cas", default=None,
                    help="cascode W,L in um (sizing experiment)")
    a = ap.parse_args(argv)
    if a.all:
        # One process per PDK: the models are loaded per deck and the two
        # device families (BSIM vs PSP OSDI) can fight over the model tables.
        rc = 0
        out = ["PDK cell study (device level, no parasitics)"]
        for name, cfg in PDKS.items():
            if cfg.get("blocked"):
                out.append(f"{name:12}: BLOCKED - {cfg['blocked']}")
                continue
            r = subprocess.run([sys.executable, str(Path(__file__)),
                                name, "--brief"], capture_output=True,
                               text=True)
            out.append(r.stdout.strip() + r.stderr.strip())
            rc |= r.returncode
        (BUILD / "pdk_summary.txt").write_text("\n".join(out) + "\n")
        print("\n".join(out))
        return 0 if rc == 0 else 1
    if a.list or not a.pdk:
        for name, cfg in PDKS.items():
            state = "BLOCKED: " + cfg["blocked"] if cfg.get("blocked") \
                else "ok"
            print(f"{name:12} vdd {cfg['vdd']:g} V  {state}")
        return 0
    if a.pdk not in PDKS:
        die(f"unknown PDK {a.pdk} (have: {', '.join(PDKS)})")
    cfg = dict(PDKS[a.pdk], name=a.pdk)
    if a.vdd is not None:
        cfg["vdd"] = a.vdd
    if a.corner is not None:
        cfg["section"] = (f"{a.corner}_mos" if a.pdk == "ics55"
                          else a.corner)
    if a.bias is not None:
        cfg["bias"] = a.bias
    if a.nbias is not None:
        w, l = (float(x) for x in a.nbias.split(","))
        cfg["nbias"] = (w, l)
    if a.mir is not None:
        cfg["mir"] = tuple(float(x) for x in a.mir.split(","))
    if a.cas is not None:
        cfg["cas"] = tuple(float(x) for x in a.cas.split(","))
    if cfg.get("blocked"):
        print(f"{a.pdk}: blocked - {cfg['blocked']}", file=sys.stderr)
        return 2
    root = root_of(cfg)
    BUILD.mkdir(exist_ok=True)
    if not a.brief:
        print(f"{a.pdk}: vdd {cfg['vdd']:g} V, section {cfg['section']}, "
              f"bias {cfg.get('bias', 'series')}, mirror {cfg['mir']}, "
              f"cascode {cfg['cas']}, pair {cfg['pair']}")
    if a.op_only:
        r = run(cfg, root, 128, 128, "op", op_only=True)
        o = r["op"]
        print(f"  dc: vbp {o.get('v(vbp)'):.4f} V, vcp {o.get('v(vcp)'):.4f} V, "
              f"mirror drain {o.get('v(md_b0_0)'):.4f} V, "
              f"tail {o.get('v(cd_b0_0)'):.4f} V, "
              f"iout {o.get('v(iout)') * 1e6:.2f} uV")
        return 0
    carry = run(cfg, root, 127, 128, "carry")
    fs = run(cfg, root, 0, 255, "fs")
    rows = [carry, fs]
    worst = max(abs(r["err_lsb"]) for r in rows)
    bias = max(max(abs(r["vbp"] - r["vbp_dc"]),
                   abs(r["vcp"] - r["vcp_dc"])) for r in rows)
    bias_mv = bias * 1e3
    if not a.brief:
        for r in rows:
            st = "inf" if r["settle_ns"] is None else f"{r['settle_ns']:.2f}"
            print(f"  {r['from']:3d} -> {r['to']:3d}: "
                  f"{r['settled_lsb']:9.3f} LSB (err {r['err_lsb']:+8.3f}), "
                  f"settle {st:>5} ns, "
                  f"dvbp {(r['vbp'] - r['vbp_dc']) * 1e3:+6.2f} mV, "
                  f"dvcp {(r['vcp'] - r['vcp_dc']) * 1e3:+6.2f} mV")
        opr = carry["op"]
        print(f"  dc: vbp {opr.get('v(vbp)'):.4f} V, "
              f"vcp {opr.get('v(vcp)'):.4f} V, "
              f"mirror drain {opr.get('v(md_b0_0)'):.4f} V, "
              f"tail {opr.get('v(cd_b0_0)'):.4f} V")
    # A missing settle time means the step never entered the 0.5 LSB window;
    # a negative vcp means the replica wants a bias below ground, which the
    # current sink cannot produce (the model would be unphysical).
    settle_ok = all(r["settle_ns"] is not None and r["settle_ns"] <= 40.0
                    for r in rows)
    vcp_ok = all(r["vcp_dc"] is not None and 0.0 <= r["vcp_dc"] <= cfg["vdd"]
                 for r in rows)
    ok = (worst <= SETTLE_LSB and bias_mv <= BIAS_MV
          and settle_ok and vcp_ok)
    if not a.brief and not ok:
        if not settle_ok:
            print("  fail: at least one step did not settle within 40 ns")
        if not vcp_ok:
            print(f"  fail: vcp outside 0..{cfg['vdd']:g} V "
                  f"({rows[0]['vcp_dc']:.4f} V at the operating point)")
    rep = {"pdk": a.pdk, "vdd": cfg["vdd"], "ok": ok,
           "mirror": cfg["mir"], "cascode": cfg["cas"], "pair": cfg["pair"],
           "runs": rows}
    tag = a.pdk if (a.vdd is None and a.corner is None and a.bias is None
                    and a.nbias is None and a.mir is None and a.cas is None) \
        else f"{a.pdk}_{cfg['section']}_{cfg['vdd']:g}_{cfg.get('bias', 'series')}"
    if cfg.get("bias") == "wide-swing":
        tag += f"_n{cfg['nbias'][0]:g}x{cfg['nbias'][1]:g}"
    if a.mir is not None or a.cas is not None:
        tag += f"_m{cfg['mir'][0]:g}x{cfg['mir'][1]:g}_c{cfg['cas'][0]:g}x{cfg['cas'][1]:g}"
    rep["bias"] = cfg.get("bias", "series")
    (BUILD / f"pdk_{tag}.json").write_text(json.dumps(rep, indent=1) + "\n")
    print(f"{a.pdk}: {'PASS' if ok else 'FAIL'}  "
          f"(worst {worst:.3f} LSB, bias {bias_mv:.2f} mV)")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
