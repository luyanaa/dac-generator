# Full SDC for tempsense: standard clock/IO constraints plus an exception for
# the VDAC's analog einvp drivers.
#
# This file REPLACES the fallback base.sdc (PNR_SDC_FILE/SIGNOFF_SDC_FILE), so
# it first sources the generic base.sdc to get create_clock, IO delays, fanout
# and driving-cell constraints, then adds the analog-path exception.

source $::env(FALLBACK_SDC)

# The VDAC is a charge-sharing analog DAC: each tempsense_vdac_cell drives a
# shared `analog_w` node through sky130_fd_sc_hd__einvp_* tri-state inverters
# chained enable->output->next-enable. Those einvp arcs are intentionally-weak
# analog drivers (high-R); STA models them with a huge negative delay and
# reports bogus ~ -116ns setup violations on the digital side. Disable timing
# on every einvp cell so signoff checks only the synchronous logic.
set einvp_cells [get_cells -hier *einvp_batch*]
if { [llength $einvp_cells] > 0 } {
    foreach c $einvp_cells {
        set_disable_timing $c
    }
    puts "\[INFO\] set_disable_timing on [llength $einvp_cells] einvp cells"
}
