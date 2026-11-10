#!/usr/bin/env python3
r"""Post-layout static mismatch Monte Carlo on the extracted P3 core (gf180).

    ./run_mismatch_pex.py [--samples 32] [--seed 0] [--brief]

Why this exists
---------------
`run_postlayout.py` proves the *drawn* core at one deterministic device model.
That is a topology and parasitics result, not a linearity one: every cell in
the PEX netlist carries the same `.model`, so the 0.177 LSB DNL it reports is
layout (matching of the drawn geometry), not process mismatch.  The only
mismatch number the leaf had was the pre-layout Pelgrom assumption in
`csteer.yaml` (1.8 % per unary cell), and that assumption is 1.8x the gf180
model's own area law (1.79 mV, i.e. 1.0 %).

This stage closes that gap on the extracted netlist.  It takes the PDK's
statistical device model (`*_03v3_dss` in `sm141064.ngspice`) apart:

  * the model's mismatch is exactly `delvto = mis_vth` and `mulu0 = 1-mis_k`
    on the BSIM3 instance, with
        var_vth = 0.7071*par_vth*1e-6 / sqrt((l-par_l)(w-par_w))
        var_k   = 0.7071*par_k  *1e-6 / sqrt((l-par_l)(w-par_w))
    and `par_vth/par_k/par_l/par_w` are the PDK's own Pelgrom constants.
  * the `_dss` wrapper also inserts source/drain diffusion resistors that the
    PEX has already extracted, so it is *not* used directly.  Instead the two
    instance parameters are drawn in Python from the PDK law and written as
    literals onto each extracted device.  Same law, no double counting, and
    the seed is ours (reproducible, and one `delvto` per device rather than
    one per shared subckt - Magic's PEX puts all 15 cells of a weight in one
    generated subckt, so the wrapper alone would have made the draw global).

Capacitors are dropped: this is a dc study, and they only cost parse time.

Per sample: one 31-point dc deck that turns on exactly one cell at a time,
which is enough to recover all 30 cell currents (15 unary at 16 LSB, 15 binary
at 1 LSB each).  The 256-code transfer is then reconstructed from those
currents and fitted with `measure.fit`, and the DWA pointer is applied
analytically by rotating the unary window - the binary part does not move.

Fail-closed gates
-----------------
 1. PEX missing or older than the GDS -> exit 2 (same rule as postlayout).
 2. Zero-mismatch reconstruction must agree with the *measured* 256-code
    transfer in `build/postlayout.json` (DNL and INL within 0.02 LSB).  If it
    does not, the per-cell decomposition is not the transfer and nothing else
    here means anything.
 3. The cell-to-cell spread within a sample must reproduce the PDK area law
    propagated through the extracted cell (the mirror's dI/I per mV is probed
    on that same cell, not borrowed from the device bench).
 4. Every sample must be monotonic; the DEM mean must meet the 0.5 LSB DNL /
    1.0 LSB INL target the leaf already uses.
"""
from __future__ import annotations

import argparse
import json
import math
import random
import re
import subprocess
import sys
from pathlib import Path

from gen_csteer import load_cfg, models, pdk_root
from measure import fit

ROOT = Path(__file__).resolve().parent
BUILD = ROOT / "build"
PEX = BUILD / "magic" / "pex.spice"
TOP = "dac_csteer_ana"
POST = BUILD / "postlayout.json"

# PDK Pelgrom constants, copied from the `*_03v3_dss` statistical subckts in
# sm141064.ngspice (par_vth, par_k) and their geometry offsets.
PELGROM = {
    "pfet_03v3": {"par_vth": 0.00666, "par_k": 0.002833},
    "nfet_03v3": {"par_vth": 0.007148, "par_k": 0.007008},
}
PAR_L, PAR_W, KAPPA = 1.5e-7, -1.0e-7, 0.7071


def die(msg: str, code: int = 2):
    print(f"error: {msg}", file=sys.stderr)
    raise SystemExit(code)


# --------------------------------------------------------------------------
# netlist surgery
# --------------------------------------------------------------------------
def split_pex(txt: str):
    """Return (preamble, {name: (ports, body)}, top_name)."""
    lines = txt.splitlines()
    pre, subs, top = [], {}, None
    i = 0
    while i < len(lines):
        ln = lines[i]
        m = re.match(r"^\.subckt\s+(\S+)\s*(.*)$", ln)
        if not m:
            if not subs:
                pre.append(ln)
            i += 1
            continue
        name, rest = m.group(1), m.group(2).replace("+", " ").split()
        body = []
        i += 1
        while i < len(lines) and not lines[i].startswith(".ends"):
            body.append(lines[i])
            i += 1
        i += 1
        subs[name] = (rest, body)
        top = name                     # last subckt is the top level
    return pre, subs, top


