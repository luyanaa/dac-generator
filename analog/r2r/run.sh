#!/bin/sh
# SPDX-License-Identifier: Apache-2.0
#
# Pre-layout regression for the R-2R DAC leaf.
#
#   ./run.sh            dc + transient + corner matrix
#   ./run.sh dc         DC linearity only
#   ./run.sh tran       settling only
#   ./run.sh matrix     corner x temperature matrix
#   ./run.sh mismatch   per-unit resistor mismatch sweep
#
# The analog core has no RTL path: it is a device-level macro, so this driver
# never calls LibreLane.  `run-analog.sh` at the repo root is the generic
# entry point.
set -e
SELF=$(readlink -f "$0")
cd "$(dirname "$0")"

BENCH=${1:-all}
PDK=${PDK:-gf180}

case "$BENCH" in
dc)
    python3 gen_r2r.py --pdk "$PDK" --bench dc
    ngspice -b build/r2r_dc.spice
    python3 measure.py dc
    ;;
tran)
    python3 gen_r2r.py --pdk "$PDK" --bench tran
    ngspice -b build/r2r_tran.spice
    python3 measure.py tran
    ;;
matrix)
    python3 run_matrix.py --pdk "$PDK"
    ;;
mismatch)
    python3 run_mismatch.py --pdk "$PDK"
    ;;
all)
    "$SELF" dc
    "$SELF" tran
    "$SELF" matrix
    ;;
*)
    echo "usage: $0 [dc|tran|matrix|mismatch|all]" >&2
    exit 2
    ;;
esac
