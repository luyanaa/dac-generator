#!/bin/sh
# Reproduce the 8-cell PEX vs CDL comparison.
#
#   ./run_block8_pex.sh
#
# The Magic-only device extraction still loses the cascode drain; this
# script uses the accepted alternative: KLayout LVS for the devices, Magic
# for the named-net capacitances.
set -e
cd "$(dirname "$0")"

N_CELLS=8 OUT="$PWD/build/video_ics55_8.gds" klayout -b -r gen_gds.py -z
PEX_LABELS=1 N_CELLS=8 OUT="$PWD/build/video_ics55_8_pex.gds" \
    klayout -b -r gen_gds.py -z
N_CELLS=8 python3 gen_cdl.py

magic -dnull -noconsole \
    -rcfile /grid/icsprout55-pdk/libs.tech/magic/experimental/ics55_pex.magicrc \
    extract_block8.tcl

klayout -b -r /grid/icsprout55-pdk/libs.tech/lvs/ics55.lvs \
    -rd input="$PWD/build/video_ics55_8.gds" -rd top=dac_video_ana \
    -rd schematic="$PWD/build/video_ics55.cdl" \
    -rd report="$PWD/build/block8.lvsdb" \
    -rd target_netlist="$PWD/build/block8_ext.cir" \
    -rd strict_topology=true -z

python3 block8_klayout_pex.py
