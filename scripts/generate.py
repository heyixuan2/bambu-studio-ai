#!/usr/bin/env python3
"""
🎨 AI 3D Model Generator — Text/Image to 3D
Supports: Meshy, Tripo3D, 3D AI Studio, Printpal

Usage:
  python3 scripts/generate.py text "a phone stand with cable hole"
  python3 scripts/generate.py image photo.jpg
  python3 scripts/generate.py image photo.jpg --prompt "make it a 3D printable model"
  python3 scripts/generate.py status <task_id>
  python3 scripts/generate.py download <task_id> [--format 3mf]
"""

import os
import sys
import json
import time
import argparse
import shutil


def _convert_model(input_path, target_format):
    """Convert GLB/OBJ to STL/3MF using trimesh. Returns new path or original if conversion fails."""
    if not input_path or not os.path.exists(input_path):
        return input_path
    
    current_ext = os.path.splitext(input_path)[1].lower().lstrip('.')
    target_format = target_format.lower().lstrip('.')
    
    # No conversion needed
    if current_ext == target_format:
        return input_path
    
    # Bambu Lab compatible formats
    BAMBU_FORMATS = {"3mf", "stl", "step", "stp", "obj"}
    
    try:
        import trimesh
        mesh = trimesh.load(input_path, force="mesh")
        new_path = os.path.splitext(input_path)[0] + f".{target_format}"
        mesh.export(new_path)
        print(f"🔄 Converted {current_ext.upper()} → {target_format.upper()}: {os.path.basename(new_path)}")
        
        # Warn if original format not Bambu-compatible
        if current_ext not in BAMBU_FORMATS:
            print(f"   ⚠️ Original {current_ext.upper()} is not Bambu Studio compatible. Using converted {target_format.upper()}.")
        
        return new_path
    except ImportError:
        print(f"⚠️ trimesh not installed — cannot convert {current_ext.upper()} to {target_format.upper()}")
        print(f"   Run: pip3 install trimesh")
        if current_ext not in BAMBU_FORMATS:
            print(f"   ❌ WARNING: {current_ext.upper()} cannot be opened in Bambu Studio!")
        return input_path
    except Exception as e:
        print(f"⚠️ Conversion failed: {e}")
        return input_path
import requests
from pathlib import Path

# ─── Config ──────────────────────────────────────────────────────────

# Load from config + secrets
_skill_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_cfg = {}
for _p in [os.path.join(_skill_dir, "config.json"), os.path.join(_skill_dir, ".secrets.json")]:
    if os.path.exists(_p):
        import json as _j
        with open(_p) as _f:
            _cfg.update(_j.load(_f))

PROVIDER = os.environ.get("BAMBU_3D_PROVIDER", _cfg.get("3d_provider", "meshy")).lower()
API_KEY = os.environ.get("BAMBU_3D_API_KEY", _cfg.get("3d_api_key", ""))
OUTPUT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "output", "models")
os.makedirs(OUTPUT_DIR, exist_ok=True)
PRINTER_MODEL = os.environ.get("BAMBU_MODEL", _cfg.get("model", ""))

# ─── Build Volume Limits (with 10% safety margin) ────────────────────

BUILD_VOLUMES = {
    "A1 Mini":  (162, 162, 162),
    "A1":       (230, 230, 230),
    "P1S":      (230, 230, 230),
    "P2S":      (230, 230, 230),
    "X1C":      (230, 230, 230),
    "X1E":      (230, 230, 230),
    "H2C":      (230, 230, 230),
    "H2S":      (306, 288, 306),
    "H2D":      (315, 288, 292),
}

def get_max_size():
    """Return max printable dimensions (W, D, H) in mm."""
    if PRINTER_MODEL in BUILD_VOLUMES:
        return BUILD_VOLUMES[PRINTER_MODEL]
    return (230, 230, 230)  # safe default

# ─── Prompt Enhancement ──────────────────────────────────────────────

