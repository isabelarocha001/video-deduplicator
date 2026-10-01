"""
Vercel FastAPI entrypoint (framework preset looks for main.py / app = FastAPI()).
"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile
import traceback
import uuid
from pathlib import Path
from typing import Any, Optional

_ROOT = Path(__file__).resolve().parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from fastapi import FastAPI, File, Form, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, RedirectResponse

app = FastAPI(title="video-deduplicator", version="0.6.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

PUBLIC = _ROOT / "public"


def _err(status: int, message: str, **extra: Any) -> JSONResponse:
    return JSONResponse({"ok": False, "error": message, **extra}, status_code=status)


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
            "traceback": traceback.format_exc()[-1200:],
        },
        status_code=500,
    )


@app.get("/api/index")
@app.get("/api/health")
@app.get("/health")
def health():
    return {
        "status": "healthy",
        "service": "video-deduplicator",
        "build": "0.6.0",
        "ffmpeg": bool(shutil.which("ffmpeg")),
        "rendi": bool(os.environ.get("RENDI_API_KEY")),
        "bunny": False,
        "supabase_storage": bool(
            os.environ.get("SUPABASE_URL")
            and os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
        ),
        "supabase": bool(
            os.environ.get("SUPABASE_URL") and os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
        ),
        "vd_pkg": (_ROOT / "vd").is_dir(),
    }


@app.get("/process")
def process_page():
    # The Vercel FastAPI runtime serves files from public/ through the CDN
    # (public/process.html -> /process.html). Redirect here instead of trying
    # to read the static file from inside the serverless function bundle.
    return RedirectResponse(url="/process.html", status_code=307)


@app.post("/api/index")
@app.post("/api/process")
@app.post("/api/process-variations")
@app.post("/api/process-and-publish")
async def process_entry(
    file: UploadFile = File(...),
    action: Optional[str] = Form("process-variations"),
    variations: int = Form(1),
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
    action = (action or "process-variations").strip().lower()
    if action in ("process-and-publish", "process"):
        variations = 1

    from vd.processor import process_video
    from vd.rendi import process_via_rendi
    from vd.supabase_media import register_media
    from vd.supabase_storage import (
        access_url,
        default_storage_path,
        delete_file,
        load_supabase_storage_config,
        upload_file,
    )
    from vd.transforms import generate_variation_params

    hflip_b = _as_bool(hflip)
    mute_b = _as_bool(mute_audio) or False
    remove_b = _as_bool(remove_metadata)
    if remove_b is None:
        remove_b = True
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
    process_needed = action != "upload-cdn"

    if process_needed and not has_ffmpeg and not has_rendi:
        return _err(
            503,
            "Sem FFmpeg e sem RENDI_API_KEY. Configure Environment Variables na Vercel.",
        )

    try:
        cfg = load_supabase_storage_config()
    except Exception as exc:
        return _err(400, f"Supabase Storage config: {exc}")

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
        params_list = [{
            "mode": "off", "hflip": False, "crop_percent": 0,
            "trim_start": 0, "trim_end": 0, "speed": 1.0,
            "label": "v1", "index": 1,
        }]

    tmp = Path(tempfile.mkdtemp(prefix="vd-"))
    items: list[dict[str, Any]] = []
    in_remote = None
    try:
        src = await _save_upload(file, tmp / "in")
        in_url = None
        if use_rendi and process_needed:
            in_remote = default_storage_path(src, prefix="rendi-in")
            in_url = upload_file(src, in_remote, config=cfg)
            in_url = access_url(in_remote, config=cfg)

        for p in params_list:
            label = p["label"]
            out = tmp / "out" / f"{src.stem}_{label}.mp4"
            out.parent.mkdir(parents=True, exist_ok=True)
            item: dict[str, Any] = {"label": label, "params": p, "ok": False}
            try:
                if process_needed:
                    if use_rendi:
                        process_via_rendi(
                            in_url,
                            output_path=out,
                            subtle=True,
                            remove_metadata=remove_b,
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
                            src, out,
                            remove_metadata=remove_b,
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

                remote = default_storage_path(
                    upload_src,
                    prefix=cdn_prefix,
                )
                upload_file(upload_src, remote, config=cfg)
                public = access_url(remote, config=cfg)
                item.update(
                    {
                        "ok": True,
                        "remote": remote,
                        "public_url": public,
                        "changes": {
                            "mode": p.get("mode"),
                            "crop_percent": p.get("crop_percent"),
                            "hflip": p.get("hflip"),
                            "trim_start": p.get("trim_start"),
                            "trim_end": p.get("trim_end"),
                            "speed": p.get("speed"),
                            "audio_removed": bool(mute_b),
                            "metadata_removed": bool(remove_b),
                        },
                    }
                )

                if register_b:
                    try:
                        row = register_media(
                            upload_src,
                            public_url=public,
                            storage_path=remote,
                            status="ready",
                            caption=(f"{caption} ({label})" if caption else label),
                            metadata={"variation": label, "params": p},
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
        if in_remote:
            try:
                delete_file(in_remote, config=cfg)
                cleaned = True
            except Exception:
                cleaned = False

        result = {
            "ok": ok_count > 0,
            "action": action,
            "build": "0.6.0",
            "variations_requested": variations,
            "variations_ok": ok_count,
            "mode": mode,
            "items": items,
            "rendi_input_cleaned": cleaned,
            "public_url": items[0].get("public_url") if items and items[0].get("ok") else None,
            "media": items[0].get("media") if items and items[0].get("ok") else None,
        }
        if ok_count == 0:
            result["error"] = "Nenhuma variação foi processada. Veja o erro de cada item."
            return JSONResponse(result, status_code=502)
        return result
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
