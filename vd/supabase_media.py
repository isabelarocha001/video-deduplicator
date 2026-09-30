"""Register processed media on Supabase (vd_media) after CDN upload.

Environment:
  SUPABASE_URL
  SUPABASE_SERVICE_ROLE_KEY

Uses service role so CLI can insert without user JWT.
Prefers official supabase client; falls back to PostgREST if package missing.
Never commit secrets.
"""

from __future__ import annotations

import hashlib
import json
import mimetypes
import os
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Optional


class SupabaseConfigError(RuntimeError):
    """Missing Supabase credentials."""


class SupabaseMediaError(RuntimeError):
    """Failed to write media registry."""


def _creds() -> tuple[str, str]:
    url = (os.environ.get("SUPABASE_URL") or "").strip().rstrip("/")
    key = (os.environ.get("SUPABASE_SERVICE_ROLE_KEY") or "").strip()
    if not url or not key:
        raise SupabaseConfigError(
            "SUPABASE_URL e SUPABASE_SERVICE_ROLE_KEY são obrigatórios"
        )
    return url, key


def _client():
    try:
        from supabase import create_client
    except ImportError:
        return None
    url, key = _creds()
    return create_client(url, key)


def _rest_insert(table: str, row: dict[str, Any]) -> dict[str, Any]:
    base, key = _creds()
    endpoint = f"{base}/rest/v1/{table}"
    data = json.dumps(row).encode("utf-8")
    req = urllib.request.Request(
        endpoint,
        data=data,
        method="POST",
        headers={
            "apikey": key,
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
            "Prefer": "return=representation",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            body = json.loads(resp.read().decode("utf-8") or "[]")
    except urllib.error.HTTPError as exc:
        err = exc.read().decode("utf-8", errors="replace")[:800]
        raise SupabaseMediaError(f"REST insert {table} HTTP {exc.code}: {err}") from exc
    if isinstance(body, list) and body:
        return body[0]
    if isinstance(body, dict) and body.get("id"):
        return body
    raise SupabaseMediaError(f"REST insert {table} sem linha retornada: {body}")


def _media_type_from_path(path: Path) -> str:
    mime, _ = mimetypes.guess_type(str(path))
    if not mime:
        return "unknown"
    if mime.startswith("video/"):
        return "video"
    if mime.startswith("image/"):
        return "image"
    if mime.startswith("audio/"):
        return "audio"
    return "unknown"


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def register_media(
    local_path: Path,
    *,
    public_url: str,
    storage_path: str,
    status: str = "ready",
    caption: Optional[str] = None,
    user_id: Optional[str] = None,
    thumb_url: Optional[str] = None,
    duration_ms: Optional[int] = None,
    width: Optional[int] = None,
    height: Optional[int] = None,
    metadata: Optional[dict[str, Any]] = None,
    register_exact_fingerprint: bool = True,
) -> dict[str, Any]:
    """
    Insert a row into vd_media (and optional exact fingerprint).

    Returns the inserted vd_media row (dict).
    """
    local_path = Path(local_path)
    if not local_path.is_file():
        raise SupabaseMediaError(f"Arquivo não encontrado: {local_path}")

    mime, _ = mimetypes.guess_type(str(local_path))
    size = local_path.stat().st_size
    meta = dict(metadata or {})
    meta.setdefault("source", "video-deduplicator-cli")

    row: dict[str, Any] = {
        "storage_path": storage_path,
        "original_name": local_path.name,
        "media_type": _media_type_from_path(local_path),
        "mime_type": mime,
        "size_bytes": size,
        "public_url": public_url,
        "status": status,
        "metadata": meta,
    }
    if caption is not None:
        row["caption"] = caption
    if user_id is not None:
        row["user_id"] = user_id
    if thumb_url is not None:
        row["thumb_url"] = thumb_url
    if duration_ms is not None:
        row["duration_ms"] = duration_ms
    if width is not None:
        row["width"] = width
    if height is not None:
        row["height"] = height

    client = _client()
    if client is not None:
        try:
            result = client.table("vd_media").insert(row).execute()
            data = (result.data or [None])[0]
        except Exception as exc:
            raise SupabaseMediaError(f"Falha ao inserir vd_media: {exc}") from exc
        if not data:
            raise SupabaseMediaError("Insert vd_media não retornou linha")
    else:
        data = _rest_insert("vd_media", row)

    media_id = data.get("id")
    if register_exact_fingerprint and media_id:
        sha = _sha256_file(local_path)
        fp = {
            "media_id": media_id,
            "algorithm": "exact",
            "version": "sha256-v1",
            "exact_sha256": sha,
            "metadata": {"source": "video-deduplicator-cli"},
        }
        try:
            if client is not None:
                client.table("vd_media_fingerprints").upsert(
                    fp, on_conflict="media_id,algorithm,version"
                ).execute()
            else:
                _rest_insert("vd_media_fingerprints", fp)
        except Exception as exc:
            data["_fingerprint_error"] = str(exc)

    return data
