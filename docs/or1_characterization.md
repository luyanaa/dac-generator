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
