# ics55 PDK blockers — re-analysis and PDK-level repair

Status: 2026-11-13. The earlier note said ics55 was blocked on three things
(the PCell shorted source/drain, a partial DRC port, HSPICE-only models). The
DRC deck was subsequently rewritten from the vendor deck (PDK commit
`12f5125`) and the cell/row now close it. This re-checks each against the
*current* PDK (`/grid/icsprout55-pdk`, PDK commit `12f5125` after `f16045b`),
the vendor Calibre deck that ships in it (`pv/DRC/`), and the full foundry PDK
of the same lineage
(`/shared/SMIC/SMIC55LL_ULP_RF/SPDK55LL_ULP_RF_09121825_OA_CDS_V1.16_2`).

| blocker | verdict | evidence |
|---|---|---|
| HSPICE-only models | **stale — no longer a blocker** | the PDK ships `libs.tech/spice/foundry/ngspice/`; ngspice 44 parses it and two runs give the same `id = 2.18971e-05 A` |
| PCell shorts S/D | **confirmed, fixed and validated** | the drawn M1 covered the whole active; LVS returned `M$1 $1 $2 $1` (S=D). After the fix: one device `M$1 $2 $3 $1 ... W=3U`, `ICS55_LVS_COMPARE=PASS` |
| DRC deck | **cleared** — rewritten from the vendor deck in `12f5125` | single cell and 255-cell row: 0 structural items (`no_density=true`); density tables flag 78 ACT/PO items, i.e. dummy active/poly fill is the remaining tapeout step.  The old 49-category port is superseded |

## 1. Models: use `foundry/ngspice`, not the HSPICE tree

```
.lib ".../libs.tech/spice/foundry/ngspice/ICsprout_55LLULP1225_V1p1_hsp.lib" tt_mos
X1 d g s b nm1p2_svt_lp w=1u l=0.1u
```

gives `id = 2.18971e-05 A`, `vth = 0.399443 V` at Vgs 0.6 / Vds 1.2, identical
on a repeat run. Points that matter for a leaf:

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
  sat 0.07 um apart (rule 0.11) and 0.015 um from the gate (rule 0.055);
* three separate gate stripes with a contact on the middle one only, so the
  outer fingers floated.

The LVS extractor on the old GDS says it directly:

```
M$1 $1 $2 $1 VSS NM1P2_SVT_LP ...     S = D
M$2 $1 $1 $1 VSS NM1P2_SVT_LP ...     S = D = G
M$3 $1 $3 $1 VSS NM1P2_SVT_LP ...     S = D
```

The repaired cell draws:

* one shared active strip, `m+1` contacts on a **0.26 um** pitch
  (`0.055 + 0.09 + 0.055`), first contact `ACT_OV` from the active edge;
* a poly bus above the active tying all gates, with a 0.17 um pad and one
  contact (0.04 poly enclosure);
* one M1 island per contact and two interdigitated straps (even contacts to a
  bus below, odd to a bus above), plus a separate gate island sized for the
  0.042 um^2 M1 area.

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

Measured on the repaired GDS (`fingers=3`, `W=1`, `L=0.06`), against the
vendor deck in `pv/DRC/`:

| check | rule (vendor id) | drawn |
|---|---|---|
| CT size | 0.09 square (`CT_W_1`) | 0.09 x 0.09 |
| CT space | 0.11, 0.14 for 3-neighbour arrays (`CT_S_1`/`CT_S_1a`), 0.12 diff net (`CT_S_2`) | 0.17 |
| CT to gate edge | 0.055 for 0.9/1.2 V (`CT_S_4`) | 0.055 |
| AA to CT on poly | 0.065 (`CT_S_3`) | 0.21 (gate contact is above the active) |
| active enclosure of CT | 0.015 (`CT_EN_2a`) | 0.030 |
| poly enclosure of gate CT | 0.01 / 0.04 / 0.025 all sides (`CT_EN_3a_3b_3c`) | 0.04 |
| M1 enclosure of CT | 0 / 0.04 two sides / 0.025 all sides (`CT_EN_4a_4b_4c`) | 0.025 |
| M1 width / space / area | 0.09 / 0.09 / 0.042 (`MET1_W_1`/`MET1_S_1`/`MET1_A_1`) | 0.14 / 0.12 / 0.0448 min |
| active width / beyond gate | 0.08 / 0.115 (`ACT_W_1`/`ACT_EN_1`) | 0.93 / 0.175 |
| poly width / space | 0.06 / 0.12-0.13 (`PO_W_1`/`PO_S_1`/`PO_S_3`) | 0.06 / 0.20 |

