# gf180mcu standard-cell variants

`run.sh` already exposes four gf180mcu flavours:

| spec | SCL | tracks | V | status |
|---|---|---|---|---|
| `gf180` | `gf180mcu_fd_sc_mcu9t5v0` | 9 | 5.0 | default, 30-combo matrix |
| `gf180-7t` | `gf180mcu_fd_sc_mcu7t5v0` | 7 | 5.0 | tested here |
| `gf180-as-7t3v3` | `gf180mcu_as_sc_mcu7t3v3` | 7 | 3.3 | tested here (local AS-SCL overlay) |
| `gf180-osu-9t` | `gf180mcu_osu_sc_gp9t3v3` | 9 | 3.3 | not installed in this workspace |

All runs below use the dense `FP_CORE_UTIL=45` / `PL_TARGET_DENSITY_PCT=40`
setting from `openlane/audiodac/config.librelane.json`, the same RTL, the
same 50 ns clock, and the flow's normal multi-corner STA.

## audiodac

| variant | V | die | cells | power | slow-corner setup | f_max (slow) | KLayout DRC |
|---|---|---|---|---|---|---|---|
| `gf180` baseline | 5.0 | 1.393 mm² | 16,809 | 78.29 mW | +17.04 ns (4.5 V/125 °C) | 30.3 MHz | 0 |
| `gf180` dense | 5.0 | 0.792 mm² | 13,688 | 75.45 mW | +19.66 ns | 33.0 MHz | 0 |
| `gf180-7t` dense | 5.0 | 0.630 mm² | 16,092 | 58.85 mW | +9.84 ns | 24.9 MHz | 0 |
| `gf180-as-7t3v3` dense | 3.3 | **0.600 mm²** | 13,690 | **16.06 mW** | **+30.74 ns** (3.0 V/125 °C) | **51.9 MHz** | 0 |

`gf180-as-7t3v3` wins on every axis: **−79 % power**, −24 % die vs the dense
5 V build (−57 % vs the original 1.393 mm²), and still 2.6× the 20 MHz
target at its slow corner. The 5 V 7-track option is the drop-in
alternative when the SoC interface must stay 5 V: −22 % power and −20 % die
for a 24.9 MHz slow-corner f_max (still above 20 MHz).

## Other macros (`gf180` 5 V 9-track vs `gf180-as-7t3v3`)

| macro | 5 V power | 3.3 V power | Δ power | 5 V f_max | 3.3 V f_max |
|---|---|---|---|---|---|
| `config_reg_mux` | 3.859 mW | 0.818 mW | **−78.8 %** | 35.8 MHz | 44.4 MHz |
| `pwmdac` | 13.97 mW | 2.923 mW | **−79.1 %** | 35.5 MHz | 60.9 MHz |
| `audiodac` | 78.29 mW | 16.06 mW | **−79.5 %** | 30.3 MHz | 51.9 MHz |
| `const_gen` | 0.073 mW | 0.087 mW | +19 % (0.014 mW) | — | — |
| `tempsense` | 2.398 mW | failed | — | — | — |

`const_gen` has no clock, so its 0.014 mW increase is irrelevant.

`tempsense` fails `DPL-0036` on the 3.3 V library: the macro's analog VDAC
instantiates the sky130 `einvp` black box, and that model/site is not
available in the AS-SCL view. This is the same sky130-specific analog cell
already documented in `LIBRELANE.md`; the digital macros are unaffected.

## Caveats

- The 3.3 V AS-SCL is a **local overlay** (`overrides/gf180mcuD_full/` and
  the composed `pdks/gf180mcuD` view), not part of the standard
  `gf180mcu_fd_sc` set. The `pdks/` and override trees are gitignored, so a
  fresh checkout needs the same local setup to reproduce these numbers.
- 3.3 V I/O is a system-level decision: the DAC is a digital macro, but its
  `fifo_i`/`ds_o` levels must match the host SoC. The default `gf180` spec
  stays 5 V for that reason; the 3.3 V build is an optional low-power
  flavour.
- `gf180-as-7t3v3` is not part of the 30-combo matrix in
  `docs/characterization.*`; it is an additional variant.
- `gf180-osu-9t` is listed in `run.sh` but the OSU SCL is not installed in
  this workspace, so it was not tested.

## Reproduce

```sh
./run.sh audiodac gf180-7t
./run.sh audiodac gf180-as-7t3v3

# other digital macros on the 3.3 V variant
for m in const_gen config_reg_mux pwmdac; do
    ./run.sh "$m" gf180-as-7t3v3
done
```

The runs land in `openlane/<macro>/runs/<spec>/` and the delivered views in
`results/<spec>/<macro>/`.
