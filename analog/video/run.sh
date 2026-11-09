#!/bin/sh
# SPDX-License-Identifier: Apache-2.0
#
# Pre-layout regression for the 8-bit 25 MS/s video current-steering leaf.
#
#   ./run.sh            ideal + mismatch + unary control + passive load
#                       + binary-carry transients + decode study
#   ./run.sh ideal      zero mismatch: the bench must be exactly linear
#   ./run.sh dc         binary decode, 1.8 %/cell, seed 0
#   ./run.sh unary      same 255 cells, thermometer decode (control)
#   ./run.sh riv        binary decode into the real 37.5 ohm load
#   ./run.sh tran       carries at 0 and 25 ps bit skew
#   ./run.sh study      20-seed binary-vs-unary DNL/INL distribution
#
# This is a device-level analog macro: hand layout (class C), no RTL, so this
# never calls LibreLane.  `run-analog.sh video gf180` is the generic entry.
set -e
SELF=$(readlink -f "$0")
cd "$(dirname "$0")"
mkdir -p build

BENCH=${1:-all}

dc_run() {                              # decode sigma seed outfile
    python3 gen_video.py --bench dc --decode "$1" --mismatch "$2" \
        --seed "$3"
    # -o keeps the deck log; stderr carries this machine's ~/.spiceinit
    # OSDI noise (an IHP PDK init file) that has nothing to do with the deck.
    ngspice -b -o build/ngspice_dc.log build/dc.spice >/dev/null 2>&1
    mv build/dc.dat "$4"
    python3 measure.py dc "$4"
}

case "$BENCH" in
ideal)
    dc_run binary 0 0 build/dc_ideal.dat pass
    ;;
dc)
    dc_run binary 0.018 0 build/dc_binary.dat pass
    ;;
unary)
    dc_run unary 0.018 0 build/dc_unary.dat pass
    ;;
riv)
    python3 gen_video.py --bench dc --decode binary --mismatch 0.018 \
        --seed 0 --riv 37.5
    ngspice -b -o build/ngspice_riv.log build/dc.spice >/dev/null 2>&1
    mv build/dc.dat build/dc_riv.dat
    # This is the documented negative result: a passive 37.5 ohm load costs
    # +1.5 LSB INL, so the bench must fail.  Flipping the expectation would
    # mean the output stage changed and the README no longer holds.
    python3 measure.py dc build/dc_riv.dat --expect fail
    ;;
tran)
    for spec in "127 128 0" "127 128 25" "63 64 25" "255 0 25"; do
        # shellcheck disable=SC2086
        set -- $spec
        python3 gen_video.py --bench tran --from "$1" --to "$2" \
            --skew-ps "$3"
        ngspice -b -o build/ngspice_tran.log build/tran.spice >/dev/null 2>&1
        f="build/tran_$1_$2_$3.dat"
        mv build/tran.dat "$f"
        echo "--- $1 -> $2, bit skew $3 ps"
        python3 measure.py tran "$f"
    done
    ;;
study)
    python3 measure.py study
    ;;
all)
    "$SELF" ideal
    "$SELF" dc
    "$SELF" unary
    "$SELF" riv
    "$SELF" tran
    "$SELF" study
    ;;
*)
    echo "usage: $0 [ideal|dc|unary|riv|tran|study|all]" >&2
    exit 2
    ;;
esac
