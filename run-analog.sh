#!/bin/sh
# SPDX-License-Identifier: Apache-2.0
#
# Analog-DAC driver: generate, DRC/LVS/PEX, corner sweep.
#
#   ./run-analog.sh <topology> <pdk> [stage]
#
#   topology   r2r | string | csteer | cdac        (only `r2r` exists today)
#   pdk        gf180 | sky130
#   stage      prelayout (default) | gds | drc | all
#
# Unlike the digital `run.sh`, this flow is fail-closed: a missing PEX,
# corner, or DRC result is an error rather than a skipped view.  Class A/B/C
# definitions and the per-PDK device gate are in
# docs/analog_dac_integration_plan.md.
set -e
cd "$(dirname "$0")"

TOP=${1:?usage: $0 <topology> <pdk> [stage]}
PDK=${2:?usage: $0 <topology> <pdk> [stage]}
STAGE=${3:-prelayout}

case "$TOP" in
r2r) DIR=analog/r2r ;;
*)
    echo "error: unknown topology '$TOP' (implemented: r2r)" >&2
    exit 2
    ;;
esac

case "$PDK" in
gf180 | sky130) ;;
*)
    echo "error: topology '$TOP' needs precision resistors;" >&2
    echo "       supported PDKs for analog leaves: gf180, sky130" >&2
    exit 2
    ;;
esac

[ -d "$DIR" ] || { echo "error: $DIR missing" >&2; exit 2; }

# gen_gds.py is a KLayout pya script: it needs `klayout -b`, never python3.
gds() {
    [ "$PDK" = gf180 ] || {
        echo "error: no GDS generator for $PDK (gf180 only)" >&2
        exit 2
    }
    klayout -b -r "$DIR/gen_gds.py" -rd "out=$DIR/build/r2r.gds" -rd check=true
}

case "$STAGE" in
prelayout)
    PDK="$PDK" "$DIR/run.sh" all
    ;;
gds)
    gds
    ;;
drc)
    gds
    "$DIR/drc.sh" "$PDK"
    ;;
all)
    PDK="$PDK" "$DIR/run.sh" all
    gds
    "$DIR/drc.sh" "$PDK"
    ;;
*)
    echo "error: unknown stage '$STAGE'" >&2
    exit 2
    ;;
esac
