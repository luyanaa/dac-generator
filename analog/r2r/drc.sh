#!/bin/sh
# SPDX-License-Identifier: Apache-2.0
#
# gf180mcu KLayout DRC for the analog leaves.  Fail-closed: any missing input,
# missing deck, or missing report is an error.
#
#   ./drc.sh [gf180] [gds] [topcell]
#
# Why this wrapper exists at all (and why it currently refuses to run):
#
#   The gf180 deck is a Ruby DRC script that calls `evaluate_nets()` and
#   `nets()`.  Those are DRC-framework entry points that only exist in a
#   newer KLayout than the 0.30.0 installed here.  With 0.30.0 the deck dies
#   on the first antenna rule ("undefined method `evaluate_nets'"); the
#   DeepShapeStore/Region crash reported earlier is the same bug surfacing
#   through the parallel workers.  Excluding the connectivity decks
#   (`-rd decks=all,-antenna,-dnwell,...`) only moves the failure to the next
#   deck, so there is no honest subset to run.
#
#   Magic is not an alternative in this environment either: this build
#   initialises Tk even under `-d null -noconsole`, so it fails with
#   "no display name and no $DISPLAY" before any PDK tech file is read.
#
#   What this script does instead: verify the tool version, run the deck when
#   it can actually work, and self-check the generator (net shorts, terminal
#   coverage, p-tap clashes) unconditionally.  It never reports "clean" from a
#   run that did not happen.
set -eu
cd "$(dirname "$0")"

PDK=${1:-gf180}
GDS=${2:-build/r2r.gds}
TOP=${3:-dac_r2r_ana}
REPORT=${REPORT:-build/drc.lyrdb}
MIN_KLAYOUT=0.30.9

case "$PDK" in
gf180) ;;
*)
    echo "error: no DRC deck wired for '$PDK'" >&2
    exit 2
    ;;
esac

GF_BASE=${PDK_ROOT:-$HOME/.ciel/ciel/gf180mcu/versions}
DECK=$(ls -d "$GF_BASE"/*/gf180mcuA/libs.tech/klayout/tech/drc/gf180mcu.drc 2>/dev/null | sort | tail -1)
[ -n "${DECK:-}" ] || { echo "error: gf180mcu DRC deck not found under $GF_BASE" >&2; exit 2; }
[ -f "$GDS" ] || { echo "error: $GDS missing; run gen_gds.py first" >&2; exit 2; }

# --- generator self-check, always ------------------------------------------
echo "== generator self-check =="
klayout -b -r gen_gds.py -rd "out=$GDS" -rd check=true

# --- tool version gate -----------------------------------------------------
ver=$(klayout -v 2>/dev/null | awk '{print $2; exit}')
echo "== klayout $ver, deck $DECK =="
if printf '%s\n%s\n' "$MIN_KLAYOUT" "$ver" | sort -V -C; then
    :
else
    cat >&2 <<EOF
error: DRC not run.
       The gf180mcu KLayout deck needs >= $MIN_KLAYOUT (it calls
       evaluate_nets()/nets(), which this KLayout does not provide) and the
       installed tool is $ver.  Magic cannot substitute: this build needs a
       display even with -d null.  Nothing was signed off.
EOF
    exit 3
fi

# --- deck run --------------------------------------------------------------
rm -f "$REPORT"
klayout -b -r "$DECK" \
    -rd "input=$PWD/$GDS" \
    -rd "report=$PWD/$REPORT" \
    -rd "topcell=$TOP" \
    -rd variant=gf180mcuA \
    -rd run_mode=flat \
    -rd workers=1 \
    -rd threads=1

[ -f "$REPORT" ] || { echo "error: DRC produced no report at $REPORT" >&2; exit 4; }

# A report with violations is still a completed run; print the counts so the
# caller can decide.  Any nonzero violation count is an error for signoff.
python3 - "$REPORT" <<'PY'
import re, sys, pathlib
txt = pathlib.Path(sys.argv[1]).read_text(errors="replace")
cats = re.findall(r"<category>\s*<name>([^<]+)</name>.*?<items>", txt, re.S)
n = len(re.findall(r"<item>", txt))
print(f"DRC report: {n} item(s) in {len(cats)} categor{'y' if len(cats)==1 else 'ies'}")
for c in cats:
    print("  ", c)
sys.exit(1 if n else 0)
PY
