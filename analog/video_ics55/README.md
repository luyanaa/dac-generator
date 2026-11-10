# ICsprout55 video DAC: state and blockers

Status: **not a closable leaf on this PDK state**.  The PCell and the DRC deck
run headlessly, but the PCell is a drawn template whose Metal1 is
`ACT + 0.05 um`, i.e. source and drain are shorted by construction, the DRC
deck is a partial Calibre source port, and the transistor models are
HSPICE-only.  Per the earlier decision we still use the PDK's PCell (there is
no other device source); what follows is exactly what that buys and what it
does not.

## PCell works headless

`libs.tech/klayout/pcells/ics55_mos_analog.py` is a normal KLayout
`db.PCellDeclarationHelper`, so no cni host is needed:

```python
import sys
sys.path.insert(0, "/grid/icsprout55-pdk/libs.tech/klayout/pcells")
import klayout.db as db
import ics55_mos_analog            # registers library "ICsprout55"
ly = db.Layout(); ly.dbu = 0.001
c = ly.create_cell("ics55_mos_analog", "ICsprout55",
                   {"dev_type": "n", "w": 8.0, "l": 0.06,
                    "fingers": 1, "guard_ring": 1, "ring_metal": 1})
ly.flatten(c.cell_index())          # PCell geometry is dynamic
```

Note `klayout.db` (not `pya`) and that the PCell geometry only materialises
after flattening.  Parameters here are plain floats in um, unlike the IHP
`cni` wrapper which wants unit strings.

## What the PCell draws (and why it cannot be signed off)

For `nmos w=8 l=0.06 fingers=1 guard_ring=1` the cell is 3.5 x 11.1 um and
contains:

| layer | shape |
|---|---|
| ACT 2/1 | device active + p+ guard-ring active |
| POLY 41/1 | the gate stripe + a gate-contact extension |
| NP 52/1 | n+ implant |
| PP 53/1 | p+ implant (guard ring) |
| CT 72/1 | two S/D contacts and one gate contact |
| M1 81/1 | **one rectangle over the whole active** (`act + 0.05`), the gate pad, the ring strap |

The M1 over the whole active is the problem: it straps source and drain
together, so the device is a short, not a transistor.  No layout built on
this PCell can pass LVS or simulate.  That is a PCell-template limitation,
not a routing one; the LVS deck is available
(`libs.tech/lvs`) but there is nothing meaningful to compare until the PCell
is fixed (or replaced by a real device drawer).

## DRC deck is a partial source port

`libs.tech/drc/ics55_drc.drc` runs under the stock KLayout:

```bash
klayout -b -r libs.tech/drc/ics55_drc.drc \
    -rd input=ics_dev.gds -rd top=TOP -rd report=ics_dev.lyrdb
```

On the single 8/0.06 nmos it reports 3 items, all density:
`ACT_D_1_min`, `PO_D_1_min`, `PO_D_2_min` (the density windows are 100 um
squares around a 3.5 x 11.1 um cell).  With `-rd no_density=true` the same
device is **0 items**, so the geometry rules the port implements are clean.
The deck's own header says it is not Calibre-equivalent: a matched Calibre
run is required before a DRC claim.

## Models are HSPICE-only

The `.mdl` bins are selected by `.param` expressions over the instance `w/l`
(`wum = w*1e6`); ngspice cannot evaluate them (`Undefined parameter [w]` /
`could not find a valid modelname`), and the PDK readme says HSPICE-only.
This is the same block recorded in `../video/README.md`: the DC transfer,
mismatch and transient benches cannot run on this PDK in this environment.

## What would unblock it

1. A functional MOS PCell (S/D separated, with the gate contact and taps) or
   a real device GDS; the current template's M1 short is fatal.
2. Either HSPICE or an ngspice port of the `.mdl` bins; the leaf's sizing
   (`../video/pdk_cell.py`) is blocked on this, which is why there are no
   16 uA-device sizes for ics55 in the first place.
3. A Calibre-equivalent DRC run (or acceptance of the partial port with its
   documented exclusions).

The layout *shape* (dump-tail cell + 510 pads on the 3.75 um row) can be
generated from the PCell at any time, but it would be a drawing, not a
signoff; this directory records the state rather than pretending otherwise.
