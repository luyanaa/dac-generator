# LibreLane standard-cell wrapper for gf180mcu_fd_sc_mcu7t5v0.
#
# Same as the mcu9t5v0 wrapper: source the ciel SCL config, then expose the
# 5 V liberty corners through ::env(LIB) (LibreLane reads LIB, not CELL_LIBS).
set _scl [file tail [file dirname [file normalize [info script]]]]
set _bases [lsort -dictionary [glob -nocomplain \
    "$::env(HOME)/.ciel/ciel/gf180mcu/versions/*/gf180mcuD"]]
if {![llength $_bases]} {
    error "gf180mcuD not found under ~/.ciel/ciel/gf180mcu/versions"
}
set _base [lindex $_bases end]

source "$_base/libs.tech/librelane/$_scl/config.tcl"

set ::env(LIB) [dict create]
foreach _c {tt_025C_5v00 ss_125C_4v50 ff_n40C_5v50} {
    dict set ::env(LIB) "*_$_c" \
        "$_base/libs.ref/$_scl/lib/${_scl}__$_c.lib"
}