def enhance_prompt(user_prompt, max_size=None, multicolor=False):
    """Add 3D-printing-specific instructions to user prompt."""
    if not max_size:
        max_size = get_max_size()

    # Don't double-enhance
    if "3d print" in user_prompt.lower() or "watertight" in user_prompt.lower():
        return user_prompt

    enhanced = (
        f"{user_prompt}. "
        f"Optimized for FDM 3D printing. "
        f"Maximum dimensions: {max_size[0]}x{max_size[1]}x{max_size[2]}mm. "
        f"CRITICAL REQUIREMENTS: "
        f"Single connected piece (no separate floating parts), "
        f"flat stable base touching the ground plane, "
        f"all parts must be physically connected to the base (no hovering elements), "
        f"watertight manifold mesh with no holes or non-manifold edges, "
        f"no overhangs beyond 45 degrees from vertical, "
        f"minimum 1.5mm wall thickness, "
        f"no thin protruding features under 2mm. "
        f"The model must be printable without supports if possible. "
        f"TEXTURE: Use flat uniform lighting with NO baked shadows, NO ambient occlusion, NO specular highlights in the texture. "
        f"The texture should be pure albedo/diffuse color only, as if lit by perfectly uniform white light from all directions."
    )
    return enhanced

# ─── Provider Backends ───────────────────────────────────────────────

class MeshyBackend:
    """Meshy.ai — docs.meshy.ai"""
    BASE = "https://api.meshy.ai"
    
    def headers(self):
        return {"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"}
    
    def text_to_3d(self, prompt, **kwargs):
        # Step 1: Preview
        r = requests.post(f"{self.BASE}/openapi/v2/text-to-3d",
            headers=self.headers(),
            json={"mode": "preview", "prompt": prompt, "art_style": kwargs.get("style", "realistic")}
        )
        r.raise_for_status()
        task_id = r.json().get("result")
        print(f"📤 Meshy task created: {task_id}")
        return task_id
    
    def image_to_3d(self, image_path, prompt="", **kwargs):
        # Upload image first or use URL
        if image_path.startswith("http"):
            image_url = image_path
        else:
            image_url = self._upload_image(image_path)
        
        r = requests.post(f"{self.BASE}/openapi/v1/image-to-3d",
            headers=self.headers(),
            json={"image_url": image_url, "enable_pbr": True}
        )
        r.raise_for_status()
        task_id = r.json().get("result")
        print(f"📤 Meshy image-to-3D task: {task_id}")
        return task_id
    
    def _upload_image(self, path):
        """Upload local image and return URL."""
        with open(path, "rb") as f:
            r = requests.post(f"{self.BASE}/openapi/v1/files",
                headers={"Authorization": f"Bearer {API_KEY}"},
                files={"file": f}
            )
        r.raise_for_status()
        return r.json().get("url", r.json().get("result", ""))
    
    def get_status(self, task_id):
        r = requests.get(f"{self.BASE}/openapi/v2/text-to-3d/{task_id}",
            headers=self.headers())
        if r.status_code == 404:
            r = requests.get(f"{self.BASE}/openapi/v1/image-to-3d/{task_id}",
                headers=self.headers())
        r.raise_for_status()
        data = r.json()
        return {
            "status": data.get("status", "unknown"),
            "progress": data.get("progress", 0),
            "model_urls": data.get("model_urls", {}),
            "thumbnail": data.get("thumbnail_url", ""),
        }
    
    def download(self, task_id, fmt="stl"):
        status = self.get_status(task_id)
        urls = status.get("model_urls", {})
        url = urls.get(fmt) or urls.get("glb") or urls.get("obj")
        if not url:
            print(f"❌ No download URL. Status: {status['status']}")
            return None
        return self._download_file(url, task_id, fmt)
    
    def _download_file(self, url, task_id, fmt):
        os.makedirs(OUTPUT_DIR, exist_ok=True)
        out = os.path.join(OUTPUT_DIR, f"{task_id}.glb")
        r = requests.get(url, stream=True, timeout=(10, 120))
        r.raise_for_status()
        with open(out, "wb") as f:
            for chunk in r.iter_content(8192):
                f.write(chunk)
        return out


