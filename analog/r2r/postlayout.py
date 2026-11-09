#!/usr/bin/env python3
"""Post-layout bench for the R-2R ladder: extracted metal R-C + poly R-C.

Magic's PEX gives the *metal* parasitics and the device geometry, but the gf180
tech deliberately does not extract parasitics from resistor bodies (see the
`# Do not extract parasitics from resistors` block in `gf180mcuA.tech`).  The
poly R-C has to be reconstructed, and this file does it from evidence, not from
a guessed number:

  R  the PDK model's own body resistance, `ppolyf_u`: rsh = 350 ohm/sq,
     r_dl = 2e-11 m, r_dw = 2.55e-8 m, plus the 1 um `ppolyf_u_t` end
     resistors (rsh 60 ohm/sq) at both terminals.  The per-device length and
     width are the ones Magic extracted (`r_length`, `r_width`, in 5 nm units,
     see `.option scale=5n`).

  C  the PDK model's own field-oxide capacitance, `fox_sub`: cj = 8.85e-5 F/m2,
     applied to the same effective area.  This is the same constant the model
     uses for `c1`/`c2`; Magic does not add it because the body is a device.

The body is then split into N segments (default 20) with R/N and C/N, i.e. a
distributed RC line, instead of the model's single-section pi network.  The
*extracted* top-level capacitances from `build/magic/pex.spice` are kept as
they are (metal straps, 0.04 fF pad-to-pad coupling, ...).  Nothing here is a
fitted or tuned number.

Two netlists are built and both are run:

  lumped     the extracted netlist verbatim: each resistor is one `ppolyf_u`
             device, so its intrinsic R-C is the model's 1-section pi form.
  segmented  the same topology, but every resistor is the N-section line above.

The DC sweep should agree between them (capacitors are open at DC), which is
the check that the reconstruction did not change the ladder; the transient
difference is the part of the settling that the poly R-C actually owns.

Usage
    ./postlayout.py                 # dc + tran, both models
    ./postlayout.py --stage dc
    ./postlayout.py --segments 40
    ./postlayout.py --selftest      # prove the gates reject a broken run

Outputs under build/postlayout/ (git-ignored).  Fail-closed: a missing PEX,
model library, ngspice, or empty result is an error.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
BUILD = ROOT / "build"
PL = BUILD / "postlayout"
PEX = BUILD / "magic" / "pex.spice"
TOP = "dac_r2r_ana"

NBITS = 8
VDD = 3.3
LOAD_R = 1.0e6
LOAD_C = 7.0e-12

# gf180mcuA `ppolyf_u` / `fox_sub` constants (sm141064.ngspice).
SCALE = 5e-9           # .option scale=5n: r_length/r_width units
RSH = 350.0            # rsh_ppolyf_u, res_typical
R_DL = 2e-11           # m
R_DW = 2.55e-8         # m
RT_RSH = 60.0          # ppolyf_u_t end/contact region
RT_L = 1e-6            # m, `l='s*1u'`
CJ = 8.85e-5           # F/m2, fox_sub


def die(msg: str) -> None:
    print(f"error: {msg}", file=sys.stderr)
    raise SystemExit(2)


def find_pdk() -> Path:
    cands = []
    if os.environ.get("PDK_ROOT"):
        cands.append(Path(os.environ["PDK_ROOT"]))
    cands.append(Path.home() / ".ciel/ciel/gf180mcu/versions")
    for c in cands:
        if not c.is_dir():
            continue
        if (c / "gf180mcuA/libs.tech/ngspice/sm141064.ngspice").is_file():
            return c
        hits = sorted(p for p in c.iterdir()
                      if (p / "gf180mcuA/libs.tech/ngspice/"
                          "sm141064.ngspice").is_file())
        if hits:
            return hits[-1]
    die("no gf180mcuA PDK found; set PDK_ROOT")


# --------------------------------------------------------------------------
# extraction
# --------------------------------------------------------------------------

def _blocks(txt: str) -> dict[str, tuple[list[str], list[str]]]:
    out = {}
    for m in re.finditer(r"^\.subckt\s+(\S+)\s+(.*?)^\.ends", txt, re.M | re.S):
        lines = m.group(2).splitlines()
        ports = lines[0].split() if lines else []
        out[m.group(1)] = (ports, lines[1:])
    return out


def _num(tok: str) -> float:
    mult = {"t": 1e12, "g": 1e9, "meg": 1e6, "k": 1e3, "m": 1e-3,
            "u": 1e-6, "n": 1e-9, "p": 1e-12, "f": 1e-15}
    s = tok.strip().lower()
    for suf in ("meg", "t", "g", "k", "m", "u", "n", "p", "f"):
        if s.endswith(suf):
            return float(s[:-len(suf)]) * mult[suf]
    return float(s)


def parse_pex(path: Path) -> dict:
    txt = path.read_text()
    blocks = _blocks(txt)
    if TOP not in blocks:
        die(f"{path} has no .subckt {TOP}")
    ports, body = blocks[TOP]

    devs = {}
    for name, (dports, dbody) in blocks.items():
        if not name.startswith("ppolyf_u_resistor"):
            continue
        geo = {}
        for ln in dbody:
            if ln.strip().startswith("X0 "):
                f = ln.split()
                # model `ppolyf_u` port order is (p, n, b)
                for key, node in zip(("p", "n", "b"), f[1:4]):
                    geo[key] = dports.index(node)
                for tok in f[4:]:
                    if tok.startswith("r_length="):
                        geo["L"] = _num(tok.split("=", 1)[1]) * SCALE
                    elif tok.startswith("r_width="):
                        geo["W"] = _num(tok.split("=", 1)[1]) * SCALE
        if not {"p", "n", "b", "L", "W"} <= set(geo):
            die(f"cannot parse geometry/ports of {name}")
        devs[name] = geo

    insts, caps = [], []
    for ln in body:
        ln = ln.strip()
        if ln.startswith("X"):
            f = ln.split()
            if f[-1] not in devs:
                die(f"top instance {f[0]} uses unknown device {f[-1]}")
            g = devs[f[-1]]
            nets = f[1:-1]
            insts.append({"name": f[0], "sub": f[-1],
                          "p": nets[g["p"]], "n": nets[g["n"]],
                          "b": nets[g["b"]],
                          "L": g["L"], "W": g["W"]})
        elif ln.startswith("C"):
            f = ln.split()
            caps.append((f[1], f[2], _num(f[3])))

    if len(insts) != 25:
        die(f"extracted netlist has {len(insts)} resistors, want 25")
    return {"ports": ports, "insts": insts, "caps": caps,
            "path": str(path)}


# --------------------------------------------------------------------------
# device model
# --------------------------------------------------------------------------

def rc(L: float, W: float) -> tuple[float, float, float]:
    """(blanket body R, one end R, poly-to-bulk C) for one drawn resistor."""
    leff = L - 2 * R_DL
    weff = W - 2 * R_DW
    if leff <= 0 or weff <= 0:
        die(f"non-physical extracted geometry L={L} W={W}")
    rb = RSH * leff / weff
    re_ = RT_RSH * RT_L / weff
    c = CJ * leff * weff
    return rb, re_, c


def _fmt(x: float) -> str:
    return f"{x:.12g}"


def emit_netlist(ext: dict, mode: str, segments: int) -> str:
    """mode = lumped (PDK device) or segmented (N-section distributed RC)."""
    lines = [f"* R-2R post-layout {mode} model (from {Path(ext['path']).name})"]
    lines.append(".temp 25")

    # one helper subckt per extracted geometry
    geos = sorted({(round(i["L"], 12), round(i["W"], 12)) for i in ext["insts"]})
    if mode == "lumped":
        for L, W in geos:
            tag = f"{int(round(L * 1e9))}_{int(round(W * 1e9))}"
            lines.append(f".subckt dev_{tag} p n b")
            # Per-device geometry in micrometres, like gen_r2r.py.  The
            # extracted `.option scale=5n` is not needed here: r_width/r_length
            # are subckt parameters, and the model computes L/W itself.
            lines.append(f"X0 p n b ppolyf_u "
                         f"r_width={W * 1e6:.6f}u r_length={L * 1e6:.6f}u")
            lines.append(".ends")
    else:
        n = segments
        for L, W in geos:
            rb, re_, c = rc(L, W)
            tag = f"{int(round(L * 1e9))}_{int(round(W * 1e9))}"
            lines.append(f".subckt dev_{tag} p n b")
            lines.append(f"* L={L * 1e6:.3f} um W={W * 1e6:.3f} um: "
                         f"Rbody={rb:.1f} ohm Rend={re_:.2f} ohm "
                         f"Cpoly={c * 1e15:.3f} fF, {n} sections")
            lines.append(f"Rend_a p m0 {re_:.6f}")
            seg = rb / n
            for k in range(n):
                lines.append(f"R{k} m{k} m{k + 1} {seg:.9f}")
            lines.append(f"Rend_b m{n} n {re_:.6f}")
            lines.append(f"Cend_a p b {c / (2 * n):.9e}")
            for k in range(1, n):
                lines.append(f"C{k} m{k} b {c / n:.9e}")
            lines.append(f"Cend_b n b {c / (2 * n):.9e}")
            lines.append(".ends")

    lines.append(f".subckt {TOP}_rc " + " ".join(ext["ports"]))
    for inst in ext["insts"]:
        tag = (f"{int(round(inst['L'] * 1e9))}_"
               f"{int(round(inst['W'] * 1e9))}")
        lines.append(f"X{inst['name']} {inst['p']} {inst['n']} {inst['b']} "
                     f"dev_{tag}")
    for a, b, c in ext["caps"]:
        lines.append(f"C{a}_{b} {a} {b} {c:.9e}")
    lines.append(".ends")
    return "\n".join(lines) + "\n"


def bit_sources() -> list[str]:
    out = []
    for i in range(NBITS):
        out.append(f"Bb{i} b{i} 0 V = {VDD}*(floor((v(code)+0.5)/{2 ** i})"
                   f"-2*floor((v(code)+0.5)/{2 ** (i + 1)}))")
    return out


def driver_block() -> list[str]:
    """Schematic-level bit buffers, the same ones `gen_r2r.py` uses.

    The ladder's trim unit is sized to absorb the mean driver on-resistance, so
    a post-layout DC sweep with ideal bit sources would show that 148.36 um
    trim as a 0.5 % 2R error and ~0.45 LSB DNL.  The drivers are not in the
    layout yet (class C), so they are included here as the schematic model
    they are; the extracted part is the ladder.
    """
    try:
        import yaml
    except ImportError:
        die("PyYAML is required: pip install pyyaml")
    cfg = yaml.safe_load((ROOT / "r2r.yaml").read_text())
    p = cfg["pdk"]["gf180"]
    return [
        ".subckt inv a y vdd vss",
        f"Xp y a vdd vdd {p['pfet']} w={cfg['drv_wp']}u l={cfg['drv_l']}u",
        f"Xn y a vss vss {p['nfet']} w={cfg['drv_wn']}u l={cfg['drv_l']}u",
        ".ends inv",
        ".subckt buf a y vdd vss",
        "X1 a t vdd vss inv",
        "X2 t y vdd vss inv",
        ".ends buf",
        "Vdd vdd 0 3.3",
        *[f"Xd{i} b{i} d{i} vdd vss buf" for i in range(NBITS)],
    ]


def dac_ports() -> str:
    return " ".join(["vss"] + [f"d{i}" for i in range(NBITS)] +
                    [f"n{i}" for i in range(NBITS - 1)] + ["vout"])


def write_bench(ext: dict, lib: Path, mode: str, stage: str) -> Path:
    PL.mkdir(parents=True, exist_ok=True)
    nl = PL / f"{mode}.spice"
    net = emit_netlist(ext, mode,
                       1 if mode == "lumped" else SEGMENTS)
    body = [f"* bench: {stage} on the extracted {mode} netlist",
            f'.lib "{lib}" typical',
            f'.lib "{lib}" res_typical',
            f'.include "{lib.parent / "design.spice"}"',
            net,
            "Vss vss 0 0",
            "Vsub VSUBS 0 0",
            *driver_block()]
    if stage == "dc":
        body += ["Vcode code 0 0", *bit_sources(),
                 f"Xdut {dac_ports()} {TOP}_rc",
                 ".control", "set wr_singlescale", "set wr_vecnames",
                 "dc Vcode 0 255 1",
                 f"wrdata {PL / ('dc_' + mode + '.dat')} v(vout)",
                 ".endc"]
    else:
        steps = [0, 1, 2, 3, 127, 128, 254, 255, 0]
        step_us, ramp_ns = STEP_US, 10.0
        pts = [f"0 {steps[0]}"]
        for k in range(1, len(steps)):
            t0 = k * step_us * 1e3
            pts.append(f"{t0 - ramp_ns:.1f}n {steps[k - 1]}")
            pts.append(f"{t0:.1f}n {steps[k]}")
        body += ["Vcode code 0 PWL(" + " ".join(pts) + ")", *bit_sources(),
                 f"Xdut {dac_ports()} {TOP}_rc",
                 f"Rload vout 0 {LOAD_R:.6g}",
                 f"Cload vout 0 {LOAD_C:.6g}",
                 ".control", "set wr_singlescale", "set wr_vecnames",
                 f"tran {TRAN_STEP} {len(steps) * step_us}u",
                 f"wrdata {PL / ('tran_' + mode + '.dat')} v(vout) v(code)",
                 ".endc"]
    body.append(".end")
    nl.write_text("\n".join(body) + "\n")
    return nl


# --------------------------------------------------------------------------
# run + measure
# --------------------------------------------------------------------------

def run_ngspice(netlist: Path) -> None:
    if not shutil.which("ngspice"):
        die("ngspice not found in PATH")
    # sm141064.ngspice's sections use `.lib 'sm141064.spice'`, a relative path,
    # so ngspice must run from the model directory (not from build/postlayout).
    proc = subprocess.run(["ngspice", "-b", str(netlist)],
                          cwd=str(MODEL_DIR), capture_output=True, text=True,
                          timeout=1800)
    log = netlist.with_suffix(".log")
    log.write_text(proc.stdout + proc.stderr)
    txt = proc.stdout + proc.stderr
    if proc.returncode != 0 or "run simulation(s) aborted" in txt:
        die(f"ngspice failed on {netlist.name}; see {log}")
    if "Error:" in txt and "no such variable" not in txt:
        die(f"ngspice reported errors on {netlist.name}; see {log}")


def read_dat(path: Path, cols: int) -> list[tuple[float, ...]]:
    rows = []
    for line in path.read_text().splitlines():
        p = line.split()
        if len(p) >= cols:
            try:
                rows.append(tuple(float(x) for x in p[:cols]))
            except ValueError:
                pass
    return rows


def measure_dc(path: Path) -> dict:
    rows = read_dat(path, 2)
    if len(rows) != 2 ** NBITS:
        die(f"{path.name}: {len(rows)} points, want {2 ** NBITS}")
    v = [r[1] for r in rows]
    vmin, vmax = v[0], v[-1]
    lsb = (vmax - vmin) / (2 ** NBITS - 1)
    if lsb <= 0:
        die(f"{path.name}: non-monotonic endpoints")
    dnl = [0.0] * len(v)
    inl = [0.0] * len(v)
    for i, x in enumerate(v):
        inl[i] = (x - vmin) / lsb - i
        if i:
            dnl[i] = (x - v[i - 1]) / lsb - 1
    return {"points": len(v), "v0": vmin, "vfs": vmax, "lsb_mv": lsb * 1e3,
            "dnl_min": min(dnl), "dnl_max": max(dnl),
            "inl_min": min(inl), "inl_max": max(inl),
            "monotonic": all(d >= -1.0 for d in dnl)}


def measure_tran(path: Path) -> dict:
    rows = read_dat(path, 3)          # (time, v(vout), v(code))
    if not rows:
        die(f"{path.name}: empty")
    t = [r[0] for r in rows]
    vout = [r[1] for r in rows]
    lsb = VDD / 2 ** NBITS
    tol = 0.5 * lsb
    steps = [0, 1, 2, 3, 127, 128, 254, 255, 0]
    step_us = STEP_US
    out = []
    for k in range(1, len(steps)):
        t0 = k * step_us * 1e-6
        t1 = (k + 1) * step_us * 1e-6
        # The next step's 10 ns ramp starts at t1 - 10 ns and would leak into
        # this window, so stop 50 ns short of it.  Half-open below t0 as well:
        # the sample at t0 is already the new code.
        t1 -= 50e-9
        ib = [i for i in range(len(t)) if t0 <= t[i] < t1]
        if len(ib) < 2:
            die(f"{path.name}: no samples in step {k}")
        vf = vout[ib[-1]]
        cross = None
        for j in range(len(ib) - 1, -1, -1):
            if abs(vout[ib[j]] - vf) > tol:
                if j + 1 < len(ib):
                    cross = t[ib[j + 1]] - t0
                break
        out.append({"from": steps[k - 1], "to": steps[k],
                    "final_v": vf,
                    "settle_ns": 0.0 if cross is None else cross * 1e9})
    worst = max(out, key=lambda r: r["settle_ns"])
    return {"steps": out, "worst_ns": worst["settle_ns"],
            "worst_step": f"{worst['from']}->{worst['to']}"}


# --------------------------------------------------------------------------
# main
# --------------------------------------------------------------------------

SEGMENTS = 20
MODEL_DIR = Path(".")
TRAN_STEP = "50n"  # tau = 1 MOhm x 7 pF; 50 ns is 0.07 % of it
STEP_US = 60.0     # 1 MOhm // 7 pF needs ~7 tau = 49 us to reach 0.5 LSB


def main(argv=None) -> int:
    global SEGMENTS
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--stage", default="all", choices=["all", "dc", "tran"])
    ap.add_argument("--segments", type=int, default=20)
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args(argv)
    SEGMENTS = a.segments
    if SEGMENTS < 1:
        die("--segments must be >= 1")

    global MODEL_DIR
    pdk = find_pdk()
    lib = pdk / "gf180mcuA/libs.tech/ngspice/sm141064.ngspice"
    MODEL_DIR = lib.parent
    if not lib.is_file():
        die(f"model library not found: {lib}")
    if not PEX.is_file():
        sign = ROOT / "signoff.py"
        if not sign.is_file():
            die(f"no {PEX}; run signoff.py --stage pex")
        print(f"pex missing; extracting with {sign.name}")
        subprocess.run([str(sign), "--stage", "pex"], cwd=str(ROOT),
                       check=True)
    ext = parse_pex(PEX)

    if a.selftest:
        return selftest(ext)

    rep = {"pdk": str(pdk), "pex": ext["path"], "segments": SEGMENTS,
           "models": {}}
    for mode in ("lumped", "segmented"):
        models = {}
        if a.stage in ("all", "dc"):
            run_ngspice(write_bench(ext, lib, mode, "dc"))
            models["dc"] = measure_dc(PL / f"dc_{mode}.dat")
        if a.stage in ("all", "tran"):
            run_ngspice(write_bench(ext, lib, mode, "tran"))
            models["tran"] = measure_tran(PL / f"tran_{mode}.dat")
        rep["models"][mode] = models

    ok = True
    for mode, m in rep["models"].items():
        if "dc" in m:
            d = m["dc"]
            print(f"{mode:9s} dc   DNL {d['dnl_min']:+.3f}..{d['dnl_max']:+.3f} "
                  f"INL {d['inl_min']:+.3f}..{d['inl_max']:+.3f} LSB  "
                  f"Vfs {d['vfs']:.6f} V")
            ok &= abs(d["dnl_max"]) < 1.0 and abs(d["dnl_min"]) < 1.0
        if "tran" in m:
            t = m["tran"]
            print(f"{mode:9s} tran worst {t['worst_ns']:.1f} ns "
                  f"({t['worst_step']})")
    if "dc" in rep["models"]["lumped"] and "dc" in rep["models"]["segmented"]:
        a1 = rep["models"]["lumped"]["dc"]["vfs"]
        a2 = rep["models"]["segmented"]["dc"]["vfs"]
        dl = abs(a1 - a2)
        print(f"lumped vs segmented DC full-scale delta: {dl * 1e3:.6f} mV")
        ok &= dl < 1e-3
    if "tran" in rep["models"]["lumped"] and "tran" in rep["models"]["segmented"]:
        t1 = rep["models"]["lumped"]["tran"]["worst_ns"]
        t2 = rep["models"]["segmented"]["tran"]["worst_ns"]
        print(f"poly R-C contribution to worst settling: {t2 - t1:+.1f} ns")

    rep["ok"] = ok
    PL.mkdir(parents=True, exist_ok=True)
    (PL / "postlayout.json").write_text(json.dumps(rep, indent=1) + "\n")
    print(f"postlayout {'PASS' if ok else 'FAIL'}  report {PL / 'postlayout.json'}")
    return 0 if ok else 1


def selftest(ext: dict) -> int:
    """The gates must reject bad data, not just print PASS on a good run."""
    ok = True
    rb, re_, c = rc(150e-6, 2e-6)
    expect = 350 * (150e-6 - 2 * 2e-11) / (2e-6 - 2 * 2.55e-8)
    good = abs(rb - expect) < 1e-6 and re_ > 0 and c > 0
    print(f"selftest geometry   : {'PASS' if good else 'FAIL'} "
          f"(Rbody={rb:.1f}, Rend={re_:.2f}, C={c * 1e15:.3f} fF)")
    ok &= good
    one = emit_netlist(ext, "segmented", 4)
    nseg = one.count("Cend_a")
    print(f"selftest netlist    : {'PASS' if nseg == len({(i['L'], i['W']) for i in ext['insts']}) else 'FAIL'} "
          f"({nseg} device subckts)")
    ok &= nseg > 0
    try:
        rc(-1e-6, 2e-6)
        print("selftest bad-geom   : PASS (bad!)")
        ok = False
    except SystemExit:
        print("selftest bad-geom   : FAIL (correctly rejected)")
    print("selftest " + ("PASS" if ok else "FAIL"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
