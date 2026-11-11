# SPDX-License-Identifier: Apache-2.0
#
# Macro timing contract for dac_video_dig (100 MHz, 25 MS/s).
#
# The generic fallback SDC only sets a max input/output delay, so every input
# port has a 0 ns min delay: the hold check at the input registers then has no
# margin and the ss corners report ~14 violations (worst -0.65 ns) even though
# every register-to-register hold path is positive at every corner.  A macro
# owns its boundary budget, so this file states it explicitly:
#
#   inputs  : data valid 1.0 ns after the edge, required 2.0 ns before it
#   outputs : same, with a 0 ns hold requirement on the receiver
#
# The wrapper must honour these numbers; they are the macro's interface.

set clk_port $::env(CLOCK_PORT)
set period $::env(CLOCK_PERIOD)

create_clock -name $clk_port -period $period [get_ports $clk_port]

# OpenSTA has no remove_from_collection: drop the clock port by index
set clk_input [get_port $clk_port]
set clk_indx [lsearch [all_inputs] $clk_input]
set inputs [lreplace [all_inputs] $clk_indx $clk_indx ""]
set outputs [all_outputs]

set_input_delay  -clock [get_clocks $clk_port] -max [expr 0.20 * $period] $inputs
set_input_delay  -clock [get_clocks $clk_port] -min 1.0 $inputs
set_output_delay -clock [get_clocks $clk_port] -max [expr 0.20 * $period] $outputs
set_output_delay -clock [get_clocks $clk_port] -min 0.0 $outputs

set_driving_cell -lib_cell [lindex [split $::env(SYNTH_DRIVING_CELL) "/"] 0] \
    -pin [lindex [split $::env(SYNTH_DRIVING_CELL) "/"] 1] $inputs
set_load [expr $::env(OUTPUT_CAP_LOAD) / 1000.0] $outputs

set_clock_uncertainty $::env(CLOCK_UNCERTAINTY_CONSTRAINT) [get_clocks $clk_port]
set_clock_transition $::env(CLOCK_TRANSITION_CONSTRAINT) [get_clocks $clk_port]
set_timing_derate -early [expr 1 - $::env(TIME_DERATING_CONSTRAINT) / 100.0]
set_timing_derate -late  [expr 1 + $::env(TIME_DERATING_CONSTRAINT) / 100.0]
set_propagated_clock [all_clocks]
