#!/usr/bin/env python3
"""Switch pair + replica cascode bias bench for the current-steering leaf.

Two things are checked here, both at the device level:

  matrix  the replica bias generator over the 5 corners x 3 temperatures.
          It forces Iref through a mirror-sized diode (vbp) and a
          cascode-sized diode (vcp), so the cell mirror copies the same gate
          and the cascode gate is one cascode Vgs below it.  The table reports
          the cell current, vbp/vcp, and the saturation margin of both devices
          (Vds - Vov).  The ideal 1.5 V cascode source used by the earlier cell
          bench is gone: vcp now comes from the bias stack.

  event   one steering transition at tt/25 C.  The differential NMOS pair has
          its tail on the cascode drain, so i(ioutp)+i(idump) must stay at the
          cell current during the crossover.  Reported: Ron, output compliance
          (the cascode's headroom), peak displacement current, the integrated
          charge error on the selected output, and the settling to +-0.5 LSB.

    ./run_switch.py                 matrix + event
    ./run_switch.py matrix
    ./run_switch.py event [corner] [temp]
    ./run_switch.py --brief         machine-readable summary only
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
CORNERS = ["tt", "ff", "ss", "fs", "sf"]
TEMPS = [-40.0, 25.0, 125.0]
I_MIN, I_MAX = 15.5e-6, 16.5e-6
MARGIN_MIN = 0.30
RON_MAX = 800.0
Q_MAX = 25e-15
QSUM_MAX = 5e-15
SETTLE_MAX = 500e-12


def run(cmd):
    return subprocess.run([str(c) for c in cmd], cwd=ROOT,
                          capture_output=True, text=True)


def read_cols(path: Path):
    rows = []
    for line in Path(path).read_text().splitlines():
        p = line.split()
        if len(p) < 2:
            continue
        try:
            rows.append([float(x) for x in p])
        except ValueError:
            continue
    return rows


def parse_print(txt: str) -> dict:
    d = {}
    for m in re.finditer(r"([@a-zA-Z][\w\[\]().@]*)\s*=\s*([-+0-9.eE]+)", txt):
        try:
            d[m.group(1)] = float(m.group(2))
        except ValueError:
            pass
    return d


def bias_point(corner: str, temp: float, pdk: str = "gf180") -> dict:
    out = ROOT / "build" / f"bias_{corner}_{int(temp)}.spice"
    r = run([sys.executable, "gen_csteer.py", "--pdk", pdk, "--bench", "bias",
             "--corner", corner, "--temp", str(temp), "--out", str(out)])
    if r.returncode:
        sys.exit(f"gen bias failed ({corner},{temp}): {r.stderr.strip()}")
    r = run(["ngspice", "-b", str(out)])
    if r.returncode:
        sys.exit(f"ngspice failed ({corner},{temp})")
    d = parse_print(r.stdout)
    if "@m1[id]" not in d:
        sys.exit(f"could not parse the bias operating point ({corner},{temp})")
    d["icell"] = d["@m1[id]"]
    d["Vm"] = d["v(vbp)"]
    d["Vc"] = d["v(vcp)"]
    d["n1"] = d["v(n1)"]
    d["margin_m"] = (3.3 - d["v(n1)"]) - (d["@m1[vgs]"] - d["@m1[vth]"])
    d["margin_c"] = (d["v(n1)"] - d["v(cd)"]) - (
        d["@mcasc[vgs]"] - d["@mcasc[vth]"])
    return d


def matrix(pdk: str, brief: bool) -> bool:
    print(f"{'corner':7} {'T':>4} {'Icell':>8} {'vbp':>6} {'vcp':>6}"
          f" {'m_mir':>6} {'m_cas':>6}  {'ok':>3}")
    ok = True
    for c in CORNERS:
        for t in TEMPS:
            d = bias_point(c, t, pdk)
            good = (I_MIN <= d["icell"] <= I_MAX
                    and d["margin_m"] >= MARGIN_MIN
                    and d["margin_c"] >= MARGIN_MIN)
            ok &= good
            print(f"{c:7} {t:>4.0f} {d['icell'] * 1e6:8.3f}"
                  f" {d['Vm']:6.3f} {d['Vc']:6.3f} {d['margin_m']:6.3f}"
                  f" {d['margin_c']:6.3f}  {'ok' if good else 'BAD':>3}")
    print(f"bias matrix {'PASS' if ok else 'FAIL'}")
    return ok


def event(corner: str = "tt", temp: float = 25.0,
          pdk: str = "gf180") -> bool:
    stem = ROOT / "build" / "switch"
    r = run([sys.executable, "gen_csteer.py", "--pdk", pdk, "--bench", "switch",
             "--corner", corner, "--temp", str(temp), "--dat", str(stem)])
    if r.returncode:
        sys.exit(f"gen switch failed: {r.stderr.strip()}")
    for sp in ("switch_dc.spice", "switch_tran.spice"):
        r = run(["ngspice", "-b", str(ROOT / "build" / sp)])
        if r.returncode:
            sys.exit(f"ngspice failed on {sp}")

    dcs = read_cols(ROOT / "build" / "switch_dc.dat")
    comp = read_cols(ROOT / "build" / "switch_comp.dat")
    trn = read_cols(ROOT / "build" / "switch_tran.dat")

    # Columns: sweep, v(swp), i(Voutp), i(Voutn), v(cd), v(n1).
    # DC crossover: the pair sums to the cell current at every control voltage.
    mid = dcs[len(dcs) // 2]
    icell = mid[2] + mid[3]
    sum_err = max(abs(r[2] + r[3] - icell) for r in dcs) / icell
    on = min(dcs, key=lambda r: abs(r[1] - 3.3))
    ron = on[4] / on[2] if on[2] else float("inf")

    # Output compliance: last point within 1 % of the cell current.
    # Columns: sweep (=v(ioutp)), v(ioutp), i(Voutp), v(cd), v(n1).
    comp_v = 0.0
    for r in comp:
        if abs(r[2] - icell) <= 0.01 * icell:
            comp_v = r[1]
    comp_v = max(comp_v, 0.0)

    # One event: charge error against an ideal step at the gate midpoint,
    # plus charge conservation on the pair.
    t0, t1 = 9.5e-9, 11.5e-9
    ts = 10.0e-9 + 0.5 * 0.2e-9
    q = qsum = 0.0
    peak = 0.0
    cd_exc = 0.0
    settle = None
    for i in range(1, len(trn)):
        t = trn[i][0]
        dt = t - trn[i - 1][0]
        if t0 <= t <= t1:
            ideal = icell if t >= ts else 0.0
            q += (trn[i][4] - ideal) * dt
            qsum += (trn[i][4] + trn[i][5] - icell) * dt
            peak = max(peak, trn[i][4])
            cd_exc = max(cd_exc, abs(trn[i][3]))
        if t > t1:
            break
    # Settling after the rising edge, before the return edge at 50 ns.
    last_bad = None
    for r in trn:
        if 10.2e-9 <= r[0] <= 45e-9 and abs(r[4] - icell) > 0.5e-6:
            last_bad = r[0]
    settle = 0.0 if last_bad is None else last_bad - 10.2e-9

    ok = True
    checks = [
        ("dc sum error", sum_err < 0.01, f"{sum_err * 100:.3f} %"),
        ("switch Ron", ron < RON_MAX, f"{ron:.0f} ohm"),
        ("output compliance", comp_v > 1.5, f"{comp_v:.2f} V"),
        ("event charge error", abs(q) < Q_MAX, f"{q * 1e15:.1f} fC"),
        ("pair charge error", abs(qsum) < QSUM_MAX, f"{qsum * 1e15:.1f} fC"),
        ("settle to 0.5 LSB", settle is not None and settle < SETTLE_MAX,
         f"{settle * 1e12:.0f} ps" if settle is not None else "n/a"),
    ]
    print(f"switch event ({corner}, {temp:g} C, Icell {icell * 1e6:.3f} uA)")
    print(f"  peak displacement   : {peak * 1e6:.1f} uA")
    print(f"  cascode drain swing : {cd_exc * 1e3:.1f} mV")
    for name, good, val in checks:
        ok &= good
        print(f"  {name:20}: {val:>12}  {'ok' if good else 'FAIL'}")
    print(f"switch event {'PASS' if ok else 'FAIL'}")
    return ok


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("what", nargs="?", default="all",
                    choices=["all", "matrix", "event"])
    ap.add_argument("--pdk", default="gf180", choices=["gf180", "sky130"])
    ap.add_argument("--brief", action="store_true")
    ap.add_argument("--corner", default="tt")
    ap.add_argument("--temp", type=float, default=25.0)
    a = ap.parse_args()
    if a.pdk != "gf180":
        sys.exit("switch/bias benches are only modelled on gf180 here")
    ok = True
    if a.what in ("all", "matrix"):
        ok &= matrix(a.pdk, a.brief)
    if a.what in ("all", "event"):
        ok &= event(a.corner, a.temp, a.pdk)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
