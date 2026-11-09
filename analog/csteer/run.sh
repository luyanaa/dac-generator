#!/bin/sh
# SPDX-License-Identifier: Apache-2.0
#
# Pre-layout regression for the unit-current-steering DAC leaf.
#
#   ./run.sh            ideal + mismatch dc + passive-I-V + cell bench
#   ./run.sh ideal      dc with sigma = 0 (checks the bench itself)
#   ./run.sh dc         dc with the Pelgrom mismatch, plus the DEM study
#   ./run.sh riv        dc into a passive 1 kOhm I-V (ro penalty)
#   ./run.sh cell       device bench: cell current, ro, Vth sensitivity
#   ./run.sh mismatch   per-cell mismatch over 10 seeds
#
# Device-level analog macro: no RTL path, so this never calls LibreLane.
# `run-analog.sh` at the repo root is the generic entry point.
set -e
SELF=$(readlink -f "$0")
cd "$(dirname "$0")"

BENCH=${1:-all}
PDK=${PDK:-gf180}

case "$BENCH" in
ideal)
    python3 gen_csteer.py --pdk "$PDK" --bench dc --mismatch 0
    ngspice -b build/csteer_dc.spice >/dev/null
    python3 measure.py dc
    ;;
dc)
    python3 gen_csteer.py --pdk "$PDK" --bench dc --mismatch 0.018
    ngspice -b build/csteer_dc.spice >/dev/null
    python3 measure.py dc
    ;;
riv)
    python3 gen_csteer.py --pdk "$PDK" --bench dc --mismatch 0.018 --riv 1000 \
        --dat build/dc_riv.dat --out build/csteer_dc_riv.spice
    ngspice -b build/csteer_dc_riv.spice >/dev/null
    python3 measure.py dc build/dc_riv.dat --no-dem
    ;;
cell)
    python3 run_cell.py --pdk "$PDK"
    ;;
mismatch)
    python3 run_mismatch.py --pdk "$PDK" --sigma 0.018 --seeds 10
    ;;
all)
    "$SELF" cell
    "$SELF" ideal
    "$SELF" dc
    "$SELF" riv
    ;;
*)
    echo "usage: $0 [ideal|dc|riv|cell|mismatch|all]" >&2
    exit 2
    ;;
esac
