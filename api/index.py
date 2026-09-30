"""
Vercel Python entrypoint.

Vercel rewrites /api/* -> this function with request path "/api/index".
We recover the original path from headers and rewrite scope["path"].
"""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
import time
import traceback
import uuid
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parent.parent
API_DIR = Path(__file__).resolve().parent
for _p in (ROOT, API_DIR, Path.cwd()):
    s = str(_p)
    if s not in sys.path:
        sys.path.insert(0, s)

from fastapi import FastAPI, File, Form, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

app = FastAPI(title="video-deduplicator", version="0.3.1")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


class VercelPathRewrite:
    """ASGI middleware: restore original URL path on Vercel rewrites."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope.get("type") == "http":
            headers = {
                k.decode().lower(): v.decode()
                for k, v in scope.get("headers") or []
            }
            # Prefer original path candidates
            original = (
                headers.get("x-forwarded-uri")
                or headers.get("x-invoke-path")
                or headers.get("x-vercel-forwarded-path")
                or headers.get("x-matched-path")
                or ""
            )
            # x-forwarded-uri may include query string
            if original.startswith("http"):
                from urllib.parse import urlparse
                original = urlparse(original).path
            if "?" in original:
                original = original.split("?", 1)[0]
            # Fallback: if path is /api/index, try to use raw url from x-url
            path = scope.get("path") or ""
            if original and original.startswith("/"):
                scope = dict(scope)
                scope["path"] = original
                scope["raw_path"] = original.encode()
            elif path in ("/api/index", "/api/index.py", "/index"):
                # Last resort: map bare entry to health on GET without body
                pass
        await self.app(scope, receive, send)




def _json_error(status: int, message: str) -> JSONResponse:
    return JSONResponse({"ok": False, "error": message}, status_code=status)


@app.exception_handler(Exception)
async def _unhandled(request: Request, exc: Exception):
    return JSONResponse(
        {
            "ok": False,
            "error": str(exc),
            "type": type(exc).__name__,
            "path": str(request.url.path),
            "traceback": traceback.format_exc()[-1500:],
        },
        status_code=500,
    )


@app.get("/api/health")
@app.get("/health")
@app.get("/")
@app.get("/api/index")
def health(request: Request):
    return {
        "status": "healthy",
        "service": "video-deduplicator",
        "path": str(request.url.path),
        "ffmpeg": bool(shutil.which("ffmpeg")),
        "rendi_configured": bool(os.environ.get("RENDI_API_KEY")),
        "bunny_configured": bool(
            os.environ.get("BUNNY_STORAGE_ZONE") and os.environ.get("BUNNY_STORAGE_API_KEY")
        ),
        "supabase_configured": bool(
            os.environ.get("SUPABASE_URL") and os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
        ),
    }


@app.get("/api/debug/headers")
@app.get("/api/index/debug")
async def debug_headers(request: Request):
    return {
        "path": request.url.path,
        "headers": dict(request.headers),
        "url": str(request.url),
    }


@app.get("/api")
@app.get("/api/")
def api_root():
    return {
        "service": "video-deduplicator",
        "status": "ok",
        "routes": [
            "GET /api/health",
            "GET /api/media",
            "POST /api/process-variations",
            "POST /api/process-and-publish",
            "POST /api/upload-cdn",
        ],
    }


def _as_bool(v):
    if v is None:
        return None
    if isinstance(v, bool):
        return v
    return str(v).strip().lower() in ("1", "true", "yes", "on")


async def _save_upload(upload: UploadFile, dest_dir: Path) -> Path:
    dest_dir.mkdir(parents=True, exist_ok=True)
    suffix = Path(upload.filename or "upload.bin").suffix or ".bin"
    dest = dest_dir / f"{uuid.uuid4().hex}{suffix}"
    with dest.open("wb") as f:
        while True:
            chunk = await upload.read(1024 * 1024)
            if not chunk:
                break
            f.write(chunk)
    return dest


@app.get("/api/media")
def list_media(limit: int = 24, status: str = "ready"):
    import json
    import urllib.error
    import urllib.parse
    import urllib.request

    base = (os.environ.get("SUPABASE_URL") or "").rstrip("/")
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY") or ""
    if not base or not key:
        return _json_error(400, "SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY não configurados")
    limit = max(1, min(limit, 100))
    qs = urllib.parse.urlencode(
        {
            "select": "id,storage_path,original_name,media_type,mime_type,size_bytes,public_url,thumb_url,caption,status,created_at",
            "status": f"eq.{status}",
            "order": "created_at.desc",
            "limit": str(limit),
        }
    )
    url = f"{base}/rest/v1/vd_media?{qs}"
    req = urllib.request.Request(
        url, headers={"apikey": key, "Authorization": f"Bearer {key}"}
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode("utf-8") or "[]")
    except Exception as exc:
        return _json_error(500, str(exc))
    return {"ok": True, "items": data, "count": len(data)}


@app.post("/api/process-variations")
@app.post("/api/index")  # Vercel may POST here when path is rewritten
async def process_variations(
    file: UploadFile = File(...),
    variations: int = Form(3),
    mode: str = Form("strong"),
    hflip: Optional[str] = Form(None),
    crop_percent: Optional[float] = Form(None),
    speed: Optional[float] = Form(None),
    trim_start: Optional[float] = Form(None),
    trim_end: Optional[float] = Form(None),
    remove_metadata: Optional[str] = Form("true"),
    subtle: Optional[str] = Form("true"),
    crf: int = Form(20),
    preset: str = Form("medium"),
    cdn_prefix: str = Form("uploads"),
    register_supabase: Optional[str] = Form("true"),
    caption: Optional[str] = Form(None),
    mute_audio: Optional[str] = Form(None),
    seed: int = Form(42),
):
    """N micro-variations → CDN → Supabase."""
    # Only handle POST /api/index when original intent is process-variations
    # (frontend posts to /api/process-variations; rewrite may land on /api/index)

    from app.cdn import delete_file, default_remote_path, load_bunny_config, upload_file
    from app.processor import process_video
    from app.rendi import process_via_rendi
    from app.supabase_media import register_media
    from app.transforms import generate_variation_params

    hflip_b = _as_bool(hflip)
    mute_b = _as_bool(mute_audio) or False
    remove_metadata_b = _as_bool(remove_metadata)
    if remove_metadata_b is None:
        remove_metadata_b = True
    register_b = _as_bool(register_supabase)
    if register_b is None:
        register_b = True

    max_var = 3 if not shutil.which("ffmpeg") else 10
    try:
        variations = max(1, min(int(variations or 1), max_var))
    except Exception:
        variations = 1

    has_ffmpeg = bool(shutil.which("ffmpeg"))
    has_rendi = bool((os.environ.get("RENDI_API_KEY") or "").strip())
    use_rendi = has_rendi and (not has_ffmpeg or os.environ.get("FORCE_RENDI") == "1")
    if not has_ffmpeg and not has_rendi:
        return _json_error(
            503,
            "Sem FFmpeg na Vercel e RENDI_API_KEY não configurada. "
            "Configure RENDI_API_KEY + BUNNY_* + SUPABASE_* em Environment Variables.",
        )

    params_list = generate_variation_params(
        variations,
        mode=mode,
        base_hflip=hflip_b,
        base_crop_percent=crop_percent,
        base_trim_start=trim_start,
        base_trim_end=trim_end,
        base_speed=speed,
        seed=seed,
    )

    tmp = Path(tempfile.mkdtemp(prefix="vd-var-"))
    items = []
    in_remote = None
    try:
        src = await _save_upload(file, tmp / "in")
        try:
            cfg = load_bunny_config()
        except Exception as exc:
            return _json_error(400, f"cdn config: {exc}")

        in_url = None
        if use_rendi:
            try:
                in_remote = default_remote_path(src, prefix="rendi-in")
                in_url = upload_file(src, in_remote, config=cfg)
            except Exception as exc:
                return _json_error(400, f"cdn input for rendi: {exc}")

        for p in params_list:
            label = p["label"]
            out = tmp / "out" / f"{src.stem}_{label}.mp4"
            out.parent.mkdir(parents=True, exist_ok=True)
            item = {"label": label, "params": p, "ok": False}
            try:
                if use_rendi:
                    process_via_rendi(
                        in_url.split("?")[0],
                        output_path=out,
                        subtle=True,
                        remove_metadata=remove_metadata_b,
                        mode=p["mode"],
                        hflip=p["hflip"],
                        crop_percent=p["crop_percent"],
                        speed=p["speed"],
                        mute_audio=mute_b,
                        trim_start=p["trim_start"],
                        trim_end=p["trim_end"],
                        crf=crf,
                        preset=preset,
                        download=True,
                    )
                else:
                    process_video(
                        src,
                        out,
                        remove_metadata=remove_metadata_b,
                        subtle=True,
                        mode=p["mode"],
                        hflip=p["hflip"],
                        crop_percent=p["crop_percent"],
                        speed=p["speed"],
                        mute_audio=mute_b,
                        trim_start=p["trim_start"],
                        trim_end=p["trim_end"],
                        crf=crf,
                        preset=preset,
                    )

                remote = f"{cdn_prefix.rstrip('/')}/{out.name}"
                upload_file(out, remote, config=cfg)
                public = cfg.public_url(remote, cache_bust=str(int(time.time())))
                item.update({"ok": True, "remote": remote, "public_url": public})

                if register_b:
                    try:
                        row = register_media(
                            out,
                            public_url=public.split("?")[0],
                            storage_path=remote,
                            status="ready",
                            caption=(f"{caption} ({label})" if caption else label),
                            metadata={"variation": label, "params": p},
                        )
                        item["media"] = {"id": row.get("id"), "public_url": row.get("public_url")}
                    except Exception as exc:
                        item["supabase_error"] = str(exc)
            except Exception as exc:
                item["error"] = str(exc)
            items.append(item)

        ok_count = sum(1 for i in items if i.get("ok"))
        cleaned = False
        if use_rendi and in_remote and ok_count > 0:
            try:
                delete_file(in_remote, config=cfg)
                cleaned = True
            except Exception:
                cleaned = False
        return {
            "ok": ok_count > 0,
            "variations_requested": variations,
            "variations_ok": ok_count,
            "mode": mode,
            "items": items,
            "rendi_input_cleaned": cleaned,
        }
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


@app.post("/api/process-and-publish")
async def process_and_publish(
    file: UploadFile = File(...),
    mode: str = Form("strong"),
    hflip: Optional[str] = Form(None),
    crop_percent: Optional[float] = Form(None),
    speed: Optional[float] = Form(None),
    trim_start: Optional[float] = Form(None),
    trim_end: Optional[float] = Form(None),
    remove_metadata: Optional[str] = Form("true"),
    subtle: Optional[str] = Form("true"),
    crf: int = Form(20),
    preset: str = Form("medium"),
    cdn_prefix: str = Form("uploads"),
    register_supabase: Optional[str] = Form("true"),
    caption: Optional[str] = Form(None),
    mute_audio: Optional[str] = Form(None),
):
    # Reuse variations with n=1
    return await process_variations(
        file=file,
        variations=1,
        mode=mode,
        hflip=hflip,
        crop_percent=crop_percent,
        speed=speed,
        trim_start=trim_start,
        trim_end=trim_end,
        remove_metadata=remove_metadata,
        subtle=subtle,
        crf=crf,
        preset=preset,
        cdn_prefix=cdn_prefix,
        register_supabase=register_supabase,
        caption=caption,
        mute_audio=mute_audio,
        seed=42,
    )

# Vercel export: pure ASGI wrapper restores original path
_fastapi_app = app
app = VercelPathRewrite(_fastapi_app)  # type: ignore[misc]
