#!/usr/bin/env python3
r"""Post-layout static mismatch Monte Carlo on the extracted P5 array (gf180).

    ./run_mismatch_pex.py [--samples 16] [--seed 0] [--brief] [--selftest]

Why this exists
---------------
`run_postlayout.py` runs the extracted devices at one deterministic model, and
because all 255 cells are drawn identically it reports DNL/INL 0.000 by
construction.  That is a layout result, not a linearity one: the array's real
linearity is set by *process* mismatch between cells, and the only number the
leaf had for it was the pre-layout Pelgrom assumption in `video.yaml`
(1.8 %/cell, from A_VT = 10 mV*um).  This stage puts the extracted netlist on
the PDK's own mismatch law instead.

Where the draws come from
-------------------------
The PDK's statistical subckt (`pfet_03v3_dss`) is not used directly: it also
inserts source/drain diffusion resistors that the extraction already has, and
Magic's hierarchical pex puts several cells in one generated subckt, so its
`agauss` would draw *once per subckt*.  The law is taken from it instead, and
drawn per extracted device in Python:

    var_vth = 0.7071*par_vth*1e-6 / sqrt((l-par_l)(w-par_w))
    var_k   = 0.7071*par_k  *1e-6 / sqrt((l-par_l)(w-par_w))

with the PDK's own `par_vth/par_k/par_l/par_w`, written as `delvto`/`mulu0`
literals on each device.  Same law, one draw per device, our seed.

The netlist is the *flat* `lvs.spice` (the same device set the post-layout
bench uses), converted from subckt instances to `M` devices so the two
instance parameters can be written on them; this is a dc study, so the PEX
capacitors and the hierarchy buy nothing.

Per sample: one selector sweep in which exactly one cell is switched on per
point (255 points), which recovers every cell's current.  The 256-code
transfer is then exact superposition of those currents and is checked against
the measured bench at zero mismatch, so the decomposition cannot drift
unnoticed.

Fail-closed gates
-----------------
 1. No netlist, a netlist older than the GDS, or no `postlayout.json` -> exit 2.
 2. Zero-mismatch reconstruction must reproduce the measured transfer in
    `postlayout.json` (DNL and INL within 0.02 LSB).
 3. The within-sample cell-to-cell spread must land on the PDK area law
    propagated through the extracted cell, with the cell's own measured
    sensitivity to each of its three devices' Vth *and* beta (all six probed
    on that cell, not borrowed from the device bench).
 4. Every sample must be monotonic, and the fixed-pointer DNL/INL must meet
    the 0.5 / 1.0 LSB target the leaf already uses.
"""
from __future__ import annotations

import argparse
import json
import math
import random
import sys
from pathlib import Path

import run_postlayout as pl

ROOT = pl.ROOT
BUILD = pl.BUILD
GDS = pl.GDS
LVS = pl.LVS
POST = BUILD / "postlayout.json"

# Pelgrom constants from the `pfet_03v3_dss` statistical subckt in
# sm141064.ngspice, and its geometry offsets (identical to the P3 stage).
PELGROM = {"pfet_03v3": {"par_vth": 0.00666, "par_k": 0.002833},
           "nfet_03v3": {"par_vth": 0.007148, "par_k": 0.007008}}
PAR_L, PAR_W, KAPPA = 1.5e-7, -1.0e-7, 0.7071


def die(msg: str, code: int = 2):
    print(f"error: {msg}", file=sys.stderr)
    raise SystemExit(code)


# --------------------------------------------------------------------------
# the extracted devices
# --------------------------------------------------------------------------
def flat_devs() -> list[str]:
    """The flat netlist's devices without their instance names.

    `X<n> d g s b pfet_03v3 w=1600 l=200` becomes `d g s b pfet_03v3 w=1600
    l=200`, so a draw can be written on the line as an `M` device.  Geometry
    stays in 5 nm units: `.option scale=5n` from `models()` scales both forms.
    """
    devs = []
    for ln in pl.devices(LVS.read_text()):
        f = ln.split()
        if not f[5].startswith("pfet"):
            die(f"{f[0]}: device model {f[5]}; P5 is a PMOS array")
        devs.append(" ".join(f[1:]))
    return devs


