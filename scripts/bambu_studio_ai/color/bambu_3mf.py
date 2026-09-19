"""Write (and read back) a Bambu Studio project 3MF whose triangles are painted by filament.

The project is what Bambu Studio 2.7 itself writes, cut down to the parts it needs:
``3D/3dmodel.model`` (marked as a Bambu Studio file, so it opens as a project) points
at ``3D/Objects/object_1.model``, whose triangles carry ``paint_color``; and
``Metadata/project_settings.config`` lists one filament per palette colour.

The settings come from ``bambu_template/project_settings.config``: the file Bambu Studio
02.07.01.62 exported for one PLA Basic filament on the Bambu Lab A1 (0.4 mm) system
profiles. Opening a project re-selects those system profiles by name. For N filaments
every per-filament setting (``bambu_template/per_filament_keys.json``, the keys whose
length grew 1 → 2 → 3 in exports with 1, 2 and 3 filaments) is repeated N times. They
must all have exactly N entries: the slicer enables painted multi-material slicing only
when ``filament_diameter`` has more than one entry, and it sizes the painted regions by
``filament_colour``, so a mismatch either ignores the paint or crashes the slicer.
"""

from __future__ import annotations

import io
import json
import re
import zipfile
from collections.abc import Sequence
from dataclasses import dataclass
from importlib import resources
from typing import Any, cast

import numpy as np
from numpy.typing import NDArray

from bambu_studio_ai.color.lab import FloatArray

TEMPLATE_PRINTER = "Bambu Lab A1 0.4 nozzle"
PROJECT_VERSION = "02.07.01.62"
DEFAULT_FLUSH_MM3 = "280"
"""Purge volume between two different filaments, as in Bambu Studio's PLA defaults."""
PRIME_TOWER_ALLOWANCE_MM = 66.0
"""Room to leave behind the prime tower's position. In G-code sliced by Bambu Studio 2.7
the tower reached 23 mm (2 filaments) to 60 mm (8 filaments) past it; at the template's
y = 220 a tower for four or more filaments ran off the A1's 256 mm bed and the slice was
refused as "G-code outside of the printable area"."""

_CORE = "http://schemas.microsoft.com/3dmanufacturing/core/2015/02"
_NAMESPACES = (
    f'xmlns="{_CORE}" xmlns:BambuStudio="http://schemas.bambulab.com/package/2021" '
    'xmlns:p="http://schemas.microsoft.com/3dmanufacturing/production/2015/06" '
    'requiredextensions="p"'
)
_RELS_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
_MODEL_REL = "http://schemas.microsoft.com/3dmanufacturing/2013/01/3dmodel"
_OBJECT_PATH = "3D/Objects/object_1.model"
_TRIANGLE = re.compile(
    rb'<triangle v1="(\d+)" v2="(\d+)" v3="(\d+)"(?: paint_color="([0-9A-F]*)")?'
)
_VERTEX = re.compile(rb'<vertex x="([^"]+)" y="([^"]+)" z="([^"]+)"')
_SHORT_CODES = {1: "4", 2: "8"}
_FIRST_LONG_STATE = 3
MAX_PAINT_FILAMENT = _FIRST_LONG_STATE + 15
"""The highest filament a two-nibble whole-triangle code can name."""
_LONG_CODE = re.compile(r"([0-9A-F])C")


def paint_code(filament: int) -> str:
    """``paint_color`` for a whole triangle painted with ``filament`` (1-based).

    Bambu Studio serialises paint as a bit stream written in hex nibbles, last nibble
    first: two bits of "not split", then the state in two bits, or ``11`` plus four more
    bits holding ``state - 3``. Filament 1 is ``"4"``, 2 is ``"8"``, 3 is ``"0C"``, 8 is
    ``"5C"``. Upper case only: the reader rejects lower-case digits.
    """
    if not 1 <= filament <= MAX_PAINT_FILAMENT:
        raise ValueError(f"filament must be between 1 and {MAX_PAINT_FILAMENT}, not {filament}")
    return _SHORT_CODES.get(filament) or f"{filament - _FIRST_LONG_STATE:X}C"


def paint_filament(code: str) -> int | None:
    """Inverse of :func:`paint_code`; ``None`` for split (partly painted) triangles."""
    for filament, short in _SHORT_CODES.items():
        if code == short:
            return filament
    match = _LONG_CODE.fullmatch(code)
    return int(match.group(1), 16) + _FIRST_LONG_STATE if match else None


@dataclass(frozen=True)
class ProjectContents:
    """What :func:`read_project` found in a 3MF."""

    vertices: FloatArray
    faces: NDArray[np.int64]
    filaments: NDArray[np.int64]
    """1-based filament per triangle; 0 for unpainted or split triangles."""
    settings: dict[str, Any]
    build_offset: FloatArray


