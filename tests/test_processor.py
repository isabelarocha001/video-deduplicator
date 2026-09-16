"""Basic tests for validation, FFmpeg argument building and processing helpers."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from app.processor import (
    FFmpegNotFoundError,
    InputValidationError,
    build_ffmpeg_args,
    check_ffmpeg,
    validate_input,
)


# ---------------------------------------------------------------------------
# validate_input
# ---------------------------------------------------------------------------


def test_validate_input_missing_file(tmp_path: Path) -> None:
    missing = tmp_path / "does_not_exist.mp4"
    with pytest.raises(InputValidationError, match="não encontrado"):
        validate_input(missing)


def test_validate_input_not_a_file(tmp_path: Path) -> None:
    directory = tmp_path / "a_dir"
    directory.mkdir()
    with pytest.raises(InputValidationError, match="não é um arquivo"):
        validate_input(directory)


def test_validate_input_unsupported_extension(tmp_path: Path) -> None:
    bad = tmp_path / "file.txt"
    bad.write_text("not a video")
    with pytest.raises(InputValidationError, match="não suportado"):
        validate_input(bad)


def test_validate_input_ok(tmp_path: Path) -> None:
    good = tmp_path / "video.mp4"
    good.write_bytes(b"\x00\x00")  # minimal placeholder
    validate_input(good)  # should not raise


# ---------------------------------------------------------------------------
# check_ffmpeg
# ---------------------------------------------------------------------------


def test_check_ffmpeg_not_found() -> None:
    with patch("shutil.which", return_value=None):
        with pytest.raises(FFmpegNotFoundError, match="não encontrado"):
            check_ffmpeg()


def test_check_ffmpeg_found() -> None:
    with patch("shutil.which", return_value="/usr/bin/ffmpeg"):
        assert check_ffmpeg() == "/usr/bin/ffmpeg"


# ---------------------------------------------------------------------------
# build_ffmpeg_args
# ---------------------------------------------------------------------------


def test_build_ffmpeg_args_basic() -> None:
    inp = Path("input/video.mp4")
    out = Path("output/video_processed.mp4")
    args = build_ffmpeg_args(inp, out)

    assert args[0] == "-y"
    assert "-i" in args
    assert str(inp) in args
    assert "-c:v" in args
    assert "libx264" in args
    assert "-c:a" in args
    assert "aac" in args
    assert "-map_metadata" in args
    assert "-1" in args
    assert "-movflags" in args
    assert "+faststart" in args
    assert str(out) in args


def test_build_ffmpeg_args_with_crop() -> None:
    args = build_ffmpeg_args(
        Path("in.mp4"),
        Path("out.mp4"),
        crop="1280:720:0:0",
    )
    assert "-vf" in args
    idx = args.index("-vf")
    assert "crop=1280:720:0:0" in args[idx + 1]


def test_build_ffmpeg_args_with_width_height_preserve() -> None:
    args = build_ffmpeg_args(
        Path("in.mp4"),
        Path("out.mp4"),
        width=1280,
        height=720,
        preserve_aspect=True,
    )
    assert "-vf" in args
    idx = args.index("-vf")
    assert "scale=1280:720" in args[idx + 1]


def test_build_ffmpeg_args_crf_and_preset() -> None:
    args = build_ffmpeg_args(
        Path("in.mp4"),
        Path("out.mp4"),
        crf=18,
        preset="slow",
    )
    assert "-crf" in args
    assert "18" in args
    assert "-preset" in args
    assert "slow" in args


def test_build_ffmpeg_args_no_metadata_removal() -> None:
    args = build_ffmpeg_args(
        Path("in.mp4"),
        Path("out.mp4"),
        remove_metadata=False,
    )
    assert "-map_metadata" not in args
