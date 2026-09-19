# Third-party notices

The skill's own code is MIT-licensed (see [LICENSE](LICENSE)). Some data files come from
other projects and keep their own licences.

## Bambu Studio

[Bambu Studio](https://github.com/bambulab/BambuStudio) by Bambu Lab and contributors is
licensed under the [GNU Affero General Public License v3.0](https://github.com/bambulab/BambuStudio/blob/master/LICENSE).
The files below were taken from Bambu Studio 02.07.01.62 (profiles 02.07.00.08), or produced by
it, and remain under that licence:

| Path | What it is |
| --- | --- |
| `tests/fixtures/slicing/profiles/` | Trimmed copies of Bambu Studio's system printer, process and filament profiles (`resources/profiles/BBL`), used only by the tests |
| `tests/fixtures/slicing/plate_1_header.gcode`, `result_p1s_box.json` | Output of the Bambu Studio command line, used only by the tests |
| `scripts/bambu_studio_ai/color/bambu_template/project_settings.config` | Project settings exported by Bambu Studio for one PLA Basic filament on the A1 (0.4 mm); the multi-colour 3MF writer starts from it |
| `scripts/bambu_studio_ai/color/bambu_template/per_filament_keys.json` | Names of the per-filament settings in that file |

These files hold figures read from Bambu Studio's profiles, its printer files and its filament
colour table (`filaments_color_codes.json`): `assets/printers.json`, `assets/materials.json`,
`assets/filaments.json` and the tables in `references/model-specs.md`. The scripts in
`tests/datagen/` regenerate the material and filament files from an installed Bambu Studio.

The skill contains no Bambu Studio code. `slice.py` and `preview.py` run the copy of Bambu Studio
that the user installed, as a separate program.

"Bambu Lab", "Bambu Studio" and "MakerWorld" are trademarks of their owner. This project is
independent and is not developed or supported by Bambu Lab.
