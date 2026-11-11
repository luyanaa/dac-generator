#!/usr/bin/env python3
"""Hand-check the ics55 device rules the KLayout DRC deck does not emit.

    klayout -b -r check_rules.py -z

The partial deck (`libs.tech/drc`) only emits area/hole/coverage predicates;
the vendor `pv/DRC` deck has the FEOL geometry rules.  This script measures
the drawn row against those values directly:

    CT_W_1   0.09 square            CT_S_1   space 0.11
    CT_S_4   poly to CT on AA 0.055 CT_S_3   AA to CT on poly 0.065
    CT_EN_2a AA enclosure 0.015     CT_EN_3  poly enclosure 0.04/0.025
    CT_EN_4  M1 enclosure 0.025     ACT_W_1  AA width 0.08
    PO_W_1   PO width 0.06

Exit status is 0 only if every check passes.
"""
import os
import sys

import klayout.db as db

GDS = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                   "build", "video_ics55.gds")
TOP = "dac_video_ana"

L_ACT = (2, 1)
L_POLY = (41, 1)
L_CT = (72, 1)
L_M1 = (81, 1)


def main():
    ly = db.Layout()
    ly.read(GDS)
    c = ly.cell(TOP)
    lay = {}
    for li in range(ly.layers()):
        i = ly.get_info(li)
        lay[(i.layer, i.datatype)] = li

    def R(layer):
        return db.Region(c.shapes(lay[layer]))

    aa, po, ct, m1 = R(L_ACT), R(L_POLY), R(L_CT), R(L_M1)
    ct_aa = ct & aa
    ct_po = ct & po
    bad = []

    def check(name, ok, detail=""):
        print(f"  {'PASS' if ok else 'FAIL'}  {name:34s} {detail}")
        if not ok:
            bad.append(name)

    sizes = sorted({(round(b.width() / 1000, 4), round(b.height() / 1000, 4))
                    for b in (s.bbox() for s in ct.each())})
    check("CT size 0.09 square", sizes == [(0.09, 0.09)], str(sizes[:3]))

    # CT space: growing every CT by 0.054 must not touch another CT
    grown = ct.sized(0.054)
    touch = (grown & ct)
    check("CT space >= 0.11", touch.count() == ct.count(),
          f"{touch.count()} vs {ct.count()} shapes")

    # poly to CT on AA >= 0.055
    check("CT on AA to POLY >= 0.055",
          (ct_aa.sized(0.054) & po).is_empty(),
          f"{(ct_aa.sized(0.054) & po).count()} hits")

    # AA to CT on poly >= 0.065
    check("CT on POLY to AA >= 0.065",
          (ct_po.sized(0.064) & aa).is_empty(),
          f"{(ct_po.sized(0.064) & aa).count()} hits")

    # enclosures
    check("AA enclosure of CT >= 0.015",
          (ct_aa - aa.sized(-0.015)).is_empty(),
          f"{(ct_aa - aa.sized(-0.015)).count()} hits")
    check("POLY enclosure of gate CT >= 0.04",
          (ct_po - po.sized(-0.04)).is_empty(),
          f"{(ct_po - po.sized(-0.04)).count()} hits")
    check("M1 enclosure of CT >= 0.025",
          (ct - m1.sized(-0.025)).is_empty(),
          f"{(ct - m1.sized(-0.025)).count()} hits")

    aa_w = sorted({round(s.bbox().width() / 1000, 4) for s in aa.each()})
    check("AA width >= 0.08", min(aa_w) >= 0.08, f"min {min(aa_w):.3f}")
    po_w = sorted({round(s.bbox().width() / 1000, 4) for s in po.each()})
    check("PO width >= 0.06", min(po_w) >= 0.06, f"min {min(po_w):.3f}")

    print(f"{TOP}: {'PASS' if not bad else 'FAIL'} "
          f"({len(bad)} failing checks)")
    return 0 if not bad else 1


if __name__ == "__main__":
    sys.exit(main())
