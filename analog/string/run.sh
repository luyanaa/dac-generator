#!/bin/sh
# SPDX-License-Identifier: Apache-2.0
#
# Pre-layout regression for the resistor-string DAC leaf.
#
#   ./run.sh            dc + transient + corner matrix
#   ./run.sh dc         DC linearity only
#   ./run.sh tran       settling only
#   ./run.sh matrix     corner x temperature matrix
#   ./run.sh mismatch   per-unit resistor mismatch sweep
#
# Device-level macro: no RTL path, so this never calls LibreLane.
# `run-analog.sh` at the repo root is the generic entry point.
set -e
cd "$(dirname "$0")"

BENCH=${1:-all}
PDK=${PDK:-gf180}

case "$BENCH" in
dc)
    python3 gen_string.py --pdk "$PDK" --bench dc
    ngspice -b build/string_dc.spice >/dev/null
    python3 measure.py dc
    ;;
tran)
    python3 gen_string.py --pdk "$PDK" --bench tran
    ngspice -b build/string_tran.spice >/dev/null
    python3 measure.py tran
    ;;
matrix)
    python3 run_matrix.py --pdk "$PDK"
    ;;
mismatch)
    python3 run_mismatch.py --pdk "$PDK"
    ;;
all)
    "$0" dc
    "$0" tran
    "$0" matrix
    ;;
*)
    echo "usage: $0 [dc|tran|matrix|mismatch|all]" >&2
    exit 2
    ;;
esac
