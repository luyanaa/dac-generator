#!/bin/sh
# SPDX-License-Identifier: Apache-2.0
#
# LibreLane run driver for the dac-generator macros.
#
# Usage:
#   ./run.sh <macro> [pdk-spec] [extra librelane args...]
#
#   macro     one of: const_gen | config_reg_mux | audiodac | tempsense
#             | pwmdac
#             or "all" to run the leaf macros in dependency order.
#   pdk-spec  one of the keys in the table below (default: sky130)
#
# Examples:
#   ./run.sh const_gen                 # ciel sky130A / sky130_fd_sc_hd
#   ./run.sh tempsense ihp130          # ciel ihp-sg13g2 / sg13g2_stdcell
#   ./run.sh audiodac gf180            # ciel gf180mcuD / gf180mcu_fd_sc_mcu9t5v0
#   ./run.sh const_gen ics55           # /grid icsprout55-pdk / ics55_LLSC_H7CL
#   ./run.sh all sky130-hdll           # /grid sky130 hdll cells on ciel sky130A
#
# Environment:
#   ALL_PROXY must NOT be set (ciel download breaks with a socks proxy);
#   this script unsets it for you. PDK_ROOT can be overridden per-spec via
#   the table below.

set -e
cd "$(dirname "$0")"

MACRO=${1:-const_gen}
SPEC=${2:-sky130}
[ $# -ge 1 ] && shift
[ $# -ge 1 ] && shift

# ciel downloads hang/break through socks proxies (httpx needs socksio).
unset ALL_PROXY all_proxy

# ---------------------------------------------------------------------------
# PDK specs:  <spec>|<pdk-name>|<mode>|<scl>
#   mode=ciel  -> PDK resolved by ciel under ~/.ciel/ciel (no --pdk-root)
#   mode=grid  -> self-contained PDK at /grid/<pdk-name>  (--manual-pdk)
# Custom /grid standard-cell libraries that overlay a ciel PDK are handled
# via the EXTRA_* overrides inside the per-PDK config sections.
# ---------------------------------------------------------------------------
spec_line () {
    case "$1" in
    # --- ciel-managed PDKs ---
    sky130)          echo "sky130A|ciel|sky130_fd_sc_hd" ;;
    sky130-hd)       echo "sky130A|ciel|sky130_fd_sc_hd" ;;
    sky130-hdll)     echo "sky130A|ciel|sky130_fd_sc_hdll" ;;
    sky130-ls)       echo "sky130A|ciel|sky130_fd_sc_ls" ;;
    sky130-osu-t18)  echo "sky130A|ciel|sky130_osu_sc_t18" ;;
    # /grid custom SCLs overlaid onto composed views under ./pdks
    sky130-as-hs)    echo "sky130A|view|sky130_as_sc_hs" ;;
    freepdk45|nangate45) echo "freepdk45|ciel|nangate45" ;;
    ihp130)          echo "ihp-sg13g2|view|sg13g2_stdcell" ;;
    ihp130-hv)       echo "ihp-sg13g2|ciel|sg13g2_stdcell_hv" ;;
    ihp130-cmos5l)   echo "ihp-sg13cmos5l|ciel|sg13g2_stdcell" ;;
    gf180)           echo "gf180mcuD|view|gf180mcu_fd_sc_mcu9t5v0" ;;
    gf180-7t)        echo "gf180mcuD|view|gf180mcu_fd_sc_mcu7t5v0" ;;
    gf180-as-7t3v3)  echo "gf180mcuD|view|gf180mcu_as_sc_mcu7t3v3" ;;
    gf180-osu-9t)    echo "gf180mcuD|view|gf180mcu_osu_sc_gp9t3v3" ;;
    or1|openrule1um) echo "OR1|grid-or1|or1_fd_sc" ;;
    # --- /grid self-contained PDKs ---
    ics55|icsprout55) echo "icsprout55-pdk|grid|ics55_LLSC_H7CL" ;;
    ics55-h7ch)      echo "icsprout55-pdk|grid|ics55_LLSC_H7CH" ;;
    ics55-h7cr)      echo "icsprout55-pdk|grid|ics55_LLSC_H7CR" ;;
    *)               echo "" ;;
    esac
}

