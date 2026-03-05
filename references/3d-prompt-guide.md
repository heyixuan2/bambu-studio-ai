# AI 3D Generation — Prompt Engineering Guide

## Why This Matters
The quality of AI-generated 3D models depends heavily on prompt quality.
Bad prompt → unprintable mesh. Good prompt → ready to print.

## Golden Rules for 3D Printing Prompts

### 1. Always Specify "for 3D printing"
```
❌ "a dragon"
✅ "a dragon figurine optimized for FDM 3D printing"
```

### 2. Describe the Base/Bottom
```
❌ "a phone stand"
✅ "a phone stand with a flat, stable base, 15-degree viewing angle"
```
3D prints need a flat bottom for bed adhesion.

### 3. Avoid Overhangs > 45°
```
❌ "a tree with spreading branches"
✅ "a stylized tree with upward-angled branches, no overhangs beyond 45 degrees"
```

### 4. Mention Wall Thickness
```
❌ "a hollow vase"
✅ "a hollow vase with 2mm wall thickness, suitable for 3D printing"
```
Thin walls fail. Minimum 1.2mm for FDM.

### 5. Specify Dimensions When Possible
```
❌ "a small box"
✅ "a box approximately 100mm x 80mm x 50mm with rounded edges"
```

### 6. Request Printability Features
Keywords that help:
- "watertight mesh" — no holes in the model
- "manifold geometry" — proper solid body
- "no floating parts" — everything connected
- "minimal supports needed" — reduce post-processing
- "flat bottom surface" — good bed adhesion

## Prompt Templates

### Functional Objects
```
"A [object] designed for FDM 3D printing. Dimensions approximately 
[W]x[D]x[H]mm. Features: [list]. Flat base, no overhangs beyond 45°, 
minimum 2mm wall thickness, watertight mesh."
```

### Decorative / Figurines
```
"A detailed [subject] figurine for 3D printing, approximately [H]mm tall. 
Stable flat base, connected geometry, no floating parts. Style: [realistic/
cartoon/low-poly]."
```

### Mechanical Parts
```
"A [part name] with [dimensions]. [Tolerance] clearance for moving parts. 
Designed for FDM printing with [material]. No supports needed where possible."
```

## Material-Aware Prompts

| Material | Add to Prompt |
|----------|--------------|
| PLA | "suitable for PLA, room temperature use" |
| PETG | "food-safe design" (if applicable) |
| ABS | "designed for ABS, account for slight shrinkage" |
| TPU | "flexible design, minimum 1.5mm walls, gradual curves" |
| Nylon | "engineering-grade, snap-fit tolerances of 0.3mm" |

## Image-to-3D Tips

### Good Input Images
- Clean background (white/solid color)
- Single object, well-lit
- Multiple angles if possible
- No reflections or transparency

### Bad Input Images
- Cluttered background
- Multiple objects
- Dark/blurry photos
- Transparent/reflective objects

### Enhance with Prompt
When using image-to-3D, add a prompt:
```
"Convert to a 3D printable model. Ensure flat base, watertight mesh, 
minimum 1.5mm wall thickness."
```

## Size Auto-Scaling

The generate script automatically scales models to fit your printer's 
build volume with a 10% safety margin:

| Printer | Max Printable (with margin) |
|---------|---------------------------|
| A1 Mini | 162 × 162 × 162 mm |
| A1 / P1S / P2S / X1C / X1E / H2C | 230 × 230 × 230 mm |
| H2S | 306 × 288 × 306 mm |
| H2D | 315 × 288 × 292 mm |

If a generated model exceeds your build volume, it's automatically 
scaled down proportionally. You can override with `--scale` or `--size`.

## Reducing Floating/Disconnected Parts

AI 3D generators frequently produce disconnected geometry. These prompt strategies reduce this significantly (tested: 255 → 0 parts):

### Always Include
- "single solid sculpture piece" or "figurine style"
- "no floating parts"
- "smooth continuous surfaces"
- "thick connected base"

### Avoid (causes floating parts)
- "particles, smoke, sparks" → use "solid sculptural flame/smoke shapes" instead
- "flowing hair, fur strands" → use "smooth stylized hair"
- "scattered debris, fragments" → use "integrated details"
- "thin wisps, tendrils" → use "thick connected tendrils"

### Effect Substitutions
| User Wants | Bad Prompt | Good Prompt |
|---|---|---|
| Fire/flames | "breathing fire" | "solid sculptural flames attached to mouth" |
| Smoke | "trailing smoke" | "thick solid smoke shape merged with body" |
| Hair | "flowing long hair" | "smooth stylized hair as single piece" |
| Water | "water splash" | "solid wave form connected to base" |
| Wings | "spread feathered wings" | "smooth spread wings as solid surfaces" |

### Example
**Before** (255 disconnected parts):
```
A dragon breathing fire, flames coming from mouth, detailed scales
```

**After** (0 disconnected parts):
```
A dragon breathing fire, single solid sculpture piece, no floating parts,
thick connected base, smooth surfaces, figurine style for 3D printing
```
