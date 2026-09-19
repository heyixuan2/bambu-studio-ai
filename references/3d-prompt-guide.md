# Writing prompts for AI 3D generation

`generate.py` sends your prompt to the provider exactly as written; nothing is added or
rewritten. So the prompt you write is the prompt the model sees.

## What current models respond to

- **One subject, described first.** "A small dragon figurine sitting on a round base" beats
  "cute fantasy scene with a dragon". Scenes and piles of objects often fail outright
  (Meshy reports `image_too_complex`).
- **Shape words, not engineering words.** Text-to-3D models generate a picture first and lift
  it into 3D. They have no notion of millimetres, wall thickness, 45° overhangs, gravity or
  "watertight manifold"; those words rarely change the mesh. Size the model with `--height MM`
  and check printability afterwards with `analyze.py`.
- **A base helps.** "standing on a thick round base" gives a flat bottom and connects thin legs.
- **Keep prompts short.** Meshy caps prompts at 800 characters, Tripo and Rodin at 1024.
  Long lists of requirements dilute the subject.

## Parts that come out detached

Particles, smoke, sparks, loose hair and splashes tend to become floating fragments. Describe
them as solid shapes instead:

| Instead of | Try |
|---|---|
| "breathing fire" | "solid sculpted flames attached to its mouth" |
| "trailing smoke" | "a thick smoke shape merged with the body" |
| "flowing long hair" | "smooth stylised hair as one piece" |
| "water splash" | "a solid wave shape joined to the base" |
| "spread feathered wings" | "smooth spread wings as solid surfaces" |

This is a rule of thumb, not a guarantee: check the result with `analyze.py`, and
`analyze.py --repair --keep-main` removes small loose pieces.

## Image-to-3D

- One object, centred, evenly lit, on a plain background; no reflections or transparency.
- The CLI sends one image. PNG or JPEG work everywhere; Meshy does not take WebP.
- The image leaves the user's computer (it is uploaded to the provider): say so first.
- `--prompt` is only used by Rodin. Meshy and Tripo image-to-3D have no prompt field, so
  `generate.py` doesn't send it and says so.
- Colours come from the image: don't ask the user to pick them.

## Size, texture and format

- Providers return arbitrary units. Pass `--height MM` to set the height (the Z extent as
  Bambu Studio imports the file); without it the provider's size is kept and reported.
- The default output is the textured GLB, which Bambu Studio 2.7+ turns into paint on import.
  `--format stl|3mf|obj` gives geometry only (no colour); `--no-texture` skips paying for a texture.
- AI models are drafts: preview and analyze before printing.