Two details that cost time and belong in the deck:

* the LVS compare does **not** understand `nf=3`; write `w=<total>` in the
  schematic (the extractor combines parallel fingers into one device).
* `run_lvs.py` needs `M1` text labels on the conductor for top-level ports
  (`PORT DEPTH 0`), otherwise it reports `ports=0` and fails on port order.

The demo script also had a hard-coded `/Users/yanlu/...` path, so it could not
run on this machine; it now uses `__file__` and honours `-rd gds=<path>`.

## 3. Direct comparison: vendor deck vs crosswalk vs KLayout port

The vendor reference is the Calibre deck shipped in this repo:

* `pv/DRC/ICsprout_CalDRC_55LLULP1233_REV1_0_OS.drc` - 9723 lines,
  `#! tvf`, frozen profile `total_metal=6`, `top_metal=1`;
* `pv/DRC/ICsprout_CalDRC_55LLULP1233_REV1_0_OS.ant` - 1095 lines, the
  antenna deck (the KLayout port has no antenna module).

It uses **two rule syntaxes**, and that is where the stored comparison breaks:

```
RULECHECK MET1_A_1 { ... }     499 rules
CT_S_4 { ... }                 180 rules, block style
```

All 23 CT rules, 17 PP, 15 NP, 15 TG, 14 DG, 14 ULLD, 14 SAB, the PVT/NVT
implant families and the RV/RDL rules are block style. The stored crosswalk
`tests/regression/official/drc_rule_comparison.json` only knows
`RULECHECK`, so those families are absent from it entirely.

`tests/regression/official/compare_current.py` recomputes the comparison:

```
vendor deck      : ICsprout_CalDRC_55LLULP1233_REV1_0_OS.drc
  RULECHECK      : 499
  block style    : 180  (CT 23, PP 17, NP 15, TG 15, ULLD 14, DG 14)
  unique rules   : 679
KLayout deck     : 49 emitted categories
crosswalk        : 466 ids, 90 covered, 376 missing
  covered and still emitted : 30
  covered but category gone : 60
  vendor ids not in crosswalk: 218

family view (vendor rules / crosswalk covered / still emitted):
  SRCK        46 /  0 /  0
  PO          45 / 40 / 22
  ACT         31 / 26 /  2
  CT          23 /  0 /  0
  ...
```

So the direct comparison says three separate things:

1. **The crosswalk is stale.** 60 of its 90 "covered" rows point at KLayout
   categories that the current deck no longer emits (e.g. `active.act.width`
   and `active.act.space` were removed; the FEOL active module now keeps only
   the area check and lists `ACT_W_1`/`ACT_S_1` as unsupported).
2. **The crosswalk is structurally blind to block-style rules.** Every CT
   rule is missing from it, and CT is the family that gates the device
   geometry. This is why the old pcell passed the port with **0 items** while
   shorting G/S/D and violating CT space by 40 nm.
3. **The KLayout deck was rewritten in `12f5125`**: it now assembles the
   FEOL/BEOL/implant/contact/metal/via/pad/seal-ring/special families from
   the vendor deck.  The old 49-category port is history; the current
   verification is the fixture/alignment regression plus the cell/row runs,
   not a rule-count comparison.  Remaining scope:
   omitted by design.

The comparison is source-level only: no Calibre run/report exists on this
machine, so `differential_status` stays `BLOCKED`. Regenerate the inventory
with `python3 tests/regression/official/compare_current.py` after any deck
change; do not use the stored JSON as a gate until it is regenerated with a
parser that reads both syntaxes.

## 4. What the SMIC reference adds

