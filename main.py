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
from fastapi.staticfiles import StaticFiles

app = FastAPI(title="video-deduplicator", version="0.8.0")
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


def _probe_metadata_safe(path: Path) -> dict[str, Any]:
    try:
        from vd.processor import probe_metadata

        return probe_metadata(path)
    except Exception as exc:
        return {"available": False, "error": str(exc)}


def _metadata_entries(snapshot: Optional[dict[str, Any]]) -> list[dict[str, str]]:
    if not snapshot or not snapshot.get("available"):
        return []
    entries: list[dict[str, str]] = []
    for key, value in (snapshot.get("tags") or {}).items():
        entries.append({"scope": "Contêiner", "key": str(key), "value": str(value)})
    for stream in snapshot.get("streams") or []:
        index = stream.get("index", "?")
        stream_type = stream.get("codec_type") or "stream"
        scope = f"Stream {index} ({stream_type})"
        for key, value in (stream.get("tags") or {}).items():
            entries.append({"scope": scope, "key": str(key), "value": str(value)})
    for chapter in snapshot.get("chapters") or []:
        chapter_id = chapter.get("id", "?")
        scope = f"Capítulo {chapter_id}"
        for key, value in (chapter.get("tags") or {}).items():
            entries.append({"scope": scope, "key": str(key), "value": str(value)})
    return entries


def _removed_metadata(
    before: Optional[dict[str, Any]], after: Optional[dict[str, Any]]
) -> list[dict[str, str]]:
    after_entries = {
        (entry["scope"], entry["key"]): entry["value"]
        for entry in _metadata_entries(after)
    }
    return [
        entry
        for entry in _metadata_entries(before)
        if after_entries.get((entry["scope"], entry["key"])) != entry["value"]
    ]


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
        "build": "0.8.0",
        "ffmpeg": bool(shutil.which("ffmpeg")),
        "rendi": bool(os.environ.get("RENDI_API_KEY")),
        "pillow": True,
        "batch_images": True,
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
    return RedirectResponse(url="/process.html", status_code=307)


