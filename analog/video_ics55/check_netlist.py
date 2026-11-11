#!/usr/bin/env python3
"""Structural check of the extracted ics55 row netlist.

    python3 check_netlist.py [build/row_ext.cir]

The ics55 LVS *extraction* is the part that depends on our layout; the
netlist comparer is a tool step that does not converge on the 1022-device
flat row (it passes on the single cell).  This script checks the extracted
netlist against the intended topology directly, which is what the comparer
would have to agree with:

  * 1022 devices: 256 mirror (8/1), 256 cascode (8/0.5), 510 pair (4/0.28);
  * per cell: mirror.d == cascode.s, cascode.d == both pair sources,
    pair drains on iout / idump, mirror.g == vbp, cascode.g == vcp;
  * the 510 pair gates are 510 distinct ports named d_<tag> / db_<tag>;
  * the replica is diode-connected (d == g) on vbp and vcp.

Exit status 0 only if every check passes.
"""
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
N = 255
DEV = re.compile(r"^M\S+\s+(\S+)\s+(\S+)\s+(\S+)\s+(\S+)\s+"
                 r"(NM1P2_SVT_LP|PM1P2_SVT_LP)\s+L=(\S+)\s+W=(\S+)")


def tag(j):
    k = 0
    while j >= 2 ** (k + 1) - 1:
        k += 1
    return f"b{k}_{j - (2 ** k - 1)}"


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else os.path.join(
        HERE, "build", "row_ext.cir")
    devs = []
    ports = []
    in_ports = False
    for line in open(path):
        m = DEV.match(line.strip())
        if m:
            in_ports = False
            d, g, s, b, cls, L, W = m.groups()
            devs.append({"d": d, "g": g, "s": s, "b": b, "cls": cls,
                         "L": L.upper().rstrip("U"), "W": W.upper().rstrip("U")})
        elif line.startswith(".SUBCKT"):
            ports = line.split()[2:]
            in_ports = True
        elif in_ports and line.startswith("+"):
            ports += line.split()[1:]
        else:
            in_ports = False
    bad = []

    def check(name, ok, detail=""):
        print(f"  {'PASS' if ok else 'FAIL'}  {name:38s} {detail}")
        if not ok:
            bad.append(name)

    n_p = sum(1 for d in devs if d["cls"].startswith("PM"))
    n_n = sum(1 for d in devs if d["cls"].startswith("NM"))
    check("device count", len(devs) == 4 * N + 2, f"{len(devs)}")
    check("PMOS count", n_p == 2 * (N + 1), f"{n_p}")
    check("NMOS count", n_n == 2 * N, f"{n_n}")

    mir = [d for d in devs if d["cls"].startswith("PM") and d["L"] == "1"]
    cas = [d for d in devs if d["cls"].startswith("PM") and d["L"] == "0.5"]
    pair = [d for d in devs if d["cls"].startswith("NM")]
    check("mirror count (8/1)", len(mir) == N + 1, f"{len(mir)}")
    check("cascode count (8/0.5)", len(cas) == N + 1, f"{len(cas)}")
    check("pair count (4/0.28)", len(pair) == 2 * N, f"{len(pair)}")

    # the replica: exactly one mirror and one cascode with d == g
    rep_m = [d for d in mir if d["d"] == d["g"]]
    rep_c = [d for d in cas if d["d"] == d["g"]]
    check("replica diode-connected", len(rep_m) == 1 and len(rep_c) == 1,
          f"{len(rep_m)}/{len(rep_c)}")
    if rep_m and rep_c:
        check("replica vbp/vcp", rep_m[0]["d"] == "vbp" and rep_c[0]["d"] == "vcp")

    # per-cell chain: build by cascode source (md) and drain (cd)
    by_md = {d["s"]: d for d in cas}          # cascode source = md
    pairs_by_cd = {}
    for d in pair:
        pairs_by_cd.setdefault(d["s"], []).append(d)
    ok_chain = 0
    for m in mir:
        c = next((c for c in cas if c["s"] == m["d"]), None)
        if c is None:
            continue
        ps = pairs_by_cd.get(c["d"], [])
        if len(ps) == 2 and all(p["b"] == "VSS" for p in ps):
            ok_chain += 1
    check("cell chains (md/cd)", ok_chain == N, f"{ok_chain}/{N}")

    # pair drains and gates
    iout = sum(1 for d in pair if d["d"] == "iout")
    idump = sum(1 for d in pair if d["d"] == "idump")
    check("pair drains on iout/idump", iout == N and idump == N,
          f"{iout}/{idump}")
    gates = sorted(d["g"] for d in pair)
    want = sorted([f"d_{tag(j)}" for j in range(N)] +
                  [f"db_{tag(j)}" for j in range(N)])
    check("pair gates are the 510 pads", gates == want,
          f"{len(set(gates))} unique")
    check("mirror gates on vbp",
          sum(1 for d in mir if d["g"] == "vbp") == N + 1)
    check("cascode gates on vcp",
          sum(1 for d in cas if d["g"] == "vcp") == N + 1)
    check("PMOS sources on vdd",
          sum(1 for d in mir + cas if d["s"] == "vdd") == N + 1)
    check("ports", len(ports) == 2 * N + 5, f"{len(ports)}")

    print(f"row netlist: {'PASS' if not bad else 'FAIL'} "
          f"({len(bad)} failing checks)")
    return 0 if not bad else 1


if __name__ == "__main__":
    sys.exit(main())
