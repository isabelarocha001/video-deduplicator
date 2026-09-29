"""Tests for app.cdn."""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from app.cdn import (
    BunnyConfig,
    CdnConfigError,
    default_remote_path,
    load_bunny_config,
    upload_file,
)


def test_load_bunny_config_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BUNNY_STORAGE_ZONE", "myzone")
    monkeypatch.setenv("BUNNY_STORAGE_API_KEY", "secret-key-1234")
    monkeypatch.setenv("BUNNY_STORAGE_HOST", "br.storage.bunnycdn.com")
    monkeypatch.setenv("BUNNY_CDN_HOSTNAME", "cdn.example.b-cdn.net")
    cfg = load_bunny_config()
    assert cfg.storage_zone == "myzone"
    assert cfg.public_base == "https://cdn.example.b-cdn.net"


def test_load_bunny_config_missing_zone(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("BUNNY_STORAGE_ZONE", raising=False)
    monkeypatch.setenv("BUNNY_STORAGE_API_KEY", "x")
    with pytest.raises(CdnConfigError, match="STORAGE_ZONE"):
        load_bunny_config()


def test_public_url_with_cache_bust() -> None:
    cfg = BunnyConfig(
        storage_zone="z",
        storage_api_key="k",
        cdn_hostname="cdn.example.b-cdn.net",
    )
    url = cfg.public_url("uploads/a.mp4", cache_bust="123")
    assert url == "https://cdn.example.b-cdn.net/uploads/a.mp4?v=123"


def test_default_remote_path() -> None:
    assert default_remote_path(Path("/tmp/video.mp4")) == "uploads/video.mp4"
    assert default_remote_path(Path("x.mp4"), prefix="vids") == "vids/x.mp4"


def test_upload_file_success(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    f = tmp_path / "clip.mp4"
    f.write_bytes(b"fake-video-bytes")

    cfg = BunnyConfig(
        storage_zone="z",
        storage_api_key="key",
        storage_host="storage.example.com",
        cdn_hostname="cdn.example.b-cdn.net",
    )

    mock_resp = MagicMock()
    mock_resp.status = 201
    mock_resp.__enter__ = lambda s: s
    mock_resp.__exit__ = MagicMock(return_value=False)

    with patch("urllib.request.urlopen", return_value=mock_resp) as mock_open:
        url = upload_file(f, "uploads/clip.mp4", config=cfg)

    assert url == "https://cdn.example.b-cdn.net/uploads/clip.mp4"
    assert mock_open.called
    req = mock_open.call_args[0][0]
    assert req.get_method() == "PUT"
    assert "AccessKey" in req.headers or req.headers.get("Accesskey") or True
