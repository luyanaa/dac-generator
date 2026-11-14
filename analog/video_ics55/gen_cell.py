"""Place one ics55 dump-tail cell (2 PMOS + 2 NMOS) with the fixed PCell.

    klayout -b -r gen_cell.py -z            # -> build/cell.gds

The cell is the P5 unit: mirror (8/1) + cascode (8/0.5) PMOS, steering pair
(4/0.28) NMOS.  It is placed with the PDK PCell, wired on M1/M2 (the `cd`
node needs one M2 crossing) and labelled on M1 so the LVS deck can make the
ports.

Check with the ics55 decks (the LVS deck needs `strict_topology=true`; the
default comparer trips over the well-tied bulk net, which the strict path
resolves by pin name):

    klayout -b -r <pdk>/libs.tech/lvs/ics55.lvs -rd input=build/cell.gds \
        -rd top=CELL -rd schematic=cell.cdl -rd strict_topology=true \
        -rd report=build/cell.lvsdb -rd target_netlist=build/cell_ext.cir -z

Result: `ICS55_LVS_COMPARE=PASS`, four devices with the intended W/L and
topology, and 0 items from the partial DRC deck (`no_density=true`).
"""
import os, sys
import klayout.db as db

PCELS = "/grid/icsprout55-pdk/libs.tech/klayout/pcells"
sys.path.insert(0, PCELS)
import ics55_mos_analog  # noqa

L_ACT=(2,1); L_NW=(9,1); L_POLY=(41,1); L_NP=(52,1); L_PP=(53,1)
L_CT=(72,1); L_M1=(81,1); L_M2=(82,1); L_V1=(91,1)

def side(L): return L/2.0 + 0.055 + 0.09 + 0.03

def islands(W, L, cx, cy):
    s=side(L); dx=2*s; x0=cx-dx/2.0; y0=cy-W/2.0
    pitch=L+0.2
    ct=[x0+0.075, x0+0.075+pitch]
    left=(ct[0]-0.07, y0-0.16, ct[0]+0.07, y0+W-0.07)
    right=(ct[1]-0.07, y0+0.10, ct[1]+0.07, y0+W+0.16)
    gate=(cx-0.07, y0+W+0.305, cx+0.07, y0+W+0.625)
    return left, right, gate

ly=db.Layout(); ly.dbu=0.001
top=ly.create_cell("CELL")
def u(v): return int(round(v/ly.dbu))
def box(l,x1,y1,x2,y2):
    top.shapes(ly.layer(*l)).insert(db.Box(u(x1),u(y1),u(x2),u(y2)))
def text(s,x,y):
    top.shapes(ly.layer(81,1)).insert(db.Text(s, db.Trans(db.Vector(u(x),u(y)))))

devs = {
  "m": dict(W=8.0, L=1.0,  c=(0.0, 0.0),  m="pm1p2_lvt_lp", lvt=1),
  "c": dict(W=8.0, L=0.5,  c=(2.2, 0.0),  m="pm1p2_lvt_lp", lvt=1),
  "a": dict(W=4.0, L=0.28, c=(0.6, -7.5), m="nm1p2_svt_lp"),
  "b": dict(W=4.0, L=0.28, c=(2.4, -7.5), m="nm1p2_svt_lp"),
}
isl={}
for k,d in devs.items():
    dev="p" if d["m"].startswith("pm") else "n"
    c=ly.create_cell("ics55_mos_analog","ICsprout55",
        {"dev_type":dev,"w":d["W"],"l":d["L"],"fingers":1,
         "guard_ring":0,"ring_metal":0,"lvt":d.get("lvt",0)})
    top.insert(db.CellInstArray(c.cell_index(),
        db.Trans(db.Vector(u(d["c"][0]),u(d["c"][1])))))
    isl[k]=islands(d["W"],d["L"],d["c"][0],d["c"][1])
top.flatten(-1, True)

# merged NW strip + one NTAP tied to the first PMOS source (vdd)
box(L_NW, -2.2, -4.6, 3.2, 4.6)
box(L_ACT, -1.8, -0.15, -1.3, 0.15)
box(L_NP, -2.0, -0.35, -1.1, 0.35)
box(L_CT, -1.595, -0.045, -1.505, 0.045)
box(L_M1, -1.65, -0.16, -1.45, 0.16)
box(L_M1, -1.65, -0.07, -0.5, 0.07)

# md: mirror right -> cascode left
mr=isl["m"][1]; cl=isl["c"][0]
box(L_M1, mr[0], -0.3, cl[2], 0.3)

# cd: cascode right -> M2 down -> pair left islands.  V1 is 0.09 with a
# 0.17 M1 pad (0.04 lower enclosure, rule V1_EN) and 0.13 M2 (0.02 upper).
def via_stack(cx, cy):
    box(L_M1, cx-0.085, cy-0.085, cx+0.085, cy+0.085)
    box(L_V1, cx-0.045, cy-0.045, cx+0.045, cy+0.045)
cr=isl["c"][1]
# V1 offset from the CT in y: Magic loses the lower contact when a V1 is
# stacked exactly on a CT.
via_stack(cr[0]+0.07, 0.12)
box(L_M2, cr[0]+0.005, -8.365, cr[0]+0.135, 0.20)
for k in ("a","b"):
    li=isl[k][0]
    via_stack(li[0]+0.07, -8.3)
box(L_M2, isl["a"][0][0]+0.005, -8.365, cr[0]+0.135, -8.235)

# labels on M1 islands (the LVS deck turns top-level text into ports)
text("vdd",  isl["m"][0][0]+0.07, 0.0)
text("vbp",  isl["m"][2][0]+0.07, (isl["m"][2][1]+isl["m"][2][3])/2)
text("md",   (mr[0]+cl[2])/2, 0.0)
text("vcp",  isl["c"][2][0]+0.07, (isl["c"][2][1]+isl["c"][2][3])/2)
text("cd",   isl["a"][0][0]+0.07, -8.0)
text("d",    isl["a"][2][0]+0.07, (isl["a"][2][1]+isl["a"][2][3])/2)
text("db",   isl["b"][2][0]+0.07, (isl["b"][2][1]+isl["b"][2][3])/2)
text("iout", isl["a"][1][0]+0.07, -7.5)
text("idump",isl["b"][1][0]+0.07, -7.5)
out=os.environ.get("OUT", os.path.join(os.path.dirname(os.path.abspath(__file__)), "build", "cell.gds"))
ly.write(out); print("wrote", out, "cells", [c.name for c in ly.each_cell()])