def build_project(
    vertices: FloatArray,
    faces: NDArray[np.int64],
    labels: NDArray[np.int64],
    colours: Sequence[str],
    name: str,
) -> bytes:
    """Return a Bambu Studio project 3MF, as bytes.

    Args:
        vertices: ``(V, 3)`` positions in mm, Z up.
        faces: ``(F, 3)`` vertex indices.
        labels: ``(F,)`` 0-based palette index of every triangle.
        colours: ``#RRGGBB`` of each filament, in filament order.
        name: object name shown in Bambu Studio's object list.
    """
    settings = project_settings(colours)
    low, high = vertices.min(axis=0), vertices.max(axis=0)
    centred = vertices - (low + high) / 2
    bed_x, bed_y = _bed_centre(settings)
    offset = (bed_x, bed_y, float(high[2] - low[2]) / 2)
    codes = [paint_code(i + 1) for i in range(len(colours))]
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", _CONTENT_TYPES)
        archive.writestr("_rels/.rels", _rels("/3D/3dmodel.model"))
        archive.writestr("3D/3dmodel.model", _root_model(name, offset))
        archive.writestr("3D/_rels/3dmodel.model.rels", _rels("/" + _OBJECT_PATH))
        archive.writestr(_OBJECT_PATH, _object_model(centred, faces, labels, codes))
        archive.writestr("Metadata/model_settings.config", _model_settings(name, len(faces)))
        archive.writestr("Metadata/project_settings.config", json.dumps(settings, indent=4))
    return buffer.getvalue()


def project_settings(colours: Sequence[str]) -> dict[str, Any]:
    """The template settings resized to ``len(colours)`` filaments."""
    count = len(colours)
    if count < 1:
        raise ValueError("a project needs at least one filament")
    template = resources.files("bambu_studio_ai.color").joinpath("bambu_template")
    settings = cast(
        "dict[str, Any]",
        json.loads(template.joinpath("project_settings.config").read_text("utf-8")),
    )
    per_filament = cast(
        "list[str]", json.loads(template.joinpath("per_filament_keys.json").read_text("utf-8"))
    )
    for key in per_filament:
        settings[key] = list(settings[key][:1]) * count
    flush = [
        ["0" if row == column else DEFAULT_FLUSH_MM3 for column in range(count)]
        for row in range(count)
    ]
    settings.update(
        {
            "filament_colour": [colour.upper() for colour in colours],
            "filament_self_index": [str(i + 1) for i in range(count)],
            "filament_map": ["1"] * count,
            "filament_nozzle_map": ["1"] * count,
            "filament_volume_map": ["0"] * count,
            "flush_volumes_matrix": [value for row in flush for value in row],
            "flush_volumes_vector": ["140"] * (2 * count),
            # print, filament 1..N, printer: empty = "same as the system profile".
            "different_settings_to_system": [""] * (count + 2),
            "inherits_group": [""] * (count + 2),
        }
    )
    bed_back = max(float(point.split("x")[1]) for point in settings["printable_area"])
    tower_y = min(float(settings["wipe_tower_y"][0]), bed_back - PRIME_TOWER_ALLOWANCE_MM)
    settings["wipe_tower_y"] = [f"{tower_y:g}"]
    return settings


def read_project(data: bytes) -> ProjectContents:
    """Parse a project written by :func:`build_project` (or by Bambu Studio)."""
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        mesh = archive.read(_OBJECT_PATH)
        settings = cast(
            "dict[str, Any]", json.loads(archive.read("Metadata/project_settings.config"))
        )
        root = archive.read("3D/3dmodel.model").decode("utf-8")
    vertices = np.array([[float(v) for v in m.groups()] for m in _VERTEX.finditer(mesh)])
    triangles = [m.groups() for m in _TRIANGLE.finditer(mesh)]
    faces = np.array([[int(t[0]), int(t[1]), int(t[2])] for t in triangles], dtype=np.int64)
    filaments = np.array([_filament_or_zero(t[3]) for t in triangles], dtype=np.int64)
    transform = re.search(r'<item [^>]*transform="([^"]+)"', root)
    offset = (
        np.array([float(v) for v in transform.group(1).split()[9:12]]) if transform else np.zeros(3)
    )
    return ProjectContents(
        np.reshape(vertices, (-1, 3)), np.reshape(faces, (-1, 3)), filaments, settings, offset
    )


def _rows(array: NDArray[Any]) -> list[list[Any]]:
    """``ndarray.tolist()`` for a 2-D array (numpy's stubs leave it untyped)."""
    return cast("list[list[Any]]", array.tolist())


