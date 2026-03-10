# Manifold3d — API Reference & 3D Printing Patterns

Agent reference for building functional parts with `parametric.py` (backed by manifold3d).
All dimensions in mm. Output is always watertight, manifold STL.

---

## 1. Core API (manifold3d Python)

### Primitives

| Function | Signature | Notes |
|----------|-----------|-------|
| `Manifold.cube(size)` | `size=[x, y, z]` | Corner at origin |
| `Manifold.cylinder(height, radius_low, radius_high)` | `radius_high` defaults to `radius_low` | Along Z axis |
| `Manifold.sphere(radius)` | | Centered at origin |

### 2D → 3D

| Function | Signature | Notes |
|----------|-----------|-------|
| `CrossSection([polygon])` | `polygon = [[x,y], ...]` | Closed polygon |
| `CrossSection.circle(radius)` | | |
| `CrossSection.square([w, h])` | | |
| `Manifold.extrude(cross_section, height)` | | Along Z |
| `Manifold.revolve(cross_section, segments)` | | Around Y axis |

### Boolean Operations

```python
union      = a + b        # or Manifold.batch_boolean([a, b], OpType.Add)
difference = a - b        # subtract b from a
intersect  = a ^ b        # keep only overlapping volume
```

Boolean operations are the core strength — they **always produce valid, watertight meshes**, unlike mesh-based boolean (trimesh/Blender) which can fail on edge cases.

### Transforms

```python
m = m.translate([dx, dy, dz])
m = m.rotate([rx, ry, rz])     # degrees, Euler XYZ
m = m.scale([sx, sy, sz])
m = m.mirror([nx, ny, nz])     # mirror across plane through origin
```

### Multi-Body

```python
# Keep bodies separate (not boolean-merged) — useful for enclosure + lid
combined = Manifold.compose([body, lid])

# Convex hull of multiple bodies
hull = Manifold.batch_hull([a, b, c])
```

### Export

```python
mesh = manifold.to_mesh()
verts = mesh.vert_properties[:, :3]   # Nx3 numpy array
faces = mesh.tri_verts               # Mx3 numpy array
# Use trimesh for file I/O:
trimesh.Trimesh(vertices=verts, faces=faces).export("output.stl")
```

---

## 2. parametric.py CLI Reference

### Primitives

```bash
python3 scripts/parametric.py box <width> <depth> <height> [--center] -o out.stl
python3 scripts/parametric.py cylinder --radius 5 --height 20 [--radius-top 3] [--segments 64] -o out.stl
python3 scripts/parametric.py sphere --radius 10 [--segments 64] -o out.stl
python3 scripts/parametric.py extrude --polygon "[[0,0],[20,0],[20,10],[0,10]]" --height 5 -o out.stl
```

### Built-in Part Helpers

```bash
# L-bracket with M3 mounting holes and 2mm fillet
python3 scripts/parametric.py bracket --width 30 --height 40 --thickness 3 --hole-diameter 3.2 --fillet 2 -o bracket.stl

# Mounting plate with 4x M3 holes, 25mm spacing
python3 scripts/parametric.py plate-with-holes --width 60 --depth 40 --thickness 3 --holes 4 --hole-diameter 3.2 --hole-spacing 25 -o plate.stl

# Hollow enclosure with snap-fit lid
python3 scripts/parametric.py enclosure --width 60 --depth 40 --height 30 --wall 2 --lid -o enclosure.stl
```

### CSG from JSON Spec

For complex parts, write a JSON spec and pass it to `csg`:

```bash
python3 scripts/parametric.py csg spec.json -o assembly.stl
```

Spec format:

```json
{
  "ops": [
    {"type": "cube", "size": [40, 30, 5], "id": "base"},
    {"type": "cylinder", "height": 20, "radius": 4, "translate": [20, 15, 5], "id": "post"},
    {"type": "add", "a": "base", "b": "post", "id": "body"},
    {"type": "cylinder", "height": 25, "radius": 1.6, "translate": [20, 15, 0], "id": "screw_hole"},
    {"type": "subtract", "a": "body", "b": "screw_hole"}
  ]
}
```

Available op types:
- **Primitives**: `cube`, `cylinder`, `sphere`, `extrude`, `revolve`
- **Boolean**: `add`/`union`, `subtract`/`difference`, `intersect`/`intersection`
- **Combine**: `hull`, `compose`

Each primitive supports optional `translate`, `rotate`, `scale` fields.

---

## 3. FDM Printing Tolerances

### Screw Holes (clearance fit — screw passes through freely)

| Screw | Nominal (mm) | Hole Diameter (mm) | Notes |
|-------|-------------|-------------------|-------|
| M2    | 2.0         | 2.2               | |
| M2.5  | 2.5         | 2.7               | |
| M3    | 3.0         | 3.2               | Most common for 3D printing |
| M4    | 4.0         | 4.2               | |
| M5    | 5.0         | 5.2               | |
| M6    | 6.0         | 6.2               | |
| M8    | 8.0         | 8.2               | |

### Heat-Set Insert Holes

| Insert | Hole Diameter (mm) | Depth = insert length + 1mm |
|--------|-------------------|------------------------------|
| M2     | 3.2               | |
| M3     | 4.0               | Standard for functional prints |
| M4     | 5.6               | |
| M5     | 6.4               | |

### General Fit Tolerances