def geom(line: str) -> tuple[float, float]:
    """(w, l) in um of a device line, whose numbers are 5 nm units."""
    d = {}
    for t in line.split():
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


def model_of(line: str) -> str:
    return line.split()[4]


def tags(cfg) -> list[str]:
    n = 2 ** int(cfg["bits"]) - 1
    out = []
    for j in range(n):
        k = pl.cell_bit(j)
        out.append(f"b{k}_{j - (2 ** k - 1)}")
    return out


def cell_devs(devs: list[str], tag: str) -> dict[str, int]:
    """Indices of a cell's switch, mirror and cascode, walked from its pad.

    The pad is the only net Magic leaves unmangled, so the walk goes pad ->
    switch gate -> switch drain -> mirror source -> mirror drain -> cascode
    source.  That is the same chain the LVS contract uses.
    """
    pad = "d_" + tag
    sw = [i for i, ln in enumerate(devs) if ln.split()[1] == pad]
    if len(sw) != 1:
        die(f"{tag}: {len(sw)} switches on {pad}; the netlist changed")
    src = devs[sw[0]].split()[0]
    mir = [i for i, ln in enumerate(devs)
           if ln.split()[2] == src and ln.split()[1] == "vbp"]
    if len(mir) != 1:
        die(f"{tag}: {len(mir)} mirrors on {src}")
    mdr = devs[mir[0]].split()[0]
    cas = [i for i, ln in enumerate(devs) if ln.split()[2] == mdr]
    if len(cas) != 1:
        die(f"{tag}: {len(cas)} cascodes on {mdr}")
    return {"switch": sw[0], "mirror": mir[0], "cascode": cas[0]}


# --------------------------------------------------------------------------
# decks
# --------------------------------------------------------------------------
def deck(cfg, root: Path, devs: list[str], draws, out: Path, tag: str,
         sweep: bool = True, sel: int = 0) -> None:
    vdd = float(cfg["vdd"])
    body = ["* %s: seed-drawn delvto/mulu0 on the extracted devices" % tag,
            *pl.models(root),
            "Vdd vdd 0 %.6g" % vdd,
            "Vgnd vgnd 0 0",
            # The reference sinked at vcp is 16 uA, as in the bench.
            "Iref vcp 0 %gu" % float(cfg["i_unit_ua"])]
    for j, (ln, (dv, dk)) in enumerate(zip(devs, draws)):
        body.append(f"M{j} {ln} delvto={dv:.6g} mulu0={1.0 - dk:.6g}")
    body.append(f"Vsel sel 0 {sel}")
    for j, t in enumerate(tags(cfg)):
        body.append(f"Bd_{t} d_{t} 0 V = {vdd:.6g}*(1-(abs(v(sel)-{j})<0.5))")
    body += ["Vmi iout 0 0",
             ".control", "set wr_singlescale", "set wr_vecnames"]
    if sweep:
        body.append(f"dc Vsel 0 {len(tags(cfg)) - 1} 1")
    else:
        body.append("op")
    body += [f"wrdata {out} i(Vmi)", ".endc", ".end"]
    nl = BUILD / (tag + ".spice")
    nl.write_text("\n".join(body) + "\n")
    pl.ngspice(nl)


def read_cells(dat: Path, n: int) -> list[float]:
    names, rows = pl.wrdata(dat)
    if "i(Vmi)" not in names:
        die(f"{dat.name}: no i(Vmi) column")
    ci = names["i(Vmi)"]
    if len(rows) < n:
        die(f"{dat.name}: {len(rows)} points, want {n}")
    cells = [abs(r[ci]) for r in rows[:n]]
    if min(cells) <= 0:
        die(f"{dat.name}: a cell delivered {min(cells) * 1e6:.3f} uA")
    return cells


# --------------------------------------------------------------------------
# transfer + metrics
# --------------------------------------------------------------------------
def transfer(cells: list[float], cfg) -> list[float]:
    """Output current for every code: exact superposition of cell currents."""
    n_code = 2 ** int(cfg["bits"])
    out = []
    for c in range(n_code):
        out.append(sum(cells[j] for j in range(len(cells))
                       if (c >> pl.cell_bit(j)) & 1))
    return out


