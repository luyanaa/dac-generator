#!/usr/bin/env python3
"""Exact integer reference model for audiodac_dsmod (2nd-order CIFF path).

Mirrors the RTL arithmetic bit-for-bit (signed fixed point in input LSBs,
1-bit feedback, integrator clamp at +/- 6*2^16) so the DC transfer, volume
map and in-band SNR documented in docs/delta_sigma.md can be reproduced.

    python3 dsmod_model.py          # DC transfer, volume map and SNR table

No third-party packages are required beyond numpy.
"""

import numpy as np

BW = 16
FS = 1 << BW
MID = FS >> 1
LIM = 6 * FS


def _sat(v, lim=LIM):
    return -lim if v < -lim else lim if v > lim else v


def _clamp16(v):
    return 0 if v < 0 else FS - 1 if v > FS - 1 else v


def volume(code, scale):
    """6 dB steps around midscale: 0 = mute, 15 = 0 dB."""
    if scale == 0:
        return MID
    if scale == 15:
        return code
    return _clamp16(((code - MID) >> (15 - scale)) + MID)


def bitstream(sample, n, scale=15):
    """Run n clocks; sample(k) returns the unsigned modulator input."""
    i1 = i2 = 0
    out = np.empty(n, dtype=np.int8)
    peak = 0
    for k in range(n):
        x = volume(sample(k), scale) - MID
        s1 = i1 + x
        y = 1 if s1 + i2 >= 0 else 0
        i1 = _sat(s1 - (MID if y else -MID))
        i2 = _sat(i2 + i1 - (MID if y else -MID))
        out[k] = y
        peak = max(peak, abs(i1), abs(i2))
    return out, peak


def inband_snr(out, fs, tone, n):
    """SNR in 20 Hz..20 kHz excluding the first 10 harmonics."""
    x = out.astype(float) - out.mean()
    p = np.abs(np.fft.rfft(x * np.hanning(n))) ** 2
    f = np.fft.rfftfreq(n, 1 / fs)
    tb = int(np.argmin(abs(f - tone)))
    sig = p[tb - 4:tb + 5].sum()
    mask = (f >= 20) & (f <= 20000)
    for h in range(1, 11):
        hb = int(round(tone * h / (fs / n)))
        if hb < len(p):
            mask[max(0, hb - 4):hb + 5] = False
    return 10 * np.log10(sig / p[mask].sum())


def dc_transfer():
    print("DC transfer (2nd order)")
    for code in (0, 1, 1000, 0x4000, 0x8000, 0xC000, FS - 1000, FS - 2, FS - 1):
        out, _ = bitstream(lambda k, c=code: c, 200_000)
        print(f"  0x{code:04X}  duty={out.mean():.6f}  ideal={code / FS:.6f}")


def volume_map():
    print("volume map (largest positive modulator input 0xFFFF)")
    for scale in (15, 14, 13, 7, 1, 0):
        db = "-inf" if scale == 0 else f"{6 * (15 - scale)}"
        print(f"  scale={scale:2d} (-{db} dB) -> 0x{volume(0xFFFF, scale):04X}")


def snr_table():
    print("sine SNR")
    for osr in (128, 256):
        fs = 48000 * osr
        n = 65536
        amp_list = ((0.45, "-0.9 dBFS"), (0.25, "-6 dBFS"), (0.125, "-12 dBFS"))
        tone = 1000.0
        tb = int(round(tone / fs * n))
        actual = tb * fs / n
        ns = n // osr
        for amp, label in amp_list:
            d = np.clip(
                MID + amp * FS * np.sin(2 * np.pi * actual * (np.arange(ns) * osr) / fs),
                0, FS - 1,
            ).astype(int)
            out, peak = bitstream(lambda k, d=d: int(d[k // osr]), n)
            snr = inband_snr(out, fs, actual, n)
            print(f"  OSR={osr:3d} {label:9s} ({amp:.3f})  SNR={snr:5.1f} dB"
                  f"  max|state|={peak / FS:.2f} FS")


if __name__ == "__main__":
    dc_transfer()
    volume_map()
    snr_table()