| Fit Type | Gap (mm) | Use Case |
|----------|----------|----------|
| Press fit | 0.1     | Tight, permanent — parts stay together without fasteners |
| Slip fit  | 0.2     | Slides in/out easily — lids, caps, sleeves |
| Clearance | 0.3     | Free movement — hinges, sliding joints |

### Wall Thickness Minimums

| Material | Min Wall (mm) | Recommended (mm) |
|----------|--------------|-------------------|
| PLA      | 0.8          | 1.2 - 2.0        |
| PETG     | 1.0          | 1.5 - 2.0        |
| ABS/ASA  | 1.0          | 1.5 - 2.0        |
| TPU      | 1.2          | 2.0+              |

### Design Rules

- **Overhangs**: Max 45° without supports. Use chamfers instead of fillets on bottom faces.
- **Bridges**: Up to 10mm unsupported span for PLA. Add support ribs for longer spans.
- **Holes**: Print vertical holes (along Z) when possible — horizontal holes need supports or teardrop shapes.
- **Text/Engravings**: Min 0.5mm depth, 1mm line width for legibility.
- **Snap-fit clips**: 0.3mm gap, 1.5-2mm deflection, 30-45° entry angle.
- **Chamfers > fillets** on build-plate faces (fillets lift off the bed).

---

## 4. Common Part Patterns (CSG JSON examples)

### Phone Stand

```json
{
  "ops": [
    {"type": "cube", "size": [80, 50, 5], "id": "base"},
    {"type": "cube", "size": [80, 5, 60], "translate": [0, 0, 5], "id": "back"},
    {"type": "add", "a": "base", "b": "back", "id": "body"},
    {"type": "cube", "size": [80, 15, 3], "translate": [0, 0, 5], "id": "lip"},
    {"type": "add", "a": "body", "b": "lip", "id": "with_lip"},
    {"type": "cube", "size": [30, 10, 40], "translate": [25, -2, 10], "id": "cable_slot"},
    {"type": "subtract", "a": "with_lip", "b": "cable_slot"}
  ]
}
```

### Wall Hook

```json
{
  "ops": [
    {"type": "cube", "size": [30, 30, 4], "id": "plate"},
    {"type": "cylinder", "height": 6, "radius": 2.5, "translate": [8, 8, -1], "id": "hole1"},
    {"type": "cylinder", "height": 6, "radius": 2.5, "translate": [22, 22, -1], "id": "hole2"},
    {"type": "subtract", "a": "plate", "b": "hole1", "id": "plate_h1"},
    {"type": "subtract", "a": "plate_h1", "b": "hole2", "id": "plate_done"},
    {"type": "cube", "size": [30, 4, 25], "translate": [0, 26, 4], "id": "arm"},
    {"type": "add", "a": "plate_done", "b": "arm", "id": "body"},
    {"type": "cylinder", "height": 30, "radius": 6, "translate": [15, 35, 29], "rotate": [90, 0, 0], "id": "hook_curve"},
    {"type": "add", "a": "body", "b": "hook_curve"}
  ]
}
```

### Raspberry Pi Case (simplified)

```json
{
  "ops": [
    {"type": "cube", "size": [90, 62, 30], "id": "outer"},
    {"type": "cube", "size": [86, 58, 28], "translate": [2, 2, 2], "id": "inner"},
    {"type": "subtract", "a": "outer", "b": "inner", "id": "shell"},
    {"type": "cylinder", "height": 5, "radius": 1.3, "translate": [5.5, 5.5, 2], "id": "standoff1"},
    {"type": "cylinder", "height": 5, "radius": 1.3, "translate": [84.5, 5.5, 2], "id": "standoff2"},
    {"type": "cylinder", "height": 5, "radius": 1.3, "translate": [5.5, 56.5, 2], "id": "standoff3"},
    {"type": "cylinder", "height": 5, "radius": 1.3, "translate": [84.5, 56.5, 2], "id": "standoff4"},
    {"type": "add", "a": "shell", "b": "standoff1", "id": "s1"},
    {"type": "add", "a": "s1", "b": "standoff2", "id": "s2"},
    {"type": "add", "a": "s2", "b": "standoff3", "id": "s3"},
    {"type": "add", "a": "s3", "b": "standoff4", "id": "case"},
    {"type": "cube", "size": [20, 4, 8], "translate": [25, -1, 10], "id": "usb_cutout"},
    {"type": "subtract", "a": "case", "b": "usb_cutout"}
  ]
}
```

---

## 5. When to Use Parametric vs AI Generation

| Signal | → Parametric | Example |
|--------|-------------|---------|
| Specific dimensions / tolerances | YES | "M3 screw hole", "inner diameter 40mm" |
| Standard interfaces | YES | "USB-C cutout", "GoPro mount base" |
| Functional keywords | YES | "bracket", "hinge", "hook", "clip", "gear", "mount", "enclosure", "stand" |
| Mating / assembly | YES | "lid that fits on", "snap into place" |
| Geometric shapes only | YES | "box with holes", "cylinder with slot" |

| Signal | → AI Generate | Example |
|--------|-------------|---------|
| Characters / figurines | YES | "pikachu", "dragon", "bust" |
| Organic / artistic forms | YES | "vase", "sculpture", "tree" |
| No dimensional constraints | YES | "something cool for my desk" |
| Photo reference | Image-to-3D | user sends a photo |

**Hybrid**: For "dragon-shaped phone stand" — AI-generate the dragon body, parametric for the phone cradle, combine in Bambu Studio.