@app.post("/api/inspect")
async def inspect_entry(file: UploadFile = File(...)):
    tmp = Path(tempfile.mkdtemp(prefix="vd-inspect-"))
    try:
        src = await _save_upload(file, tmp / "in")
        metadata = _probe_metadata_safe(src)
        if not metadata.get("available"):
            from vd.image_processor import is_image_file

            if is_image_file(src):
                return {
                    "ok": True,
                    "metadata": {
                        "available": True,
                        "tags": {},
                        "format": {"format_name": src.suffix.lstrip(".").lower()},
                        "note": "Imagem: metadados serão removidos no re-save JPEG.",
                    },
                }
            return _err(503, metadata.get("error", "Não foi possível ler os metadados."))
        return {"ok": True, "metadata": metadata}
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _process_one_image(
    src: Path,
    *,
    mode: str,
    seed: int,
    crop_percent: Optional[float],
    cdn_prefix: str,
    register_b: bool,
    caption: Optional[str],
    cfg: Any,
    label: str = "v1",
) -> dict[str, Any]:
    """Processa uma única foto e faz upload. Retorna item dict."""
    from vd.image_processor import process_image, ImageProcessingError, ImageValidationError
    from vd.supabase_media import register_media
    from vd.supabase_storage import access_url, default_storage_path, upload_file

    item: dict[str, Any] = {
        "label": label,
        "source_name": src.name,
        "ok": False,
        "media_type": "image",
    }
    try:
        out = src.parent.parent / "out" / f"{src.stem}_{label}.jpg"
        out.parent.mkdir(parents=True, exist_ok=True)

        result = process_image(
            src,
            out,
            mode=mode,
            seed=seed,
            crop_percent=crop_percent,
        )
        upload_src = result.output_path
        changes = dict(result.changes)
        changes["notes"] = result.notes

        source_metadata = _probe_metadata_safe(src)
        output_metadata = _probe_metadata_safe(upload_src)

        remote = default_storage_path(upload_src, prefix=cdn_prefix)
        upload_file(upload_src, remote, config=cfg)
        public = access_url(remote, config=cfg)

        item.update(
            {
                "ok": True,
                "remote": remote,
                "public_url": public,
                "changes": changes,
                "metadata_after": output_metadata,
                "metadata_removed_details": _removed_metadata(
                    source_metadata, output_metadata
                ),
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
                    metadata={
                        "variation": label,
                        "media_type": "image",
                        "source_name": src.name,
                    },
                )
                item["media"] = {
                    "id": row.get("id"),
                    "public_url": row.get("public_url"),
                }
            except Exception as exc:
                item["supabase_error"] = str(exc)
    except (ImageValidationError, ImageProcessingError) as exc:
        item["error"] = str(exc)
    except Exception as exc:
        item["error"] = str(exc)
    return item


@app.post("/api/process-batch")
async def process_batch(
    files: list[UploadFile] = File(...),
    mode: str = Form("light"),
    crop_percent: Optional[float] = Form(None),
    variations: int = Form(1),
    cdn_prefix: str = Form("uploads"),
    register_supabase: Optional[str] = Form("true"),
    caption: Optional[str] = Form(None),
    seed: int = Form(42),
):
    """Processa várias fotos de uma vez (lote).

    Cada arquivo de imagem é limpo (metadados) + microeditado e enviado ao storage.
    Máximo 30 arquivos por request.
    """
    from vd.image_processor import is_image_file, generate_image_variations
    from vd.supabase_storage import load_supabase_storage_config

    register_b = _as_bool(register_supabase)
    if register_b is None:
        register_b = True

    try:
        variations = max(1, min(int(variations or 1), 5))
    except Exception:
        variations = 1

    if not files:
        return _err(400, "Nenhum arquivo enviado.")

    if len(files) > 30:
        return _err(400, "Máximo de 30 arquivos por lote.")

    try:
        cfg = load_supabase_storage_config()
    except Exception as exc:
        return _err(400, f"Supabase Storage config: {exc}")

    img_mode = mode if mode in ("off", "light", "medium", "strong", "heavy") else "light"

    tmp = Path(tempfile.mkdtemp(prefix="vd-batch-"))
    all_items: list[dict[str, Any]] = []
    skipped: list[str] = []

    try:
        for idx, upload in enumerate(files):
            src = await _save_upload(upload, tmp / "in" / str(idx))
            if not is_image_file(src):
                skipped.append(upload.filename or src.name)
                continue

            params_list = generate_image_variations(
                variations, mode=img_mode, seed=seed + idx * 100
            )
            if crop_percent is not None and params_list:
                params_list[0]["crop_percent"] = float(crop_percent)

            for p in params_list:
                item = _process_one_image(
                    src,
                    mode=p.get("mode", img_mode),
                    seed=int(p.get("seed", seed)),
                    crop_percent=p.get("crop_percent"),
                    cdn_prefix=cdn_prefix,
                    register_b=register_b,
                    caption=caption,
                    cfg=cfg,
                    label=f"{Path(upload.filename or src.name).stem}_{p['label']}",
                )
                item["source_name"] = upload.filename or src.name
                all_items.append(item)

        ok_count = sum(1 for i in all_items if i.get("ok"))
        return {
            "ok": ok_count > 0,
            "action": "process-batch",
            "build": "0.8.0",
            "media_type": "image",
            "files_received": len(files),
            "files_processed": len(files) - len(skipped),
            "files_skipped": skipped,
            "variations_per_file": variations,
            "items_ok": ok_count,
            "items_total": len(all_items),
            "mode": img_mode,
            "items": all_items,
        }
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


@app.post("/api/index")
@app.post("/api/process")
@app.post("/api/process-variations")
@app.post("/api/process-and-publish")
async def process_entry(
    file: UploadFile = File(...),
    action: Optional[str] = Form("process-variations"),
    variations: int = Form(1),
    mode: str = Form("heavy"),
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

    from vd.image_processor import (
        generate_image_variations,
        is_image_file,
        process_image,
        ImageProcessingError,
        ImageValidationError,
    )
    from vd.processor import get_duration_seconds, process_video
    from vd.rendi import process_via_rendi
    from vd.supabase_media import register_media
    from vd.supabase_storage import (
        access_url,
        default_storage_path,
        delete_file,
        load_supabase_storage_config,
        upload_file,
    )
    from vd.transforms import generate_multi_account_params, generate_variation_params

    hflip_b = _as_bool(hflip)
    mute_b = _as_bool(mute_audio) or False
    remove_b = _as_bool(remove_metadata)
    if remove_b is None:
        remove_b = True
    register_b = _as_bool(register_supabase)
    if register_b is None:
        register_b = True

    try:
        variations = max(1, min(int(variations or 1), 10))
    except Exception:
        variations = 1

    has_ffmpeg = bool(shutil.which("ffmpeg"))
    has_rendi = bool((os.environ.get("RENDI_API_KEY") or "").strip())
    use_rendi = has_rendi and (not has_ffmpeg or os.environ.get("FORCE_RENDI") == "1")
    process_needed = action != "upload-cdn"

    try:
        cfg = load_supabase_storage_config()
    except Exception as exc:
        return _err(400, f"Supabase Storage config: {exc}")

    tmp = Path(tempfile.mkdtemp(prefix="vd-"))
    items: list[dict[str, Any]] = []
    in_remote = None

    try:
        src = await _save_upload(file, tmp / "in")
        is_image = is_image_file(src)
        source_metadata = _probe_metadata_safe(src)

        if is_image:
            img_mode = mode if mode in ("off", "light", "medium", "strong", "heavy") else "light"
            if mode in ("multi", "contas", "accounts"):
                img_mode = "medium"

            if process_needed:
                params_list = generate_image_variations(
                    variations, mode=img_mode, seed=seed
                )
                if crop_percent is not None and params_list:
                    params_list[0]["crop_percent"] = float(crop_percent)
            else:
                params_list = [
                    {
                        "mode": "off",
                        "crop_percent": 0,
                        "rotate_deg": 0,
                        "seed": seed,
                        "label": "v1",
                        "index": 1,
                    }
                ]

            for p in params_list:
                item = _process_one_image(
                    src,
                    mode=p.get("mode", img_mode),
                    seed=int(p.get("seed", seed)),
                    crop_percent=p.get("crop_percent"),
                    cdn_prefix=cdn_prefix,
                    register_b=register_b,
                    caption=caption,
                    cfg=cfg,
                    label=p["label"],
                )
                items.append(item)
        else:
            if process_needed and not has_ffmpeg and not has_rendi:
                return _err(
                    503,
                    "Sem FFmpeg e sem RENDI_API_KEY. Configure Environment Variables na Vercel.",
                )

            if process_needed:
                if mode in ("multi", "contas", "accounts"):
                    dur = get_duration_seconds(src) or 30.0
                    params_list = generate_multi_account_params(
                        variations, dur, seed=seed
                    )
                else:
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

            in_url = None
            if use_rendi and process_needed:
                in_remote = default_storage_path(src, prefix="rendi-in")
                upload_file(src, in_remote, config=cfg)
                in_url = access_url(in_remote, config=cfg)

            for p in params_list:
                label = p["label"]
                out = tmp / "out" / f"{src.stem}_{label}.mp4"
                out.parent.mkdir(parents=True, exist_ok=True)
                item: dict[str, Any] = {
                    "label": label,
                    "params": p,
                    "ok": False,
                    "media_type": "video",
                }
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
                                src,
                                out,
                                remove_metadata=remove_b,
                                subtle=True,
                                mode=p["mode"],
                                hflip=p["hflip"],
                                crop_percent=p["crop_percent"],
                                speed=p["speed"],
                                mute_audio=bool(p.get("mute_audio", mute_b)),
                                trim_start=p["trim_start"],
                                trim_end=p.get("trim_end") or 0,
                                clip_duration=p.get("clip_duration"),
                                crf=crf,
                                preset=preset,
                            )
                        upload_src = out
                    else:
                        upload_src = src

                    output_metadata = _probe_metadata_safe(upload_src)
                    remote = default_storage_path(upload_src, prefix=cdn_prefix)
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
                            "metadata_after": output_metadata,
                            "metadata_removed_details": _removed_metadata(
                                source_metadata, output_metadata
                            ),
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
                                metadata={
                                    "variation": label,
                                    "params": p,
                                    "media_type": "video",
                                },
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
            "build": "0.8.0",
            "media_type": "image" if is_image else "video",
            "variations_requested": variations,
            "variations_ok": ok_count,
            "mode": mode,
            "items": items,
            "rendi_input_cleaned": cleaned,
            "public_url": items[0].get("public_url") if items and items[0].get("ok") else None,
            "media": items[0].get("media") if items and items[0].get("ok") else None,
            "metadata_before": source_metadata,
        }
        if ok_count == 0:
            result["error"] = "Nenhuma variação foi processada. Veja o erro de cada item."
            return JSONResponse(result, status_code=502)
        return result
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if PUBLIC.is_dir():
    app.mount("/", StaticFiles(directory=str(PUBLIC), html=True), name="public")
