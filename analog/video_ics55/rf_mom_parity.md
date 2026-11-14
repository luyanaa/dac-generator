# ics55 RF / MOM LVS parity (gap 5)

Status: **partial parity; MOM is a real gap; no Calibre oracle available.**
This note records what the KLayout ics55 LVS deck
(`/grid/icsprout55-pdk/libs.tech/lvs/ics55.lvs`) does versus the vendor
Calibre LVS deck
(`/grid/icsprout55-pdk/pv/LVS/ICsprout_CalLVS_55LLULP1233_REV1_0_OS.lvs`)
for the RF, varactor, inductor and MOM device families.

## Evidence

The PDK's own fixture check is the source of the numbers:

```sh
cat /grid/icsprout55-pdk/tests/regression/out/lvs_fixtures/lvs_fixture_check.json
# status PASS, official_oracle UNAVAILABLE, cross_tool_equivalence BLOCKED
```

Selected cases (all PASS in the KLayout deck):

| fixture | KLayout extracted model |
|---|---|
| `varactor_1p2` | `VAR1P2_NPD_NW_LP` x1 |
| `varactor_2p5` | `VAR2P5_NPD_NW_LP` x1 |
| `varactor_dnw_1p2` | `VAR1P2_NPD_NW_DNW_LP` x1 |
| `varactor_dnw_2p5` | `VAR2P5_NPD_NW_DNW_LP` x1 |
| `rf_nmos_5t` | `ICS55_RF_NMOS_SVT_5T` x1 |
| `rf_nmos_6t` | `ICS55_RF_NMOS_SVT_6T` x1 |
| `rf_pmos_5t` | `ICS55_RF_PMOS_SVT_5T` x1 |
| `inductor_1tm_alpa` | `ICS55_IND` x1 |

The fixture check is a **local extraction check**; `cross_tool_equivalence`
is `BLOCKED` because no Calibre binary/oracle is installed.  The KLayout
deck header also says "Provisional KLayout port ... not an LVS signoff
result".

## Device-by-device parity

| Family | Calibre deck | KLayout deck | Parity |
|---|---|---|---|
| RF NMOS 5T/6T | DNW-qualified NMOS with P-well tap, terminals D G S B DNW (+PSUB for 6T) | same classes/terminals, DNW-based recognition (no RF marker in the PDK) | topology match; S/D equivalent; KLayout checks topology only, not W/L or wrapper internals |
| RF PMOS 5T | DNW-qualified PMOS with N-well tap, D G S B SUB | same class/terminals | topology match; topology-only |
| Varactor 1.2/2.5 NW | `DEVICE var1p2/var2p5_npd_nw_lp`, POS=gate, NEG=nTap, `TRACE WR/LR/NF` | two-terminal NW varactor classes, POS/NEG from the VARAM core and NW tap | class/terminal match; WR/LR/NF parameter comparison not demonstrated |
| Varactor 1.2/2.5 DNW | same inside DNW, DNW tied to NW | same classes | class/terminal match |
| RF 3T varactor | present in the vendor family | not extracted (README known limitation) | gap |
| 1TM+ALPA1 inductor | `INDALL` keep-out + RV terminal pads, spiral body from TM2/RDL | `ics55_ind` class, PLUS/MINUS RV pairing | class/terminal match; topology-only |
| **MOM capacitor** | `MOM_PRO_2T` / `MOM_MIS_PRO`, `MOMLVS1..6`, `MOMCAP`, `MOMTER`, `MOM_poly`, `mom_metal1..`, `mom_V1..` | **not extracted** (README: "MOM capacitors ... not extracted") | **gap** |

## MOM experiment

A MOM DRC fixture was run through the KLayout LVS extractor:

```sh
klayout -b -zz -r /grid/icsprout55-pdk/libs.tech/lvs/ics55.lvs \
  -rd input=/grid/icsprout55-pdk/tests/regression/out/drc_fixtures/fixtures/mom_cap12_valid_label.gds \
  -rd top=TOP -rd net_only=true \
  -rd target_netlist=/tmp/opencode/mom_klayout.spice \
  -rd run_mode=deep -rd flow_mode=true
# NET_ONLY: extraction complete.
# /tmp/opencode/mom_klayout.spice contains no devices.
```

The Calibre deck defines MOM devices (e.g. `DMACRO MOM_PRO_2T`,
`momcap12`, `MOMLVS1..6`, `MOMCAP`, `MOMTER`); the KLayout deck has no
placement layer for `MOMLVS*`/`MOMCAP`/`MOMTER` and extracts zero devices.
This is a **real parity gap**, but the video DAC (analog row, digital macro,
bias, replica) uses no MOM capacitors, so the DAC LVS result is unaffected.

## Conclusion / next

* RF MOS, two-terminal NW/DNW varactors and the 1TM+ALPA1 inductor are
  recognised with the same class names and terminals as the vendor deck; the
  local fixtures pass.  Parameter-level parity (W/L, WR/LR/NF, inductor
  values) is not demonstrated and is topology-only in the current deck.
* MOM is not extracted.  A macro that uses MOM capacitors cannot be signed
  off with this KLayout deck; use Calibre (not installed here) or port the
  Calibre MOM recognition to KLayout first.
* Cross-tool equivalence remains `BLOCKED` until a same-input Calibre run is
  available.  This is a PDK-level gap, independent of the DAC's own LVS.
