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
csteer) DIR=analog/csteer ;;
cdac) DIR=analog/cdac ;;
*)
    echo "error: unknown topology '$TOP' (implemented: r2r, string, csteer, cdac)" >&2
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

# GDS stage.  Two leaves have device generators: R-2R (gf180) and the CDAC
# array (sky130).  The string's switch tree/follower and the current-steering
# array are class C (hand layout), so there is nothing to generate and
# pretending otherwise would be worse than refusing.
gds() {
    case "$TOP:$PDK" in
    r2r:gf180) ;;
    cdac:sky130)
        [ -f "$DIR/gen_gds.py" ] || {
            echo "error: cdac has no device generator yet (array pass open)" >&2
            exit 2
        }
        klayout -b -r "$DIR/gen_gds.py" -rd "out=$DIR/build/cdac.gds"
        return 0
        ;;
    *)
        echo "error: no GDS generator for $TOP on $PDK" >&2
        exit 2
        ;;
    esac
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
