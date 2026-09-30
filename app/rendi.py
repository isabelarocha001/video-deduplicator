"""Rendi.dev FFmpeg-as-a-Service client.

Docs: https://www.rendi.dev/docs/introduction
Auth: header X-API-KEY = RENDI_API_KEY

Flow:
  1. Ensure input is a public URL (or upload via Rendi multipart / Bunny CDN)
  2. POST /v1/run-ffmpeg-command
  3. Poll GET /v1/commands/{command_id} until SUCCESS | FAILED
  4. Read output_files.*.storage_url
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

RENDI_BASE = "https://api.rendi.dev/v1"


class RendiConfigError(RuntimeError):
    """Missing RENDI_API_KEY."""


class RendiError(RuntimeError):
    """Rendi API or processing failure."""


def _api_key() -> str:
    key = (os.environ.get("RENDI_API_KEY") or "").strip()
    if not key:
        raise RendiConfigError("RENDI_API_KEY não configurado")
    return key


def _headers() -> dict[str, str]:
    return {
        "X-API-KEY": _api_key(),
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


def _request(
    method: str,
    path: str,
    *,
    body: Optional[dict] = None,
    timeout: int = 120,
) -> dict[str, Any]:
    url = f"{RENDI_BASE}{path}"
    data = None if body is None else json.dumps(body).encode("utf-8")
    req = urllib.request.Request(url, data=data, method=method, headers=_headers())
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8") or "{}"
            return json.loads(raw)
    except urllib.error.HTTPError as e:
        err = e.read().decode("utf-8", errors="replace")[:800]
        raise RendiError(f"Rendi HTTP {e.code}: {err}") from e
    except urllib.error.URLError as e:
        raise RendiError(f"Rendi network error: {e}") from e


def build_subtle_command(
    *,
    crf: int = 23,
    preset: str = "medium",
    trim_start: Optional[float] = None,
    trim_end: Optional[float] = None,
    subtle: bool = True,
    remove_metadata: bool = True,
    mode: Optional[str] = None,
    hflip: Optional[bool] = None,
    crop_percent: Optional[float] = None,
    speed: Optional[float] = None,
    mute_audio: bool = False,
) -> str:
    """Build FFmpeg command string for Rendi (no binary name). Uses {{in_1}}/{{out_1}}."""
    from app.transforms import build_transform_plan, resolve_mode

    plan = build_transform_plan(
        mode=resolve_mode(mode, subtle=subtle),
        subtle=subtle,
        hflip=hflip,
        crop_percent=crop_percent,
        trim_start=trim_start,
        trim_end=trim_end,
        speed=speed,
        mute_audio=mute_audio,
    )
    parts: list[str] = []
    if plan.trim_start and plan.trim_start > 0:
        parts.extend(["-ss", str(plan.trim_start)])
    parts.extend(["-i", "{{in_1}}"])
    # Note: end trim without duration is best-effort; Rendi jobs should prefer mode defaults
    if plan.vf:
        parts.extend(["-vf", ",".join(plan.vf)])
    if mute_audio:
        pass
    elif plan.af:
        parts.extend(["-af", ",".join(plan.af)])
    parts.extend(["-c:v", "libx264", "-crf", str(crf), "-preset", preset])
    if mute_audio:
        parts.append("-an")
    else:
        parts.extend(["-c:a", "aac", "-b:a", "192k"])
    if remove_metadata:
        parts.extend(["-map_metadata", "-1"])
    parts.extend(["-movflags", "+faststart", "{{out_1}}"])
    return " ".join(parts)


def run_ffmpeg_command(
    *,
    input_url: str,
    output_filename: str = "output.mp4",
    ffmpeg_command: Optional[str] = None,
    vcpu_count: int = 2,
    max_command_run_seconds: int = 60,
    metadata: Optional[dict] = None,
) -> str:
    """
    Submit a command. Returns command_id.
    input_url must be publicly reachable by Rendi.
    """
    cmd = ffmpeg_command or build_subtle_command()
    body: dict[str, Any] = {
        "input_files": {"in_1": input_url},
        "output_files": {"out_1": output_filename},
        "ffmpeg_command": cmd,
        "vcpu_count": vcpu_count,
        "max_command_run_seconds": max_command_run_seconds,
    }
    if metadata:
        body["metadata"] = metadata
    result = _request("POST", "/run-ffmpeg-command", body=body)
    command_id = result.get("command_id")
    if not command_id:
        raise RendiError(f"Resposta sem command_id: {result}")
    return str(command_id)


def poll_command(
    command_id: str,
    *,
    timeout_seconds: float = 600,
    interval_seconds: float = 2.0,
) -> dict[str, Any]:
    """Poll until SUCCESS or FAILED (or timeout)."""
    deadline = time.time() + timeout_seconds
    last: dict[str, Any] = {}
    while time.time() < deadline:
        last = _request("GET", f"/commands/{command_id}", timeout=60)
        status = (last.get("status") or "").upper()
        if status in ("SUCCESS", "FAILED", "ERROR", "CANCELLED"):
            return last
        time.sleep(interval_seconds)
    raise RendiError(f"Timeout esperando command {command_id}; last={last}")


def extract_output_url(poll_result: dict[str, Any]) -> str:
    """Get the first output storage_url from a successful poll result."""
    status = (poll_result.get("status") or "").upper()
    if status != "SUCCESS":
        raise RendiError(f"Command não teve sucesso: {status} — {poll_result}")
    outputs = poll_result.get("output_files") or {}
    if isinstance(outputs, dict):
        for _k, v in outputs.items():
            if isinstance(v, dict) and v.get("storage_url"):
                return str(v["storage_url"])
            if isinstance(v, str) and v.startswith("http"):
                return v
    # alternate shapes
    if poll_result.get("storage_url"):
        return str(poll_result["storage_url"])
    raise RendiError(f"Sem storage_url na resposta: {poll_result}")


def download_url(url: str, dest: Path, *, timeout: int = 300) -> Path:
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    req = urllib.request.Request(url, method="GET")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        dest.write_bytes(resp.read())
    if not dest.exists() or dest.stat().st_size == 0:
        raise RendiError(f"Download vazio: {url}")
    return dest


@dataclass
class RendiProcessResult:
    command_id: str
    output_url: str
    local_path: Optional[Path] = None
    raw: Optional[dict] = None


def process_via_rendi(
    input_url: str,
    *,
    output_path: Optional[Path] = None,
    subtle: bool = True,
    remove_metadata: bool = True,
    trim_start: Optional[float] = None,
    trim_end: Optional[float] = None,
    mode: Optional[str] = None,
    hflip: Optional[bool] = None,
    crop_percent: Optional[float] = None,
    speed: Optional[float] = None,
    mute_audio: bool = False,
    crf: int = 23,
    preset: str = "medium",
    vcpu_count: int = 2,
    poll_timeout: float = 600,
    download: bool = True,
) -> RendiProcessResult:
    """
    Full cycle: submit → poll → optional download.

    input_url must be publicly accessible (e.g. Bunny CDN URL).
    """
    cmd = build_subtle_command(
        crf=crf,
        preset=preset,
        trim_start=trim_start,
        trim_end=trim_end,
        subtle=subtle,
        remove_metadata=remove_metadata,
        mode=mode,
        hflip=hflip,
        crop_percent=crop_percent,
        speed=speed,
        mute_audio=mute_audio,
    )
    command_id = run_ffmpeg_command(
        input_url=input_url,
        output_filename="processed.mp4",
        ffmpeg_command=cmd,
        vcpu_count=vcpu_count,
        metadata={"source": "video-deduplicator"},
    )
    result = poll_command(command_id, timeout_seconds=poll_timeout)
    out_url = extract_output_url(result)
    local: Optional[Path] = None
    if download and output_path is not None:
        local = download_url(out_url, Path(output_path))
    return RendiProcessResult(
        command_id=command_id,
        output_url=out_url,
        local_path=local,
        raw=result,
    )


def is_configured() -> bool:
    return bool((os.environ.get("RENDI_API_KEY") or "").strip())
