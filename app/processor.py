"""Core video processing logic using FFmpeg via subprocess."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Optional


class FFmpegNotFoundError(RuntimeError):
    """Raised when the FFmpeg binary is not available on PATH."""


class InputValidationError(ValueError):
    """Raised when the input file is missing or incompatible."""


class ProcessingError(RuntimeError):
    """Raised when FFmpeg fails during processing."""


def check_ffmpeg() -> str:
    """Return the path to the FFmpeg executable or raise FFmpegNotFoundError."""
    ffmpeg_path = shutil.which("ffmpeg")
    if not ffmpeg_path:
        raise FFmpegNotFoundError(
            "FFmpeg não encontrado. Instale o FFmpeg e certifique-se de que "
            "ele está disponível no PATH do sistema."
        )
    return ffmpeg_path


def validate_input(input_path: Path) -> None:
    """Validate that the input file exists and has a supported extension."""
    if not input_path.exists():
        raise InputValidationError(f"Arquivo de entrada não encontrado: {input_path}")
    if not input_path.is_file():
        raise InputValidationError(f"O caminho informado não é um arquivo: {input_path}")

    supported = {".mp4", ".mkv", ".avi", ".mov", ".webm", ".flv", ".wmv", ".m4v"}
    suffix = input_path.suffix.lower()
    if suffix not in supported:
        raise InputValidationError(
            f"Formato de arquivo não suportado: {suffix}. "
            f"Formatos aceitos: {', '.join(sorted(supported))}"
        )


def build_ffmpeg_args(
    input_path: Path,
    output_path: Path,
    *,
    remove_metadata: bool = True,
    crop: Optional[str] = None,
    width: Optional[int] = None,
    height: Optional[int] = None,
    preserve_aspect: bool = True,
    crf: int = 23,
    preset: str = "medium",
) -> list[str]:
    """
    Build a safe list of arguments for the FFmpeg command.

    All values are passed as separate list elements; no string concatenation
    of user-controlled data is performed.
    """
    args: list[str] = [
        "-y",  # overwrite output
        "-i",
        str(input_path),
    ]

    # Video filters
    vf_parts: list[str] = []

    if crop:
        # Expected format: w:h:x:y  e.g. 1280:720:0:0
        vf_parts.append(f"crop={crop}")

    if width is not None or height is not None:
        if preserve_aspect:
            # Scale keeping aspect ratio; -2 means "calculate to keep even dimension"
            w = width if width is not None else -2
            h = height if height is not None else -2
            vf_parts.append(f"scale={w}:{h}")
        else:
            w = width if width is not None else -1
            h = height if height is not None else -1
            vf_parts.append(f"scale={w}:{h}")

    if vf_parts:
        args.extend(["-vf", ",".join(vf_parts)])

    # Video codec
    args.extend(
        [
            "-c:v",
            "libx264",
            "-crf",
            str(crf),
            "-preset",
            preset,
        ]
    )

    # Audio codec
    args.extend(["-c:a", "aac"])

    # Metadata removal
    if remove_metadata:
        args.extend(["-map_metadata", "-1"])

    # Fast start for web playback
    args.extend(["-movflags", "+faststart"])

    # Output path
    args.append(str(output_path))

    return args


def process_video(
    input_path: Path,
    output_path: Path,
    *,
    remove_metadata: bool = True,
    crop: Optional[str] = None,
    width: Optional[int] = None,
    height: Optional[int] = None,
    preserve_aspect: bool = True,
    crf: int = 23,
    preset: str = "medium",
) -> Path:
    """
    Process a video file with FFmpeg.

    - Validates input
    - Checks FFmpeg availability
    - Builds arguments safely
    - Runs subprocess and raises ProcessingError on failure
    """
    validate_input(input_path)
    ffmpeg = check_ffmpeg()

    # Ensure output directory exists
    output_path.parent.mkdir(parents=True, exist_ok=True)

    args = build_ffmpeg_args(
        input_path,
        output_path,
        remove_metadata=remove_metadata,
        crop=crop,
        width=width,
        height=height,
        preserve_aspect=preserve_aspect,
        crf=crf,
        preset=preset,
    )

    cmd = [ffmpeg, *args]

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError as exc:
        raise ProcessingError(f"Falha ao executar FFmpeg: {exc}") from exc

    if result.returncode != 0:
        stderr = (result.stderr or "").strip()
        raise ProcessingError(
            f"FFmpeg retornou código {result.returncode}.\n"
            f"Detalhes: {stderr[-2000:] if stderr else 'sem saída de erro'}"
        )

    if not output_path.exists():
        raise ProcessingError("Processamento concluído, mas o arquivo de saída não foi gerado.")

    return output_path