class TripoBackend:
    """Tripo3D — platform.tripo3d.ai"""
    BASE = "https://api.tripo3d.ai/v2/openapi"
    
    def headers(self):
        return {"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"}
    
    def text_to_3d(self, prompt, **kwargs):
        r = requests.post(f"{self.BASE}/task",
            headers=self.headers(),
            json={"type": "text_to_model", "texture": True, "prompt": prompt}
        )
        r.raise_for_status()
        task_id = r.json()["data"]["task_id"]
        print(f"📤 Tripo task created: {task_id}")
        return task_id
    
    def image_to_3d(self, image_path, prompt="", **kwargs):
        if not image_path.startswith("http"):
            # Upload first
            with open(image_path, "rb") as f:
                r = requests.post(f"{self.BASE}/upload",
                    headers={"Authorization": f"Bearer {API_KEY}"},
                    files={"file": f}
                )
            r.raise_for_status()
            image_token = r.json()["data"]["image_token"]
        else:
            image_token = image_path
        
        r = requests.post(f"{self.BASE}/task",
            headers=self.headers(),
            json={"type": "image_to_model", "texture": True, "file": {"type": "jpg", "file_token": image_token}}
        )
        r.raise_for_status()
        task_id = r.json()["data"]["task_id"]
        print(f"📤 Tripo image task: {task_id}")
        return task_id
    
    def get_status(self, task_id):
        r = requests.get(f"{self.BASE}/task/{task_id}", headers=self.headers(), timeout=(10, 120))
        r.raise_for_status()
        data = r.json()["data"]
        return {
            "status": data.get("status", "unknown"),
            "progress": data.get("progress", 0),
            "model_urls": {"glb": data.get("output", {}).get("pbr_model") or data.get("output", {}).get("model", "")},
        }
    
    def download(self, task_id, fmt="glb"):
        status = self.get_status(task_id)
        url = status.get("model_urls", {}).get("glb") or status.get("model_urls", {}).get(fmt)
        if not url:
            print(f"❌ No download URL. Status: {status['status']}")
            return None
        os.makedirs(OUTPUT_DIR, exist_ok=True)
        out = os.path.join(OUTPUT_DIR, f"{task_id}.glb")
        r = requests.get(url, stream=True, timeout=(10, 120))
        with open(out, "wb") as f:
            for chunk in r.iter_content(8192):
                f.write(chunk)
        return out


class PrintpalBackend:
    """Printpal.io — printpal.io/api/documentation"""
    BASE = "https://printpal.io"
    
    def headers(self):
        return {"X-API-Key": API_KEY, "Content-Type": "application/json"}
    
    def text_to_3d(self, prompt, **kwargs):
        r = requests.post(f"{self.BASE}/api/generate",
            headers=self.headers(),
            json={"prompt": prompt, "quality": kwargs.get("quality", "default")}
        )
        r.raise_for_status()
        uid = r.json().get("generation_uid")
        print(f"📤 Printpal task: {uid}")
        return uid
    
    def image_to_3d(self, image_path, prompt="", **kwargs):
        if image_path.startswith("http"):
            r = requests.post(f"{self.BASE}/api/generate",
                headers=self.headers(),
                json={"image_url": image_path, "prompt": prompt})
        else:
            with open(image_path, "rb") as f:
                r = requests.post(f"{self.BASE}/api/generate",
                    headers={"X-API-Key": API_KEY},
                    files={"image": f},
                    data={"prompt": prompt})
        r.raise_for_status()
        uid = r.json().get("generation_uid")
        print(f"📤 Printpal image task: {uid}")
        return uid
    
    def get_status(self, task_id):
        r = requests.get(f"{self.BASE}/api/generate/{task_id}/status",
            headers=self.headers())
        r.raise_for_status()
        data = r.json()
        return {
            "status": data.get("status", "unknown"),
            "progress": 100 if data.get("status") == "completed" else 0,
            "model_urls": {"glb": data.get("download_url", "")},
        }
    
    def download(self, task_id, fmt="stl"):
        r = requests.get(f"{self.BASE}/api/generate/{task_id}/download",
            headers=self.headers(), params={"format": fmt}, stream=True)
        r.raise_for_status()
        os.makedirs(OUTPUT_DIR, exist_ok=True)
        out = os.path.join(OUTPUT_DIR, f"{task_id}.glb")
        with open(out, "wb") as f:
            for chunk in r.iter_content(8192):
                f.write(chunk)
        return out


