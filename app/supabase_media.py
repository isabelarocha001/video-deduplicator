"""Register processed media on Supabase (vd_media) after CDN upload.

Environment:
  SUPABASE_URL
  SUPABASE_SERVICE_ROLE_KEY

Uses service role so CLI can insert without user JWT.
Never commit secrets.
"""

from __future__ import annotations

import hashlib
import mimetypes
import os
from pathlib import Path
from typing import Any, Optional


class SupabaseConfigError(RuntimeError):
    """Missing Supabase credentials."""


class SupabaseMediaError(RuntimeError):
    """Failed to write media registry."""


def _client():
    try:
        from supabase import create_client
    except ImportError as exc:
        raise SupabaseConfigError(
            "Pacote supabase não instalado. Rode: pip install supabase"
        ) from exc

    url = (os.environ.get("SUPABASE_URL") or "").strip()
    key = (os.environ.get("SUPABASE_SERVICE_ROLE_KEY") or "").strip()
    if not url or not key:
        raise SupabaseConfigError(
            "SUPABASE_URL e SUPABASE_SERVICE_ROLE_KEY são obrigatórios"
        )
    return create_client(url, key)


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

    client = _client()
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

    try:
        result = client.table("vd_media").insert(row).execute()
    except Exception as exc:
        raise SupabaseMediaError(f"Falha ao inserir vd_media: {exc}") from exc

    data = (result.data or [None])[0]
    if not data:
        raise SupabaseMediaError("Insert vd_media não retornou linha")

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
            client.table("vd_media_fingerprints").upsert(
                fp, on_conflict="media_id,algorithm,version"
            ).execute()
        except Exception as exc:
            # Media row exists; fingerprint is best-effort
            data["_fingerprint_error"] = str(exc)

    return data
