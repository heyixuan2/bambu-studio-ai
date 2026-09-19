# Bambu Lab printers and materials

The tables below are generated from [`assets/printers.json`](../assets/printers.json) and
[`assets/materials.json`](../assets/materials.json), which the scripts read through
`scripts/bambu_studio_ai/hardware.py`. Each JSON entry lists its sources and the date they were
checked. Don't edit the tables by hand: change the JSON, then run
`python3 tests/datagen/model_specs.py --write` (a test fails while they disagree).

## Printers

These are the Bambu Lab printers the skill knows (Bambu Studio 02.07, September 2026). Volumes and
temperature limits are what Bambu Studio itself allows, which is sometimes a little less than the
headline figure on the spec sheet (shown as "spec").

<!-- generated:printers (tests/datagen/model_specs.py) -->
| Model | Plate W × D × H (mm) | Per nozzle (mm) | Nozzle max | Bed max | Chamber | Nozzle fitted | AMS | Status |
|---|---|---|---|---|---|---|---|---|
| A1 Mini | 180 × 180 × 180 | one nozzle | 300 °C | 80 °C | none | stainless | AMS lite, AMS, AMS 2 Pro, AMS HT (≤ 16 slots) | current |
| A1 | 256 × 256 × 256 | one nozzle | 300 °C | 100 °C | none | stainless | AMS lite, AMS, AMS 2 Pro, AMS HT (≤ 16 slots) | current |
| A2L | 330 × 320 × 325 | one nozzle | 300 °C | 80 °C | none | stainless | AMS lite, AMS, AMS 2 Pro, AMS HT (≤ 19 slots) | current |
| P1P | 256 × 256 × 250 (spec 256 × 256 × 256) | one nozzle | 300 °C | 100 °C | none | stainless | AMS, AMS 2 Pro, AMS HT (≤ 16 slots) | discontinued 2026-02-10 |
| P1S | 256 × 256 × 250 (spec 256 × 256 × 256) | one nozzle | 300 °C | 100 °C | passive | stainless | AMS, AMS 2 Pro, AMS HT (≤ 16 slots) | current |
| P2S | 256 × 256 × 256 | one nozzle | 300 °C | 110 °C | passive | hardened | AMS 2 Pro, AMS HT (≤ 20 slots) | current |
| X1C | 256 × 256 × 250 (spec 256 × 256 × 256) | one nozzle | 300 °C | 110 °C | passive | hardened | AMS, AMS 2 Pro, AMS HT (≤ 16 slots) | discontinued 2026-03-31 |
| X1E | 256 × 256 × 250 (spec 256 × 256 × 256) | one nozzle | 320 °C | 110 °C | heated 60 °C | hardened | AMS, AMS 2 Pro, AMS HT (≤ 16 slots) | discontinued 2026-03-31 |
| X2D | 256 × 256 × 261 (spec 256 × 256 × 260) | main 256 × 256 × 261 · auxiliary 235.5 × 256 × 256 · both 235.5 × 256 × 256 | 300 °C | 120 °C | heated 65 °C | hardened | AMS 2 Pro, AMS HT (≤ 24 slots) | current |
| H2C | 330 × 320 × 325 | left 325 × 320 × 320 · right 305 × 320 × 325 · both 300 × 320 × 320 | 350 °C | 120 °C | heated 65 °C | hardened | AMS 2 Pro, AMS HT (≤ 24 slots) | current |
| H2S | 340 × 320 × 340 | one nozzle | 350 °C | 120 °C | heated 65 °C | hardened | AMS 2 Pro, AMS HT (≤ 24 slots) | current |
| H2D | 350 × 320 × 325 | left 325 × 320 × 320 · right 325 × 320 × 325 · both 300 × 320 × 320 | 350 °C | 120 °C | heated 65 °C | hardened | AMS 2 Pro, AMS HT (≤ 24 slots) | current |
| H2D Pro | 350 × 320 × 325 | left 325 × 320 × 320 · right 325 × 320 × 325 · both 300 × 320 × 320 | 350 °C | 120 °C | heated 65 °C | hardened | AMS 2 Pro, AMS HT (≤ 24 slots) | current |
<!-- /generated:printers -->

- **Two-nozzle printers (H2D, H2D Pro, H2C, X2D).** Each nozzle reaches only part of the plate. The
  whole plate is usable only with both nozzles printing separate objects; one object printed with both
  nozzles has to fit the "both" region.
- **H2C.** The right nozzle takes hotends from a Vortek changer that holds up to six. Bambu Studio won't
  print TPU with the left nozzle or PPA-CF/PPS-CF with the right one.
- **AMS slots** count AMS slots only; the external spool holder adds one feed per nozzle. The A2L takes
  four AMS-family units plus one AMS lite at the same time; the A1 and A1 mini take one or the other.
- **Discontinued models** keep receiving spare parts and support: the P1P until February 2031, the X1
  series until March 2031.

