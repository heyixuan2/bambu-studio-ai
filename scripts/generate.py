#!/usr/bin/env python3
"""
🎨 AI 3D Model Generator — Text/Image to 3D
Supports: Meshy, Tripo3D, 3D AI Studio, Printpal

Usage:
  python3 generate.py text "a phone stand with cable hole"
  python3 generate.py image photo.jpg
  python3 generate.py image photo.jpg --prompt "make it a 3D printable model"
  python3 generate.py status <task_id>
  python3 generate.py download <task_id> [--format stl]
"""

import os
import sys
import json
import time
import argparse
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
OUTPUT_DIR = os.path.expanduser("~/bambu-models")
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

def enhance_prompt(user_prompt, max_size=None):
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
        f"Flat stable base, watertight manifold mesh, "
        f"no overhangs beyond 45 degrees, "
        f"minimum 1.5mm wall thickness, no floating parts."
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
        out = os.path.join(OUTPUT_DIR, f"{task_id}.{fmt}")
        r = requests.get(url, stream=True)
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
            json={"type": "text_to_model", "prompt": prompt}
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
            json={"type": "image_to_model", "file": {"type": "jpg", "file_token": image_token}}
        )
        r.raise_for_status()
        task_id = r.json()["data"]["task_id"]
        print(f"📤 Tripo image task: {task_id}")
        return task_id
    
    def get_status(self, task_id):
        r = requests.get(f"{self.BASE}/task/{task_id}", headers=self.headers())
        r.raise_for_status()
        data = r.json()["data"]
        return {
            "status": data.get("status", "unknown"),
            "progress": data.get("progress", 0),
            "model_urls": {"glb": data.get("output", {}).get("model", "")},
        }
    
    def download(self, task_id, fmt="glb"):
        status = self.get_status(task_id)
        url = status.get("model_urls", {}).get("glb") or status.get("model_urls", {}).get(fmt)
        if not url:
            print(f"❌ No download URL. Status: {status['status']}")
            return None
        os.makedirs(OUTPUT_DIR, exist_ok=True)
        out = os.path.join(OUTPUT_DIR, f"{task_id}.{fmt}")
        r = requests.get(url, stream=True)
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
        out = os.path.join(OUTPUT_DIR, f"{task_id}.{fmt}")
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
        out = os.path.join(OUTPUT_DIR, f"{task_id}.{fmt}")
        r = requests.get(url, stream=True)
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

def cmd_text(prompt, wait=False, **kwargs):
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
        return _wait_and_download(backend, task_id, kwargs.get("format", "stl"))
    else:
        print(f"\n💡 Check status: python3 generate.py status {task_id}")
        print(f"💡 Download:     python3 generate.py download {task_id}")
    return task_id

def cmd_image(image_path, prompt="", wait=False, **kwargs):
    if not image_path.startswith("http") and not os.path.exists(image_path):
        print(f"❌ File not found: {image_path}")
        sys.exit(1)
    
    backend = get_backend()
    task_id = backend.image_to_3d(image_path, prompt, **kwargs)
    
    if wait:
        return _wait_and_download(backend, task_id, kwargs.get("format", "stl"))
    else:
        print(f"\n💡 Check status: python3 generate.py status {task_id}")
        print(f"💡 Download:     python3 generate.py download {task_id}")
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
    
    if state == "completed":
        urls = status.get("model_urls", {})
        if urls:
            print(f"📦 Available formats: {', '.join(urls.keys())}")
            print(f"\n💡 Download: python3 generate.py download {task_id} --format stl")
    
    return status

def cmd_download(task_id, fmt="stl"):
    backend = get_backend()
    path = backend.download(task_id, fmt)
    if path:
        size = os.path.getsize(path)
        print(f"✅ Downloaded: {path} ({size / 1024:.1f} KB)")
        print(f"\n💡 Print it: python3 bambu.py print {os.path.basename(path)}")
    return path

def _wait_and_download(backend, task_id, fmt="stl"):
    """Poll until complete, then download."""
    print(f"\n⏳ Waiting for generation...")
    
    for i in range(120):  # Max 10 min
        time.sleep(5)
        status = backend.get_status(task_id)
        state = status["status"]
        progress = status.get("progress", 0)
        
        bar = "█" * (progress // 5) + "░" * (20 - progress // 5)
        print(f"\r  [{bar}] {progress}% - {state}", end="", flush=True)
        
        if state == "completed":
            print(f"\n✅ Done!")
            path = backend.download(task_id, fmt)
            if path:
                print(f"📦 Saved: {path}")
            return path
        elif state == "failed":
            print(f"\n❌ Generation failed")
            return None
    
    print(f"\n⚠️ Timeout. Check later: python3 generate.py status {task_id}")
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
    p_dl.add_argument("--format", default="stl")
    
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
    main()