def _filament_or_zero(code: bytes | None) -> int:
    return (paint_filament(code.decode()) or 0) if code is not None else 0


def _bed_centre(settings: dict[str, Any]) -> tuple[float, float]:
    corners = np.array(
        [[float(v) for v in point.split("x")] for point in settings["printable_area"]]
    )
    centre = (corners.min(axis=0) + corners.max(axis=0)) / 2
    return float(centre[0]), float(centre[1])


def _root_model(name: str, offset: tuple[float, float, float]) -> str:
    x, y, z = offset
    # The UUIDs are the ones Bambu Studio writes for the first object of a project.
    component = (
        f'<component p:path="/{_OBJECT_PATH}" objectid="1" '
        'p:UUID="00010000-b206-40ff-9872-83e8017abed1" transform="1 0 0 0 1 0 0 0 1 0 0 0"/>'
    )
    item = (
        '<item objectid="2" p:UUID="00000002-b1ec-4553-aec9-835e5b724bb4" '
        f'transform="1 0 0 0 1 0 0 0 1 {x:.4f} {y:.4f} {z:.4f}" printable="1"/>'
    )
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<model unit="millimeter" xml:lang="en-US" {_NAMESPACES}>
 <metadata name="Application">BambuStudio-{PROJECT_VERSION}</metadata>
 <metadata name="BambuStudio:3mfVersion">1</metadata>
 <metadata name="Title">{_escape(name)}</metadata>
 <resources>
  <object id="2" p:UUID="00000001-61cb-4c03-9d28-80fed5dfa1dc" type="model">
   <components>
    {component}
   </components>
  </object>
 </resources>
 <build p:UUID="2c7c17d8-22b5-4d84-8835-1976022ea369">
  {item}
 </build>
</model>
"""


def _object_model(
    vertices: FloatArray, faces: NDArray[np.int64], labels: NDArray[np.int64], codes: list[str]
) -> str:
    vertex_lines = [
        f'     <vertex x="{x:.5f}" y="{y:.5f}" z="{z:.5f}"/>' for x, y, z in _rows(vertices)
    ]
    code_of = [codes[label] for label in cast("list[int]", labels.tolist())]
    triangle_lines = [
        f'     <triangle v1="{a}" v2="{b}" v3="{c}" paint_color="{code}"/>'
        for (a, b, c), code in zip(_rows(faces), code_of, strict=True)
    ]
    return "\n".join(
        [
            '<?xml version="1.0" encoding="UTF-8"?>',
            f'<model unit="millimeter" xml:lang="en-US" {_NAMESPACES}>',
            ' <metadata name="BambuStudio:3mfVersion">1</metadata>',
            " <resources>",
            '  <object id="1" p:UUID="00010000-81cb-4c03-9d28-80fed5dfa1dc" type="model">',
            "   <mesh>",
            "    <vertices>",
            *vertex_lines,
            "    </vertices>",
            "    <triangles>",
            *triangle_lines,
            "    </triangles>",
            "   </mesh>",
            "  </object>",
            " </resources>",
            " <build/>",
            "</model>",
            "",
        ]
    )


def _model_settings(name: str, face_count: int) -> str:
    value = f'"{_escape(name)}"'
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<config>
  <object id="2">
    <metadata key="name" value={value}/>
    <metadata key="extruder" value="1"/>
    <metadata face_count="{face_count}"/>
    <part id="1" subtype="normal_part">
      <metadata key="name" value={value}/>
      <metadata key="matrix" value="1 0 0 0 0 1 0 0 0 0 1 0 0 0 0 1"/>
    </part>
  </object>
  <plate>
    <metadata key="plater_id" value="1"/>
    <metadata key="plater_name" value=""/>
    <metadata key="locked" value="false"/>
    <model_instance>
      <metadata key="object_id" value="2"/>
      <metadata key="instance_id" value="0"/>
      <metadata key="identify_id" value="1"/>
    </model_instance>
  </plate>
</config>
"""


def _rels(target: str) -> str:
    return (
        f'<?xml version="1.0" encoding="UTF-8"?>\n<Relationships xmlns="{_RELS_NS}">\n'
        f' <Relationship Target="{target}" Id="rel-1" Type="{_MODEL_REL}"/>\n</Relationships>\n'
    )


def _escape(text: str) -> str:
    return (
        text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")
    )


_CONTENT_TYPES = """<?xml version="1.0" encoding="UTF-8"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
 <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
 <Default Extension="model" ContentType="application/vnd.ms-package.3dmanufacturing-3dmodel+xml"/>
 <Default Extension="png" ContentType="image/png"/>
</Types>
"""
