# ICsprout55 video DAC: cell study and next step

Status 2026-11-12: **the device-level cell passes the P5 carry gate and the
single-cell layout closes LVS and the partial DRC.**  The three recorded
blockers are down to one:

| blocker | state |
|---|---|
| models "HSPICE-only" | **cleared** — `libs.tech/spice/foundry/ngspice` parses in ngspice 44, `mismod=0`, deterministic |
| PCell S/D short | **cleared** — fixed in `icsprout55-pdk` `b756fc8`; LVS extracts one device per finger group and passes |
| DRC deck partial | **open** — 49 KLayout categories against 679 vendor rules; the device rules are checked by hand against the vendor ids (see `docs/ics55_pdk_repair.md`) |

## Cell study (device level, no parasitics)

`analog/video/pdk_cell.py ics55` now runs the same P5 method as gf180/IHP:
255 unit cells + diode-connected replica, 37.5 ohm and 2 pF load, 20 ps edge,
25 ps bit skew, 40 ns period.  The ics55 entry uses the 1.2 V core devices
(`pm1p2_svt_lp` / `nm1p2_svt_lp`) with mirror 8/1, cascode 8/0.5, pair 4/0.28:

```
ics55: vdd 1.2 V, mirror (8.0, 1.0), cascode (8.0, 0.5), pair (4.0, 0.28)
  127 -> 128:   127.953 LSB (err   -0.047), settle  2.03 ns, dvbp  -0.00 mV, dvcp  -0.00 mV
    0 -> 255:   254.561 LSB (err   -0.439), settle  2.41 ns, dvbp  +0.12 mV, dvcp  +0.30 mV
  dc: vbp 0.6134 V, vcp 0.0196 V, mirror drain 0.6146 V, tail 0.0836 V
ics55: PASS  (worst 0.439 LSB, bias 0.30 mV)
```

That is the first ics55 DAC result: carry inside 0.05 LSB, full scale inside
0.44 LSB, bias excursion 0.3 mV, settling 2.4 ns at 25 MS/s.

One design note for the layout/wrapper: at 1.2 V the replica forces
`vcp = Vdd - Vsg(mirror) - Vsg(cascode) = 19.6 mV`, i.e. the cascode gate is
almost at ground.  It works (the cascode still has Vsd ~0.53 V) and the bias
excursion is tiny, but generating a 20 mV bias line is awkward.  Sizing
sweep at the same 16 uA/cell (`--op-only`):

| mirror | cascode | vbp | vcp |
|---|---|---|---|
| 8/1 | 8/0.5 | 0.613 | **0.020** |
| 32/1 | 16/0.5 | 0.726 | 0.191 |
| 32/1 | 32/0.5 | 0.726 | 0.230 |
| 64/1 | 32/0.5 | 0.766 | 0.274 |

Wider devices buy bias headroom at area cost; a wide-swing cascode bias
branch is the other option.  Decide before the row is wired to a shared
bias generator.

## What the PCell gives now

`libs.tech/klayout/pcells/ics55_mos_analog.py` (PDK commit `b756fc8`) draws,
for `fingers=m`:

* one shared active strip, `m+1` contacts on a 0.26 um pitch
  (`CT_S_4` 0.055 + CT 0.09 + 0.055), 0.03 active enclosure;
* a poly bus tying every finger, one gate contact on a 0.17 um pad;
* one M1 island per contact with interdigitated straps (even to a bus below,
  odd to a bus above) and a separate gate island (0.042 um^2).

For `fingers=1` the cell is 0.41 um wide (`L + 2*0.205`) and `W` tall, with
two S/D islands at x = +/-0.13 um and the gate island above the active.  The
array plan is the same as gf180/sky130: one row of 255 cells on a 7.5 um
pitch, `d_`/`db_` pads on a 3.75 um grid, which is what the fixed cell has to
be placed on.

## Single-cell layout

`gen_cell.py` places the four devices with the PDK PCell, wires them on M1/M2
(`cd` needs one M2 crossing with 0.09 V1 / 0.17 M1 pad / 0.13 M2), labels the
nine ports on M1, and writes `build/cell.gds`.  `cell.cdl` is the matching
schematic (the PMOS bulk is written as the same `vdd` net as its source; the
deck ties the n-well to the power alias).

The ics55 LVS deck returns:

```
.SUBCKT CELL cd d db idump iout md vbp vcp vdd
M$1 iout  d  cd  VSS NM1P2_SVT_LP L=0.28U W=4U
M$2 idump db cd  VSS NM1P2_SVT_LP L=0.28U W=4U
M$3 md    vbp vdd vdd PM1P2_SVT_LP L=1U   W=8U
M$4 cd    vcp md  vdd PM1P2_SVT_LP L=0.5U W=8U
```

`ICS55_LVS_COMPARE=PASS` with `-rd strict_topology=true` (the default
comparer trips over the well-tied bulk net; the strict path resolves it by
pin name).  The partial KLayout DRC reports 0 items with `no_density=true`
(the density windows are 100 um squares, meaningless for a 5 um cell).

## Next step

1. Generate the 255-cell row + replica with the same pad plan as
   `analog/video_sky130/gen_gds.py` (7.5 um cell pitch, 510 M2 pads on a
   3.75 um grid) and run the partial DRC plus the hand-rule checks
   (CT/ACT/PO/MET1) that the deck does not yet emit.
2. Re-run `pdk_cell.py ics55` on the extracted netlist once the row exists;
   the PDK has no RCX ruleset for ics55, so this needs the Magic/KLayout
   extractor path used by the other leaves.
3. Resolve the `vcp = 20 mV` bias point (wide-swing cascode bias or a wider
   cascode device) before the row is wired to a shared bias generator.

The pre-fix record (M1 over the whole active, "no layout can pass LVS") is in
the git history of this file; that geometry no longer exists in the PDK.
