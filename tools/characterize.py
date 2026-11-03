#!/usr/bin/env python3
"""Post-PnR characterization for the dac-generator macro matrix.

For every (macro, PDK) pair this reads the LibreLane run results and reports:

  * the clock used for closure and the worst setup / hold slack
    (worst over all PVT corners),
  * an implied maximum clock frequency fmax = 1 / (T_clk - ws_setup),
  * whether the post-PnR STA was PEX-annotated (SPEF from OpenROAD.RCX),
  * die area, standard-cell utilization/count, total power,
  * sign-off counters (KLayout/Magic DRC, LVS).

Sources, in order of preference:
  1. openlane/<macro>/runs/<pdk>/final/metrics.json   (aggregated by LibreLane)
  2. openlane/<macro>/runs/<pdk>/*stapostpnr*/summary.rpt  (per-corner table)

LibreLane writes ~1e39 (metrics.json) or "1000000…" (summary.rpt) for "no
timed path"; both are normalised to None so such rows show `-` instead of a
nonsense f_max.

Writes docs/characterization.csv and docs/characterization.md.
"""

from __future__ import annotations

import csv
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PDKS = ["sky130", "gf180", "ihp130", "ics55", "freepdk45", "or1"]
MACROS = ["const_gen", "config_reg_mux", "audiodac", "tempsense", "pwmdac"]
SENTINEL = 1e6  # LibreLane uses ~1e39 for "no timed path"

# Corners whose liberty does not model the macro's cells completely. On OR1
# only TT_5P0 has timing for the async-reset flops (DFFRX*); the TT_3P3 lib
# omits them, so its slacks are meaningless and are excluded.
CORNER_EXCLUDE = {"or1": ("3P3",)}


def read_json(path: Path):
    try:
        return json.loads(path.read_text())
    except Exception:
        return None


def resolve_dir(macro: str, pdk: str) -> Path:
    return ROOT / "openlane" / macro / "runs" / pdk


def clock_info(rundir: Path):
    cfg = read_json(rundir / "resolved.json") or {}
    t = cfg.get("CLOCK_PERIOD")
    port = cfg.get("CLOCK_PORT") or cfg.get("CLOCK_NET")
    return (float(t) if isinstance(t, (int, float)) else None), port


def _bbox(v):
    if isinstance(v, str):
        try:
            v = [float(x) for x in v.split()]
        except ValueError:
            return (None, None)
    if not isinstance(v, (list, tuple)) or len(v) < 4:
        return (None, None)
    return (v[2] - v[0], v[3] - v[1])


def _skip_corner(name: str, pdk: str) -> bool:
    return any(x in name for x in CORNER_EXCLUDE.get(pdk, ()))


def from_final_metrics(rundir: Path, pdk: str):
    m = read_json(rundir / "final" / "metrics.json")
    if not m:
        return None
    setup = {
        k.split("corner:", 1)[1]: v
        for k, v in m.items()
        if k.startswith("timing__setup__ws__corner:")
        and abs(v) < SENTINEL
        and not _skip_corner(k, pdk)
    }
    hold = {
        k.split("corner:", 1)[1]: v
        for k, v in m.items()
        if k.startswith("timing__hold__ws__corner:")
        and abs(v) < SENTINEL
        and not _skip_corner(k, pdk)
    }
    if not setup:
        # metrics exist but there is no timed register-to-register path
        return {
            "source": "final/metrics.json (no timed path)",
            "setup_ws": None, "setup_corner": None,
            "hold_ws": None, "hold_corner": None,
            "die": _bbox(m.get("design__die__bbox")),
            "util": m.get("design__instance__utilization"),
            "stdcell": m.get("design__instance__count__stdcell"),
            "power": m.get("power__total"),
            "drc_klayout": m.get("klayout__drc_error__count"),
            "drc_magic": m.get("magic__drc_error__count"),
            "lvs": m.get("design__lvs_error__count"),
            "setup_vio": m.get("timing__setup_vio__count"),
        }
    corner, ws = min(setup.items(), key=lambda kv: kv[1])
    hcorner, hws = (min(hold.items(), key=lambda kv: kv[1]) if hold else (None, None))
    bbox = m.get("design__die__bbox")
    return {
        "source": "final/metrics.json",
        "setup_ws": ws,
        "setup_corner": corner,
        "hold_ws": hws,
        "hold_corner": hcorner,
        "die": _bbox(bbox),
        "util": m.get("design__instance__utilization"),
        "stdcell": m.get("design__instance__count__stdcell"),
        "power": m.get("power__total"),
        "drc_klayout": m.get("klayout__drc_error__count"),
        "drc_magic": m.get("magic__drc_error__count"),
        "lvs": m.get("design__lvs_error__count"),
        "setup_vio": m.get("timing__setup_vio__count"),
    }


