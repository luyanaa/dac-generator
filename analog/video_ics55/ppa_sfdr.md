# ics55 video DAC PPA and SFDR (gap 6)

Status: **first full-row PPA/SFDR result; static PEX + dynamic method check.**
The analog row is the 255-cell LVT row (`analog/video_ics55`, KLayout PEX with
the named-net cap stamp, 1022 devices); the digital macro is
`openlane/dac_video_dig_ics55` (H7CR, LVS-clean cell subset, 100 MHz).

## PPA

| item | value | source |
|---|---|---|
| process / supply | ics55 55 nm, 1.2 V core | PDK |
| analog row area | 1912.5 x 25.6 = **48,960 um^2** | `gen_gds.py` bbox (-18.2..7.4) |
| digital macro die / core | **153,000 / 130,861 um^2** | `final/metrics.json` |
| chip area (assembled) | 1932 x 105 = **202,860 um^2** | `assemble_digital.py` bbox |
| analog supply power | **4.919 mW** | `static_sfdr.py` (mean i(VDD) at 1.2 V) |
| digital power | **1.603 mW** total (0.826 internal, 0.770 switching, 0.007 leakage) | `final/metrics.json` (`nom_tt`) |
| total supply power | **~6.52 mW** | sum |
| update rate | **25 MS/s** (40 ns) | video spec |
| LSB / full scale | **600.3 uV** into 37.5 ohm (16 uA/cell); 127-cell full scale **76.2 mV / 2.03 mA** | PEX DC |
| analog settling | **~2-3 ns** (carry transient) | `README.md` |
| digital timing (ss, 1.08 V) | setup WNS **+4.098 ns**, hold WNS +0.454 ns, 0 violations | `final/metrics.json` |
| digital timing (tt, 1.20 V) | setup WNS +5.832 ns, hold WNS +0.123 ns, 0 violations | `final/metrics.json` |
| digital timing (ff, 1.32 V) | setup WNS +6.512 ns, **hold WNS -0.0149 ns, 1 violation** | `final/metrics.json` |

The ff hold violation is 14.9 ps on one endpoint; it needs a hold buffer or a
slightly slower clock before tapeout.  It appeared after the LVS-clean cell
subset (`EXTRA_EXCLUDED_CELLS`) changed the mapping; the ss/tt corners are
clean.

## SFDR / SNDR / ENOB

Method: `static_sfdr.py` sweeps the 128 thermometer codes on the full-row
KLayout PEX netlist, measures the static transfer and then evaluates a
256-sample, 7-cycle coherent sine through that transfer (FFT, rectangular
window).  `sfdr_row.py` is the full-transistor dynamic check; 8 samples takes
minutes because every gate edge re-solves the 1022-device row, so the full
256-sample transient would be ~4 hours and is not used for the reported SFDR.

| metric | value | note |
|---|---|---|
| static PEX INL | **0.010 LSB** | after removing the dummy/offset code |
| static PEX DNL | **0.0003 LSB** | nominal devices, no mismatch |
| **SFDR** | **52.8 dB** | 256-sample, 7-cycle coherent sine |
| **SNDR** | **42.5 dB** | 7-bit quantization-limited (ideal 7-bit SNDR 43.9 dB) |
| **ENOB** | **6.76 bit** | (SNDR - 1.76)/6.02 |
| dynamic 8-sample check | 47.0 dB SFDR | method check only, not a full sine |

The static PEX transfer is essentially ideal: the layout parasitics move the
carry by +0.066 LSB (127->128) and -0.301 LSB (0->255), which is a **dynamic**
(cap-coupled/settling) effect and is not in the DC transfer.  The measured
static SFDR 52.8 dB is therefore an upper bound; the dynamic PEX carry puts
the realistic SFDR in the high-40s to low-50s dB.  A full dynamic number needs
a behavioural current-source model with the PEX per-cell currents and output
RC (the transistor-level 256-sample transient is too slow), or a longer run.

Reproduce:

```sh
cd analog/video_ics55
python3 static_sfdr.py          # build/static_sfdr.json
python3 sfdr_row.py --samples 8 --cycles 3   # method check, build/sfdr_row.json
```

## Caveats

* No device mismatch Monte Carlo: the PEX row uses nominal extracted devices.
  The real SFDR/INL will include cell mismatch (the 8-cell and bias studies
  already bound some of it).
* The digital macro hold at ff needs one buffer; the analog row supply is
  constant-current (4.92 mW) because the tail current is steered to
  `iout`/`idump`.
* The full dynamic SFDR and a mismatch Monte Carlo are the remaining gap-6
  items.
