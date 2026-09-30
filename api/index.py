"""
FastAPI backend for video-deduplicator.

Routes:
  GET  /api/health
  GET  /api/cdn-config
  GET  /api/media
  POST /api/process
  POST /api/upload-cdn
  POST /api/process-and-publish
"""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
import time
import uuid
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

PUBLIC = ROOT / "public"

app = FastAPI(title="video-deduplicator", version="0.2.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

if PUBLIC.is_dir():
    app.mount("/css", StaticFiles(directory=str(PUBLIC / "css")), name="css")
    app.mount("/js", StaticFiles(directory=str(PUBLIC / "js")), name="js")
    assets = PUBLIC / "assets"
    if assets.is_dir():
        app.mount("/assets", StaticFiles(directory=str(assets)), name="assets")


def _json_error(status: int, message: str) -> JSONResponse:
    return JSONResponse({"ok": False, "error": message}, status_code=status)


@app.get("/api/health")
@app.get("/health")
def health():
    ffmpeg = shutil.which("ffmpeg")
    return {
        "status": "healthy",
        "service": "video-deduplicator",
        "ffmpeg": bool(ffmpeg),
        "rendi_configured": bool(os.environ.get("RENDI_API_KEY")),
        "bunny_configured": bool(os.environ.get("BUNNY_STORAGE_ZONE") and os.environ.get("BUNNY_STORAGE_API_KEY")),
        "supabase_configured": bool(os.environ.get("SUPABASE_URL") and os.environ.get("SUPABASE_SERVICE_ROLE_KEY")),
    }


@app.get("/api/cdn-config")
def cdn_config():
    try:
        from app.cdn import CdnConfigError, load_bunny_config

        cfg = load_bunny_config()
        return {
            "ok": True,
            "storage_zone": cfg.storage_zone,
            "storage_host": cfg.storage_host,
            "cdn_hostname": cfg.cdn_hostname or None,
            "public_base": None if not (cfg.cdn_hostname or cfg.cdn_base_url) else cfg.public_base,
        }
    except Exception as exc:
        return _json_error(400, str(exc))


@app.get("/api/media")
def list_media(limit: int = 24, status: str = "ready"):
    """List recent rows from vd_media via PostgREST."""
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
        url,
        headers={
            "apikey": key,
            "Authorization": f"Bearer {key}",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode("utf-8") or "[]")
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")[:400]
        return _json_error(exc.code, f"Supabase: {body}")
    except Exception as exc:
        return _json_error(500, str(exc))

    return {"ok": True, "items": data, "count": len(data)}


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


@app.post("/api/process")
async def process_endpoint(
    file: UploadFile = File(...),
    subtle: bool = Form(False),
    remove_metadata: bool = Form(True),
    trim_start: Optional[float] = Form(None),
    trim_end: Optional[float] = Form(None),
    crf: int = Form(23),
    preset: str = Form("medium"),
):
    """Process video with FFmpeg (requires ffmpeg on the host)."""
    if not shutil.which("ffmpeg") and not os.environ.get("RENDI_API_KEY"):
        return _json_error(503, "FFmpeg local e RENDI_API_KEY indisponíveis")

    from app.processor import InputValidationError, ProcessingError, process_video

    tmp = Path(tempfile.mkdtemp(prefix="vd-"))
    try:
        src = await _save_upload(file, tmp / "in")
        out = tmp / "out" / f"{src.stem}_processed.mp4"
        out.parent.mkdir(parents=True, exist_ok=True)
        try:
            process_video(
                src,
                out,
                remove_metadata=remove_metadata,
                subtle=subtle,
                trim_start=trim_start,
                trim_end=trim_end,
                crf=crf,
                preset=preset,
            )
        except (InputValidationError, ProcessingError) as exc:
            return _json_error(400, str(exc))

        # Return file as download
        return FileResponse(
            out,
            media_type="video/mp4",
            filename=out.name,
            background=None,
        )
    except Exception as exc:
        return _json_error(500, str(exc))


@app.post("/api/upload-cdn")
async def upload_cdn_endpoint(
    file: UploadFile = File(...),
    remote_path: Optional[str] = Form(None),
    cdn_prefix: str = Form("uploads"),
    register_supabase: bool = Form(False),
    caption: Optional[str] = Form(None),
    mute_audio: Optional[str] = Form(None),
    variations: int = Form(1),
    seed: int = Form(42),
):
    """Upload a file to Bunny Storage and optionally register on vd_media."""
    from app.cdn import CdnConfigError, CdnUploadError, default_remote_path, load_bunny_config, upload_file
    from app.supabase_media import SupabaseConfigError, SupabaseMediaError, register_media

    tmp = Path(tempfile.mkdtemp(prefix="vd-up-"))
    try:
        local = await _save_upload(file, tmp)
        remote = (remote_path or default_remote_path(local, prefix=cdn_prefix)).lstrip("/")
        try:
            cfg = load_bunny_config()
            base_url = upload_file(local, remote, config=cfg)
            public = cfg.public_url(remote, cache_bust=str(int(time.time())))
        except (CdnConfigError, CdnUploadError) as exc:
            return _json_error(400, str(exc))

        result = {
            "ok": True,
            "remote": remote,
            "public_url": public,
            "base_url": base_url,
        }

        if register_supabase:
            try:
                row = register_media(
                    local,
                    public_url=public.split("?")[0],
                    storage_path=remote,
                    status="ready",
                    caption=caption,
                )
                result["media"] = {
                    "id": row.get("id"),
                    "public_url": row.get("public_url"),
                    "status": row.get("status"),
                }
            except (SupabaseConfigError, SupabaseMediaError) as exc:
                result["supabase_error"] = str(exc)

        return result
    except Exception as exc:
        return _json_error(500, str(exc))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)