def metrics(vals: list[float], bits: int) -> dict:
    """Endpoint-fit DNL/INL, the same definition the bench uses."""
    n_code = len(vals)
    i0 = vals[0]
    fs = vals[-1] - i0
    if fs <= 0:
        die("reconstructed full scale is not positive")
    lsb = fs / (n_code - 1)
    steps = [vals[c] - vals[c - 1] for c in range(1, n_code)]
    dnl = max(abs(s / lsb - 1.0) for s in steps)
    inl = max(abs((vals[c] - i0) / lsb - c) for c in range(n_code))
    nonmono = sum(1 for s in steps if s < -0.05 * lsb)
    return {"dnl": dnl, "inl": inl, "nonmono": nonmono}


def spread(cells: list[float]) -> float:
    """Within-sample cell-to-cell sigma, in % of the mean.

    This is the quantity DNL/INL see: the bias reference is shared by every
    cell, so the endpoint fit removes it and only the cell-to-cell part is
    left.
    """
    mu = sum(cells) / len(cells)
    var = sum((x - mu) ** 2 for x in cells) / (len(cells) - 1)
    return math.sqrt(var) / mu * 100.0


def sensitivity(cfg, root: Path, devs, base: float, i: int,
                dv: float = 0.0, dk: float = 0.0) -> float:
    """Cell 0's current ratio when one of its devices' draws is perturbed.

    Probed on the extracted cell itself: the series switch degenerates the
    mirror, so the cell's sensitivity to mirror Vth is 0.44x what an
    undegenerated 8/1 would show, and to mirror beta likewise.  A number
    borrowed from a device bench would not describe this cell.
    """
    draws = [(0.0, 0.0)] * len(devs)
    draws[i] = (dv, dk)
    deck(cfg, root, devs, draws, BUILD / "mm_sens.dat", "mm_sens",
         sweep=False, sel=0)
    cur = read_cells(BUILD / "mm_sens.dat", 1)[0]
    return cur / base


def expected_sigma(devs, sig, sens: dict, tag: str) -> float:
    """Per-cell sigma predicted from the PDK law and the cell's own gain."""
    idx = cell_devs(devs, tag)
    total = 0.0
    for role, i in idx.items():
        sv, sk = sig[i]
        dv = (sens[role]["vth"] - 1.0) * 100.0 / 2.0       # %/mV (2 mV)
        dk = (sens[role]["beta"] - 1.0) * 100.0 / 1.0      # %/%  (1 %)
        total += (sv * 1e3 * dv) ** 2 + (sk * 100.0 * dk) ** 2
    return math.sqrt(total)