class Studio3DBackend:
    """3D AI Studio — docs.3daistudio.com/API"""
    BASE = "https://api.3daistudio.com"
    
    def headers(self):
        return {"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"}
    
    def text_to_3d(self, prompt, **kwargs):
        r = requests.post(f"{self.BASE}/v1/generate",
            headers=self.headers(),
            json={"prompt": prompt, "type": "text-to-3d"})
        r.raise_for_status()
        task_id = r.json().get("id", r.json().get("task_id"))
        print(f"📤 3D AI Studio task: {task_id}")
        return task_id
    
    def image_to_3d(self, image_path, prompt="", **kwargs):
        if image_path.startswith("http"):
            r = requests.post(f"{self.BASE}/v1/generate",
                headers=self.headers(),
                json={"image_url": image_path, "type": "image-to-3d"})
        else:
            with open(image_path, "rb") as f:
                r = requests.post(f"{self.BASE}/v1/generate",
                    headers={"Authorization": f"Bearer {API_KEY}"},
                    files={"image": f})
        r.raise_for_status()
        task_id = r.json().get("id", r.json().get("task_id"))
        print(f"📤 3D AI Studio image task: {task_id}")
        return task_id
    
    def get_status(self, task_id):
        r = requests.get(f"{self.BASE}/v1/generate/{task_id}",
            headers=self.headers())
        r.raise_for_status()
        data = r.json()
        return {
            "status": data.get("status", "unknown"),
            "progress": data.get("progress", 0),
            "model_urls": data.get("output", {}),
        }
    
    def download(self, task_id, fmt="stl"):
        status = self.get_status(task_id)
        url = status.get("model_urls", {}).get(fmt) or status.get("model_urls", {}).get("obj")
        if not url:
            print(f"❌ No URL. Status: {status['status']}")
            return None
        os.makedirs(OUTPUT_DIR, exist_ok=True)
        out = os.path.join(OUTPUT_DIR, f"{task_id}.glb")
        r = requests.get(url, stream=True, timeout=(10, 120))
        with open(out, "wb") as f:
            for chunk in r.iter_content(8192):
                f.write(chunk)
        return out


# ─── Provider Registry ───────────────────────────────────────────────

PROVIDERS = {
    "meshy": MeshyBackend,
    "tripo": TripoBackend,
    "printpal": PrintpalBackend,
    "3daistudio": Studio3DBackend,
}

def get_backend():
    if not API_KEY:
        print(f"❌ Missing API key for {PROVIDER}")
        print(f"   export BAMBU_3D_API_KEY='your_api_key'")
        print(f"   export BAMBU_3D_PROVIDER='{PROVIDER}'  (meshy/tripo/printpal/3daistudio)")
        sys.exit(1)
    
    cls = PROVIDERS.get(PROVIDER)
    if not cls:
        print(f"❌ Unknown provider: {PROVIDER}")
        print(f"   Options: {', '.join(PROVIDERS.keys())}")
        sys.exit(1)
    
    return cls()

# ─── Commands ────────────────────────────────────────────────────────

def _finalize(file_path, target_format="stl"):
    """Unified post-download processing: validate format, convert, verify."""
    if not file_path or not os.path.exists(file_path):
        print(f"❌ File not found: {file_path}")
        return None
    
    # 1. Validate magic bytes
    with open(file_path, 'rb') as f:
        magic = f.read(8)
    actual_ext = None
    if magic[:4] == b'glTF':
        actual_ext = '.glb'
    elif magic[:2] == b'PK':
        actual_ext = '.3mf'
    elif magic[:1] == b'v' or magic[:2] == b'# ':
        actual_ext = '.obj'
    else:
        # Binary STL: 80-byte header + 4-byte uint32 face count
        import struct
        with open(file_path, 'rb') as f2:
            f2.seek(80)
            fc = f2.read(4)
        if len(fc) == 4:
            nf = struct.unpack('<I', fc)[0]
            expected = 80 + 4 + nf * 50
            if 0 < nf < 50_000_000 and abs(expected - os.path.getsize(file_path)) < 100:
                actual_ext = '.stl'
    
    if actual_ext and not file_path.endswith(actual_ext):
        correct = file_path.rsplit('.', 1)[0] + actual_ext
        os.rename(file_path, correct)
        file_path = correct
        print(f"🔄 Format corrected → {actual_ext}")
    
    # 2. Convert if needed
    current_ext = os.path.splitext(file_path)[1].lstrip('.').lower()
    target = target_format.lower().lstrip('.')
    if current_ext != target and current_ext in ('glb', 'gltf', 'obj'):
        converted = _convert_model(file_path, target)
        if converted and converted != file_path:
            print(f"🔄 Converted {current_ext.upper()} → {target.upper()}")
            file_path = converted
    
    # 3. Verify file is readable
    size = os.path.getsize(file_path)
    if size < 100:
        print(f"⚠️ File suspiciously small ({size} bytes)")
    
    return file_path


