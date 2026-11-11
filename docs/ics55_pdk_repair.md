# ics55 PDK blockers — re-analysis and PDK-level repair

Status: 2026-11-12. The earlier note said ics55 was blocked on three things
(the PCell shorted source/drain, a partial DRC port, HSPICE-only models). This
re-checks each against the *current* PDK (`/grid/icsprout55-pdk`,
`v1.10.102-31-g3beae16`) and against the full foundry PDK of the same lineage
(`/shared/SMIC/SMIC55LL_ULP_RF/SPDK55LL_ULP_RF_09121825_OA_CDS_V1.16_2`).

| blocker | verdict | evidence |
|---|---|---|
| HSPICE-only models | **stale — no longer a blocker** | the PDK now ships `libs.tech/spice/foundry/ngspice/`; ngspice 44 parses it and two runs give the same `id = 2.18971e-05 A` |
| PCell shorts S/D | **confirmed, fixed and validated** | the drawn M1 covered the whole active; the LVS extractor returned `M$1 $1 $2 $1` (S=D). After the fix: one device `M$1 $2 $3 $1 ... W=3U`, `ICS55_LVS_COMPARE=PASS` |
| partial DRC deck | **confirmed, still open** | the KLayout port emits 59 checks against 516 active Calibre `RULECHECK`s; the FEOL active module has 1 of 19 rules (area only) and lists the other 18 as unsupported |

## 1. Models: use `foundry/ngspice`, not the HSPICE tree

The PDK's `libs.tech/spice/README.md` already states the position, and it is
measurable:

```
.lib "/grid/icsprout55-pdk/libs.tech/spice/foundry/ngspice/ICsprout_55LLULP1225_V1p1_hsp.lib" tt_mos
X1 d g s b nm1p2_svt_lp w=1u l=0.1u
```

gives `id = 2.18971e-05 A`, `vth = 0.399443 V` at Vgs 0.6 / Vds 1.2, and the
same number on a repeat run. Points that matter for a leaf:

* use the `ngspice/` tree: its wrapper defaults `mismod=0`, so the `agauss`
  mismatch terms are multiplied by zero and an `op` is deterministic. The
  `hspice/` tree defaults `mismod=1` and every run differs.
* `.option scale = 0.9` comes from the top `.lib`; netlist sizes are drawn
  sizes (the wrapper also computes `lef/wef` with the same 0.9 factor).
* each device class has exactly one `.MODEL ..._core` card, so ngspice's lack
  of HSPICE-style bin selection does not change the device (the
  `binunit/lmin/lmax` fields are metadata here).
* the 13 released subcircuits are the ones the standard-cell/IO CDL uses, so
  the digital macro's `.lib` and the analog leaf share one model set.

## 2. PCell: the M1 strap, the contacts and the gate bus

`libs.tech/klayout/pcells/ics55_mos_analog.py` drew, for `fingers=3`:

* one M1 rectangle over the whole active
  (`Region(act).sized(CT_M1_OV)`) - that is the source/drain short;
* the gate M1 strap *inside* that rectangle, so the gate joined the same net;
* two contacts per finger instead of `m+1` shared contacts: the inner pair
  sat 0.07 um apart (rule 0.11) and 0.015 um from the gate (rule 0.05);
* three separate gate stripes with a contact on the middle one only, so the
  outer fingers floated.

The LVS extractor on the old GDS says it directly:

```
M$1 $1 $2 $1 VSS NM1P2_SVT_LP ...     S = D
M$2 $1 $1 $1 VSS NM1P2_SVT_LP ...     S = D = G
M$3 $1 $3 $1 VSS NM1P2_SVT_LP ...     S = D
```

The repaired cell draws:

* one shared active strip, `m+1` contacts on a 0.25 um pitch, first contact
  `ACT_OV` from the active edge, so every contact has 0.05 to the gate and
  0.03 active enclosure;
* a poly bus above the active tying all gates, with a 0.17 um pad and one
  contact (0.04 poly enclosure);
* one M1 island per contact and two interdigitated straps (even contacts to a
  bus below, odd to a bus above), plus a separate gate island grown upward to
  meet the 0.042 um^2 M1 area.

Extraction after the fix, for 1/2/3/4 fingers:

```
m=1: M$1 $2 $3 $1 VSS NM1P2_SVT_LP L=0.06U W=1U
m=2: M$1 $2 $3 $1 VSS NM1P2_SVT_LP L=0.06U W=2U
m=3: M$1 $2 $3 $1 VSS NM1P2_SVT_LP L=0.06U W=3U
m=4: M$1 $2 $3 $1 VSS NM1P2_SVT_LP L=0.06U W=4U
```