def is_device(line: str) -> bool:
    return line[:1].upper() in ("X", "M") and len(line.split()) >= 6


def flatten(subs, top):
    """Flat (nodes, model, params) for every device, in cell order.

    Each device subckt is a single MOSFET plus its own capacitor network, so
    substitution is just the port map.  The binary weight is the cell count,
    which is why every binary cell is its own device at 0.5/1.
    """
    ports_of = {n: p for n, (p, _) in subs.items()}

    def device_from(body, nmap):
        dev = [ln for ln in body if ln[:1].upper() in ("X", "M")]
        if len(dev) != 1:
            die(f"device subckt has {len(dev)} devices, expected 1")
        f = dev[0].split()
        nodes = [nmap.get(t, t) for t in f[1:5]]
        model = f[5]
        params = f[6:]
        return nodes, model, params

    _, top_body = subs[top]
    devs = []
    for ln in top_body:
        if ln[:1].upper() != "X":
            continue
        f = ln.split()
        cn = f[-1]
        if cn not in subs:
            die(f"{ln[:24]}: unknown subckt {cn}")
        args = f[1:-1]
        plist = ports_of[cn]
        if len(args) != len(plist):
            die(f"{cn}: {len(args)} nets for {len(plist)} ports")
        nodes, model, params = device_from(subs[cn][1], dict(zip(plist, args)))
        devs.append((nodes, model, params))
    return devs


def geom(params: list[str]) -> tuple[float, float]:
    """w, l of a PEX device line in um (PEX writes them in 5 nm units)."""
    d = {}
    for t in params:
        if "=" in t:
            k, v = t.split("=", 1)
            d[k.lower()] = v
    return float(d["w"]) * 0.005, float(d["l"]) * 0.005


def sigmas(model: str, w_um: float, l_um: float) -> tuple[float, float]:
    """(sigma_vth [V], sigma_k [ratio]) from the PDK's own area law."""
    p = PELGROM[model]
    leff = l_um * 1e-6 - PAR_L
    weff = w_um * 1e-6 - PAR_W
    if leff <= 0 or weff <= 0:
        die(f"{model} {w_um}/{l_um} um is outside the Pelgrom law")
    sq = math.sqrt(leff * weff)
    return (KAPPA * p["par_vth"] * 1e-6 / sq,
            KAPPA * p["par_k"] * 1e-6 / sq)


def deck(cfg, pdk, root, devs, ndev, draws, out: Path,
         tag: str, ncell: int) -> None:
    vdd = float(cfg["vdd"])
    ub = int(cfg["unary_bits"])
    bb = int(cfg["binary_bits"])
    tags = [f"u{j}" for j in range(2 ** ub - 1)]
    idx = len(tags)
    for w in (2 ** k for k in range(bb)):
        for i in range(w):
            tags.append(f"b{w}_{i}")
            idx += 1
    if len(tags) != ncell:
        die(f"{len(tags)} cell tags, want {ncell}")

    body = ["* %s: seed-drawn delvto/mulu0 on the extracted devices" % tag,
            models(cfg, pdk, root, 25.0, "tt"),
            ".option scale=5n",
            "Vdd vdd 0 %.6g" % vdd,
            "Vss vss 0 0",
            # The bias reference sinked at vcp is 16 uA, as in run_postlayout.
            "Iref vcp 0 %gu" % float(cfg["i_unit_ua"]),
            "Vsel sel 0 0"]
    for j, (nodes, model, params) in enumerate(devs):
        dv, dk = draws[j]
        body.append("M%d %s %s %s delvto=%.6g mulu0=%.6g"
                    % (j, " ".join(nodes), model, " ".join(params), dv, 1.0 - dk))
    for j, t in enumerate(tags):
        cond = f"(abs(v(sel)-{j})<0.5)"
        body += [f"Bswa_{t} swa_{t} 0 V = {vdd:.6g}*{cond}",
                 f"Bswb_{t} swb_{t} 0 V = {vdd:.6g}*(1-{cond})"]
    body += ["Vmi iout 0 0", "Vmn idump 0 0",
             ".control", "set wr_singlescale", "set wr_vecnames",
             f"dc Vsel 0 {len(tags)} 1",
             f"wrdata {out} v(sel) i(Vmi) i(Vmn)",
             ".endc", ".end"]
    (BUILD / (tag + ".spice")).write_text("\n".join(body) + "\n")