`/shared/SMIC/SMIC55LL_ULP_RF/...` is the same process family with the full
foundry collateral:

* `DRC_ORI/...drc` (13 153 lines, 517 `RULECHECK` + 513 block-style = 1030
  rules) and `.ant` - a superset of the repo deck, useful for rules the OS
  release omits, but **the two decks do not always agree**: e.g. M1 area is
  0.042 in the OS deck and 0.027 in the SMIC deck; gate-to-contact is 0.055
  (OS, `CT_S_4`) vs 0.05 (SMIC, `CT_4a`). The PDK's own `pv/DRC` deck is the
  arbiter for this PDK; use SMIC to cross-check, not to override.
* `techfile.tf` - layer functions, `currentDensity` (M1 1.6, CT 0.3 mA/um^2),
  `routingDirections`; geometric limits are in the Calibre decks.
* `smic55llrf/<device>/layout/thumbnail_128x128.png` - a cheap topology check
  (the n12ll thumbnail shows two separate M1 islands either side of the gate,
  i.e. no strap over the channel).
* `models/hspice` and `models/spectre` - cross-checks for the vendor model
  set the open PDK already ships; the open PDK's `foundry/ngspice` is the
  runnable one here.

The OA `.oa` layouts are binary and need Cadence, so they are not a geometry
source; the Calibre rules plus the thumbnails are.

## 5. Remaining work

1. Regenerate the crosswalk with a parser that reads both `RULECHECK` and
   block-style rules, then diff the 679 vendor rules against the 49 emitted
   categories to get a truthful gap list.
2. Port the FEOL families (ACT/PO/CT) and M1/V1 first - they gate the pcell;
   then the metal width/space families and the antenna module.
3. Re-run the pcell matrix (n/p, 1..8 fingers, ring on/off) through the new
   rules and add it to `tests/regression`.
4. `ics55_res_poly` / `ics55_mom` still need the same rule-based review.
5. Only then re-attempt the video leaf: the cell needs a 4-terminal MOS with
   correct S/D straps, which is what this repair provides.

## Magic PEX contact/via issue (2026-11-13)

The KLayout LVS deck is the reference for the lower-layer connectivity.  Its
`devices_connections.lvs` uses:

```
NSD/PSD/POLY_CON -> CT -> M1 -> V1 -> M2 -> V2 -> M3 ...
```

(the top T4/TM2 branch is separate and is not used here).  The Magic tech's
`contact` section lists the same edges:

```
ct ndiff m1 / ct pdiff m1 / ct poly m1 / v1 m1 m2
```

so the topology is right; the problem is type registration.  In
`ics55.tech`, `types` aliases `ct` to `active` and `v1` to `metal1`, and the
extractor treats those aliases as non-cut.  A minimal M1/V1/M2 stack then
extracts with `equiv "A" "B"` for the via but `ext2spice` does not merge the
equivalence, and the CT poly-to-M1 contact is lost entirely.

An 8-cell block (`N_CELLS=8`) extracts in seconds (34 devices, 217
capacitors, 13 kB), so runtime is not the blocker.  With `PEX_LABELS=1` the
M1 gate fanout is named (`C76 d_b0_0`), but the MOS gate remains an internal
poly net (`M1000 ... a_452_n1900# ...`) because the CT is not merged.  The
same was true of the earlier single-cell PEX; it was valid for device W/L,
not for driving ports.

One-line fixes were tried and rejected by Magic's tech parser:

* size/overlap on the extract `contact v1` line — that syntax belongs to the
  `wiring` section, not `extract`;
* remove `v1` from the `metal1` alias, or add `cut v1` — the `types` section
  has no `cut` plane, and `connect`/`extract` then report an unknown type.

The fix is a contact-type refactor in `ics55.tech` (define CT/V1 as true cut
types, mirroring the KLayout `CT -> M1 -> V1` chain) plus a minimal CT/V1
stack regression in the PDK tests.  Until then `extracted_carry.py` remains
the device-level signoff and the parasitic carry is open.  `PEX_LABELS` in
`analog/video_ics55/gen_gds.py` is kept for that work.