and with a matching schematic (`w=3u l=0.06u`) the deck returns
`ICS55_LVS_COMPARE=PASS`. PMOS extracts as `PM1P2_SVT_LP` with bulk `VDD`,
and the guard-ring variant is also clean.

Measured on the repaired GDS (`fingers=3`, `W=1`, `L=0.06`):

| check | rule | drawn |
|---|---|---|
| CT size | 0.09 square | 0.09 x 0.09 |
| CT space (same/diff net) | 0.11 / 0.14 | 0.16 |
| CT to gate edge | 0.05 | 0.050 |
| active enclosure of CT | 0.015 | 0.030 |
| active beyond gate | 0.115 | 0.170 |
| poly beyond active | 0.14 | 0.15 (below) / 0.33 (bus) |
| M1 enclosure of CT | 0.025 | 0.025 (0.14 wide island) |
| M1 area | 0.042 | 0.0448 (gate), >= 0.0896 (S/D) |
| M1 space | 0.09 | 0.11 |

Two details that cost time and belong in the deck:

* the LVS compare does **not** understand `nf=3`; write `w=<total>` in the
  schematic (the extractor combines parallel fingers into one device).
* `run_lvs.py` needs `M1` text labels on the conductor for top-level ports
  (`PORT DEPTH 0`), otherwise it reports `ports=0` and fails on port order.

The demo script also had a hard-coded `/Users/yanlu/...` path, so it could not
run on this machine; it now uses `__file__` and honours `-rd gds=<path>`.

## 3. DRC: what is missing, in the order that gates the leaf

The Calibre source is `DRC_ORI/SMIC_CalDRC_55LLULPGE_0912182533_V1.13_REV1_0`
(13 153 lines, 516 active `RULECHECK`s, plus a separate 993-line `.ant`).
The KLayout port (`libs.tech/drc/`) emits 59 `output()` checks. The FEOL
modules are explicit about it, e.g. `02_active.drc` keeps only `ACT_A_1`
(area) and lists `ACT_W_1..3b`, `ACT_L_1..2`, `ACT_S_1..8`, `ACT_EN_1..2a`,
`ACT_R_1/3` as unsupported.

Priority for a leaf macro (each one is a small KLayout predicate; the values
below are from the Calibre source, with line numbers):

| family | rules to port | source |
|---|---|---|
| ACT | width 0.08, space 0.10/0.11, enclosure of CT 0.015 | 2805, 2821/2827, 4911 |
| GT | width, space 0.12/0.13, AA extension 0.115, poly extension 0.14 | 3795/3817, 3914, 3920 |
| CT | size 0.09, space 0.11 (0.14 diff net), gate spacing 0.05, poly enclosure 0.04 | 4822, 4832/4855, 4900, 4944 |
| M1 | width/space 0.09, enclosure of CT 0.025, area 0.042 | 5058/5063, 4961, LEF |
| V1-V4 | width, space, enclosure upper/lower | via modules |
| metals M2-M5/T4 | width/space/area | metal modules |
| antenna | the whole `.ant` module | `.ant` |

Until that is done the port cannot catch a pcell violation: the old cell
passed it with **0 items** while shorting G/S/D. That is the argument for
porting the FEOL/BEOL width/space families *before* any further analog work
on this PDK.

## 4. What to take from the SMIC reference

`/shared/SMIC/SMIC55LL_ULP_RF/.../smic55ll_ulp_rf_09121825_oa_cds_v1.16_2`
is the same process family with the full foundry collateral:

* `DRC_ORI/...drc` + `.ant` - the rule source for section 3;
* `techfile.tf` - layer *functions* and `currentDensity` (M1 1.6, CT 0.3
  mA/um^2), `routingDirections`; geometric limits are in the Calibre deck;
* `smic55llrf/<device>/layout/thumbnail_128x128.png` - a cheap sanity check
  of the intended topology (the n12ll thumbnail shows two separate M1
  islands either side of the gate, i.e. no S/D strap over the channel);
* `models/hspice` and `models/spectre` - cross-checks for the vendor model
  set the open PDK already ships; the open PDK's `foundry/ngspice` is the
  runnable one here.

The OA `.oa` layouts are binary and need Cadence, so they are not a geometry
source; the Calibre rules plus the thumbnails are.

## 5. Remaining work

1. Port the FEOL families (ACT/GT/CT) and M1/V1 from the Calibre deck; gate
   the pcell on them. This is the item that unblocks analog layout.
2. Re-run the pcell matrix (n/p, 1..8 fingers, ring on/off) through the new
   rules; add it to `tests/regression`.
3. `ics55_res_poly` / `ics55_mom` still need the same rule-based review
   (the resistor draws its own M1 heads, the MOM has no DRC beyond area).
4. Only then re-attempt the video leaf: the cell needs a 4-terminal MOS with
   correct S/D straps, which is exactly what this repair provides.