def run(deck_path: Path) -> None:
    r = subprocess.run(["ngspice", "-b", str(deck_path)], capture_output=True,
                       text=True)
    txt = r.stdout + r.stderr
    if r.returncode or "Error!" in txt:
        tail = "\n".join(l for l in txt.splitlines()
                         if "rror" in l or "singular" in l)[-1200:]
        die(f"ngspice failed on {deck_path.name}\n{tail}")


def read_cells(dat: Path, n: int) -> list[float]:
    rows = []
    for ln in dat.read_text().splitlines():
        f = ln.split()
        if len(f) < 3:
            continue
        try:
            rows.append([float(v) for v in f])
        except ValueError:
            continue
    if len(rows) < n:
        die(f"{dat.name}: {len(rows)} points, want {n}")
    # Point k has cell k on iout, so i(Vmi) at point k is that cell's current.
    cells = [rows[k][2] for k in range(n)]
    if min(cells) <= 0:
        die(f"{dat.name}: a cell delivered {min(cells) * 1e6:.3f} uA")
    return cells


# --------------------------------------------------------------------------
# transfer reconstruction + DEM
# --------------------------------------------------------------------------
def transfers(cells: list[float], cfg) -> list[list[float]]:
    """Output current for every code, one vector per DEM pointer position."""
    ub = int(cfg["unary_bits"])
    bb = int(cfg["binary_bits"])
    bits = int(cfg["bits"])
    nu = 2 ** ub - 1
    unary = cells[:nu]
    bin_cells = cells[nu:]
    bit_cur = []
    k = 0
    for b in range(bb):
        w = 2 ** b
        bit_cur.append(sum(bin_cells[k:k + w]))
        k += w
    out = []
    for p in range(nu):
        row = []
        for c in range(2 ** bits):
            nact = c >> bb
            total = sum(unary[(j - p) % nu] for j in range(nact))
            for b in range(bb):
                if (c >> b) & 1:
                    total += bit_cur[b]
            row.append(total)
        out.append(row)
    return out


def metrics(vals: list[float], bits: int) -> dict:
    lsb, dnl, inl = fit(vals, bits)
    return {"lsb": lsb,
            "dnl": max(abs(d) for d in dnl[1:]),
            "inl": max(abs(v) for v in inl),
            "nonmono": sum(1 for d in dnl[1:] if d < -1.0)}


def spread(cells: list[float], lo: int = 0, hi: int = 15) -> float:
    """Within-sample cell-to-cell sigma, in % of that group's mean.

    This is the quantity DNL/INL see: the shared bias reference is common to
    every cell and the endpoint fit removes it.
    """
    v = cells[lo:hi]
    mu = sum(v) / len(v)
    return math.sqrt(sum((x - mu) ** 2 for x in v) / (len(v) - 1)) / mu * 100.0


def mirror_of_cell(devs, tag: str) -> int:
    """Index of the mirror device that feeds cell `tag`, from the topology."""
    cas = [i for i, (n, _, _) in enumerate(devs) if n[0] == "cd_" + tag]
    if len(cas) != 1:
        die(f"{tag}: {len(cas)} cascodes; the PEX port list changed")
    src = devs[cas[0]][0][2]
    mir = [i for i, (n, _, _) in enumerate(devs)
           if n[0] == src and n[1] == "vbp"]
    if len(mir) != 1:
        die(f"{tag}: {len(mir)} mirrors on {src}")
    return mir[0]


def sensitivity(cfg, root, devs, base_cells, out: Path) -> float:
    """dI/I per mV of mirror Vth, measured on the extracted cell itself.

    The device bench reports 0.519 %/mV with its own replica-bias netlist; the
    extracted cell differs (the cascode bias node is distributed RC), so the
    gate must not borrow the bench's number.
    """
    m = mirror_of_cell(devs, "u0")
    dv = 2.0e-3
    draws = [(0.0, 0.0)] * len(devs)
    draws[m] = (dv, 0.0)
    deck(cfg, "gf180", root, devs, len(devs), draws, out, "mm_sens", 30)
    run(out.with_suffix(".spice"))
    cells = read_cells(out, 30)
    return (cells[0] - base_cells[0]) / base_cells[0] / (dv * 1e3) * 100.0


