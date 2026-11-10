#!/bin/sh
# SPDX-License-Identifier: Apache-2.0
#
# Analog-DAC driver: generate, DRC/LVS/PEX, corner sweep.
#
#   ./run-analog.sh <topology> <pdk> [stage]
#
#   topology   r2r | string | csteer | cdac | video
#   pdk        gf180 | sky130
#   stage      prelayout (default) | gds | drc | lvs | pex | pins | all
#              postlayout (r2r: poly R-C reconstruction; csteer: PEX core)
#              mm (csteer: static mismatch Monte Carlo on the PEX netlist)
#
# gds/drc/lvs/pex are implemented for the leaves that have a device-level
# macro: r2r (gf180, full ladder), string (gf180, the 255-unit string only;
# its TG tree is class C), csteer (gf180, the 30-cell array + replica bias +
# 60 steering switches, plus the analog-facing pin row via `pins`; the
# wrapper and its pin script are class C) and cdac (sky130).  Every other leaf
# is class C and the stage exits 2 instead of reporting a run that did not
# happen.
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
video) DIR=analog/video ;;
*)
    echo "error: unknown topology '$TOP' (implemented: r2r, string, csteer, cdac, video)" >&2
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

# video is sized from the gf180 cell bench; there is no sky130 cell data for
# this leaf, so refusing is honest rather than silently running a quadratic
# model on a PDK whose devices it never touched.
if [ "$TOP" = video ] && [ "$PDK" != gf180 ]; then
    echo "error: video leaf is gf180-only (cell data from analog/csteer)" >&2
    exit 2
fi

# GDS stage.  Only leaves with a device generator get here, and they route
# every layout stage through their own signoff.py (see below).  The parts a
# generator does not cover - the string's TG tree/follower, the current-
# steering I-V - are class C (hand layout), so for a leaf with no
# generator at all there is nothing to emit and refusing beats pretending
# otherwise.
gds() {
    echo "error: no GDS generator for $TOP on $PDK" >&2
    echo "       $TOP is class C: hand layout, see" >&2
    echo "       docs/analog_dac_integration_plan.md section 2" >&2
    exit 2
}

# Leaves with a device-level layout have one fail-closed entry point: their
# signoff.py builds the macro, then gates DRC, LVS and PEX.  Routing the stages
# here instead of a second script means `gds` cannot succeed while `drc` checks
# a different file.
case "$TOP:$PDK" in
cdac:sky130 | r2r:gf180 | string:gf180 | csteer:gf180)
    SIGN="$DIR/signoff.py"
    [ -x "$SIGN" ] || { echo "error: $SIGN missing" >&2; exit 2; }
    case "$STAGE" in
    prelayout) PDK="$PDK" "$DIR/run.sh" all ;;
    gds) "$SIGN" --stage build ;;
    drc) "$SIGN" --stage drc ;;
    lvs) "$SIGN" --stage lvs ;;
    pex) "$SIGN" --stage pex ;;
    pins) "$SIGN" --stage pins ;;
    postlayout)
        "$SIGN" --stage postlayout
        ;;
    mm)
        "$SIGN" --stage mm
        ;;
    all)
        PDK="$PDK" "$DIR/run.sh" all
        "$SIGN"
        ;;
    *)
        echo "error: unknown stage '$STAGE'" >&2
        exit 2
        ;;
    esac
    exit 0
    ;;
esac

case "$STAGE" in
prelayout)
    PDK="$PDK" "$DIR/run.sh" all
    ;;
gds | drc | lvs | pex | pins | mm | all)
    # Class C leaves have no generator, so every layout stage refuses rather
    # than reporting a run that did not happen.
    gds
    ;;
*)
    echo "error: unknown stage '$STAGE'" >&2
    exit 2
    ;;
esac
