"""Supabase Storage client used by the web processing flow.

The API intentionally uses the service-role key only on the server.  The
bucket must already exist in Supabase Storage.  Public buckets return a
stable public URL; private buckets use short-lived signed URLs for Rendi and
for the result link.

Environment:
  SUPABASE_URL
  SUPABASE_SERVICE_ROLE_KEY
  SUPABASE_STORAGE_BUCKET       (default: vd-media)
  SUPABASE_STORAGE_PUBLIC       (default: false)
  SUPABASE_STORAGE_SIGNED_TTL   (default: 86400 seconds)
"""

from __future__ import annotations

import json
import mimetypes
import os
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional
from urllib.parse import quote


class SupabaseStorageConfigError(RuntimeError):
    """Missing or invalid Supabase Storage configuration."""


class SupabaseStorageError(RuntimeError):
    """Failed to upload, sign, or remove a Storage object."""


@dataclass(frozen=True)
class SupabaseStorageConfig:
    project_url: str
    service_role_key: str
    bucket: str = "vd-media"
    public: bool = False
    signed_ttl: int = 86400

    def _object_path(self, path: str) -> str:
        clean = path.strip("/")
        if not clean:
            raise SupabaseStorageError("storage_path vazio")
        encoded = "/".join(quote(part, safe="") for part in clean.split("/"))
        return f"{self.project_url}/storage/v1/object/{quote(self.bucket, safe='')}/{encoded}"

    def public_url(self, path: str) -> str:
        clean = path.strip("/")
        encoded = "/".join(quote(part, safe="") for part in clean.split("/"))
        return (
            f"{self.project_url}/storage/v1/object/public/"
            f"{quote(self.bucket, safe='')}/{encoded}"
        )


def _as_bool(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def load_supabase_storage_config() -> SupabaseStorageConfig:
    project_url = (os.environ.get("SUPABASE_URL") or "").strip().rstrip("/")
    service_role_key = (os.environ.get("SUPABASE_SERVICE_ROLE_KEY") or "").strip()
    bucket = (os.environ.get("SUPABASE_STORAGE_BUCKET") or "vd-media").strip()
    public = _as_bool(os.environ.get("SUPABASE_STORAGE_PUBLIC"), default=False)
    try:
        signed_ttl = max(300, int(os.environ.get("SUPABASE_STORAGE_SIGNED_TTL") or "86400"))
    except ValueError:
        signed_ttl = 86400

    if not project_url:
        raise SupabaseStorageConfigError("SUPABASE_URL não configurado")
    if not service_role_key:
        raise SupabaseStorageConfigError("SUPABASE_SERVICE_ROLE_KEY não configurado")
    if not bucket:
        raise SupabaseStorageConfigError("SUPABASE_STORAGE_BUCKET não configurado")

    return SupabaseStorageConfig(
        project_url=project_url,
        service_role_key=service_role_key,
        bucket=bucket,
        public=public,
        signed_ttl=signed_ttl,
    )


def _headers(config: SupabaseStorageConfig, *, content_type: Optional[str] = None) -> dict[str, str]:
    result = {
        "apikey": config.service_role_key,
        "Authorization": f"Bearer {config.service_role_key}",
    }
    if content_type:
        result["Content-Type"] = content_type
    return result


def _request_json(
    url: str,
    *,
    method: str,
    config: SupabaseStorageConfig,
    body: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    payload = json.dumps(body).encode("utf-8") if body is not None else None
    headers = _headers(config, content_type="application/json" if body is not None else None)
    req = urllib.request.Request(url, data=payload, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            parsed = json.loads(raw) if raw else {}
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:800]
        raise SupabaseStorageError(f"Storage HTTP {exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise SupabaseStorageError(f"Falha de rede no Supabase Storage: {exc}") from exc
    if isinstance(parsed, dict):
        return parsed
    return {"data": parsed}


def upload_file(
    local_path: Path,
    storage_path: str,
    *,
    config: Optional[SupabaseStorageConfig] = None,
    content_type: Optional[str] = None,
) -> str:
    """Upload a local file to an existing Supabase Storage bucket."""
    path = Path(local_path)
    if not path.is_file():
        raise SupabaseStorageError(f"Arquivo local não encontrado: {path}")
    cfg = config or load_supabase_storage_config()
    data = path.read_bytes()
    mime, _ = mimetypes.guess_type(str(path))
    ctype = content_type or mime or "application/octet-stream"
    req = urllib.request.Request(
        cfg._object_path(storage_path),
        data=data,
        method="POST",
        headers={
            **_headers(cfg, content_type=ctype),
            "x-upsert": "true",
            "cache-control": "31536000",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=300) as resp:
            if resp.status not in (200, 201):
                raise SupabaseStorageError(f"Upload falhou HTTP {resp.status}")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:800]
        raise SupabaseStorageError(f"Upload Storage HTTP {exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise SupabaseStorageError(f"Falha de rede no upload para o Storage: {exc}") from exc
    return storage_path.strip("/")


def signed_url(storage_path: str, *, config: Optional[SupabaseStorageConfig] = None, ttl: Optional[int] = None) -> str:
    cfg = config or load_supabase_storage_config()
    clean = storage_path.strip("/")
    encoded = "/".join(quote(part, safe="") for part in clean.split("/"))
    endpoint = (
        f"{cfg.project_url}/storage/v1/object/sign/"
        f"{quote(cfg.bucket, safe='')}/{encoded}"
    )
    result = _request_json(
        endpoint,
        method="POST",
        config=cfg,
        body={"expiresIn": int(ttl or cfg.signed_ttl)},
    )
    value = result.get("signedURL") or result.get("signedUrl")
    if not value:
        raise SupabaseStorageError(f"Resposta sem signedURL: {result}")
    if str(value).startswith("http"):
        return str(value)
    return f"{cfg.project_url}/storage/v1{value if str(value).startswith('/') else '/' + str(value)}"


def access_url(storage_path: str, *, config: Optional[SupabaseStorageConfig] = None) -> str:
    cfg = config or load_supabase_storage_config()
    if cfg.public:
        return cfg.public_url(storage_path)
    return signed_url(storage_path, config=cfg)


def delete_file(storage_path: str, *, config: Optional[SupabaseStorageConfig] = None) -> None:
    cfg = config or load_supabase_storage_config()
    endpoint = f"{cfg.project_url}/storage/v1/object/remove/{quote(cfg.bucket, safe='')}"
    _request_json(endpoint, method="POST", config=cfg, body={"prefixes": [storage_path.strip("/")]})


def default_storage_path(local_path: Path, *, prefix: str = "uploads") -> str:
    name = Path(local_path).name
    clean_prefix = prefix.strip("/") or "uploads"
    return f"{clean_prefix}/{name}"
