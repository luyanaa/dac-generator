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
#              postlayout (r2r: poly R-C reconstruction; csteer, video:
#              extracted DC transfer)
#              mm (csteer, video: static mismatch Monte Carlo on the PEX
#              netlist; video is a flat dc sweep, ~1 min per sample)
#              tran (video: carry transient on the extracted netlist, with
#              its capacitance; the stage that sees bias settling).
#
# gds/drc/lvs/pex are implemented for the leaves that have a device-level
# macro: r2r (gf180, full ladder), string (gf180, the 255-unit string only;
# its TG tree is class C), csteer (gf180, the 30-cell array + replica bias +
# 60 steering switches, plus the analog-facing pin row via `pins`; the
# wrapper and its pin script are class C) and cdac (sky130), and video (gf180,
# the 255-cell dump-tail array + replica bias + the 510-pad digital pin row;
# the digital macro, the wrapper and the output driver are class C).
# Every other leaf is class C and the stage exits 2 instead of reporting a run
# that did not happen.
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

# video has a per-PDK cell study (analog/video/pdk_cell.py) and device-level
# macro layouts on gf180 and sky130; ihp/ics have no leaf layout, so refusing
# is honest rather than silently running a quadratic model on a PDK whose
# devices it never touched.
if [ "$TOP" = video ] && [ "$PDK" != gf180 ] && [ "$PDK" != sky130 ] && [ "$PDK" != ihp-sg13g2 ]; then
    echo "error: video leaf has no layout on $PDK (gf180, sky130, ihp-sg13g2)" >&2
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
cdac:sky130 | r2r:gf180 | string:gf180 | csteer:gf180 | video:gf180 | video:sky130 | video:ihp-sg13g2)
    SIGN="$DIR/signoff.py"
    [ -x "$SIGN" ] || { echo "error: $SIGN missing" >&2; exit 2; }
    case "$STAGE" in
    prelayout) PDK="$PDK" "$DIR/run.sh" all ;;
    gds) "$SIGN" --stage build ;;
    drc) "$SIGN" --stage drc ;;
    lvs) "$SIGN" --stage lvs ;;
    pex)
        if [ "$PDK" = gf180 ] || [ "$PDK" = sky130 ]; then
            "$SIGN" --stage pex
        else
            echo "error: video/$PDK has no PEX stage yet" >&2
            exit 2
        fi
        ;;
    pins) "$SIGN" --stage pins ;;
    dc)
        if [ "$TOP:$PDK" = video:sky130 ]; then
            "$SIGN" --stage dc
        else
            echo "error: $TOP/$PDK has no DC stage yet" >&2
            exit 2
        fi
        ;;
    postlayout | mm | tran)
        # Only the leaves that own a bench get these stages: the stage is
        # routed, never silently run against another leaf's netlist.
        if [ "$PDK" = gf180 ]; then
            "$SIGN" --stage "$STAGE"
        else
            echo "error: video/$PDK has no $STAGE bench yet" >&2
            exit 2
        fi
        ;;
    all)
        if [ "$PDK" = gf180 ]; then
            PDK="$PDK" "$DIR/run.sh" all
        fi
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
gds | drc | lvs | pex | pins | mm | tran | all)
    # Class C leaves have no generator, so every layout stage refuses rather
    # than reporting a run that did not happen.
    gds
    ;;
*)
    echo "error: unknown stage '$STAGE'" >&2
    exit 2
    ;;
esac
