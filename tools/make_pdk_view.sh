#!/bin/sh
# Compose a LibreLane PDK view by overlaying a /grid SCL repo onto a base
# ciel PDK using symlinks -> <outdir>/<pdkname>/{libs.ref,libs.tech}.
#
# usage: make_pdk_view.sh <outdir> <pdkname> <base-pdkdir> <overlay-dir>
# Strategy: for libs.ref and libs.tech, link each *immediate child* from
# base; then from overlay.  For libs.tech/<tool> that exists in BOTH (e.g.
# base has openlane/<many>, overlay adds openlane/<newlib>), link the tool
# dir to a real dir and populate it with per-lib symlinks.
set -e
OUT=$1; NAME=$2; BASE=$3; OVL=$4
DST="$OUT/$NAME"
rm -rf "$DST"
mkdir -p "$DST/libs.ref" "$DST/libs.tech"

kids () { [ -d "$1" ] && ls -1A "$1"; }

# ---- libs.ref -------------------------------------------------------------
for lib in $(kids "$BASE/libs.ref"); do
    ln -sfn "$BASE/libs.ref/$lib" "$DST/libs.ref/$lib"
done
for lib in $(kids "$OVL/libs.ref"); do
    ln -sfn "$OVL/libs.ref/$lib" "$DST/libs.ref/$lib"
done

# ---- libs.tech -------------------------------------------------------------
# collect the union of tool names present in base or overlay
tools=$( { kids "$BASE/libs.tech"; kids "$OVL/libs.tech"; } | sort -u )
for t in $tools; do
    b="$BASE/libs.tech/$t"; o="$OVL/libs.tech/$t"; d="$DST/libs.tech/$t"
    if [ -d "$b" ] && [ -d "$o" ]; then
        # both present at the tool level -> real dir, merge per-lib
        mkdir -p "$d"
        libs=$( { kids "$b"; kids "$o"; } | sort -u )
        for l in $libs; do
            bl="$b/$l"; ol="$o/$l"; dl="$d/$l"
            if [ -d "$bl" ] && [ -d "$ol" ]; then
                # lib dir in both -> real dir, merge per-file
                mkdir -p "$dl"
                for f in $(kids "$bl"); do ln -sfn "$bl/$f" "$dl/$f"; done
                for f in $(kids "$ol"); do ln -sfn "$ol/$f" "$dl/$f"; done
            elif [ -e "$bl" ]; then
                ln -sfn "$bl" "$dl"
            else
                ln -sfn "$ol" "$dl"
            fi
        done
    elif [ -d "$b" ]; then
        ln -sfn "$b" "$d"
    elif [ -d "$o" ]; then
        ln -sfn "$o" "$d"
    fi
done
echo "built $DST"