LINE=$(spec_line "$SPEC")
if [ -z "$LINE" ]; then
    echo "unknown pdk-spec '$SPEC'" >&2
    exit 2
fi
PDK_NAME=$(echo "$LINE" | cut -d'|' -f1)
MODE=$(echo "$LINE" | cut -d'|' -f2)
SCL=$(echo "$LINE" | cut -d'|' -f3)

# Resolve the on-disk PDK root. For ciel PDKs we point --pdk-root straight at
# the installed version directory (which contains <pdk-name>/), avoiding a
# network fetch entirely. Use the newest installed version by default.
ciel_root () {
    fam=$1
    base=$HOME/.ciel/ciel/$fam/versions
    ver=$(ls -1 "$base" | sort | tail -1)
    echo "$base/$ver"
}

if [ "$MODE" = grid ]; then
    PDKROOT=/grid
elif [ "$MODE" = grid-or1 ]; then
    PDKROOT=/grid/OpenRule1um/OR1PDK
elif [ "$MODE" = view ]; then
    PDKROOT=$PWD/pdks
else
    case "$PDK_NAME" in
    sky130*)    PDKROOT=$(ciel_root sky130) ;;
    ihp-sg13*)  PDKROOT=$(ciel_root ihp-sg13) ;;
    gf180mcu*)  PDKROOT=$(ciel_root gf180mcu) ;;
    freepdk45*) PDKROOT=$(ciel_root freepdk45) ;;
    *)          PDKROOT=$HOME/.ciel/ciel ;;
    esac
fi
PDKOPT="--manual-pdk --pdk-root $PDKROOT"

# Steps that cannot run on a given deck (missing magic LEF, unsupported
# extraction, escaped hierarchical names, ...). They only affect sign-off
# views, never the GDS, and are skipped explicitly so a combos's run is
# reproducible from this script alone.
skips_for () {
    case "$1/$2" in
    */or1)
        echo "-S Odb.SetPowerConnections -S Odb.CheckDesignAntennaProperties" ;;
    tempsense/freepdk45)
        echo "-S Odb.CheckDesignAntennaProperties" ;;
    */ics55)
        # Magic cannot parse the ics55 RV/RDL/T4M2 LEF and loops on the 41k
        # instances: no LEF is written, the antenna checker needs that LEF, and
        # SPICE extraction (LVS is off anyway) does not finish either.
        echo "-S Magic.WriteLEF -S Magic.SpiceExtraction -S Odb.CheckDesignAntennaProperties" ;;
    audiodac/ihp130)
        echo "-S Magic.WriteLEF -S Odb.CheckDesignAntennaProperties" ;;
    *)
        echo "" ;;
    esac
}

run_one () {
    m=$1
    shift
    if [ "$SPEC" = "or1" ] && [ -f "openlane/$m/config.or1.yaml" ]; then
        # OR1 needs a single self-contained file: step-scoped variables and
        # MACROS/MACRO_PLACEMENT_CFG do not survive the multi-file merge.
        cfg="openlane/$m/config.or1.yaml"
    else
        cfg="openlane/common.json openlane/$m/config.librelane.json"
    fi
    SKIPS=$(skips_for "$m" "$SPEC")
    echo "=================================================================="
    echo " LibreLane  macro=$m  pdk=$PDK_NAME  scl=$SCL  root=$PDKROOT"
    [ -n "$SKIPS" ] && echo " extra: $SKIPS"
    echo "=================================================================="
    rm -rf "openlane/$m/runs/$SPEC"
    # shellcheck disable=SC2086
    librelane $cfg $PDKOPT \
        --pdk "$PDK_NAME" \
        --scl "$SCL" \
        --run-tag "$SPEC" \
        --ef-save-views-to "results/$SPEC/$m" \
        $SKIPS \
        "$@"
}

if [ "$MACRO" = all ]; then
    for m in const_gen config_reg_mux audiodac pwmdac tempsense; do
        run_one "$m" "$@"
    done
else
    run_one "$MACRO" "$@"
fi
