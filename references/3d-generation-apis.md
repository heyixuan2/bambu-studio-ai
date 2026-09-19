# AI 3D generation APIs

Checked 2026-09-19 against each vendor's docs (links below) and unauthenticated route probes
(401 = route exists, 404 = it doesn't). Nothing here was called with a real key. Prices change;
re-check the linked pages before quoting them to a user.

`generate.py` talks to these through `scripts/bambu_studio_ai/generation/providers/`.

| | Meshy | Tripo | Hyper3D Rodin |
|---|---|---|---|
| Docs | [docs.meshy.ai](https://docs.meshy.ai/llms.txt) | [developers.tripo3d.ai](https://developers.tripo3d.ai/llms.txt) (API v3) | [docs.hyper3d.ai](https://docs.hyper3d.ai/en/api-specification/rodin-gen2-5) |
| Auth | `Authorization: Bearer msy_…` | `Authorization: Bearer …` | `Authorization: Bearer …` |
| Text → 3D | `POST /openapi/v2/text-to-3d` `mode=preview` (untextured), then `mode=refine` with `preview_task_id` (texture) | `POST /v3/generation/text-to-model` | `POST /api/v2/rodin` (multipart form) |
| Image → 3D | `POST /openapi/v1/image-to-3d`, `image_url` = public URL or `data:` URI (no upload endpoint; PNG/JPEG only) | `POST /v3/files` (multipart) → `file_token`, then `/v3/generation/image-to-model` with `input` = token or URL (uploads: PNG/JPEG) | same endpoint, 1–5 `images` files |
| Uses `--prompt` for images | No (only `texture_prompt`, which replaces the photo as the texture guide; not sent) | No | Yes (optional) |
| Status | `GET …/{id}` (text and image have separate routes) | `GET /v3/tasks/{id}` | `POST /api/v2/status` with `jobs.subscription_key` |
| Vendor statuses → ours | PENDING→queued, IN_PROGRESS→running, SUCCEEDED, FAILED, CANCELED→cancelled | queued, running, success→succeeded, failed, cancelled, banned→rejected, expired, unknown (v2 docs)→failed | per job: Waiting→queued, Generating→running, Done (all)→succeeded, Failed (any)→failed; `NO_SUCH_TASK`→expired |
| Result | `model_urls`: glb, fbx, obj+mtl, usdz, stl; 3mf only if requested in `target_formats`. Kept 3 days | `output.model_url` (GLB). Signed links expire within minutes | `POST /api/v2/download` with top-level `uuid` → `[{name, url}]` (model, textures, preview) |
| Server-side STL/3MF | STL always listed; 3MF via `target_formats` or `POST /openapi/v1/convert` (1 credit) | `POST /v3/models/convert` `format=STL`/`3MF` (5 credits) | `geometry_file_format=stl` at submit (no 3MF) |
| Errors | HTTP status + `{"message"}`; failed tasks carry `task_error` | `{"code", "message", "suggestion"}`, also inside HTTP 200 | HTTP 201 with `{"error", "message"}` for rejections |
| Default in generate.py | `ai_model=latest` (Meshy 7.1 on 2026-09-18) | `model=v3.1-20260211` | `tier=Gen-2.5-Medium` (or config `rodin_tier` / env `BAMBU_RODIN_TIER`) |
| Price (2026-09-19) | Preview 20 cr (+5 at 2k/4k geometry), refine 10 cr (15 at 8k), image 20 / 30 textured; API needs a paid plan since 2025-03-20, Pro from $20/mo ([pricing](https://docs.meshy.ai/api/pricing)) | $1 = 100 cr: text 10 / 20 textured, image 20 / 30, convert 5 (10 with options) ([pricing](https://developers.tripo3d.ai/en/pricing)) | 0.5 credits per Gen-2.5 task (+0.5 Extreme-High); needs a paid Rodin plan with API access ([docs](https://docs.hyper3d.ai/en/api-specification/rodin-gen2-5), [pricing](https://hyper3d.ai/pricing)) |

## Things to know

- **Tripo API v2 stops accepting requests on 2026-11-01 00:00 UTC+8** (notice on
  [platform.tripo3d.ai](https://platform.tripo3d.ai)). v3 moved the base URL to
  `https://openapi.tripo3d.ai/v3`, dropped the `type` field and unified inputs as `input`
  ([migration guide](https://developers.tripo3d.ai/en/docs/migration-v2-to-v3)). Tripo's v3 gateway
  answers 401 for every path without a key, so v3 routes are confirmed by the docs only.
- **Meshy text-to-3D is two paid steps.** The preview has no texture; `generate.py` runs the refine
  only when a coloured GLB is wanted (not for `--no-texture`, STL, 3MF or OBJ).
- **Rodin needs `tier` on every request.** Without it Rodin falls back to the legacy Gen-1 `Regular` tier.
- **Model sizes are arbitrary.** None of the three returns millimetres by default; pass
  `--height MM`. Bambu Studio 2.7 reads GLB coordinates as millimetres with Z up and does not
  convert glTF's Y-up axis (checked in its source and with `bambu-studio --export-stl`), so a
  provider's model would import lying on its back. `generate.py` therefore wraps every
  downloaded GLB in one root node that turns it Z-up; meshes and textures are untouched.
- **Not supported:** Printpal and 3D AI Studio (removed: the old code called routes that don't
  exist). fal.ai is planned as the next provider.