def selftest(cfg, root, devs, c0, sig, ref, want_u) -> int:
    """Prove the gate rejects the two ways this stage could silently pass.

    The stage's whole claim is that each *device* gets its own draw.  Any
    implementation that draws once per shared subckt, or that forgets to draw
    at all, still produces a plausible-looking DNL - so the mutations below
    are checked against the same spread gate the real run uses.
    """
    ncell = 30
    ok = True
    # Correct behaviour: one independent draw per device at the PDK sigma.
    rng = random.Random(1)
    real = [(rng.gauss(0.0, sv), rng.gauss(0.0, sk)) for sv, sk in sig]
    deck(cfg, "gf180", root, devs, len(devs), real,
         BUILD / "mm_st_real.dat", "mm_st_real", ncell)
    run(BUILD / "mm_st_real.spice")
    cr = read_cells(BUILD / "mm_st_real.dat", ncell)
    sp = spread(cr)
    p = abs(sp - want_u) < 0.20 * want_u
    print(f"selftest mm-devices: {'PASS' if p else 'FAIL'} "
          f"(spread {sp:.3f} % vs law {want_u:.3f} %)")
    ok &= p

    # One draws array shared by every device: exactly what a per-subckt draw
    # would give (all 30 cells move together), so the spread collapses.
    shared = [(sig[0][0], sig[0][1])] * len(devs)
    deck(cfg, "gf180", root, devs, len(devs), shared,
         BUILD / "mm_st_shared.dat", "mm_st_shared", ncell)
    run(BUILD / "mm_st_shared.spice")
    cs = read_cells(BUILD / "mm_st_shared.dat", ncell)
    sp = spread(cs)
    p = not (abs(sp - want_u) < 0.20 * want_u)
    print(f"selftest mm-shared : {'FAIL' if p else 'PASS (bad!)'} "
          f"(spread {sp:.4f} %)")
    ok &= p

    # Correct per-device draws but at half the PDK sigma: the spread lands
    # outside the 20 % band, so the gate is checking magnitude, not merely
    # that something moved.
    rng = random.Random(7)
    half = [(rng.gauss(0.0, sv / 2), rng.gauss(0.0, sk / 2))
            for sv, sk in sig]
    deck(cfg, "gf180", root, devs, len(devs), half,
         BUILD / "mm_st_half.dat", "mm_st_half", ncell)
    run(BUILD / "mm_st_half.spice")
    ch = read_cells(BUILD / "mm_st_half.dat", ncell)
    sp = spread(ch)
    p = not (abs(sp - want_u) < 0.20 * want_u)
    print(f"selftest mm-half   : {'FAIL' if p else 'PASS (bad!)'} "
          f"(spread {sp:.3f} % vs law {want_u:.3f} %)")
    ok &= p

    print("selftest " + ("PASS" if ok else "FAIL"))
    return 0 if ok else 1


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--samples", type=int, default=32)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--brief", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args(argv)

    if not PEX.is_file():
        die(f"no {PEX.relative_to(ROOT)}; run ./signoff.py --stage pex")
    gds = BUILD / "csteer.gds"
    if gds.is_file() and gds.stat().st_mtime > PEX.stat().st_mtime:
        die(f"stale {PEX.name}: {gds.name} is newer; re-extract")
    if not POST.is_file():
        die(f"no {POST.relative_to(ROOT)}; run ./signoff.py --stage postlayout")
    post = json.loads(POST.read_text())
    cfg = load_cfg()
    root = pdk_root(cfg, "gf180", None)
    bits = int(cfg["bits"])

    pre, subs, top = split_pex(PEX.read_text())
    if top != TOP:
        die(f"top subckt is {top}, want {TOP}")
    devs = flatten(subs, top)

    # Per-device sigma from the PDK area law; printed once because it is the
    # number the pre-layout Pelgrom assumption should have used.
    sig = [sigmas(m, *geom(p)) for _, m, p in devs]
    # The PEX interleaves mirrors, cascodes and switches, so report the
    # distinct (model, w, l) groups rather than pretending to know the cell
    # order; the per-cell sigma is measured below from the cell currents.
    groups = {}
    for (_, m, p), (sv, sk) in zip(devs, sig):
        key = (m, round(geom(p)[0], 3), round(geom(p)[1], 3))
        groups.setdefault(key, [0, sv, sk])
        groups[key][0] += 1
    ncell = (2 ** int(cfg["unary_bits"]) - 1) + (2 ** int(cfg["binary_bits"]) - 1)
    if not a.brief:
        print(f"mismatch MC: {len(devs)} extracted devices, {ncell} cells, "
              f"PDK area law")
        for (m, w, l), (n, sv, sk) in sorted(groups.items()):
            print(f"  {m:9} {w:5.2f}/{l:4.2f} um x{n:2d}: "
                  f"sigma_vth {sv * 1e3:.2f} mV, sigma_k {sk * 100:.2f} %")

    zero = [(0.0, 0.0)] * len(devs)
    deck(cfg, "gf180", root, devs, len(devs), zero,
         BUILD / "mm_cells_0.dat", "mm_cells_0", ncell)
    run(BUILD / "mm_cells_0.spice")
    c0 = read_cells(BUILD / "mm_cells_0.dat", ncell)
    tf0 = transfers(c0, cfg)
    m0 = [metrics(r, bits) for r in tf0]
    # Pointer 0 is the modelled bench; the DWA mean is the average over the 15.
    ref = post["transfer"]
    d_dnl = abs(m0[0]["dnl"] - ref["dnl"])
    d_inl = abs(m0[0]["inl"] - ref["inl"])
    if not a.brief:
        print(f"  zero-mismatch check : DNL {m0[0]['dnl']:.3f} "
              f"(bench {ref['dnl']:.3f}), INL {m0[0]['inl']:.3f} "
              f"(bench {ref['inl']:.3f})")
    if d_dnl > 0.02 or d_inl > 0.02:
        die(f"reconstruction disagrees with the measured transfer: "
            f"dDNL {d_dnl:.3f}, dINL {d_inl:.3f} LSB")

    sens = sensitivity(cfg, root, devs, c0, BUILD / "mm_sens.dat")
    want_u = sig[0][0] * 1e3 * sens          # sigma_VT [mV] x %/mV
    if a.selftest:
        return selftest(cfg, root, devs, c0, sig, post["transfer"], want_u)

    rng = random.Random(a.seed)
    rows = []
    for s in range(a.samples):
        draws = [(rng.gauss(0.0, sv), rng.gauss(0.0, sk)) for sv, sk in sig]
        tag = f"mm_cells_s{s}"
        deck(cfg, "gf180", root, devs, len(devs), draws,
             BUILD / (tag + ".dat"), tag, ncell)
        run(BUILD / (tag + ".spice"))
        cells = read_cells(BUILD / (tag + ".dat"), ncell)
        tf = transfers(cells, cfg)
        ms = [metrics(r, bits) for r in tf]
        mean = [sum(tf[p][c] for p in range(len(tf))) / len(tf)
                for c in range(2 ** bits)]
        mm = metrics(mean, bits)
        rows.append({"seed": a.seed + s,
                     "dnl_ptr": [m["dnl"] for m in ms],
                     "inl_ptr": [m["inl"] for m in ms],
                     "dnl_mean": mm["dnl"], "inl_mean": mm["inl"],
                     "nonmono": sum(m["nonmono"] for m in ms),
                     "cells": cells})
        if not a.brief:
            print(f"  sample {s:3d}          : fixed DNL {ms[0]['dnl']:.3f} "
                  f"INL {ms[0]['inl']:.3f} | DEM mean DNL {mm['dnl']:.3f} "
                  f"INL {mm['inl']:.3f} | worst ptr INL "
                  f"{max(m['inl'] for m in ms):.3f}")

    # Two different sigmas, and they must not be conflated:
    #   across samples, one cell: includes the shared bias reference, which is
    #     a common gain error the endpoint fit removes - so ~sqrt(2) a cell's
    #     own spread and NOT what linearity sees;
    #   within a sample, cell to cell: this is the mismatch that DNL/INL see.
    n = len(rows)

    def std(v):
        mu = sum(v) / n
        if n < 2:
            return 0.0
        return math.sqrt(sum((x - mu) ** 2 for x in v) / (n - 1))

    def across(idx):
        v = [r["cells"][idx] for r in rows]
        return std(v) / (sum(v) / n) * 100.0

    un_across = [across(j) for j in range(15)]
    bi_across = [across(j) for j in range(15, 30)]
    un_sig = sum(spread(r["cells"], 0, 15) for r in rows) / n
    bi_sig = sum(spread(r["cells"], 15, 30) for r in rows) / n
    dem_dnl = [r["dnl_mean"] for r in rows]
    dem_inl = [r["inl_mean"] for r in rows]
    fixed_dnl = [r["dnl_ptr"][0] for r in rows]
    fixed_inl = [r["inl_ptr"][0] for r in rows]
    worst_inl = max(max(r["inl_ptr"]) for r in rows)
    worst_dnl = max(max(r["dnl_ptr"]) for r in rows)
    nonmono = sum(r["nonmono"] for r in rows)

    def rng_of(v):
        return min(v), max(v)

    checks = [
        ("zero-mismatch dDNL", d_dnl < 0.02, f"{d_dnl:.4f} LSB"),
        ("zero-mismatch dINL", d_inl < 0.02, f"{d_inl:.4f} LSB"),
        # The drawn cell-to-cell spread must land on the area law propagated
        # through the extracted cell (a 32-sample std has ~13 % sampling error,
        # so the band is 20 %; a shared draw across cells would give 0).
        ("spread vs PDK law", abs(un_sig - want_u) < 0.20 * want_u,
         f"{un_sig:.2f} % vs {want_u:.2f} %"),
        # DEM averages the 15 unary pointers, so the mean converter is the
        # target: 0.5 LSB DNL, 1.0 LSB INL.
        ("DEM mean DNL", max(dem_dnl) < 0.5, f"{max(dem_dnl):.3f} LSB"),
        ("DEM mean INL", max(dem_inl) < 1.0, f"{max(dem_inl):.3f} LSB"),
        ("monotonic", nonmono == 0, f"{nonmono} bad samples"),
    ]
    ok = True
    if not a.brief:
        print()

    print(f"post-layout mismatch MC ({a.samples} samples, seed {a.seed}, "
          f"gf180 tt 25 C)")
    print(f"  mirror sensitivity  : {sens:.3f} %/mV (device bench 0.519; "
          f"PDK sigma_VT {sig[0][0] * 1e3:.2f} mV for an 8/1 mirror)")
    print(f"  unary cell spread   : {un_sig:.2f} % within a sample "
          f"(pre-layout assumption 1.80 %, PDK area law {want_u:.2f} %)")
    print(f"  binary cell spread  : {bi_sig:.2f} % within a sample")
    print(f"  unary cell, across samples (incl. shared bias ref): "
          f"{min(un_across):.2f} .. {max(un_across):.2f} %")
    print(f"  binary cell, across samples (incl. shared bias ref): "
          f"{min(bi_across):.2f} .. {max(bi_across):.2f} %")
    print(f"  fixed pointer DNL   : {rng_of(fixed_dnl)[0]:.3f} .. "
          f"{rng_of(fixed_dnl)[1]:.3f} LSB (mean {sum(fixed_dnl) / n:.3f})")
    print(f"  fixed pointer INL   : {rng_of(fixed_inl)[0]:.3f} .. "
          f"{rng_of(fixed_inl)[1]:.3f} LSB (mean {sum(fixed_inl) / n:.3f})")
    print(f"  DEM mean DNL/INL    : {rng_of(dem_dnl)[0]:.3f}/"
          f"{rng_of(dem_inl)[0]:.3f} .. {rng_of(dem_dnl)[1]:.3f}/"
          f"{rng_of(dem_inl)[1]:.3f} LSB")
    print(f"  worst pointer, any sample: DNL {worst_dnl:.3f} / "
          f"INL {worst_inl:.3f} LSB")
    for name, good, val in checks:
        ok &= good
        print(f"  {name:22}: {val:>12}  {'ok' if good else 'FAIL'}")
    print(f"post-layout mismatch {'PASS' if ok else 'FAIL'}")
    (BUILD / "mismatch.json").write_text(json.dumps(
        {"ok": ok, "samples": a.samples, "seed": a.seed,
         "sens_pct_per_mv": sens,
         "sigma_unary_pct": un_sig, "sigma_binary_pct": bi_sig,
         "sigma_unary_across_pct": un_across,
         "sigma_binary_across_pct": bi_across,
         "pdk_law_pct": want_u,
         "zero": {"dnl": m0[0]["dnl"], "inl": m0[0]["inl"]},
         "fixed": {"dnl": fixed_dnl, "inl": fixed_inl},
         "dem_mean": {"dnl": dem_dnl, "inl": dem_inl},
         "worst_ptr": {"dnl": worst_dnl, "inl": worst_inl}},
        indent=1) + "\n")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
