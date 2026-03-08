# AI 3D Generation API Reference

## Meshy (docs.meshy.ai)
- Text-to-3D: `POST /openapi/v2/text-to-3d`
- Image-to-3D: `POST /openapi/v1/image-to-3d`
- Auth: `Bearer {api_key}`
- Formats: STL, 3MF, OBJ, FBX, GLB, USDZ, BLEND
- Pricing: Free tier → $20/mo Pro

## Tripo3D (platform.tripo3d.ai)
- Text-to-3D: `POST /v2/openapi/task` type=text_to_model
- Image-to-3D: `POST /v2/openapi/task` type=image_to_model
- Auth: `Bearer {api_key}`
- Python SDK: `pip install tripo3d`
- Pricing: Free tier → $10/mo

## Printpal (printpal.io/api/documentation)
- Generate: `POST /api/generate`
- Status: `GET /api/generate/{uid}/status`
- Download: `GET /api/generate/{uid}/download`
- Auth: `X-API-Key: {key}`
- Optimized for 3D printing (printable geometry)

## 3D AI Studio (docs.3daistudio.com/API)
- Generate: `POST /v1/generate`
- Auth: `Bearer {api_key}`
- Early access (request API key)

## Hyper3D Rodin (developer.hyper3d.ai)
- Text/Image-to-3D: `POST /api/v2/rodin` (multipart/form-data)
- Status: `POST /api/v2/status` (subscription_key JWT polling)
- Download: `POST /api/v2/download` (task_uuid → signed URLs)
- Auth: `Bearer {api_key}`
- Tiers: Regular, Gen-2 (set via `BAMBU_RODIN_TIER` or config `rodin_tier`)
- Formats: GLB (PBR), Quad mesh mode
- Note: Task ID is composite `uuid::subscription_key` to support status polling
- Pricing: Business subscription required
