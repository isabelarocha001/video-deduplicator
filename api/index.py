"""
Vercel Python entrypoint.

Important: with vercel.json rewrites, the ASGI path is always "/api/index".
All routes are therefore registered on /api/index (and / for safety).
The frontend sends header X-VD-Action or form field "action".
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import time
import traceback
import uuid
from pathlib import Path
from typing import Any, Optional

ROOT = Path(__file__).resolve().parent.parent
API_DIR = Path(__file__).resolve().parent
for _p in (ROOT, API_DIR, Path.cwd()):
    s = str(_p)
    if s not in sys.path:
        sys.path.insert(0, s)

from fastapi import FastAPI, File, Form, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

app = FastAPI(title="video-deduplicator", version="0.4.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


def _json_error(status: int, message: str, **extra: Any) -> JSONResponse:
    body = {"ok": False, "error": message}
    body.update(extra)
    return JSONResponse(body, status_code=status)


def _as_bool(v: Any) -> Optional[bool]:
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


@app.exception_handler(Exception)
async def _unhandled(request: Request, exc: Exception):
    return JSONResponse(
        {
            "ok": False,
            "error": str(exc),
            "type": type(exc).__name__,
            "traceback": traceback.format_exc()[-1500:],
        },
        status_code=500,
    )


def _health() -> dict:
    return {
        "status": "healthy",
        "service": "video-deduplicator",
        "ffmpeg": bool(shutil.which("ffmpeg")),
        "rendi_configured": bool(os.environ.get("RENDI_API_KEY")),
        "bunny_configured": bool(
            os.environ.get("BUNNY_STORAGE_ZONE") and os.environ.get("BUNNY_STORAGE_API_KEY")
        ),
        "supabase_configured": bool(
            os.environ.get("SUPABASE_URL") and os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
        ),
    }


@app.get("/api/index")
@app.get("/api/health")
@app.get("/health")
@app.get("/")
def health():
    return _health()


@app.get("/api/index/media")
def list_media(limit: int = 24, status: str = "ready"):
    import urllib.parse
    import urllib.request

    base = (os.environ.get("SUPABASE_URL") or "").rstrip("/")
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY") or ""
    if not base or not key:
        return _json_error(400, "SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY não configurados")
    limit = max(1, min(int(limit), 100))
    qs = urllib.parse.urlencode(
        {
            "select": "id,storage_path,original_name,media_type,mime_type,size_bytes,public_url,thumb_url,caption,status,created_at",
            "status": f"eq.{status}",
            "order": "created_at.desc",
            "limit": str(limit),
        }
    )
    req = urllib.request.Request(
        f"{base}/rest/v1/vd_media?{qs}",
        headers={"apikey": key, "Authorization": f"Bearer {key}"},
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode("utf-8") or "[]")
    except Exception as exc:
        return _json_error(500, str(exc))
    return {"ok": True, "items": data, "count": len(data)}


@app.post("/api/index")
async def entry_post(
    request: Request,
    file: UploadFile = File(...),
    action: Optional[str] = Form("process-variations"),
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
    """
    Single POST entry for Vercel.
    action: process-variations | process-and-publish | upload-cdn
    """
    action = (action or request.headers.get("x-vd-action") or "process-variations").strip().lower()
    if action in ("process-and-publish", "process"):
        variations = 1
    return await _process_variations(
        file=file,
        variations=variations,
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
        seed=seed,
        action=action,
    )


async def _process_variations(
    *,
    file: UploadFile,
    variations: int,
    mode: str,
    hflip: Optional[str],
    crop_percent: Optional[float],
    speed: Optional[float],
    trim_start: Optional[float],
    trim_end: Optional[float],
    remove_metadata: Optional[str],
    subtle: Optional[str],
    crf: int,
    preset: str,
    cdn_prefix: str,
    register_supabase: Optional[str],
    caption: Optional[str],
    mute_audio: Optional[str],
    seed: int,
    action: str = "process-variations",
):
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

    # upload-cdn only: no ffmpeg needed
    process_needed = action != "upload-cdn"

    if process_needed and not has_ffmpeg and not has_rendi:
        return _json_error(
            503,
            "Sem FFmpeg na Vercel e RENDI_API_KEY não configurada. "
            "Em Vercel → Project → Settings → Environment Variables, defina: "
            "RENDI_API_KEY, BUNNY_STORAGE_ZONE, BUNNY_STORAGE_API_KEY, "
            "BUNNY_STORAGE_HOST, BUNNY_CDN_HOSTNAME, SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY.",
        )

    try:
        cfg = load_bunny_config()
    except Exception as exc:
        return _json_error(
            400,
            f"CDN não configurado: {exc}. Defina BUNNY_STORAGE_ZONE, BUNNY_STORAGE_API_KEY, BUNNY_CDN_HOSTNAME.",
        )

    if process_needed:
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
    else:
        params_list = [
            {
                "mode": "off",
                "hflip": False,
                "crop_percent": 0,
                "trim_start": 0,
                "trim_end": 0,
                "speed": 1.0,
                "label": "v1",
                "index": 1,
            }
        ]

    tmp = Path(tempfile.mkdtemp(prefix="vd-var-"))
    items = []
    in_remote = None
    try:
        src = await _save_upload(file, tmp / "in")
        in_url = None
        if use_rendi and process_needed:
            try:
                in_remote = default_remote_path(src, prefix="rendi-in")
                in_url = upload_file(src, in_remote, config=cfg)
            except Exception as exc:
                return _json_error(400, f"Falha ao subir original para Rendi: {exc}")

        for p in params_list:
            label = p["label"]
            out = tmp / "out" / f"{src.stem}_{label}.mp4"
            out.parent.mkdir(parents=True, exist_ok=True)
            item: dict[str, Any] = {"label": label, "params": p, "ok": False}
            try:
                if process_needed:
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
                    upload_src = out
                else:
                    upload_src = src

                remote = f"{cdn_prefix.rstrip('/')}/{upload_src.name}"
                upload_file(upload_src, remote, config=cfg)
                public = cfg.public_url(remote, cache_bust=str(int(time.time())))
                item.update({"ok": True, "remote": remote, "public_url": public})

                if register_b:
                    try:
                        row = register_media(
                            upload_src,
                            public_url=public.split("?")[0],
                            storage_path=remote,
                            status="ready",
                            caption=(f"{caption} ({label})" if caption else label),
                            metadata={"variation": label, "params": p, "action": action},
                        )
                        item["media"] = {
                            "id": row.get("id"),
                            "public_url": row.get("public_url"),
                        }
                    except Exception as exc:
                        item["supabase_error"] = str(exc)
            except Exception as exc:
                item["error"] = str(exc)
            items.append(item)

        ok_count = sum(1 for i in items if i.get("ok"))
        cleaned = False
        if in_remote and ok_count > 0:
            try:
                delete_file(in_remote, config=cfg)
                cleaned = True
            except Exception:
                cleaned = False

        return {
            "ok": ok_count > 0,
            "action": action,
            "variations_requested": variations,
            "variations_ok": ok_count,
            "mode": mode,
            "items": items,
            "rendi_input_cleaned": cleaned,
            # convenience for n=1 clients
            "public_url": (items[0].get("public_url") if items and items[0].get("ok") else None),
            "media": (items[0].get("media") if items and items[0].get("ok") else None),
        }
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