def selftest(cfg, root, devs, sig, want_u) -> int:
    """Prove the gate rejects the ways this stage could silently pass.

    Every mutation below is a plausible implementation of "draw mismatch":
    one draw shared by all devices (what a per-subckt draw gives), per-device
    draws at half the law's sigma, and draws applied only to the mirrors.
    Each is checked against the same spread gate the real run uses.
    """
    n = len(tags(cfg))
    ok = True

    def one(draws, tag):
        deck(cfg, root, devs, draws, BUILD / (tag + ".dat"), tag)
        return read_cells(BUILD / (tag + ".dat"), n)

    rng = random.Random(1)
    real = [(rng.gauss(0.0, sv), rng.gauss(0.0, sk)) for sv, sk in sig]
    sp = spread(one(real, "mm_st_real"))
    p = abs(sp - want_u) < 0.20 * want_u
    print(f"selftest mm-devices: {'PASS' if p else 'FAIL'} "
          f"(spread {sp:.3f} % vs law {want_u:.3f} %)")
    ok &= p

    # One draw for the whole array: every cell moves together, spread -> 0.
    shared = [real[0]] * len(devs)
    sp = spread(one(shared, "mm_st_shared"))
    p = not (abs(sp - want_u) < 0.20 * want_u)
    print(f"selftest mm-shared : {'FAIL' if p else 'PASS (bad!)'} "
          f"(spread {sp:.4f} %)")
    ok &= p

    # Correct per-device draws at half the law's sigma.
    rng = random.Random(7)
    half = [(rng.gauss(0.0, sv / 2), rng.gauss(0.0, sk / 2)) for sv, sk in sig]
    sp = spread(one(half, "mm_st_half"))
    p = not (abs(sp - want_u) < 0.20 * want_u)
    print(f"selftest mm-half   : {'FAIL' if p else 'PASS (bad!)'} "
          f"(spread {sp:.3f} % vs law {want_u:.3f} %)")
    ok &= p

    # Draws on the mirrors only: the switch's Vth and beta are half of the
    # cell's sigma here, so this cannot land on the law either.
    mir = {i for t in tags(cfg) for r, i in cell_devs(devs, t).items()
           if r == "mirror"}
    rng = random.Random(9)
    dr = [(rng.gauss(0.0, sv), rng.gauss(0.0, sk)) if i in mir else (0.0, 0.0)
          for i, (sv, sk) in enumerate(sig)]
    sp = spread(one(dr, "mm_st_mirror"))
    p = not (abs(sp - want_u) < 0.20 * want_u)
    print(f"selftest mm-mirror : {'FAIL' if p else 'PASS (bad!)'} "
          f"(spread {sp:.3f} % vs law {want_u:.3f} %)")
    ok &= p

    print("selftest " + ("PASS" if ok else "FAIL"))
    return 0 if ok else 1


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--samples", type=int, default=16)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--brief", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args(argv)

    if not LVS.is_file():
        die(f"no {LVS.relative_to(ROOT)}; run ./signoff.py --stage lvs")
    if GDS.is_file() and GDS.stat().st_mtime > LVS.stat().st_mtime:
        die(f"stale {LVS.name}: {GDS.name} is newer; re-extract")
    if not POST.is_file():
        die(f"no {POST.relative_to(ROOT)}; run ./signoff.py --stage postlayout")
    post = json.loads(POST.read_text())
    ref = post["virtual_ground"]
    cfg = pl.load_cfg()
    root = pl.pdk_root()
    bits = int(cfg["bits"])
    n = len(tags(cfg))

    devs = flat_devs()
    if len(devs) != 3 * n + 3:
        die(f"{len(devs)} devices, want {3 * n + 3}")
    sig = [sigmas(model_of(ln), *geom(ln)) for ln in devs]

    # The distinct (model, w, l) groups, which is all the PEX order allows us
    # to say about which device is which before the pad walk.
    groups = {}
    for ln, (sv, sk) in zip(devs, sig):
        key = (model_of(ln), *[round(v, 3) for v in geom(ln)])
        groups.setdefault(key, [0, sv, sk])
        groups[key][0] += 1
    if not a.brief:
        print(f"mismatch MC: {len(devs)} extracted devices, {n} cells, "
              f"PDK area law")
        for (m, w, l), (cnt, sv, sk) in sorted(groups.items()):
            print(f"  {m:9} {w:5.2f}/{l:4.2f} um x{cnt:3d}: "
                  f"sigma_vth {sv * 1e3:6.2f} mV, sigma_k {sk * 100:5.3f} %")

    zero = [(0.0, 0.0)] * len(devs)
    deck(cfg, root, devs, zero, BUILD / "mm_cells_0.dat", "mm_cells_0")
    c0 = read_cells(BUILD / "mm_cells_0.dat", n)
    m0 = metrics(transfer(c0, cfg), bits)
    d_dnl, d_inl = abs(m0["dnl"] - ref["dnl"]), abs(m0["inl"] - ref["inl"])
    if not a.brief:
        print(f"  zero-mismatch       : DNL {m0['dnl']:.4f} "
              f"(bench {ref['dnl']:.4f}), INL {m0['inl']:.4f} "
              f"(bench {ref['inl']:.4f}), unit {c0[0] * 1e6:.3f} uA")
    if d_dnl > 0.02 or d_inl > 0.02:
        die(f"reconstruction disagrees with the measured transfer: "
            f"dDNL {d_dnl:.4f}, dINL {d_inl:.4f} LSB")

    # Per-role sensitivity of cell 0, from the extracted cell itself.
    idx = cell_devs(devs, tags(cfg)[0])
    sens = {}
    for role, i in idx.items():
        sens[role] = {"vth": sensitivity(cfg, root, devs, c0[0], i, dv=2e-3),
                      "beta": sensitivity(cfg, root, devs, c0[0], i, dk=0.01)}
    want_u = expected_sigma(devs, sig, sens, tags(cfg)[0])
    if not a.brief:
        for role in ("mirror", "cascode", "switch"):
            s = sens[role]
            print(f"  cell 0 {role:8}: "
                  f"{(s['vth'] - 1) * 100 / 2:+.4f} %/mV, "
                  f"{(s['beta'] - 1) * 100:+.4f} %/% beta")
        print(f"  predicted cell sigma: {want_u:.3f} % "
              f"(pre-layout assumption 1.80 %)")

    if a.selftest:
        return selftest(cfg, root, devs, sig, want_u)

    rng = random.Random(a.seed)
    rows = []
    for s in range(a.samples):
        draws = [(rng.gauss(0.0, sv), rng.gauss(0.0, sk)) for sv, sk in sig]
        tag = f"mm_cells_s{s}"
        deck(cfg, root, devs, draws, BUILD / (tag + ".dat"), tag)
        cells = read_cells(BUILD / (tag + ".dat"), n)
        m = metrics(transfer(cells, cfg), bits)
        rows.append({"seed": a.seed + s, "dnl": m["dnl"], "inl": m["inl"],
                     "nonmono": m["nonmono"], "sig": spread(cells)})
        if not a.brief:
            print(f"  sample {s:3d}          : DNL {m['dnl']:.3f} "
                  f"INL {m['inl']:.3f} | spread {spread(cells):.3f} %"
                  f" | nonmono {m['nonmono']}")

    n_s = len(rows)
    dnl = [r["dnl"] for r in rows]
    inl = [r["inl"] for r in rows]
    sg = [r["sig"] for r in rows]
    nonmono = sum(r["nonmono"] for r in rows)

    checks = [
        ("zero-mismatch dDNL", d_dnl < 0.02, f"{d_dnl:.4f} LSB"),
        ("zero-mismatch dINL", d_inl < 0.02, f"{d_inl:.4f} LSB"),
        # 16 samples estimate sigma to ~13 %, so the band is 20 %; a shared
        # draw would collapse it to 0.00 % and a half-sigma draw to half.
        ("spread vs PDK law", abs(sum(sg) / n_s - want_u) < 0.20 * want_u,
         f"{sum(sg) / n_s:.3f} % vs {want_u:.3f} %"),
        # No DEM in P5 by design (binary decode), so this is the converter's
        # actual linearity, not a pointer-averaged one.
        ("fixed DNL", max(dnl) < 0.5, f"{max(dnl):.3f} LSB"),
        ("fixed INL", max(inl) < 1.0, f"{max(inl):.3f} LSB"),
        ("monotonic", nonmono == 0, f"{nonmono} bad samples"),
    ]
    ok = True

    print()
    print(f"post-layout mismatch MC ({a.samples} samples, seed {a.seed}, "
          f"gf180 tt 25 C)")
    print(f"  cell spread         : mean {sum(sg) / n_s:.3f} %, "
          f"{min(sg):.3f} .. {max(sg):.3f} % (law {want_u:.3f} %)")
    print(f"  fixed-pointer DNL   : {min(dnl):.3f} .. {max(dnl):.3f} LSB "
          f"(mean {sum(dnl) / n_s:.3f})")
    print(f"  fixed-pointer INL   : {min(inl):.3f} .. {max(inl):.3f} LSB "
          f"(mean {sum(inl) / n_s:.3f})")
    for name, good, val in checks:
        ok &= good
        print(f"  {name:20}: {val:>14}  {'ok' if good else 'FAIL'}")
    print(f"post-layout mismatch {'PASS' if ok else 'FAIL'}")
    (BUILD / "mismatch.json").write_text(json.dumps(
        {"ok": ok, "samples": a.samples, "seed": a.seed,
         "predicted_sigma_pct": want_u,
         "cell_spread_pct": sg,
         "sensitivity": {r: {"vth_pct_per_mv": (s["vth"] - 1) * 100 / 2,
                             "beta_pct_per_pct": (s["beta"] - 1) * 100}
                         for r, s in sens.items()},
         "zero": {"dnl": m0["dnl"], "inl": m0["inl"]},
         "fixed": {"dnl": dnl, "inl": inl},
         "nonmono": nonmono}, indent=1) + "\n")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