NUM = re.compile(r"^-?\d+(?:\.\d+)?")


def _num(tok: str):
    tok = tok.strip()
    if tok.startswith("1000000") or tok.startswith("1e6"):
        return None
    mm = NUM.match(tok)
    return float(mm.group(0)) if mm else None


def _no_timing(source: str):
    return {
        "source": source,
        "setup_ws": None, "setup_corner": None,
        "hold_ws": None, "hold_corner": None,
        "die": (None, None), "util": None, "stdcell": None,
        "power": None, "drc_klayout": None, "drc_magic": None,
        "lvs": None, "setup_vio": None,
    }


def from_summary_rpt(rundir: Path, pdk: str):
    cands = sorted(rundir.glob("*stapostpnr*/summary.rpt"))
    if not cands:
        return None
    text = cands[-1].read_text(errors="ignore")
    rows = []
    for line in text.splitlines():
        if "|" not in line and "│" not in line:
            continue
        cells = [c.strip() for c in re.split(r"[|│]", line.strip().strip("|│"))]
        if len(cells) < 6:
            continue
        name = cells[0]
        if not re.match(r"^(nom_|min_|max_)", name):
            continue
        if _skip_corner(name, pdk):
            continue
        rows.append(cells)
    if not rows:
        return _no_timing("stapostpnr/summary.rpt (no timed path)")
    best = None
    for cells in rows:
        ws = _num(cells[6])          # Setup Worst Slack
        hws = _num(cells[1])         # Hold Worst Slack
        if ws is None:
            continue
        if best is None or ws < best[1]:
            best = (cells[0], ws, hws)
    if best is None:
        return _no_timing("stapostpnr/summary.rpt (no timed path)")
    corner, ws, hws = best
    return {
        "source": "stapostpnr/summary.rpt",
        "setup_ws": ws,
        "setup_corner": corner,
        "hold_ws": hws,
        "hold_corner": corner,
        "die": (None, None),
        "util": None,
        "stdcell": None,
        "power": None,
        "drc_klayout": None,
        "drc_magic": None,
        "lvs": None,
        "setup_vio": None,
    }


def spef_exists(macro: str, pdk: str, rundir: Path) -> bool:
    res = ROOT / "results" / pdk / macro / "spef"
    if res.exists() and any(res.rglob("*.spef")):
        return True
    fin = rundir / "final" / "spef"
    if fin.exists() and any(fin.rglob("*.spef")):
        return True
    return False


def characterize(macro: str, pdk: str):
    rundir = resolve_dir(macro, pdk)
    t, port = clock_info(rundir)
    info = from_final_metrics(rundir, pdk) or from_summary_rpt(rundir, pdk)
    if info is None:
        info = _no_timing("missing")
    ws = info["setup_ws"]
    fmax = None
    if t and ws is not None and (t - ws) > 0:
        fmax = 1000.0 / (t - ws)  # ns -> MHz
    if ws is None:
        status = "no timed path"
    elif ws < 0:
        status = "TIMING VIOLATED"
    else:
        status = "met"
    return {
        "macro": macro,
        "pdk": pdk,
        "clock_port": port or "-",
        "t_clk_ns": t,
        "status": status,
        "setup_ws_ns": ws,
        "setup_corner": info["setup_corner"],
        "fmax_mhz": fmax,
        "hold_ws_ns": info["hold_ws"],
        "hold_corner": info["hold_corner"],
        "die_um": (f"{info['die'][0]:.0f}x{info['die'][1]:.0f}"
                   if info["die"][0] else "-"),
        "util_pct": (info["util"] * 100 if info["util"] is not None else None),
        "stdcell": info["stdcell"],
        "power_mw": (info["power"] * 1000 if info["power"] is not None else None),
        "pex": spef_exists(macro, pdk, rundir),
        "drc_klayout": info["drc_klayout"],
        "drc_magic": info["drc_magic"],
        "lvs": info["lvs"],
        "source": info["source"],
    }