def cmd_text(prompt, wait=False, multicolor=False, **kwargs):
    if not prompt or not prompt.strip():
        print("❌ Empty prompt. Please describe what you want to generate.")
        return
    backend = get_backend()

    # Enhance prompt for printability
    if not kwargs.get("raw"):
        original = prompt
        prompt = enhance_prompt(prompt)
        max_sz = get_max_size()
        if PRINTER_MODEL:
            print(f"🖨️ Printer: {PRINTER_MODEL} (max {max_sz[0]}x{max_sz[1]}x{max_sz[2]}mm)")
        print(f"📝 Original: {original}")
        print(f"✨ Enhanced: {prompt[:120]}...")
        print()

    task_id = backend.text_to_3d(prompt, **kwargs)
    
    if wait:
        return _wait_and_download(backend, task_id, kwargs.get("format", "3mf"))
    else:
        print(f"\n💡 Check status: python3 scripts/generate.py status {task_id}")
        print(f"💡 Download:     python3 scripts/generate.py download {task_id}")
    return task_id

def cmd_image(image_path, prompt="", wait=False, **kwargs):
    if not image_path.startswith("http") and not os.path.exists(image_path):
        print(f"❌ File not found: {image_path}")
        sys.exit(1)
    
    backend = get_backend()
    task_id = backend.image_to_3d(image_path, prompt, **kwargs)
    
    if wait:
        return _wait_and_download(backend, task_id, kwargs.get("format", "3mf"))
    else:
        print(f"\n💡 Check status: python3 scripts/generate.py status {task_id}")
        print(f"💡 Download:     python3 scripts/generate.py download {task_id}")
    return task_id

