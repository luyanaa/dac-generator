#!/bin/sh
# SPDX-License-Identifier: Apache-2.0
#
# Analog-DAC driver: generate, DRC/LVS/PEX, corner sweep.
#
#   ./run-analog.sh <topology> <pdk> [stage]
#
#   topology   r2r | string | csteer | cdac
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
string) DIR=analog/string ;;
*)
    echo "error: unknown topology '$TOP' (implemented: r2r, string)" >&2
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

# GDS stage.  Only the R-2R leaf has a device generator today: the string's
# switch tree and follower are class C (hand layout), so there is nothing to
# generate yet and pretending otherwise would be worse than refusing.
gds() {
    [ "$PDK" = gf180 ] || {
        echo "error: no GDS generator for $PDK (gf180 only)" >&2
        exit 2
    }
    case "$TOP" in
    r2r)
        klayout -b -r "$DIR/gen_gds.py" -rd "out=$DIR/build/r2r.gds" -rd check=true
        ;;
    *)
        echo "error: $TOP has no GDS generator (class C: hand layout)" >&2
        echo "       see docs/analog_dac_integration_plan.md section 2" >&2
        exit 2
        ;;
    esac
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
