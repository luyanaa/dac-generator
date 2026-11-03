# LibreLane standard-cell wrapper for sg13g2_stdcell.
#
# Source the ciel SCL config, then expose the liberty corners as ::env(LIB);
# LibreLane resolves STA corners from LIB while the upstream config only sets
# CELL_LIBS. The ciel install is located under ~/.ciel, so no user or version
# hash is pinned here.
set _scl [file tail [file dirname [file normalize [info script]]]]
set _bases [lsort -dictionary [glob -nocomplain \
    "$::env(HOME)/.ciel/ciel/ihp-sg13/versions/*/ihp-sg13g2"]]
if {![llength $_bases]} {
    error "ihp-sg13g2 not found under ~/.ciel/ciel/ihp-sg13/versions"
}
set _base [lindex $_bases end]

source "$_base/libs.tech/librelane/$_scl/config.tcl"

set ::env(LIB) [dict create]
foreach _c {typ_1p20V_25C slow_1p08V_125C fast_1p32V_m40C} {
    dict set ::env(LIB) "*_$_c" \
        "$_base/libs.ref/$_scl/lib/${_scl}_$_c.lib"
}
