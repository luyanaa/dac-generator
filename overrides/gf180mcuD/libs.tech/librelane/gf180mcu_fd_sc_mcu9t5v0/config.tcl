# LibreLane standard-cell wrapper.
#
# The ciel PDK config only fills ::env(CELL_LIBS); LibreLane resolves corners
# from ::env(LIB), so this wrapper sources the upstream SCL config and then
# builds LIB from the liberty files in libs.ref.
#
# The upstream PDK is located without pinning a user or version hash: the
# composed view under $PDK_ROOT/$PDK symlinks libs.tech/librelane/config.tcl
# back into the ciel install, so its target gives the real PDK base. When the
# PDK is used directly (ciel mode) that file is a regular file and the PDK
# root itself is the base.

set _scl gf180mcu_fd_sc_mcu9t5v0
set _pdk "$::env(PDK_ROOT)/$::env(PDK)"
set _probe "$_pdk/libs.tech/librelane/config.tcl"
if {[file type $_probe] eq "link"} {
    set _base [file dirname [file dirname [file dirname [file readlink $_probe]]]]
} else {
    set _base $_pdk
}

source "$_base/libs.tech/librelane/$_scl/config.tcl"

set ::env(LIB) [dict create]
foreach _c {tt_025C_5v00 ss_125C_4v50 ff_n40C_5v50} {
    dict set ::env(LIB) "*_$_c" \
        "$_base/libs.ref/$_scl/lib/${_scl}__$_c.lib"
}
