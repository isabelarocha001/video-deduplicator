"""Bunny.net Storage / CDN client for video-deduplicator.

Environment variables (never commit secrets):
  BUNNY_STORAGE_ZONE       Storage zone name (e.g. privsexv5)
  BUNNY_STORAGE_API_KEY    Storage zone password / access key
  BUNNY_STORAGE_HOST       Region host (default: br.storage.bunnycdn.com)
  BUNNY_CDN_HOSTNAME       Pull zone hostname (e.g. privsexcdnv5.b-cdn.net)
  BUNNY_CDN_BASE_URL       Optional full base URL (overrides hostname)

Optional Stream (future):
  BUNNY_LIBRARY_ID
  BUNNY_STREAM_API_KEY
  BUNNY_STREAM_CDN_HOSTNAME
"""

from __future__ import annotations

import mimetypes
import os
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Optional
from urllib.parse import quote


class CdnConfigError(RuntimeError):
    """Missing or invalid CDN configuration."""


class CdnUploadError(RuntimeError):
    """Failed to upload or manage an object on the CDN/storage."""


@dataclass(frozen=True)
class BunnyConfig:
    storage_zone: str
    storage_api_key: str
    storage_host: str = "br.storage.bunnycdn.com"
    cdn_hostname: str = ""
    cdn_base_url: str = ""

    @property
    def public_base(self) -> str:
        if self.cdn_base_url:
            return self.cdn_base_url.rstrip("/")
        host = self.cdn_hostname.strip().replace("https://", "").replace("http://", "").rstrip("/")
        if not host:
            raise CdnConfigError(
                "BUNNY_CDN_HOSTNAME ou BUNNY_CDN_BASE_URL é obrigatório para URL pública"
            )
        return f"https://{host}"

    def storage_url(self, remote_path: str) -> str:
        path = remote_path.lstrip("/")
        # Encode path segments but keep slashes
        encoded = "/".join(quote(seg, safe="") for seg in path.split("/"))
        return f"https://{self.storage_host}/{self.storage_zone}/{encoded}"

    def public_url(self, remote_path: str, *, cache_bust: Optional[str] = None) -> str:
        path = remote_path.lstrip("/")
        url = f"{self.public_base}/{path}"
        if cache_bust:
            url = f"{url}?v={cache_bust}"
        return url


def load_bunny_config(
    *,
    storage_zone: Optional[str] = None,
    storage_api_key: Optional[str] = None,
    storage_host: Optional[str] = None,
    cdn_hostname: Optional[str] = None,
    cdn_base_url: Optional[str] = None,
) -> BunnyConfig:
    """Load config from explicit args or environment."""
    zone = (storage_zone or os.environ.get("BUNNY_STORAGE_ZONE") or "").strip()
    key = (storage_api_key or os.environ.get("BUNNY_STORAGE_API_KEY") or "").strip()
    host = (
        storage_host
        or os.environ.get("BUNNY_STORAGE_HOST")
        or "br.storage.bunnycdn.com"
    ).strip()
    hostname = (cdn_hostname or os.environ.get("BUNNY_CDN_HOSTNAME") or os.environ.get("BUNNY_CDN_PUBLIC") or "").strip()
    base = (cdn_base_url or os.environ.get("BUNNY_CDN_BASE_URL") or "").strip()

    if not zone:
        raise CdnConfigError("BUNNY_STORAGE_ZONE não configurado")
    if not key:
        raise CdnConfigError("BUNNY_STORAGE_API_KEY não configurado")

    return BunnyConfig(
        storage_zone=zone,
        storage_api_key=key,
        storage_host=host,
        cdn_hostname=hostname,
        cdn_base_url=base,
    )


def _guess_content_type(path: Path) -> str:
    ctype, _ = mimetypes.guess_type(str(path))
    return ctype or "application/octet-stream"


def upload_file(
    local_path: Path,
    remote_path: str,
    *,
    config: Optional[BunnyConfig] = None,
    content_type: Optional[str] = None,
) -> str:
    """
    Upload a local file to Bunny Storage.

    Returns the public CDN URL (without cache-bust query).
    """
    local_path = Path(local_path)
    if not local_path.is_file():
        raise CdnUploadError(f"Arquivo local não encontrado: {local_path}")

    cfg = config or load_bunny_config()
    remote_path = remote_path.lstrip("/")
    url = cfg.storage_url(remote_path)
    data = local_path.read_bytes()
    ctype = content_type or _guess_content_type(local_path)

    req = urllib.request.Request(
        url,
        data=data,
        method="PUT",
        headers={
            "AccessKey": cfg.storage_api_key,
            "Content-Type": ctype,
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=300) as resp:
            if resp.status not in (200, 201):
                raise CdnUploadError(f"Upload falhou HTTP {resp.status}")
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")[:500]
        raise CdnUploadError(f"Upload HTTP {exc.code}: {body}") from exc
    except urllib.error.URLError as exc:
        raise CdnUploadError(f"Falha de rede no upload: {exc}") from exc

    return cfg.public_url(remote_path)


def delete_file(
    remote_path: str,
    *,
    config: Optional[BunnyConfig] = None,
) -> None:
    """Delete an object from Bunny Storage."""
    cfg = config or load_bunny_config()
    url = cfg.storage_url(remote_path.lstrip("/"))
    req = urllib.request.Request(
        url,
        method="DELETE",
        headers={"AccessKey": cfg.storage_api_key},
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            if resp.status not in (200, 204):
                raise CdnUploadError(f"Delete falhou HTTP {resp.status}")
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return
        body = exc.read().decode("utf-8", errors="replace")[:500]
        raise CdnUploadError(f"Delete HTTP {exc.code}: {body}") from exc


def default_remote_path(local_path: Path, *, prefix: str = "uploads") -> str:
    """Build a remote path from local filename under a prefix."""
    name = local_path.name
    prefix = prefix.strip("/") or "uploads"
    return f"{prefix}/{name}"
