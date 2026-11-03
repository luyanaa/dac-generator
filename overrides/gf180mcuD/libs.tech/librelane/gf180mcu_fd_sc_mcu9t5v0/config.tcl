# LibreLane standard-cell wrapper for gf180mcu_fd_sc_mcu9t5v0.
#
# The ciel SCL config only fills ::env(CELL_LIBS); LibreLane resolves corners
# from ::env(LIB), so build that dict here from the liberty files that exist in
# this PDK. The 3v3 corners are absent for the fd_sc flavours, hence the 5 V
# set below (kept in sync with the STA corners used by the flow).
#
# The ciel install is located under ~/.ciel so the wrapper does not pin a
# user or version hash.
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
