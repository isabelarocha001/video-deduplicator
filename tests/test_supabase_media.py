"""Tests for app.supabase_media (offline helpers)."""

from __future__ import annotations

from pathlib import Path

from vd.supabase_media import _media_type_from_path, _sha256_file


def test_media_type_video(tmp_path: Path) -> None:
    p = tmp_path / "a.mp4"
    p.write_bytes(b"x")
    assert _media_type_from_path(p) == "video"


def test_media_type_image(tmp_path: Path) -> None:
    p = tmp_path / "a.jpg"
    p.write_bytes(b"x")
    assert _media_type_from_path(p) == "image"


def test_sha256(tmp_path: Path) -> None:
    p = tmp_path / "a.bin"
    p.write_bytes(b"hello")
    assert len(_sha256_file(p)) == 64