def fmt(v, nd=2):
    if v is None:
        return "-"
    if isinstance(v, float):
        return f"{v:.{nd}f}"
    return str(v)


def main():
    rows = [characterize(m, p) for p in PDKS for m in MACROS]
    docs = ROOT / "docs"
    docs.mkdir(exist_ok=True)

    cols = ["macro", "pdk", "clock_port", "t_clk_ns", "status", "setup_ws_ns",
            "setup_corner", "fmax_mhz", "hold_ws_ns", "hold_corner",
            "die_um", "util_pct", "stdcell", "power_mw", "pex",
            "drc_klayout", "drc_magic", "lvs", "source"]
    with (docs / "characterization.csv").open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        for r in rows:
            w.writerow({k: ("" if r[k] is None else r[k]) for k in cols})

    lines = []
    lines.append("# Macro characterization (post-PnR)\n")
    lines.append("Generated by `tools/characterize.py` from the LibreLane run "
                 "results. `f_max = 1 / (T_clk - worst_setup_slack)`, worst "
                 "slack taken over all PVT corners. `PEX` = SPEF from "
                 "`OpenROAD.RCX` was available to the post-PnR STA. "
                 "`status` refers to setup; `hold WS` is reported separately.\n")
    lines.append("Caveats: OR1 is evaluated on the `TT_5P0` corner only (the "
                 "`TT_3P3` liberty omits the async-reset flop timing). "
                 "`util %` and `cells` are LibreLane's stdcell metrics; on "
                 "ics55 the deck classifies filler cells as `other`, so both "
                 "read high.\n")
    lines.append("## Per-macro x PDK\n")
    lines.append("| macro | PDK | clk | T (ns) | setup | setup WS (ns) | corner | "
                 "f_max (MHz) | hold WS (ns) | die (um) | util % | cells | "
                 "power (mW) | PEX | DRC kl/mg | LVS |")
    lines.append("|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|")
    for r in rows:
        drc = f"{fmt(r['drc_klayout'],0)}/{fmt(r['drc_magic'],0)}"
        lines.append(
            f"| {r['macro']} | {r['pdk']} | {r['clock_port']} | "
            f"{fmt(r['t_clk_ns'],1)} | {r['status']} | {fmt(r['setup_ws_ns'],2)} | "
            f"{r['setup_corner'] or '-'} | {fmt(r['fmax_mhz'],1)} | "
            f"{fmt(r['hold_ws_ns'],2)} | {r['die_um']} | "
            f"{fmt(r['util_pct'],1)} | {r['stdcell'] or '-'} | "
            f"{fmt(r['power_mw'],3)} | {'yes' if r['pex'] else 'no'} | "
            f"{drc} | {fmt(r['lvs'],0)} |")
    lines.append("")

    # per-macro summary
    lines.append("## f_max summary per macro (MHz)\n")
    lines.append("| macro | " + " | ".join(PDKS) + " |")
    lines.append("|---|" + "---|" * len(PDKS))
    for m in MACROS:
        cells = []
        for p in PDKS:
            r = next(x for x in rows if x["macro"] == m and x["pdk"] == p)
            cells.append(fmt(r["fmax_mhz"], 1))
        lines.append(f"| {m} | " + " | ".join(cells) + " |")
    lines.append("")
    lines.append("`-` means no timed clock path (const_gen is purely "
                 "combinational) or the run's STA data was not retained.\n")
    (docs / "characterization.md").write_text("\n".join(lines))

    # console digest
    for r in rows:
        print(f"{r['macro']:16s} {r['pdk']:10s} T={fmt(r['t_clk_ns'],1):>5s} "
              f"ws={fmt(r['setup_ws_ns'],2):>7s} fmax={fmt(r['fmax_mhz'],1):>7s} "
              f"pex={'Y' if r['pex'] else 'n'} src={r['source']}")


if __name__ == "__main__":
    sys.exit(main())