def cmd_status(task_id):
    backend = get_backend()
    status = backend.get_status(task_id)
    
    state = status["status"]
    progress = status.get("progress", 0)
    
    icons = {"pending": "⏳", "processing": "🔄", "completed": "✅", "failed": "❌"}
    icon = icons.get(state, "❓")
    
    print(f"{icon} Status: {state}")
    if progress:
        bar = "█" * (progress // 5) + "░" * (20 - progress // 5)
        print(f"📊 Progress: [{bar}] {progress}%")
    
    if state in ("completed", "success"):
        urls = status.get("model_urls", {})
        if urls:
            print(f"📦 Available formats: {', '.join(urls.keys())}")
            print(f"\n💡 Download: python3 scripts/generate.py download {task_id} --format stl")
            print(f"   Note: If provider returns GLB, it will be auto-converted to your preferred format.")
    
    return status

def cmd_download(task_id, fmt="3mf"):
    backend = get_backend()
    path = backend.download(task_id, fmt)
    if path:
        # Auto-convert to requested format if provider returned different format (e.g., GLB)
        actual_ext = os.path.splitext(path)[1].lower().lstrip('.')
        if actual_ext != fmt.lower():
            path = _finalize(path)  # Detect actual format from magic bytes
            path = _convert_model(path, fmt)
        size = os.path.getsize(path)
        print(f"✅ Downloaded: {path} ({size / 1024:.1f} KB)")
        # Verify Bambu compatibility
        final_ext = os.path.splitext(path)[1].lower().lstrip('.')
        if final_ext in ("3mf", "stl", "step", "stp", "obj"):
            print(f"   ✅ {final_ext.upper()} is Bambu Studio compatible")
        else:
            print(f"   ❌ WARNING: {final_ext.upper()} is NOT compatible with Bambu Studio!")
            print(f"   Run: python3 scripts/generate.py download {task_id} --format stl")
        print(f"\n💡 Next: python3 scripts/analyze.py {path}")
        print(f"         python3 scripts/bambu.py print {os.path.basename(path)}")
    return path

def _wait_and_download(backend, task_id, fmt="stl"):
    """Poll until complete, then download."""
    print(f"\n⏳ Waiting for generation...")
    
    retries_502 = 0
    max_502_retries = 10
    for i in range(120):  # Max 10 min
        time.sleep(5)
        try:
            status = backend.get_status(task_id)
        except Exception as poll_err:
            err_str = str(poll_err)
            if "502" in err_str or "503" in err_str or "500" in err_str:
                retries_502 += 1
                if retries_502 <= max_502_retries:
                    print(f"   ⚠️ API returned error ({err_str[:30]}), retry {retries_502}/{max_502_retries}...")
                    time.sleep(10)  # Wait longer on server error
                    continue
                else:
                    print(f"   ❌ API error persisted after {max_502_retries} retries.")
                    print(f"   💡 Try manually: python3 scripts/generate.py status {task_id}")
                    print(f"   💡 Or download: python3 scripts/generate.py download {task_id}")
                    sys.exit(1)
            raise
        retries_502 = 0  # Reset on success
        state = status["status"]
        progress = status.get("progress", 0)
        
        bar = "█" * (progress // 5) + "░" * (20 - progress // 5)
        print(f"\r  [{bar}] {progress}% - {state}", end="", flush=True)
        
        if state in ("completed", "success"):
            print(f"\n✅ Done!")
            path = backend.download(task_id, fmt)
            if path:
                path = _finalize(path, target_format=fmt)
                print(f"📦 Saved: {path}")
            return path
        elif state == "failed":
            print(f"\n❌ Generation failed")
            sys.exit(1)
    
    print(f"\n⚠️ Timeout. Check later: python3 scripts/generate.py status {task_id}")
    return None

# ─── Main ────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="🎨 AI 3D Model Generator",
        epilog=f"Provider: {PROVIDER.upper()} | Set BAMBU_3D_PROVIDER & BAMBU_3D_API_KEY"
    )
    sub = parser.add_subparsers(dest="command")
    
    p_text = sub.add_parser("text", help="Text to 3D model")
    p_text.add_argument("prompt", help="Description of the 3D model")
    p_text.add_argument("--wait", action="store_true", help="Wait and auto-download")
    p_text.add_argument("--format", default="3mf", help="Output format (3mf recommended for Bambu Lab) (stl/obj/glb/3mf)")
    p_text.add_argument("--style", default="realistic", help="Art style")
    p_text.add_argument("--raw", action="store_true", help="Skip prompt enhancement")
    
    p_img = sub.add_parser("image", help="Image to 3D model")
    p_img.add_argument("image", help="Image path or URL")
    p_img.add_argument("--prompt", default="", help="Additional description")
    p_img.add_argument("--wait", action="store_true", help="Wait and auto-download")
    p_img.add_argument("--format", default="3mf", help="Output format (3mf recommended for Bambu Lab)")
    p_img.add_argument("--raw", action="store_true", help="Skip prompt enhancement")
    
    p_stat = sub.add_parser("status", help="Check generation status")
    p_stat.add_argument("task_id")
    
    p_dl = sub.add_parser("download", help="Download generated model")
    p_dl.add_argument("task_id")
    p_dl.add_argument("--format", default="3mf", help="Output format (auto-converts from GLB if needed)")
    
    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        print(f"\n📡 Provider: {PROVIDER} | Models saved to: {OUTPUT_DIR}")
        sys.exit(1)
    
    if args.command == "text":
        cmd_text(args.prompt, wait=args.wait, format=args.format, style=args.style, raw=args.raw)
    elif args.command == "image":
        cmd_image(args.image, prompt=args.prompt, wait=args.wait, format=args.format, raw=args.raw)
    elif args.command == "status":
        cmd_status(args.task_id)
    elif args.command == "download":
        cmd_download(args.task_id, args.format)

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n⏹️ Cancelled.")
    except Exception as e:
        err = str(e)
        if "401" in err or "Unauthorized" in err:
            print(f"❌ API authentication failed. Check your API key.")
            print(f"   export BAMBU_3D_API_KEY='your_key'")
        elif "403" in err or "Forbidden" in err:
            print(f"❌ API access denied. Your plan may not support this feature.")
        elif "429" in err or "rate" in err.lower():
            print(f"❌ Rate limited. Wait a moment and try again.")
        elif "timeout" in err.lower():
            print(f"❌ Request timed out. The API may be slow. Try again.")
        else:
            print(f"❌ Error: {e}")