## How the scripts use this

- **Fit check** (`analyze.py`, and the size hint in `generate.py`): a part must fit the region every
  nozzle reaches (the "both" region on two-nozzle printers, the plate otherwise), less 5 mm on each side
  in X and Y for a brim (Bambu Studio's default brim width). The height is not reduced.
- **Material check** (`analyze.py --material X`): materials that need an enclosure are flagged on
  open-frame printers (A1 mini, A1, A2L, P1P).
- **Print monitor** (`monitor.py`): alerts when the nozzle or bed goes above the printer's rating. An
  unknown printer gets the highest ratings in the table, so it never raises a false alarm.

## Materials

Values are Bambu Studio's profiles for Bambu Lab's own filament (Textured PEI plate for the bed). "Needs
enclosure" means Bambu Studio heats the chamber for this material on printers that can: expect warping
and fumes on an open printer. "Hardened nozzle" means the filament is fibre-filled and wears out a
stainless-steel nozzle (the A1 mini, A1, A2L, P1P and P1S ship with stainless steel).

<!-- generated:materials (tests/datagen/model_specs.py) -->
| Material | Nozzle | Bed | Chamber | Needs | AMS | Bambu Studio profile for |
|---|---|---|---|---|---|---|
| PLA | 190–240 °C | 55 °C | — | — | yes | all |
| PLA-CF | 210–250 °C | 55 °C | — | hardened nozzle | yes | all |
| PETG | 230–270 °C | 70 °C | — | — | yes | all |
| PETG-CF | 240–270 °C | 70 °C | — | hardened nozzle | yes | all |
| TPU 95A | 200–250 °C | 35 °C | — | — | **no** | all |
| TPU 90A | 200–240 °C | 35 °C | — | — | **no** | all |
| TPU 85A | 200–240 °C | 35 °C | — | — | **no** | all but A1 Mini, A1 |
| TPU for AMS | 220–240 °C | 35 °C | — | — | yes | all |
| ABS | 240–280 °C | 90 °C | 65 °C | enclosure | yes | all but A1 Mini, A2L |
| ASA | 240–280 °C | 100 °C | 65 °C | enclosure | yes | all but A1 Mini, A2L |
| PA | 240–280 °C | 100 °C | 60 °C | enclosure | yes | all but A1 Mini, A2L, P1S, X1C, X1E |
| PA-CF | 260–300 °C | 100 °C | 60 °C | enclosure, hardened nozzle | yes | all but A1 Mini, A2L |
| PC | 260–290 °C | 110 °C | 60 °C | enclosure | yes | all but A1 Mini, A2L |
| PVA | 210–250 °C | 55 °C | — | water-soluble | yes | all |
| BVOH | 190–240 °C | 55 °C | — | water-soluble | yes | all |
| Support for PLA | 190–240 °C | 55 °C | — | support only | yes | all |
| Support for PLA/PETG | 190–240 °C | 60 °C | — | support only | yes | all |
| Support for ABS | 240–270 °C | 90 °C | 60 °C | enclosure, support only | yes | all but A1 Mini, A2L |
| Support for PA/PET | 260–300 °C | 100 °C | 60 °C | enclosure, support only | yes | all but A1 Mini, A2L |
| PPA-CF | 280–320 °C | 100 °C | 60 °C | enclosure, hardened nozzle | yes | all but A1 Mini, A1, A2L |
| PPS-CF | 310–340 °C | 110 °C | 65 °C | heated chamber, hardened nozzle | yes | X1E, H2C, H2S, H2D, H2D Pro |

- **PEEK: not printable.** Needs a nozzle hotter than 350 °C and a chamber far above 65 °C; no Bambu Lab printer reaches either, and Bambu Studio has no profile for it.
- **PEI: not printable.** Needs a nozzle hotter than 350 °C and a chamber far above 65 °C; no Bambu Lab printer reaches either, and Bambu Studio has no profile for it.
- **PPSU: not printable.** Needs a nozzle hotter than 350 °C and a chamber far above 65 °C; no Bambu Lab printer reaches either, and Bambu Studio has no profile for it.
<!-- /generated:materials -->

- **TPU and the AMS.** Bambu Studio blocks every filament of type TPU in the AMS. Only *TPU for AMS* can
  be loaded there; other TPUs feed from the external spool holder.
- **Minimum wall** for every material is 0.9 mm with a 0.4 mm nozzle: two perimeters at Bambu Studio's
  default line widths (0.42 mm outer, 0.45 mm inner). Thinner walls print as a single line or gap fill.
- **Aliases.** `PLA+`, `PLA Basic` and `PLA Matte` resolve to PLA; `TPU` to TPU 95A; `PAHT-CF` and
  `PA6-CF` to PA-CF; `Support W` / `Support G` to the matching Bambu support filament.
- Colours for these materials are in [`assets/filaments.json`](../assets/filaments.json), converted from
  the colour table Bambu Studio ships.
