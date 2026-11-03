# OR1 characterization (audiodac)

OR1 (`/grid/OpenRule1um/OR1PDK/OR1`, ~1 µm, 5 V) exposes a **single**
`nom_tt_5P0_25C` corner. These numbers are therefore TT estimates, not
signoff: the liberty header states the DFF setup/hold tables are inherited
and "NOT characterised yet", and no slow/fast corner or corner derating is
available.

Measured on the post-route netlist of `audiodac` (24,239 std cells,
6600 x 6600 µm die, 25.5 % utilization, 46.4 mW) with the OR1 RCX rules
(`OR1.rcx_rules`, rules-based SPEF) and the flow's base SDC
(50 ns clock, 10 ns input/output delay, 0.25 ns uncertainty, 5 % derate).

| Path | Worst slack | Path delay | Implied f_max |
|---|---|---|---|
| overall (I/O dominated) | +34.11 ns | 15.89 ns | **62.9 MHz** |
| register-to-register | +36.24 ns | 13.76 ns | **72.7 MHz** |
| hold (overall = reg-to-reg) | +0.29 ns | — | — |

- The overall worst path starts at `tst_sinegen_en_i`: **10 ns of its
  15.89 ns is the external input delay** (20 % of the clock period), so the
  headline f_max is I/O-limited, not a raw gate-speed figure.
- Clock skew: +0.62 ns (setup) / -0.80 ns (hold) on the 6.6 mm die with
  metal2/metal3 routing only.
- The reg-to-reg critical path is dominated by the `BUFX2` chain that
  `repair_design` inserted into the ~600-fanout sinegen select nets
  (each BUFX2 is ~0.35-0.40 ns at TT/5 V); the logic itself is shallow.

## Reading the number

At 1 µm / 5 V a ~13.8 ns register-to-register path (~0.3 ns per gate/wire
stage) is physically plausible, and the PDK's own reference counter
(31 cells, 20 ns clock) shows +15 ns slack — the deck is simply fast at TT.

Treat 62.9 / 72.7 MHz as an optimistic TT ceiling. With a 2x guardband for a
missing slow corner and uncharacterised setup/hold, the macro would still be
~31-36 MHz, i.e. comfortably above the 20 MHz target.

## Why OR1 looks "fast" on most macros

The reported `f_max = 1/(T_clk - worst_setup_slack)` is only a gate-speed
figure when the critical path is register-to-register. On OR1 that is true
for only one of the five macros, and that one is limited by fanout instead:

| macro | worst path | path | fixed I/O delay | logic | f_max | note |
|---|---|---|---|---|---|---|
| `tempsense` | FF -> output port | 11.11 ns | 10 ns (output) | 0.86 ns (3 stages) | 90.0 MHz | almost entirely the output delay |
| `audiodac` | input -> FF | 15.89 ns | 10 ns (input) | 5.89 ns | 62.9 MHz | reg-to-reg 13.76 ns = 72.7 MHz |
| `config_reg_mux` | input -> FF | 21.64 ns | 10 ns (input) | 11.64 ns | 46.2 MHz | |
| `pwmdac` | FF -> FF | 25.18 ns | 0 | 25.18 ns | 39.7 MHz | 21.2 ns is two unrepaired fanout nets |
| `const_gen` | combinational | - | - | - | - | no clock |

`pwmdac`/OR1 is the only register-to-register measurement, and 21.2 ns of its
25.2 ns path is a DFF `Q` net with fanout 192 (4.5 ns) followed by an `INVX1`
with fanout 141 (16.7 ns). `openlane/pwmdac/config.or1.yaml` sets
`RUN_REPAIR_DESIGN: false` and `RUN_POST_GPL_DESIGN_REPAIR: false`, so those
nets are never buffered; the 39.7 MHz is a fanout limit, not gate speed.
`audiodac` (the only OR1 config with repair enabled) buffers the ~600-fanout
sinegen net down to 80 and gives the cleanest OR1 number: 13.76 ns
register-to-register, 82 cell stages, ~0.17-0.20 ns per stage.

At the same TT corner the other decks are not faster than OR1:

| PDK | TT worst setup slack | implied f_max |
|---|---|---|
| sky130 | +32.51 ns | 57.1 MHz |
| gf180 | +29.53 ns | 48.9 MHz |
| ihp130 | +34.09 ns | 62.9 MHz |
| ics55 | +35.97 ns | 71.3 MHz |
| freepdk45 | +38.93 ns | 90.3 MHz |
| **or1** | **+34.11 ns** | **62.9 MHz** |

All six TT worst paths are input paths with the same fixed 10 ns external
delay, so this table mostly ranks where the logic lands, not the process.
The published per-PDK table shows the slow-corner decks at 39.3/30.3/51.8/
55.8 MHz and the TT-only decks at 90.3/62.9 MHz; that is a corner
difference, not a PDK defect.

## Accuracy limits of the OR1 liberty

The OR1 cell tables are characterised only for input slew 0.2-2.0 ns and
load 0.01-0.12 pF (`lu_table_template(char_4x4)`), but this design runs at
0.05-0.06 ns slews and 7.1 % of its nets (1683/23646) are above 0.12 pF,
up to 0.65 pF. The post-route checkers also report 1387 max-capacitance and
1894 max-slew violations at the only corner. Every cell delay on the critical
path is therefore extrapolated outside the tabulated range, and the DFF
setup/hold tables are explicitly uncharacterised (a constant 0.1904 ns setup,
2.9 ps hold). Treat the OR1 numbers as a TT estimate with an unknown, not
necessarily pessimistic, error - not as signoff.

## Reproduce

The register-to-register split is not in `metrics.json` (the flow reports the
overall worst path). It was measured with OpenSTA on the same netlist, LIB,
SDC and SPEF as the flow's `OpenROAD.STAPostPNR` step:

```tcl
define_corners nom_tt_5P0_25C
read_liberty -corner nom_tt_5P0_25C .../or1_fd_sc_TT_5P0_25C.lib
read_verilog .../51-openroad-fillinsertion/audiodac.nl.v
link_design audiodac
source .../librelane/scripts/base.sdc          ;# with the step's _env_*.tcl
set_propagated_clock [all_clocks]
read_spef .../53-openroad-rcx/tt/audiodac.tt.spef
report_checks -sort_by_slack -path_delay max \
    -from [all_registers] -to [all_registers] -group_path_count 3
```
