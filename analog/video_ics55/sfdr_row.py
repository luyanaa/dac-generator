#!/usr/bin/env python3
"""Full-row ics55 DAC SFDR / PPA from the KLayout PEX row.

The row netlist is the KLayout LVS extraction with the named-net cap stamp
from `pex_row.py` (`build/row_pex_x.cir`).  A coherent 7-bit sine code is
thermometer-decoded onto the 255 cell gate pairs with behavioural sources,
the output is sampled once per 40 ns update, and the FFT gives SFDR / SNDR /
ENOB.  The same run reports area, average supply power and update rate.

Usage:
    python3 sfdr_row.py                 # 256 samples, 7 cycles
    python3 sfdr_row.py --samples 64 --cycles 7
"""

from __future__ import annotations

import argparse
import json
import math
import re
import subprocess
from pathlib import Path

import numpy as np

import pex_row as px

HERE = Path(__file__).resolve().parent
BUILD = HERE / "build"
N = px.N
I_UNIT = px.I_UNIT_UA * 1e-6
RL = px.RL
PERIOD = px.PERIOD_NS * 1e-9
EDGE = px.EDGE_PS * 1e-12
T0 = px.T0_NS * 1e-9

# Layout areas (um^2)
AREA_ANALOG = 1912.5 * (7.4 - (-18.2))
AREA_DIGITAL = 1912.5 * 80.0
AREA_CHIP = (1929.0 - (-3.0)) * (7.4 - (-97.6))


def build_netlist(samples: int, cycles: int, path: Path) -> tuple[Path, Path]:
    pex = px.convert()
    ports = px.ports_of(pex)
    dat = BUILD / "sfdr_row.dat"
    lines = [
        "* full-row PEX coherent sine",
        f'.lib "{px.MODELS}" tt_mos',
        "Vdd vdd 0 1.2", "Vss VSS 0 0", "Vdump idump 0 0",
        f"Rl iout 0 {RL}", f"Cl iout 0 {px.CL_PF}p",
        f"Cvcp vcp 0 {px.VCP_CAP_PF}p", "Iref vcp 0 16u",
        f'.include "{pex}"',
        "Xtop " + " ".join(ports) + " dac_video_ana",
    ]
    lines += px.cap_lines(set(ports))

    # Coherent sine code 0..127 (7-bit thermometer, 127 of 255 cells).
    codes = []
    for n in range(samples):
        c = 63.5 + 63.5 * math.sin(2 * math.pi * cycles * n / samples)
        codes.append(max(0, min(127, int(round(c)))))

    # One code node steps at the sample boundary; B-sources compare it with
    # each cell index and drive the differential gate pair.
    # Each cell gate is an explicit PWL source: hold code[n], step at the
    # sample boundary with a finite edge.  This is much better conditioned
    # than a behavioural comparator with abrupt code steps.
    edge = 200e-12
    for j in range(N):
        t = px.tag(j)
        vals = [1.2 if j < c else 0.0 for c in codes]
        def pwl(vs):
            pts = [f"0 {vs[0]:g}"]
            for n in range(samples - 1):
                tb = T0 + (n + 1) * PERIOD
                pts.append(f"{tb - edge:.9g} {vs[n]:g}")
                pts.append(f"{tb:.9g} {vs[n + 1]:g}")
            tend = T0 + samples * PERIOD
            pts.append(f"{tend - edge:.9g} {vs[-1]:g}")
            pts.append(f"{tend:.9g} {vs[-1]:g}")
            return "PWL(" + " ".join(pts) + ")"
        lines.append(f"Vd_{t} d_{t} 0 {pwl(vals)}")
        lines.append(f"Vdb_{t} db_{t} 0 {pwl([1.2 - x for x in vals])}")

    lines += [
        ".control",
        "set wr_singlescale", "set wr_vecnames",
        f"tran 200p {T0 + samples * PERIOD + 100e-9:.9g}",
        f"wrdata {dat} v(iout) i(Vdd)",
        ".endc", ".end",
    ]
    path.write_text("\n".join(lines) + "\n")
    return path, dat


def fft_metrics(y: np.ndarray, cycles: int) -> dict:
    n = len(y)
    y = y - y.mean()
    spec = np.fft.rfft(y)
    mag = np.abs(spec) / n * 2
    mag[0] = 0.0
    k = cycles
    fund = mag[k]
    # ignore DC, the fundamental and its nearest leakage bins
    mask = np.ones_like(mag, dtype=bool)
    mask[0] = False
    mask[k] = False
    for d in (-1, 1):
        if 0 <= k + d < len(mag):
            mask[k + d] = False
    spur = float(mag[mask].max()) if mask.any() else 0.0
    # SNDR: signal power over all remaining bins (noise + distortion)
    sig = fund ** 2
    nd = float((mag[mask] ** 2).sum())
    sfdr = 20 * math.log10(fund / spur) if spur > 0 else float('inf')
    sndr = 10 * math.log10(sig / nd) if nd > 0 else float('inf')
    enob = (sndr - 1.76) / 6.02
    return dict(sfdr_db=sfdr, sndr_db=sndr, enob=enob,
                fundamental_v=float(fund), spur_v=spur)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--samples", type=int, default=256)
    ap.add_argument("--cycles", type=int, default=7)
    ap.add_argument("--keep", action="store_true")
    a = ap.parse_args()
    samples = a.samples
    cycles = a.cycles
    if math.gcd(samples, cycles) != 1:
        raise SystemExit("samples and cycles must be coprime for coherent sampling")

    nl, dat = build_netlist(samples, cycles, BUILD / "sfdr_row.spice")
    print(f"running ngspice: {nl}")
    r = subprocess.run(["ngspice", "-b", str(nl)], capture_output=True,
                       text=True, timeout=7200)
    (BUILD / "sfdr_row.log").write_text(r.stdout + r.stderr)
    if r.returncode:
        print(r.stdout[-2000:])
        print(r.stderr[-2000:])
        return 1

    data = []
    for ln in dat.read_text().splitlines():
        f = ln.split()
        if len(f) < 3:
            continue
        try:
            data.append([float(x) for x in f])
        except ValueError:
            continue
    raw = np.asarray(data)
    if raw.shape[1] >= 6:
        t, vout, ivdd = raw[:, 0], raw[:, 3], raw[:, 5]
    else:
        t, vout, ivdd = raw[:, 0], raw[:, 1], raw[:, 2]

    # sample at the end of each hold window (5 ns before the next edge)
    ts = T0 + (np.arange(samples) + 1) * PERIOD - 5e-9
    y = np.interp(ts, t, vout)
    i = np.interp(ts, t, ivdd)
    m = fft_metrics(y, cycles)
    lsb = I_UNIT * RL
    out = dict(samples=samples, cycles=cycles)
    out.update(
        sfdr=m["sfdr_db"], sndr=m["sndr_db"], enob=m["enob"],
        fundamental_lsb=m["fundamental_v"] / lsb,
        spur_lsb=m["spur_v"] / lsb,
        power_mw=float(1.2 * -i.mean() * 1000.0),
        area_analog_um2=AREA_ANALOG,
        area_digital_um2=AREA_DIGITAL,
        area_chip_um2=AREA_CHIP,
        update_rate_msps=1.0 / PERIOD / 1e6,
        lsb_uv=lsb * 1e6,
    )
    (BUILD / "sfdr_row.json").write_text(json.dumps(out, indent=2) + "\n")
    print(json.dumps(out, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
