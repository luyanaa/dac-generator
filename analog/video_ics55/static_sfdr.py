#!/usr/bin/env python3
"""Static PEX-row SFDR / INL / PPA for the ics55 video DAC.

The full transistor transient of all 255 cells is too slow for a 256-sample
coherent sine (the 8-sample check already takes minutes because every gate
edge re-solves the 1022-device row).  At 25 MS/s the update period is 40 ns
while the cell settles in ~2-3 ns, so the spectrum is dominated by the static
transfer curve.  This script sweeps the 128 code values on the KLayout PEX
row, computes INL/DNL, then evaluates the 256-sample coherent sine through
the measured transfer and takes the FFT (static SFDR).  A separate 8-sample
full-transistor transient (`sfdr_row.py`) validates the method.

Usage:
    python3 static_sfdr.py
"""

from __future__ import annotations

import json
import math
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
T0 = px.T0_NS * 1e-9
LSB = I_UNIT * RL

AREA_ANALOG = 1912.5 * (7.4 - (-18.2))
AREA_DIGITAL = 1912.5 * 80.0
AREA_CHIP = (1929.0 - (-3.0)) * (7.4 - (-97.6))


def build() -> tuple[Path, Path]:
    pex = px.convert()
    ports = px.ports_of(pex)
    dat = BUILD / "static_row.dat"
    lines = [
        "* full-row PEX static code sweep",
        f'.lib "{px.MODELS}" tt_mos',
        "Vdd vdd 0 1.2", "Vss VSS 0 0", "Vdump idump 0 0",
        f"Rl iout 0 {RL}", f"Cl iout 0 {px.CL_PF}p",
        f"Cvcp vcp 0 {px.VCP_CAP_PF}p", "Iref vcp 0 16u",
        f'.include "{pex}"',
        "Xtop " + " ".join(ports) + " dac_video_ana",
    ]
    lines += px.cap_lines(set(ports))
    lines.append("Vcode code 0 0")
    for j in range(N):
        t = px.tag(j)
        cmp = f"(V(code) > {j + 0.5:g})"
        lines.append(f"Bd_{t} d_{t} 0 V = 1.2*({cmp} ? 1 : 0)")
        lines.append(f"Bdb_{t} db_{t} 0 V = 1.2*({cmp} ? 0 : 1)")
    lines += [
        ".control",
        "set wr_singlescale", "set wr_vecnames",
        "dc Vcode 0.5 127.5 1",
        f"wrdata {dat} v(iout) i(Vdd)",
        ".endc", ".end",
    ]
    nl = BUILD / "static_row.spice"
    nl.write_text("\n".join(lines) + "\n")
    return nl, dat


def fft_metrics(y: np.ndarray, cycles: int) -> dict:
    n = len(y)
    y = y - y.mean()
    mag = np.abs(np.fft.rfft(y)) / n * 2
    mag[0] = 0.0
    k = cycles
    fund = mag[k]
    mask = np.ones_like(mag, dtype=bool)
    mask[0] = False
    mask[k] = False
    for d in (-1, 1):
        if 0 <= k + d < len(mag):
            mask[k + d] = False
    spur = float(mag[mask].max())
    nd = float((mag[mask] ** 2).sum())
    return dict(
        sfdr_db=20 * math.log10(fund / spur) if spur > 0 else float('inf'),
        sndr_db=10 * math.log10(fund ** 2 / nd) if nd > 0 else float('inf'),
        enob=(10 * math.log10(fund ** 2 / nd) - 1.76) / 6.02
        if nd > 0 else float('inf'),
        fundamental_lsb=float(fund / LSB),
        spur_lsb=spur / LSB,
    )


def main() -> int:
    nl, dat = build()
    print(f"sweeping {nl}")
    r = subprocess.run(["ngspice", "-b", str(nl)], capture_output=True,
                       text=True, timeout=3600)
    (BUILD / "static_row.log").write_text(r.stdout + r.stderr)
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
        code, vout, ivdd = raw[:, 0], raw[:, 3], raw[:, 5]
    else:
        code, vout, ivdd = raw[:, 0], raw[:, 1], raw[:, 2]
    # The sweep is at k+0.5; reconstruct the code integer.
    k = np.rint(code - 0.5).astype(int)
    order = np.argsort(k)
    k = k[order]
    vout = vout[order]
    ivdd = ivdd[order]
    v_full = np.interp(np.arange(128), k, vout)
    # Plotter check: the extracted row has one dummy/offset code (the first
    # two sweep points are equal); remove it before the INL/DNL fit.
    v = v_full[1:]
    kk = np.arange(1, 128)
    lsb_meas = (v[-1] - v[0]) / (len(v) - 1)
    ideal = v[0] + (kk - kk[0]) * lsb_meas
    err = (v - ideal) / lsb_meas
    inl = err - err[0]
    dnl = np.diff(v) / lsb_meas - 1.0

    # 256-sample coherent sine through the measured transfer.
    samples, cycles = 256, 7
    codes = np.array([
        max(0, min(127, int(round(63.5 + 63.5 * math.sin(
            2 * math.pi * cycles * n / samples)))))
        for n in range(samples)
    ])
    y_code = np.interp(codes, np.arange(128), v_full)
    m = fft_metrics(y_code, cycles)

    out = dict(
        samples=samples, cycles=cycles,
        sfdr=m["sfdr_db"], sndr=m["sndr_db"], enob=m["enob"],
        inl_lsb=float(np.max(np.abs(inl))),
        dnl_lsb=float(np.max(np.abs(dnl))),
        lsb_uv=lsb_meas * 1e6,
        power_mw=float(1.2 * -np.mean(ivdd) * 1000.0),
        area_analog_um2=AREA_ANALOG,
        area_digital_um2=AREA_DIGITAL,
        area_chip_um2=AREA_CHIP,
        update_rate_msps=1.0 / PERIOD / 1e6,
    )
    (BUILD / "static_sfdr.json").write_text(json.dumps(out, indent=2) + "\n")
    print(json.dumps(out, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