@app.post("/api/process-variations")
async def process_variations(
    file: UploadFile = File(...),
    variations: int = Form(3),
    mode: str = Form("strong"),
    hflip: Optional[str] = Form(None),
    crop_percent: Optional[float] = Form(None),
    speed: Optional[float] = Form(None),
    trim_start: Optional[float] = Form(None),
    trim_end: Optional[float] = Form(None),
    remove_metadata: bool = Form(True),
    subtle: bool = Form(True),
    crf: int = Form(20),
    preset: str = Form("medium"),
    cdn_prefix: str = Form("uploads"),
    register_supabase: bool = Form(True),
    caption: Optional[str] = Form(None),
    mute_audio: Optional[str] = Form(None),
    seed: int = Form(42),
):
    """
    Generate N micro-variations from one video.
    Each variation: process → Bunny CDN → optional vd_media.
    """
    from app.cdn import CdnConfigError, CdnUploadError, default_remote_path, delete_file, load_bunny_config, upload_file
    from app.processor import InputValidationError, ProcessingError, process_video
    from app.rendi import RendiError, process_via_rendi
    from app.supabase_media import SupabaseConfigError, SupabaseMediaError, register_media
    from app.transforms import generate_variation_params

    def _as_bool(v):
        if v is None:
            return None
        if isinstance(v, bool):
            return v
        return str(v).strip().lower() in ("1", "true", "yes", "on")

    hflip_b = _as_bool(hflip)
    mute_b = _as_bool(mute_audio) or False
    variations = max(1, min(int(variations or 1), 10))

    use_rendi = bool(os.environ.get("RENDI_API_KEY")) and (
        not shutil.which("ffmpeg") or os.environ.get("FORCE_RENDI") == "1"
    )
    if not shutil.which("ffmpeg") and not os.environ.get("RENDI_API_KEY"):
        return _json_error(503, "FFmpeg local e RENDI_API_KEY indisponíveis")

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
    try:
        src = await _save_upload(file, tmp / "in")
        cfg = None
        try:
            cfg = load_bunny_config()
        except Exception as exc:
            return _json_error(400, f"cdn config: {exc}")

        in_url = None
        in_remote = None
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
                        remove_metadata=remove_metadata,
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
                        remove_metadata=remove_metadata,
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
                base_url = upload_file(out, remote, config=cfg)
                public = cfg.public_url(remote, cache_bust=str(int(time.time())))
                item.update({"ok": True, "remote": remote, "public_url": public, "base_url": base_url})

                if register_supabase:
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
                    except (SupabaseConfigError, SupabaseMediaError) as exc:
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
    subtle: bool = Form(True),
    mode: str = Form("strong"),
    hflip: Optional[str] = Form(None),  # "true"/"false"
    crop_percent: Optional[float] = Form(None),
    speed: Optional[float] = Form(None),
    remove_metadata: bool = Form(True),
    trim_start: Optional[float] = Form(None),
    trim_end: Optional[float] = Form(None),
    crf: int = Form(20),
    preset: str = Form("medium"),
    cdn_prefix: str = Form("uploads"),
    register_supabase: bool = Form(True),
    caption: Optional[str] = Form(None),
    mute_audio: Optional[str] = Form(None),
    variations: int = Form(1),
    seed: int = Form(42),
):
    # normalize form flags from multipart strings
    def _as_bool(v):
        if v is None:
            return None
        if isinstance(v, bool):
            return v
        return str(v).strip().lower() in ("1", "true", "yes", "on")
    hflip_b = _as_bool(hflip)
    mute_b = _as_bool(mute_audio) or False
    """
    Full pipeline: process (FFmpeg) → Bunny CDN → optional vd_media register.
    """
    from app.cdn import CdnConfigError, CdnUploadError, default_remote_path, load_bunny_config, upload_file
    from app.processor import InputValidationError, ProcessingError, process_video
    from app.supabase_media import SupabaseConfigError, SupabaseMediaError, register_media

    use_rendi = bool(os.environ.get("RENDI_API_KEY")) and (
        not shutil.which("ffmpeg") or os.environ.get("FORCE_RENDI") == "1"
    )
    if not shutil.which("ffmpeg") and not os.environ.get("RENDI_API_KEY"):
        return _json_error(
            503,
            "FFmpeg local e RENDI_API_KEY indisponíveis — configure um dos dois",
        )

    tmp = Path(tempfile.mkdtemp(prefix="vd-pub-"))
    try:
        src = await _save_upload(file, tmp / "in")
        out = tmp / "out" / f"{src.stem}_processed.mp4"
        out.parent.mkdir(parents=True, exist_ok=True)

        in_remote = None
        if use_rendi:
            from app.cdn import default_remote_path as _drp, delete_file as _del, load_bunny_config as _lbc, upload_file as _up
            from app.rendi import RendiError, process_via_rendi

            # Input must be a public URL for Rendi
            try:
                cfg = _lbc()
                in_remote = _drp(src, prefix="rendi-in")
                in_url = _up(src, in_remote, config=cfg)
            except Exception as exc:
                return _json_error(400, f"cdn input for rendi: {exc}")
            try:
                rendi_res = process_via_rendi(
                    in_url.split("?")[0],
                    output_path=out,
                    subtle=subtle,
                    remove_metadata=remove_metadata,
                    mode=mode,
                    hflip=hflip_b,
                    crop_percent=crop_percent,
                    speed=speed,
                    mute_audio=mute_b,
                    trim_start=trim_start,
                    trim_end=trim_end,
                    crf=crf,
                    preset=preset,
                    download=True,
                )
            except RendiError as exc:
                return _json_error(400, f"rendi: {exc}")
        else:
            try:
                process_video(
                    src,
                    out,
                    remove_metadata=remove_metadata,
                    subtle=subtle,
                    mode=mode,
                    hflip=hflip_b,
                    crop_percent=crop_percent,
                    speed=speed,
                    mute_audio=mute_b,
                    trim_start=trim_start,
                    trim_end=trim_end,
                    crf=crf,
                    preset=preset,
                )
            except (InputValidationError, ProcessingError) as exc:
                return _json_error(400, f"process: {exc}")

        remote = default_remote_path(out, prefix=cdn_prefix)
        try:
            cfg = load_bunny_config()
            base_url = upload_file(out, remote, config=cfg)
            public = cfg.public_url(remote, cache_bust=str(int(time.time())))
        except (CdnConfigError, CdnUploadError) as exc:
            return _json_error(400, f"cdn: {exc}")

        result = {
            "ok": True,
            "remote": remote,
            "public_url": public,
            "base_url": base_url,
            "processed": True,
            "subtle": subtle,
            "mode": mode,
        }

        # Delete temporary original used only as Rendi input
        if in_remote:
            try:
                from app.cdn import delete_file as _del2
                _del2(in_remote, config=cfg)
                result["rendi_input_cleaned"] = True
            except Exception as exc:
                result["rendi_input_cleaned"] = False
                result["rendi_input_cleanup_error"] = str(exc)

        if register_supabase:
            try:
                row = register_media(
                    out,
                    public_url=public.split("?")[0],
                    storage_path=remote,
                    status="ready",
                    caption=caption,
                )
                result["media"] = {
                    "id": row.get("id"),
                    "public_url": row.get("public_url"),
                    "status": row.get("status"),
                    "caption": row.get("caption"),
                }
            except (SupabaseConfigError, SupabaseMediaError) as exc:
                result["supabase_error"] = str(exc)

        return result
    except Exception as exc:
        return _json_error(500, str(exc))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


@app.get("/process")
def process_page():
    page = PUBLIC / "process.html"
    if page.is_file():
        return FileResponse(page, media_type="text/html; charset=utf-8")
    return JSONResponse({"error": "process.html missing"}, status_code=404)


@app.get("/")
def index():
    index_file = PUBLIC / "index.html"
    if index_file.is_file():
        return FileResponse(index_file, media_type="text/html; charset=utf-8")
    return JSONResponse(
        {"service": "video-deduplicator", "status": "ok", "message": "Frontend not found"}
    )


@app.get("/api")
def api_root():
    return {
        "service": "video-deduplicator",
        "status": "ok",
        "routes": [
            "GET  /api/health",
            "GET  /api/cdn-config",
            "GET  /api/media",
            "POST /api/process",
            "POST /api/upload-cdn",
            "POST /api/process-variations",
            "POST /api/process-and-publish",
        ],
    }
