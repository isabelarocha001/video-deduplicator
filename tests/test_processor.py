"""Tests for app.processor."""

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


def test_validate_input_missing(tmp_path: Path) -> None:
    with pytest.raises(InputValidationError, match="não encontrado"):
        validate_input(tmp_path / "missing.mp4")


def test_validate_input_bad_extension(tmp_path: Path) -> None:
    bad = tmp_path / "file.txt"
    bad.write_text("x")
    with pytest.raises(InputValidationError, match="não suportado"):
        validate_input(bad)


def test_validate_input_ok(tmp_path: Path) -> None:
    good = tmp_path / "video.mp4"
    good.write_bytes(b"\x00\x00")
    validate_input(good)


def test_check_ffmpeg_not_found() -> None:
    with patch("shutil.which", return_value=None):
        with pytest.raises(FFmpegNotFoundError, match="não encontrado"):
            check_ffmpeg()


def test_check_ffmpeg_found() -> None:
    with patch("shutil.which", return_value="/usr/bin/ffmpeg"):
        assert check_ffmpeg() == "/usr/bin/ffmpeg"


def test_build_ffmpeg_args_basic() -> None:
    args = build_ffmpeg_args(Path("input/video.mp4"), Path("output/video_processed.mp4"))
    assert args[0] == "-y"
    assert "-i" in args
    assert "-c:v" in args and "libx264" in args
    assert "-c:a" in args and "aac" in args
    assert "-map_metadata" in args and "-1" in args
    assert "-movflags" in args and "+faststart" in args


def test_build_ffmpeg_args_with_crop() -> None:
    args = build_ffmpeg_args(Path("in.mp4"), Path("out.mp4"), crop="1280:720:0:0")
    assert "-vf" in args
    assert "crop=1280:720:0:0" in args[args.index("-vf") + 1]


def test_build_ffmpeg_args_with_width_height_preserve() -> None:
    args = build_ffmpeg_args(Path("in.mp4"), Path("out.mp4"), width=1280, height=720, preserve_aspect=True)
    assert "scale=1280:720" in args[args.index("-vf") + 1]


def test_build_ffmpeg_args_crf_and_preset() -> None:
    args = build_ffmpeg_args(Path("in.mp4"), Path("out.mp4"), crf=18, preset="slow")
    assert "18" in args and "slow" in args


def test_build_ffmpeg_args_no_metadata_removal() -> None:
    args = build_ffmpeg_args(Path("in.mp4"), Path("out.mp4"), remove_metadata=False)
    assert "-map_metadata" not in args


def test_build_ffmpeg_args_subtle() -> None:
    args = build_ffmpeg_args(Path("in.mp4"), Path("out.mp4"), subtle=True)
    vf = args[args.index("-vf") + 1]
    assert "crop=" in vf
    assert "eq=contrast=" in vf
    assert "-af" in args


def test_build_ffmpeg_args_trim_start() -> None:
    args = build_ffmpeg_args(Path("in.mp4"), Path("out.mp4"), trim_start=0.5, duration=10.0)
    assert "-ss" in args and "0.5" in args
    assert args[args.index("-t") + 1] == "9.5"


def test_build_ffmpeg_args_trim_both() -> None:
    args = build_ffmpeg_args(Path("in.mp4"), Path("out.mp4"), trim_start=1.0, trim_end=0.5, duration=20.0)
    assert args[args.index("-t") + 1] == "18.5"
