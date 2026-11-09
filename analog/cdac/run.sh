#!/bin/sh
# SPDX-License-Identifier: Apache-2.0
#
# Pre-layout regression for the binary CDAC leaf (roadmap P4).
#
#   ./run.sh            unit C(V) + control + MIM design + moscap study
#   ./run.sh unit       device bench: measured unit cap vs cdac.yaml
#   ./run.sh control    constant-C array must transfer exactly
#   ./run.sh mim        flat-cap (MIM) 8-bit design, gated on the SAR spec
#   ./run.sh moscap     measured-moscap 8-bit array, recorded as a study
#
# sky130 only: the measured unit cap, TG and comparator numbers are sky130A
# measurements and do not transfer to gf180.  The PDK gate is in cdac.yaml.
#
# The analog core is a device-level macro; this driver never calls LibreLane.
# `run-analog.sh` at the repo root is the generic entry point.
set -e
SELF=$(readlink -f "$0")
cd "$(dirname "$0")"

BENCH=${1:-all}
PDK=${PDK:-sky130}

case "$PDK" in
sky130) ;;
*)
    echo "error: cdac is a sky130 leaf (measured moscap/TG/comparator)" >&2
    echo "       gf180 would need its own unit-cap C(V) measurement" >&2
    exit 2
    ;;
esac

unit() {
    ./gen_cdac.py --bench unit
}

control() {
    ./gen_cdac.py --bench model --cap const --mismatch 0
    ./measure.py --cap const --expect control
}

mim() {
    ./gen_cdac.py --bench model --cap mim --seeds 10
    ./measure.py --cap mim
}

moscap() {
    ./gen_cdac.py --bench model --cap moscap --seeds 10
    ./measure.py --cap moscap --expect study
}

case "$BENCH" in
unit) unit ;;
control) control ;;
mim) mim ;;
moscap) moscap ;;
all)
    unit
    control
    mim
    moscap
    ;;
*)
    echo "usage: $0 [unit|control|mim|moscap|all]" >&2
    exit 2
    ;;
esac
