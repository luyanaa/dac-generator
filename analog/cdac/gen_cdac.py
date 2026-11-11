#!/usr/bin/env python3
"""8-bit differential binary CDAC leaf: sizing model + device C(V) bench.

Two benches, one physical model:

  --bench unit   AC C(V) sweep of the sky130 moscap unit cell on the
                 flattened corner deck.  This is the measurement the model
                 consumes; it must reproduce cdac.yaml before the model's
                 numbers mean anything.

  --bench model  charge-redistribution transfer of the differential binary
                 array, 2^N codes, from the measured C(V) curve (or a flat
                 MIM/ideal cap) plus a Pelgrom per-unit mismatch.  Reports
                 DNL/INL, kT/C, settling and comparator noise.

Why the model is charge based and not "C_u * code": a MOSCAP is not a
constant.  Its capacitance moves 2.67 -> 5.02 fF over the +-0.9 V a
bottom-plate array actually applies, and the top plate is floating, so the
capacitance and the top-plate voltage solve each other:

    Q_sample = sum_k C_k(Vcm - Vbot_k)              (top plate held at Vcm)
    Vtop     = (Q_sample + sum_k C_k(Vtop-Vbot_k)*Vbot_k)
               / sum_k C_k(Vtop-Vbot_k)

That fixed point is iterated per code.  A constant-capacitance model is kept
as the control: with `--cap const --mismatch 0` the transfer must be exactly
linear, which is the bench's self-check.

    ./gen_cdac.py --bench unit
    ./gen_cdac.py --bench model --cap moscap --mismatch 0.00295
    ./gen_cdac.py --bench model --cap mim --seeds 20
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import os
import random
import re
import statistics
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent

# sky130 1.8 V core devices are subcircuits, not .model cards: instantiate
# with X, not M.
CAP_LEAF = """.subckt CDAC_CAP_UNIT VSH FL VNW VPW
XN0 FL VSH FL VPW sky130_fd_pr__nfet_01v8 w={wn:g}u l={l:g}u nf=1
XP0 FL VSH FL VNW sky130_fd_pr__pfet_01v8 w={wp:g}u l={l:g}u nf=1
.ends
"""

ROW = re.compile(r"^\s*\d+\s+([-\d.eE+]+)\s+([-\d.eE+]+),\s*([-\d.eE+]+)\s*$")
FREQ = 1.0e6


def load_cfg(path=None) -> dict:
    import yaml
    with open(path or ROOT / "cdac.yaml") as fh:
        return yaml.safe_load(fh)


# --------------------------------------------------------------------------
# capacitor models
# --------------------------------------------------------------------------

class CapModel:
    """Unit capacitance as a function of the voltage across the unit."""

    def __init__(self, cfg: dict, kind: str):
        self.kind = kind
        if kind == "moscap":
            curve = cfg["c_ff_vs_vdiff"]
            self.points = sorted((float(k), float(v)) for k, v in curve.items())
        elif kind == "mim":
            self.points = None
            self.flat = float(cfg.get("mim_cu_ff", 8.0))
        elif kind == "const":
            self.points = None
            self.flat = float(cfg["cu_ff"])
        else:
            raise SystemExit(f"unknown cap backend {kind!r}")
        self.area = float(cfg.get("cu_area_um2", 0.63))
        # 2-D small-signal tables (fF) on a (Vg,Vb) grid.  The well is fixed,
        # so a 3-terminal MOSCAP is not described by C(Vg-Vb): the top-plate
        # charge is a state function of both plates, with Cgg = dQg/dVg and
        # Cgb = dQg/dVb (both measured by .ac, see measure_c2.py).  The device
        # charge is path independent, but the .ac matrix is only symmetric,
        # not integrable (BSIM4 charge non-conservation), so Q is built along
        # one explicit path - see the qb loop below.
        self.q_grid = None
        tab_g = cfg.get("cgg_ff_vs_vg_vb")
        tab_b = cfg.get("cgb_ff_vs_vg_vb")
        if kind == "moscap" and tab_g and tab_b:
            self.q_vg = [float(v) for v in tab_g["vg"]]
            self.q_vb = [float(v) for v in tab_g["vb"]]
            self.cgg = [[float(v) for v in row] for row in tab_g["c_ff"]]
            self.cgb = [[float(v) for v in row] for row in tab_b["c_ff"]]
            nv, nb = len(self.q_vg), len(self.q_vb)
            qg = [[0.0] * nv for _ in range(nb)]
            for j in range(nb):
                acc = 0.0
                for i in range(1, nv):
                    acc += 0.5 * (self.cgg[j][i - 1] + self.cgg[j][i]) \
                        * (self.q_vg[i] - self.q_vg[i - 1])
                    qg[j][i] = acc
            # The .ac capacitance matrix is symmetric but not exactly
            # integrable (BSIM4 charge non-conservation), so Q has to be
            # built along ONE path.  Use the vg integral at fixed vb plus
            # the vb integral at vg=0:
            #   Q(vg,vb) = int_0^vg Cgg(u,vb)du + int_0^vb Cgb(0,w)dw
            # Each 1-D integral is verified against a device transient ramp
            # to <0.01 fC (see xcheck_mos.py --ramps).
            qb = [[0.0] * nv for _ in range(nb)]
            acc = 0.0
            for j in range(1, nb):
                acc += 0.5 * (self.cgb[j - 1][0] + self.cgb[j][0]) \
                    * (self.q_vb[j] - self.q_vb[j - 1])
                for i in range(nv):
                    qb[j][i] = acc
            self.q_mat = [[qg[j][i] + qb[j][i] for i in range(nv)]
                          for j in range(nb)]
            self.q_grid = True

    def c(self, vdiff: float) -> float:
        if self.points is None:
            return self.flat
        xs = self.points
        if vdiff <= xs[0][0]:
            return xs[0][1]
        if vdiff >= xs[-1][0]:
            return xs[-1][1]
        for (a, ca), (b, cb) in zip(xs, xs[1:]):
            if a <= vdiff <= b:
                t = (vdiff - a) / (b - a)
                return ca + t * (cb - ca)
        return xs[-1][1]

    def _bilinear(self, mat, vg: float, vb: float) -> float:
        vg = min(max(vg, self.q_vg[0]), self.q_vg[-1])
        vb = min(max(vb, self.q_vb[0]), self.q_vb[-1])

        def find(xs, v):
            for i in range(len(xs) - 1):
                if xs[i] <= v <= xs[i + 1]:
                    return i, (v - xs[i]) / (xs[i + 1] - xs[i])
            return len(xs) - 2, 1.0

        i, tx = find(self.q_vg, vg)
        j, ty = find(self.q_vb, vb)
        m00 = mat[j][i]
        m10 = mat[j][i + 1]
        m01 = mat[j + 1][i]
        m11 = mat[j + 1][i + 1]
        return ((1 - tx) * (1 - ty) * m00 + tx * (1 - ty) * m10
                + (1 - tx) * ty * m01 + tx * ty * m11)

    def charge(self, vg: float, vb: float) -> float:
        """Top-plate charge (fC) at (Vgate, Vbottom)."""
        if self.q_grid is None:
            if self.points is None:
                return self.flat * (vg - vb)
            # fall back to the 1-D differential table, integrated at fixed vb
            return self.q(vg - vb)
        return self._bilinear(self.q_mat, vg, vb)

    def dcharge(self, vg: float, vb: float) -> float:
        """dQ/dVg (fF) at (Vg,Vb)."""
        if self.q_grid is None:
            return self.flat if self.points is None else self.c(vg - vb)
        return self._bilinear(self.cgg, vg, vb)

    def q(self, v: float) -> float:
        """Charge per unit: Q(v) = integral_0^v C(u) du (fF*V).

        The C(V) curve is a *differential* capacitance from an ac run, so the
        charge is its integral, not C(V)*V.  The piecewise-linear curve is
        integrated exactly (trapezoids), with the endpoint value held outside
        the measured range.
        """
        if self.points is None:
            return self.flat * v
        if v == 0.0:
            return 0.0
        a, b = (0.0, v) if v > 0 else (v, 0.0)
        xs = [a] + [x for x, _ in self.points if a < x < b] + [b]
        q = 0.0
        for x0, x1 in zip(xs, xs[1:]):
            q += 0.5 * (self.c(x0) + self.c(x1)) * (x1 - x0)
        return q if v > 0 else -q

    def sigma_rel(self, cfg: dict) -> float:
        """Pelgrom sigma_C/C for one unit of this backend."""
        if self.kind == "mim":
            ac = float(cfg.get("mim_ac_pct_um", 0.3))
            area = float(cfg.get("mim_area_um2", 4.0))
        else:
            ac = float(cfg["a_c_pct_um"])
            area = self.area
        return ac / 100.0 / math.sqrt(area)


def unit_factors(cfg: dict, cap: CapModel, sigma: float, seed: int,
                 n_units: int):
    """Per-unit multiplicative gain errors, one draw per physical unit."""
    if sigma <= 0.0:
        return [1.0] * n_units
    rnd = random.Random(seed)
    return [1.0 + rnd.gauss(0.0, sigma) for _ in range(n_units)]


# --------------------------------------------------------------------------
# charge-redistribution transfer
# --------------------------------------------------------------------------

def side_top(cfg: dict, cap: CapModel, code: int, invert: bool,
             factors, nbits: int, vh: float, vl: float, vcm: float,
             vin: float, dummy_mode: str, vref_dummy: float,
             vdiff_pad: float = 1e-13) -> tuple[float, float]:
    """Solve one side's floating top-plate voltage for `code`.

    Returns (Vtop, conversion-time total capacitance in fF).  The dummy unit's
    bottom plate is hardwired (to Vcm by default); the switched bits sample
    `vin` and then move to VREFH/VREFL.
    """
    bots: list[float] = []
    sample: list[float] = []
    gains: list[float] = []
    idx = 0
    for k in range(nbits):
        bit = (code >> k) & 1
        if invert:
            bit ^= 1
        vb = vh if bit else vl
        for _ in range(1 << k):
            bots.append(vb)
            sample.append(vin)
            gains.append(factors[idx])
            idx += 1
    dummy_vb = vcm if dummy_mode == "vcm" else vref_dummy
    bots.append(dummy_vb)
    sample.append(dummy_vb)
    gains.append(factors[idx])
    assert idx + 1 == (1 << nbits), (idx, nbits)

    # sampling: top plate held at Vcm; charge on the floating node.  With the
    # 2-D table this is the device gate charge Q(Vg,Vb), not C(V)*V.
    q = 0.0
    for s, g in zip(sample, gains):
        q += g * cap.charge(vcm, s)

    # conversion: solve sum_k Q_k(Vtop - Vbot_k) = Q_sample.  Q is monotonic
    # in Vtop, so Newton on F(V) = sum Q - q converges in a few steps.
    vtop = vcm
    for _ in range(60):
        f = -q
        df = 0.0
        for vb, g in zip(bots, gains):
            f += g * cap.charge(vtop, vb)
            df += g * cap.dcharge(vtop, vb)
        if abs(df) < 1e-15:
            break
        nv = vtop - f / df
        if abs(nv - vtop) < vdiff_pad:
            vtop = nv
            break
        vtop = nv
    den = 0.0
    for vb, g in zip(bots, gains):
        den += g * cap.c(vtop - vb)
    return vtop, den


def differential(cfg: dict, cap: CapModel, code: int, factors,
                 nbits: int) -> tuple[float, float, float]:
    vh = float(cfg["vrefh"])
    vl = float(cfg["vrefl"])
    vcm = float(cfg["vcm"])
    vin = float(cfg.get("vin_dc", vcm))
    dm = str(cfg.get("dummy_mode", "vcm"))
    vdummy = float(cfg.get("vrefl", 0.0))
    p, den_p = side_top(cfg, cap, code, False, factors, nbits, vh, vl, vcm,
                        vin, dm, vdummy)
    n, den_n = side_top(cfg, cap, code, True, factors, nbits, vh, vl, vcm,
                        vin, dm, vdummy)
    return p - n, den_p, den_n


def fit(vals: list[float]) -> tuple[float, list[float], list[float]]:
    """Endpoint fit.  Returns (lsb, dnl, inl) in LSB."""
    vmin, vmax = vals[0], vals[-1]
    lsb = (vmax - vmin) / (len(vals) - 1)
    inl = [(v - vmin) / lsb - i for i, v in enumerate(vals)]
    dnl = [0.0] * len(vals)
    for i in range(1, len(vals)):
        dnl[i] = (vals[i] - vals[i - 1]) / lsb - 1.0
    return lsb, dnl, inl


def summarise(label: str, vals: list[float], brief: bool) -> dict:
    lsb, dnl, inl = fit(vals)
    mono = all(d >= -1.0 for d in dnl[1:])
    res = {"lsb_v": lsb, "dnl": dnl, "inl": inl, "monotonic": mono}
    if brief:
        print(f"DNL_{label} {min(dnl[:-1] if len(dnl) > 1 else dnl):+.6f} "
              f"{max(dnl):+.6f}")
        print(f"INL_{label} {min(inl):+.6f} {max(inl):+.6f}")
    else:
        print(f"-- {label}")
        print(f"   LSB       : {lsb*1e3:.4f} mV")
        print(f"   DNL       : {min(dnl[1:]):+.3f} .. {max(dnl[1:]):+.3f} LSB")
        print(f"   INL       : {min(inl):+.3f} .. {max(inl):+.3f} LSB")
        print(f"   monotonic : {'yes' if mono else 'no'}")
    return res


# --------------------------------------------------------------------------
# unit device bench
# --------------------------------------------------------------------------

def find_pdk_root(cfg: dict) -> Path:
    env = os.environ.get("PDK_ROOT")
    cands = []
    if env:
        cands.append(Path(env).expanduser())
    ver = cfg.get("pdk", {}).get("sky130", {}).get("version")
    if ver:
        cands.append(Path.home() / ".ciel/ciel/sky130/versions" / ver)
    cands += sorted((Path.home() / ".ciel/ciel/sky130/versions").glob("*"),
                    reverse=True)
    for p in cands:
        if (p / "sky130A/libs.tech/ngspice/corners/tt.spice").is_file():
            return p
    raise SystemExit("no sky130A install found; set PDK_ROOT")


def ensure_deck(cfg: dict) -> Path:
    pdk = find_pdk_root(cfg)
    deck = ROOT / "build" / "sky130_tt.spice"
    corner = pdk / "sky130A/libs.tech/ngspice/corners/tt.spice"
    if deck.is_file() and deck.stat().st_mtime >= corner.stat().st_mtime:
        return deck
    r = subprocess.run([sys.executable, str(ROOT / "deck_sky130.py"),
                        "--corner-index", str(corner), "--out", str(deck)],
                       capture_output=True, text=True)
    if r.returncode:
        sys.exit(f"deck build failed: {r.stderr.strip()}")
    print(r.stdout.strip())
    return deck


def ngspice(netlist: str, workdir: Path) -> str:
    path = workdir / "unit.sp"
    path.write_text(netlist)
    r = subprocess.run(["ngspice", "-b", str(path)], cwd=workdir,
                       capture_output=True, text=True, timeout=600)
    if r.returncode:
        raise SystemExit(f"ngspice failed: {r.stderr[-800:]}")
    return r.stdout + r.stderr


def cap_from_log(log: str) -> float:
    for line in log.splitlines():
        m = ROW.match(line)
        if m:
            return abs(float(m.group(3))) / (2 * math.pi * FREQ) * 1e15
    raise SystemExit("no AC current row in ngspice output")


def unit_netlist(cfg: dict, deck: Path, vdiff: float) -> str:
    vcm = float(cfg["vcm"])
    geom = (f"wn={cfg['cu_wn_um']:g} wp={cfg['cu_wp_um']:g} "
            f"l={cfg['cu_l_um']:g}")
    leaf = CAP_LEAF.format(wn=cfg["cu_wn_um"], wp=cfg["cu_wp_um"],
                           l=cfg["cu_l_um"])
    return f"""* CDAC unit cap C(V), sky130, flattened deck
{leaf}.include {deck}
Vg vsh 0 dc {vcm:.6f} ac 1
Vb fl 0 dc {vcm - vdiff:.6f}
Vnw vnw 0 dc {vcm * 2:.6f}
Vpw vpw 0 dc 0
Xc vsh fl vnw vpw CDAC_CAP_UNIT
.ac lin 1 {FREQ:g} {FREQ:g}
.print ac i(vg)
.end
"""


def bench_unit(cfg: dict, brief: bool) -> int:
    deck = ensure_deck(cfg)
    curve = {float(k): float(v) for k, v in cfg["c_ff_vs_vdiff"].items()}
    points = sorted(set(curve) | {-0.9, 0.9})
    worst = 0.0
    with tempfile.TemporaryDirectory(prefix="cdac_unit_") as tmp:
        tmp = Path(tmp)
        for v in points:
            c = cap_from_log(ngspice(unit_netlist(cfg, deck, v), tmp))
            ref = curve.get(v)
            err = "" if ref is None else f"  yaml {ref:7.4f}  " \
                                        f"({(c-ref)/ref*100:+.2f}%)"
            if ref:
                worst = max(worst, abs((c - ref) / ref))
            print(f"vdiff {v:+.1f} V : C {c:7.4f} fF{err}")
    if not brief:
        print(f"worst deviation from cdac.yaml: {worst*100:.3f}%")
    return 0 if worst < 0.02 else 1


# --------------------------------------------------------------------------
# model bench
# --------------------------------------------------------------------------

def budget(cfg: dict, cap: CapModel, nbits: int) -> dict:
    nu = 1 << nbits
    c_u = cap.c(0.0)
    c_tot = nu * c_u * 1e-15
    kT = 1.380649e-23 * (float(cfg.get("temp_c", 27.0)) + 273.15)
    sig_v = math.sqrt(2.0 * kT / c_tot)          # differential, two sides
    vfs = abs(float(cfg["vrefh"]) - float(cfg["vrefl"]))
    lsb = vfs / nu
    ron = float(cfg["tg_ron_ohm"])
    c_msb = (nu // 2) * c_u * 1e-15
    tau_msb = ron * c_msb * (c_tot - c_msb) / c_tot
    t_set = tau_msb * (nbits + 1) * math.log(2.0)
    tau_smp = ron * c_tot
    t_smp = tau_smp * (nbits + 1) * math.log(2.0)
    t_cmp = float(cfg.get("cmp_delay_ns", 0.101)) * 1e-9
    t_conv = nbits * (t_set + t_cmp) + t_smp
    fs = 1.0 / t_conv if t_conv else float("inf")
    return {
        "c_unit_ff": c_u, "c_tot_ff": c_tot * 1e15, "lsb_v": lsb,
        "ktc_diff_uv": sig_v * 1e6, "ktc_lsb": sig_v / lsb,
        "cmp_noise_uv": float(cfg.get("cmp_sigma_uv", 0.0)),
        "cmp_noise_lsb": float(cfg.get("cmp_sigma_uv", 0.0)) / lsb * 1e-6,
        "t_settle_ns": t_set * 1e9, "t_sample_ns": t_smp * 1e9,
        "t_conv_ns": t_conv * 1e9, "fs_max_hz": fs,
    }


def bench_model(cfg: dict, a) -> int:
    nbits = int(cfg.get("bits", 8))
    nu = 1 << nbits
    cap = CapModel(cfg, a.cap)
    if a.mismatch is None:
        sigma = cap.sigma_rel(cfg)      # backend's Pelgrom by default
    else:
        sigma = a.mismatch               # 0 = ideal control

    codes = range(nu)
    seeds = a.seeds if sigma > 0 else 1
    all_dnl, all_inl = [], []
    first = None
    for seed in range(1, seeds + 1):
        factors = unit_factors(cfg, cap, sigma, seed, nu)
        vals = [differential(cfg, cap, c, factors, nbits)[0] for c in codes]
        res = summarise(f"seed{seed}" if seeds > 1 else a.cap, vals,
                        brief=a.brief and seeds == 1)
        if first is None:
            first = (vals, res)
        all_dnl.append(res["dnl"][1:])
        all_inl.append(res["inl"])

    if seeds > 1:
        dnl_lo = min(min(d) for d in all_dnl)
        dnl_hi = max(max(d) for d in all_dnl)
        inl_w = [max(abs(x) for x in d) for d in all_inl]
        if a.brief:
            print(f"DNL_seeds {dnl_lo:+.6f} {dnl_hi:+.6f}")
            print(f"INL_seeds {-max(inl_w):+.6f} {max(inl_w):+.6f}")
        else:
            print(f"\n{seeds} seeds, sigma_C/C = {sigma*100:.4f}% per unit")
            print(f"   DNL worst : {dnl_lo:+.3f} .. {dnl_hi:+.3f} LSB")
            print(f"   INL worst : {max(inl_w):.3f} LSB (mean "
                  f"{statistics.mean(inl_w):.3f})")

    b = budget(cfg, cap, nbits)
    if not a.brief:
        print("\n-- budget (nominal, C at vdiff = 0)")
        print(f"   C_unit    : {b['c_unit_ff']:.3f} fF   Ctot "
              f"{b['c_tot_ff']:.1f} fF")
        print(f"   kT/C      : {b['ktc_diff_uv']:.2f} uV rms "
              f"({b['ktc_lsb']*1e3:.2f} mLSB, differential)")
        print(f"   comparator: {b['cmp_noise_uv']:.1f} uV rms "
              f"({b['cmp_noise_lsb']*1e3:.2f} mLSB)")
        print(f"   settling  : {b['t_settle_ns']:.2f} ns/bit, sample "
              f"{b['t_sample_ns']:.2f} ns, convert {b['t_conv_ns']:.2f} ns")
        print(f"   fs_max    : {b['fs_max_hz']/1e6:.2f} MS/s")

    # artifacts: first seed's transfer plus the budget
    out_csv = ROOT / "build" / f"model_{a.cap}.csv"
    vals, res = first
    with open(out_csv, "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["code", "vd_v", "inl_lsb", "dnl_lsb"])
        for c in codes:
            w.writerow([c, f"{vals[c]:.12g}", f"{res['inl'][c]:.6f}",
                        f"{res['dnl'][c]:.6f}"])
    meta = {"cap": a.cap, "bits": nbits, "sigma_rel": sigma,
            "vrefh": cfg["vrefh"], "vrefl": cfg["vrefl"], "vcm": cfg["vcm"],
            "dummy_mode": cfg.get("dummy_mode", "vcm"),
            "dnl": [min(min(d) for d in all_dnl), max(max(d) for d in all_dnl)],
            "inl": [min(min(d) for d in all_inl), max(max(d) for d in all_inl)],
            "budget": b}
    out_json = ROOT / "build" / f"model_{a.cap}.json"
    out_json.write_text(json.dumps(meta, indent=1))
    # convenience copy of the most recent run
    (ROOT / "build" / "model.csv").write_bytes(out_csv.read_bytes())
    (ROOT / "build" / "model.json").write_text(out_json.read_text())
    if not a.brief:
        print(f"\nwrote {out_csv} and {out_json}")
    return 0


# --------------------------------------------------------------------------

def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--bench", choices=["unit", "model"], required=True)
    ap.add_argument("--cap", choices=["moscap", "mim", "const"],
                    default="moscap")
    ap.add_argument("--mismatch", type=float, default=None,
                    help="per-unit sigma_C/C; default = the backend's Pelgrom")
    ap.add_argument("--seeds", type=int, default=1)
    ap.add_argument("--brief", action="store_true")
    ap.add_argument("--config", default=None)
    a = ap.parse_args(argv)

    cfg = load_cfg(a.config)
    if a.bench == "unit":
        return bench_unit(cfg, a.brief)
    return bench_model(cfg, a)


if __name__ == "__main__":
    sys.exit(main())
