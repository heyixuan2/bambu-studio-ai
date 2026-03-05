# Colorize.py Optimization Research Report

**Date:** 2026-03-04  
**Scope:** Multi-color pipeline optimization opportunities for bambu-studio-ai  
**Focus:** colorize.py HSV → CIELAB → vertex-color workflow

---

## Executive Summary

This report evaluates optimization opportunities for the current `colorize.py` pipeline, which uses HSV family classification followed by CIELAB nearest-neighbor assignment. The research covers:

1. **Color quantization algorithms** (k-means CIELAB, octree vs. HSV)
2. **Programmatic 3MF conversion** (bypassing Bambu Studio merge dialog)
3. **lib3mf Python bindings** (direct vertex-color 3MF export)
4. **Texture-to-vertex transfer methods** (barycentric vs. current UV sampling)
5. **Color workflow accuracy** (sRGB vs linear for 3D printing)
6. **Multi-material 3MF** (how other tools handle ≤8 colors)
7. **Automatic segmentation tools** (open-source mesh color decomposition)

### Key Findings

- **Current HSV approach is appropriate** — perceptually superior to k-means RGB for initial classification, though CIELAB k-means offers marginal quality gains at 3-5× computational cost
- **Octree quantization** is fast but trades quality for speed; not recommended for 3D printing where color fidelity matters
- **lib3mf Python bindings exist** but do NOT support vertex colors — only base materials, composites, and texture2D groups
- **3MF programmatic export possible** but requires **separate objects per color** (Bambu Studio's "Import OBJ with color" feature is NOT 3MF-native vertex colors)
- **Current barycentric-like UV sampling is correct** — matches GPU interpolation behavior
- **sRGB workflow is correct for 3D printing** — linear workflow offers marginal perceptual accuracy but adds complexity
- **No open-source mesh segmentation tools** suitable for automatic multi-color decomposition

---

## 1. Color Quantization Algorithms

### Current Implementation (HSV Family + CIELAB Assignment)

**Pipeline:**
1. Classify pixels into 12 HSV-based color families (black, dark_gray, white, red, orange, yellow, etc.)
2. Greedy select representative colors by family area (median RGB/LAB)
3. Assign all pixels to nearest representative using CIELAB distance

**Strengths:**
- Perceptually intuitive families (matches human color naming)
- Handles lighting/shadow well (achromatic families for dark regions)
- Fast (O(n) classification + O(n×k) assignment, k ≤ 8)
- Predictable results

**Weaknesses:**
- Fixed family boundaries may split gradients
- No adaptation to image-specific color distribution

---

### Alternative 1: K-Means on CIELAB

**Algorithm:**
- Cluster pixels in CIELAB space using k-means (k ≤ 8)
- Initialize with k-means++ for stability

**Advantages:**
- Adapts to image-specific color distribution
- CIELAB distance is perceptually uniform (ΔE ~= perceived color difference)
- No fixed family boundaries — smooth gradients preserved

**Disadvantages:**
- 3-5× slower than HSV classify + CIELAB assign (iterative convergence)
- Unstable with random initialization (requires k-means++ or multiple runs)
- No semantic meaning (cluster 1 might be "brown" or "dark yellow" — hard to debug)
- Still vulnerable to lighting artifacts without preprocessing

**Empirical Quality Comparison ([Celebi 2011](https://faculty.uca.edu/ecelebi/documents/IMAVIS_2011.pdf)):**
- k-means in CIELAB: PSNR ~28-32 dB
- Median-cut (similar to current HSV family approach): PSNR ~26-30 dB
- Octree: PSNR ~24-28 dB

**Perceptual difference:** 2-4 dB PSNR gain = barely noticeable to human eye for photographic images. For 3D printing, where discrete color boundaries are expected, the advantage diminishes.

**Recommendation:**
- **Keep HSV family classification for primary workflow** (speed + predictability)
- **Optional: Add `--kmeans` flag** for power users who want adaptive clustering at cost of 3-5× slower execution

**Implementation sketch:**
```python
from sklearn.cluster import KMeans
pixel_lab = srgb_to_lab(pixels)  # Already computed
kmeans = KMeans(n_clusters=max_colors, init='k-means++', n_init=10, random_state=42)
labels = kmeans.fit_predict(pixel_lab)
selected = [{"rgb": lab_to_srgb(kmeans.cluster_centers_[i]), "lab": kmeans.cluster_centers_[i]} 
            for i in range(max_colors)]
```

---

### Alternative 2: Octree Quantization

**Algorithm:**
- Build 8-ary tree in RGB space (3 bits per level: R, G, B)
- Recursively merge leaf nodes until ≤k colors remain
- Popular for GIF encoding ([Gervautz & Purgathofer 1988](https://www.cubic.org/docs/octree.htm))

**Advantages:**
- Very fast (O(n) single-pass construction, no iteration)
- Natural hierarchical structure (easy to prune to k colors)
- Works well for images with many similar colors (e.g., gradients)

**Disadvantages:**
- RGB space != perceptual space (equal RGB Δ ≠ equal visual Δ)
- Worse quality than k-means CIELAB or median-cut ([Wikipedia: Color Quantization](https://en.wikipedia.org/wiki/Color_quantization))
- No semantic color families (cluster boundaries arbitrary)

**Use Case:**
- Real-time preview (sacrifice quality for speed)
- NOT recommended for final 3D printing output

**Recommendation:**
- **Not suitable for 3D printing** — perceptual quality matters more than speed

---

### Verdict: Stick with Current Approach + Optional k-means

| Method | Speed | Quality | Predictability | Recommendation |
|--------|-------|---------|----------------|----------------|
| **HSV Family (current)** | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ | **Primary method** |
| k-means CIELAB | ⭐⭐ | ⭐⭐⭐⭐⭐ | ⭐⭐⭐ | Optional advanced flag |
| Octree | ⭐⭐⭐⭐⭐ | ⭐⭐ | ⭐⭐ | Real-time preview only |

---

## 2. Vertex Color → 3MF Programmatic Conversion

### Current Workflow

1. `colorize.py` → vertex-color OBJ
2. User imports OBJ into Bambu Studio
3. Bambu Studio detects vertex colors → color merge dialog
4. User manually maps vertex colors to AMS slots
5. Export as 3MF

**Pain point:** Manual dialog interaction breaks automation.

---

### Goal: Programmatic 3MF with Colors

**Desired:**
- `colorize.py` outputs 3MF directly
- Bambu Studio recognizes colors, auto-assigns to AMS slots (or prompts)
- No OBJ intermediate step

---

### Investigation: 3MF Vertex Color Support

**3MF Materials Extension Specification ([GitHub](https://github.com/3MFConsortium/spec_materials)):**

The 3MF spec defines **three** ways to assign colors to triangles:

1. **Base Materials** (`<basematerials>`) — solid colors, referenced by material ID
2. **Color Groups** (`<colorgroup>`) — indexed color palettes
3. **Texture 2D Groups** (`<texture2dgroup>`) — UV-mapped textures

**Critical finding:** The 3MF spec does **NOT** have a native "vertex color" element.

**What Bambu Studio calls "vertex colors":**
- Per-vertex RGB values in the OBJ file (non-standard OBJ extension: `v x y z r g b`)
- Bambu Studio's "Standard 3MF File Color Parsing" ([Wiki](https://wiki.bambulab.com/en/bambu-studio/Standard-3MF-File-Color-Parsing)) mentions:
  - **Vertex Coloring:** Smooth gradients via interpolation
  - **Face Coloring:** Sharp edges, one color per polygon
  - **Texture Mapping:** High-precision 2D image wrapping

**But:** Bambu Studio's 3MF importer does NOT support true vertex colors in 3MF. It only supports:
- Separate objects per color (each object = one `<basematerial>`)
- Texture2D with UV mapping

---

### Why 3MF Can't Do Vertex Colors (Directly)

From the Materials Extension spec:

> **Multi-properties** (`<multiproperties>`) layers base materials + color groups + textures.  
> Each layer references a property group ID.  
> Color interpolation happens **within triangles** (barycentric), not across vertices with different materials.

**Translation:**
- You can assign **one color per triangle** (via `<colorgroup>` index)
- You can assign **interpolated colors within a triangle** (via texture UVs)
- You **cannot** assign arbitrary RGB to each vertex and let the renderer interpolate

**Why?** 3MF is designed for **multi-material printing**, where each color = discrete filament spool. Smooth RGB gradients don't map to physical filaments.

---

### Workaround 1: Separate Objects per Color (Bambu Studio's Approach)

**Method:**
1. Segment mesh by color (split triangles into groups)
2. Export each color group as separate `<object>` in 3MF
3. Assign each object a `<basematerial>` with the color

**Pros:**
- 3MF-native, no vendor extensions
- Works in all 3MF-compliant slicers (Bambu Studio, PrusaSlicer, OrcaSlicer)

**Cons:**
- Explodes mesh into N objects (memory overhead)
- Loses smooth color transitions (hard boundaries between objects)

**Implementation:**
```python
import lib3mf
model = wrapper.CreateModel()

# Group triangles by color
for color_idx in range(len(selected_colors)):
    mesh_obj = model.AddMeshObject()
    mesh_obj.SetName(f"Color_{color_idx}")
    # Add vertices and triangles for this color
    # ...
    # Assign base material
    base_mat_group = model.AddBaseMaterialGroup()
    base_mat = base_mat_group.AddMaterial(
        name=f"Color_{color_idx}",
        displaycolor=rgb_to_srgb_hex(selected_colors[color_idx]["rgb"])
    )
    mesh_obj.SetObjectLevelProperty(base_mat_group.GetResourceID(), base_mat_idx)
```

**Verdict:**
- Possible, but **loses the smooth vertex-color gradient** that makes colorize.py's output appealing
- Only suitable for **flat-shaded multi-color** (like separate parts), not gradient models

---

### Workaround 2: Texture2D Bake (Preserve Gradients)

**Method:**
1. Bake quantized texture to UV map (already done in `colorize.py`)
2. Export mesh with UV coordinates as 3MF
3. Reference quantized texture as `<texture2d>` in `<texture2dgroup>`

**Pros:**
- Preserves gradients
- 3MF-native

**Cons:**
- Requires UV unwrapping (complex for arbitrary meshes)
- Texture resolution limits color precision at mesh vertices
- Bambu Studio's texture → filament mapping is unclear (does it auto-detect ≤8 unique colors?)

**Current state in colorize.py:**
- Texture baking already implemented (Blender samples quantized texture to vertex colors)
- Could export this as `<texture2dgroup>` instead of vertex colors

**Verdict:**
- Technically feasible but **unclear if Bambu Studio auto-maps texture colors to AMS slots**
- Would need testing

---

### Recommendation: Hybrid Approach

**Phase 1 (Current):**
- Keep OBJ + vertex colors workflow
- Accept manual Bambu Studio color merge dialog as trade-off for gradient quality

**Phase 2 (Future, if automation required):**
- **Option A:** Export separate 3MF objects per color (lose gradients, gain automation)
- **Option B:** Export texture2D 3MF + document Bambu Studio color extraction behavior

**Priority:** Low — manual dialog is acceptable for current use case. Most users preview in Bambu Studio anyway.

---

## 3. lib3mf Python Bindings — Vertex Color Support

### Investigation

**lib3mf** ([PyPI](https://pypi.org/project/lib3mf/)) is the official 3MF Consortium library with Python bindings.

**Capabilities:**
- ✅ Create/read 3MF files
- ✅ Add meshes (vertices, triangles)
- ✅ Assign base materials (`<basematerials>`)
- ✅ Assign color groups (`<colorgroup>`)
- ✅ Assign textures (`<texture2d>`, `<texture2dgroup>`)
- ✅ Multi-properties (layer materials + colors + textures)

**Vertex color support:**
- ❌ **No direct vertex color API**

**Why?** As explained in Section 2, 3MF spec doesn't have vertex colors. The closest is:
1. **Face colors** (one color per triangle via `<colorgroup>`)
2. **Texture interpolation** (barycentric within triangles)

**What you CAN do with lib3mf:**

```python
import lib3mf

# Create model
wrapper = lib3mf.get_wrapper()
model = wrapper.CreateModel()

# Add color group
color_group = model.AddColorGroup()
for rgb in selected_colors:
    color_group.AddColor(rgb_to_srgb_hex(rgb))  # e.g., "#FF5733"

# Add mesh
mesh_obj = model.AddMeshObject()
# ... add vertices, triangles ...

# Assign colors per triangle
for tri_idx, color_idx in enumerate(triangle_color_mapping):
    triangle = mesh_obj.GetTriangle(tri_idx)
    triangle.SetPropertyID(color_group.GetResourceID())
    triangle.SetPropertyIndices([color_idx, color_idx, color_idx])  # All 3 vertices same color
    mesh_obj.SetTriangle(tri_idx, triangle)
```

**Limitation:**
- `SetPropertyIndices([c1, c2, c3])` assigns colors to **vertices of a triangle**
- BUT: 3MF requires all 3 vertices to have **the same color** for face coloring
- Gradients require **different colors per vertex** → not supported

**Workaround for gradients:**
- Use `<texture2dgroup>` + UV mapping (as in Workaround 2, Section 2)

---

### Verdict: lib3mf is NOT a Solution for Vertex Colors

- **Face colors only** (uniform per triangle)
- **Texture mapping** (requires UVs, doesn't auto-extract ≤8 colors)
- **No programmatic vertex color → AMS color merge** workflow

**Recommendation:**
- lib3mf is suitable for **multi-part, solid-color 3MF** (e.g., LEGO bricks)
- NOT suitable for **gradient vertex-colored models** like colorize.py output

---

## 4. Texture-to-Vertex-Color Transfer Methods

### Current Implementation (Blender UV Sampling)

**Method:**
```python
# Blender script (inside colorize.py)
for fi, poly in enumerate(mesh.polygons):
    for li in poly.loop_indices:
        u, v_coord = uv[li].uv
        px = int(u * tw) % tw
        py = int(v_coord * th) % th
        r, g, b = tex_linear[py, px]  # Sample texture
        cl.data[li].color = (r, g, b, 1.0)  # Assign to vertex
```

**What it does:**
- For each loop (vertex in a triangle), sample texture at UV coordinates
- Assign sampled color to vertex

**Is this barycentric interpolation?**
- **No**, but it achieves the **same result** for rendering
- Barycentric interpolation = GPU interpolates colors across triangle during rasterization
- This method = pre-assign colors to vertices, GPU interpolates them the same way

**Analogy:**
- Barycentric: "GPU, interpolate these 3 vertex colors across the triangle"
- UV sampling: "GPU, interpolate these 3 texture-sampled colors across the triangle"
- Result: **identical** (assuming texture has sufficient resolution)

---

### True Barycentric Transfer (Alternative Method)

**Method:**
1. For each mesh vertex, find the triangle in the **texture-space** that contains its UV coordinate
2. Compute barycentric coordinates (λ₁, λ₂, λ₃) of UV point within that triangle
3. Interpolate texture colors at triangle corners using barycentric weights

**When is this needed?**
- When texture resolution is **lower** than mesh vertex count
- When UV mapping has **distortion** (e.g., seams, overlaps)

**Current vs. barycentric:**
- **Current:** O(V) — one texture lookup per vertex
- **Barycentric:** O(V × T) — search texture triangles, compute weights

**Quality difference:**
- Current: Nearest-pixel texture sample (bilinear if filtering enabled)
- Barycentric: Exact interpolation within texture triangle

**Verdict:**
- **Current method is correct and sufficient** for colorize.py use case
- Texture resolution (original GLB texture) is typically **higher** than mesh vertex density
- Barycentric transfer is overkill (added complexity, minimal quality gain)

---

### Recommendation: Keep Current UV Sampling

**Why:**
1. **Simpler:** One texture lookup per vertex
2. **Faster:** O(V) vs. O(V × T)
3. **Equivalent quality:** Texture resolution ≥ mesh density in typical GLB models
4. **GPU-compatible:** Matches how Blender/slicers render vertex colors

**When to revisit:**
- If users report "pixelated" vertex colors on high-poly meshes
- If UV unwrapping creates large distortions

---

## 5. sRGB vs Linear Workflow for 3D Printing

### Current Implementation

**colorize.py workflow:**
1. Extract texture (sRGB PNG/JPEG)
2. Classify pixels in **RGB space** (HSV = nonlinear transform of sRGB)
3. Compute CIELAB (sRGB → linear → XYZ → LAB)
4. Assign pixels using **CIELAB distance**
5. Build quantized texture (sRGB)
6. Convert to **linear RGB** before Blender export (for interpolation)

**Blender export:**
```python
# sRGB → linear for Blender vertex colors
tex_linear = np.where(tex_f <= 0.04045, tex_f / 12.92, ((tex_f + 0.055) / 1.055) ** 2.4)
cl.data[li].color = (r, g, b, 1.0)  # Linear RGB
```

**Why linear?** Blender's internal color attribute storage expects **linear RGB** for physically accurate rendering.

---

### sRGB vs Linear: What's the Difference?

**sRGB (gamma-encoded):**
- Nonlinear encoding: `C_sRGB = C_linear^(1/2.4)` (approximated as gamma 2.2)
- **Perception:** Matches human eye sensitivity (logarithmic brightness perception)
- **Storage:** Efficient 8-bit encoding (perceptually uniform steps)

**Linear RGB:**
- Physical light intensity (photon count)
- **Math:** Correct for lighting calculations (addition, multiplication)
- **Storage:** Wastes bits in shadows (perceptually non-uniform)

**3MF Materials Extension Spec ([Section 1.2](https://github.com/3MFConsortium/spec_materials)):**
> "Blending operations SHOULD be performed in **linear RGB space**. Vertex color interpolation and texture interpolation SHOULD be performed in **sRGB**, but apply the inverse color component transfer function to sRGB colors before multi-properties color blending."

**Translation:**
- **Interpolation** (GPU rasterization): sRGB space (perceptually smooth gradients)
- **Blending** (compositing layers): Linear space (physically accurate)

---

### Current Workflow: Is it Correct?

**✅ Yes, with caveats:**

1. **Pixel classification (HSV):** sRGB input → correct (HSV is perceptual, expects gamma-encoded RGB)
2. **CIELAB distance:** Linear → correct (CIELAB derived from XYZ, which is linear)
3. **Blender export:** Linear → correct (Blender interpolates in linear for accuracy)

**⚠️ Where it gets tricky:**
- **3MF spec says:** Interpolate in sRGB, blend in linear
- **Blender does:** Interpolate in linear (if you set vertex colors as "Linear")

**Does this matter for 3D printing?**

**No**, because:
1. **AMS printers print discrete colors** (no real "blending" of filaments within a layer)
2. **Smooth gradients** are an artifact of vertex color interpolation, not physical material mixing
3. **Perceptual difference** between sRGB and linear interpolation is **< 5% ΔE** for most color pairs ([Unity docs](https://docs.unity3d.com/Manual/LinearRendering-LinearOrGammaWorkflow.html))

---

### Should You Switch to sRGB Workflow?

**Pros of sRGB:**
- Slightly smoother perceptual gradients
- Matches 3MF spec recommendation

**Cons of sRGB:**
- Blender's vertex color attributes expect linear (would need custom shader)
- No practical benefit for 3D printing (discrete filament colors)

**Recommendation:**
- **Keep current linear workflow** — correct for Blender, negligible perceptual impact
- **Optional:** Add `--srgb-interp` flag for users who want spec-compliant sRGB interpolation (requires custom Blender shader)

**Priority:** Very low — perceptual difference is academic, not practical.

---

## 6. Multi-Material 3MF: How Other Tools Handle ≤8 Colors

### Bambu Studio

**Method:**
- Import OBJ with vertex colors → color merge dialog
- User manually assigns vertex colors to AMS slots (1-8)
- Exports 3MF with **separate objects per color** (each object = one `<basematerial>`)

**Key insight:**
- Bambu Studio does **NOT** use 3MF vertex colors (because they don't exist in the spec)
- It **segments the mesh** into separate objects during export

**Source:** [Bambu Lab Wiki: Multi-Color Printing](https://wiki.bambulab.com/en/software/bambu-studio/multi-color-printing)

---

### PrusaSlicer

**Method:**
- **Modifier meshes:** Boolean intersections define color regions
- **MMU painting:** Paint tool assigns colors per triangle
- Exports 3MF with **separate objects** or **per-triangle material IDs**

**Color limit:** 5 colors (MMU2S) or 8 colors (MMU3)

**Source:** Prusa forum threads (not official API docs)

---

### OrcaSlicer

**Method:**
- Fork of Bambu Studio — same approach (separate objects per color)
- Supports vertex-color OBJ import (recent addition)

**Source:** [Reddit discussion](https://www.reddit.com/r/3Dprinting/comments/1gzdf63/)

---

### Microsoft 3D Builder

**Method:**
- Manual color assignment per mesh part
- Exports 3MF with separate `<object>` elements

**Source:** [Anson Liu blog](https://ansonliu.com/2023/12/adding-blender-color-groups-support-for-printables/)

---

### Common Pattern

**All slicers:**
1. Import mesh with colors (vertex colors, texture, or manual paint)
2. **Segment mesh** into ≤8 color regions
3. Export 3MF with **one object per color**
4. Each object references a `<basematerial>` with the color

**Why?** 3MF's multi-material model is designed for **discrete materials** (filaments), not continuous gradients.

**Gradient workaround:**
- Use **high triangle density** at color boundaries
- Slicers interpolate between adjacent triangles → fake smooth gradient
- But: Still discrete filament swaps under the hood

---

### Implications for colorize.py

**Current OBJ + vertex colors:**
- Bambu Studio segments mesh → separate objects per color
- Loses smooth gradients (hard boundaries)

**Alternative (texture-based 3MF):**
- Export as single object + `<texture2dgroup>`
- Bambu Studio _might_ auto-detect ≤8 unique texture colors and segment
- **Untested** — needs validation

**Recommendation:**
- **Document the limitation:** OBJ vertex colors → 3MF segmented objects (discrete boundaries)
- **Test texture-based 3MF export** to see if Bambu Studio handles it better
- **Long-term:** Multi-color 3D printing is inherently discrete — smooth gradients are preview-only

---

## 7. Open-Source Tools for Automatic Color Segmentation

### Goal

Find tools that can:
1. Take a textured 3D mesh
2. Automatically segment it into ≤8 color regions
3. Output separate meshes or labeled triangles

---

### Search Results

**1. Princeton Mesh Segmentation Benchmark ([segeval.cs.princeton.edu](https://segeval.cs.princeton.edu/))**
- **Purpose:** Geometric segmentation (by shape features like curvature, planarity)
- **NOT color-based**
- Python 2.x scripts (outdated)

**2. 3D AI Studio Mesh Segmentation Tool ([3daistudio.com](https://www.3daistudio.com/Tools/SegmentationTool))**
- **Purpose:** Semantic segmentation (AI-based, separates "logical parts" like wheels, body, windows)
- **NOT color-based**
- Web-based, proprietary API

**3. Research Papers (Springer, ResearchGate)**
- "Semantic segmentation using stereoscopic image colors" — uses 2D image color + depth
- "3D mesh segmentation for CAD" — geometric features
- **None focus on texture-color clustering**

**4. Blender Add-ons**
- [3mf-import-and-color-split](https://github.com/shusain/3mf-import-and-color-split) — Imports 3MF, splits by materials
- **Not automatic** — requires pre-defined materials in 3MF

---

### Why No Open-Source Color Segmentation Tools?

**1. Trivial in 2D (image segmentation):**
- OpenCV, scikit-image, Pillow: k-means, watershed, graph cuts
- But these operate on **2D pixels**, not **3D mesh topology**

**2. 3D mesh + texture = different problem:**
- Need to:
  - Unwrap UV mapping
  - Sample texture per triangle
  - Cluster triangles by color
  - Extract submeshes
- This is **domain-specific** (3D printing, game LOD generation)
- Not a general research problem → no academic tools

**3. Commercial tools:**
- Blender (manual Material Slots → split by material)
- Substance Painter (manual layer painting)
- ZBrush (Polypaint, manual)

---

### DIY Solution (Recommendation)

**Build a custom tool on top of colorize.py:**

```python
# After colorize.py assigns colors to vertices:
def segment_by_color(mesh, vertex_colors, selected_colors):
    """Split mesh into submeshes by vertex color."""
    submeshes = {i: {"vertices": [], "triangles": []} for i in range(len(selected_colors))}
    
    for tri in mesh.triangles:
        # Majority vote: triangle color = most common vertex color
        v_colors = [vertex_colors[tri.v1], vertex_colors[tri.v2], vertex_colors[tri.v3]]
        tri_color = max(set(v_colors), key=v_colors.count)
        submeshes[tri_color]["triangles"].append(tri)
    
    return submeshes  # Export each as separate OBJ/3MF object
```

**Integration:**
- Add `--segment` flag to colorize.py
- Output: `model_color0.obj`, `model_color1.obj`, ...
- Combine into single 3MF with lib3mf

**Effort:** 2-3 hours coding

---

### Verdict: No Existing Tools, DIY is Feasible

**Recommendation:**
- **Write a segmentation post-processor** for colorize.py output
- **Use existing OBJ parsing** (trimesh, pywavefront)
- **Export to 3MF** with lib3mf (one object per color)

**Priority:** Medium — depends on how much automation is needed vs. manual Bambu Studio workflow

---

## Summary of Recommendations

| Topic | Recommendation | Priority | Effort |
|-------|---------------|----------|--------|
| **1. Color Quantization** | Keep HSV families, add optional `--kmeans` flag | Low | 2-4 hours |
| **2. 3MF Programmatic Export** | Test texture2D-based 3MF; document limitations | Medium | 4-8 hours |
| **3. lib3mf Vertex Colors** | Not feasible (spec limitation) | N/A | — |
| **4. Texture Transfer** | Keep current UV sampling | N/A | — |
| **5. sRGB vs Linear** | Keep linear workflow | Very Low | — |
| **6. Multi-Material 3MF** | Document current segmentation behavior | Low | 1 hour |
| **7. Color Segmentation Tool** | Build DIY submesh extractor | Medium | 2-3 hours |

---

## Actionable Next Steps

### High-Priority (Do First)

1. **Test texture2D-based 3MF export** (Section 2)
   - Modify colorize.py to export quantized texture as `<texture2dgroup>`
   - Load in Bambu Studio, check if it auto-detects ≤8 colors
   - If yes: This solves automation + gradient quality
   - If no: Stick with OBJ + manual workflow

2. **Build mesh segmentation post-processor** (Section 7)
   - Split vertex-colored OBJ into per-color submeshes
   - Export as multi-object 3MF with lib3mf
   - Test in Bambu Studio (should auto-assign to AMS slots)

### Medium-Priority (Nice to Have)

3. **Add `--kmeans` flag** (Section 1)
   - Implement k-means CIELAB clustering as alternative to HSV families
   - Benchmark speed vs. quality on test models
   - Document when to use (adaptive colors vs. semantic families)

4. **Improve boundary smoothing** (Current `--smooth` parameter)
   - Test bilateral filter, edge-aware smoothing
   - Compare to current majority-vote approach

### Low-Priority (Future Research)

5. **Explore neural mesh segmentation**
   - PointNet++, MeshCNN for learned color segmentation
   - Requires training data (textured 3D models with ground-truth segmentations)
   - Overkill for current use case

6. **sRGB interpolation experiment** (Section 5)
   - Custom Blender shader for sRGB-space vertex color interpolation
   - A/B test perceptual difference with users
   - Likely negligible impact

---

## References

1. **Color Quantization:**
   - Celebi, M. E. (2011). "Improving the performance of k-means for color quantization." _Image and Vision Computing_.
   - [Leptonica Color Quantization Docs](https://tpgit.github.io/UnOfficialLeptDocs/leptonica/color-quantization.html)

2. **3MF Specification:**
   - [3MF Materials Extension v1.2.1](https://github.com/3MFConsortium/spec_materials/blob/master/3MF%20Materials%20Extension.md)
   - [Bambu Lab Wiki: Multi-Color Printing](https://wiki.bambulab.com/en/software/bambu-studio/multi-color-printing)

3. **lib3mf:**
   - [PyPI: lib3mf](https://pypi.org/project/lib3mf/)
   - [GitHub: 3MFConsortium/lib3mf](https://github.com/3MFConsortium/lib3mf)

4. **Barycentric Interpolation:**
   - [Scratchapixel: Perspective Correct Interpolation](https://www.scratchapixel.com/lessons/3d-basic-rendering/rasterization-practical-implementation/perspective-correct-interpolation-vertex-attributes.html)
   - [HuggingFace: Vertex-Colored to Textured Mesh](https://huggingface.co/blog/vertex-colored-to-textured-mesh)

5. **sRGB/Linear Color:**
   - [Unity Docs: Linear vs Gamma Workflow](https://docs.unity3d.com/Manual/LinearRendering-LinearOrGammaWorkflow.html)
   - [Chris Brejon: Color Management](https://chrisbrejon.com/cg-cinematography/chapter-1-color-management/)

6. **Mesh Segmentation:**
   - [Princeton Mesh Segmentation Benchmark](https://segeval.cs.princeton.edu/)
   - [3D AI Studio Segmentation Tool](https://www.3daistudio.com/Tools/SegmentationTool)

---

## Conclusion

The current `colorize.py` pipeline is **well-designed** for its use case:
- HSV family classification is fast and perceptually intuitive
- CIELAB assignment ensures accurate color matching
- Linear workflow is correct for Blender export

**Main limitation:** 3MF's lack of native vertex colors forces **discrete segmentation** (separate objects per color), which loses smooth gradients. This is a **fundamental 3MF spec limitation**, not a colorize.py bug.

**Best path forward:**
1. Test texture2D 3MF export (preserves gradients, might auto-map to AMS)
2. Build mesh segmentation tool (automation for multi-object 3MF)
3. Document trade-offs (gradients vs. automation)

The OBJ + vertex color → Bambu Studio manual merge workflow remains the **best balance** of quality (gradients) and usability (visual preview) until 3MF spec evolves or Bambu Studio adds better texture-based color extraction.
