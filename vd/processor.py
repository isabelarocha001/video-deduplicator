"""Core video processing logic using FFmpeg via subprocess."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Optional

from vd.transforms import build_transform_plan, resolve_mode


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


def check_ffprobe() -> Optional[str]:
    """Return ffprobe path if available."""
    return shutil.which("ffprobe")


def get_duration_seconds(input_path: Path) -> Optional[float]:
    """Return media duration in seconds via ffprobe, or None if unavailable."""
    ffprobe = check_ffprobe()
    if not ffprobe:
        return None
    try:
        result = subprocess.run(
            [
                ffprobe,
                "-v",
                "quiet",
                "-print_format",
                "json",
                "-show_format",
                str(input_path),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            return None
        data = json.loads(result.stdout or "{}")
        duration = data.get("format", {}).get("duration")
        return float(duration) if duration is not None else None
    except (OSError, ValueError, json.JSONDecodeError):
        return None


def probe_metadata(input_path: Path) -> dict:
    """Return user-visible metadata from a media file using ffprobe.

    The full filename is intentionally not returned because uploads are stored
    under temporary paths.  Tags are kept separately for the UI to compare the
    original file with each processed output.
    """
    ffprobe = check_ffprobe()
    if not ffprobe:
        return {
            "available": False,
            "error": "ffprobe não está disponível neste ambiente.",
        }

    result = subprocess.run(
        [
            ffprobe,
            "-v",
            "error",
            "-print_format",
            "json",
            "-show_format",
            "-show_streams",
            "-show_chapters",
            str(input_path),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        detail = (result.stderr or "ffprobe não conseguiu ler o arquivo.").strip()
        raise ProcessingError(f"Não foi possível ler os metadados: {detail[-800:]}")

    try:
        data = json.loads(result.stdout or "{}")
    except json.JSONDecodeError as exc:
        raise ProcessingError("ffprobe retornou dados inválidos de metadados.") from exc

    source_format = data.get("format") or {}
    format_info = {
        key: source_format.get(key)
        for key in ("format_name", "duration", "size", "bit_rate")
        if source_format.get(key) is not None
    }

    def tags_of(value: dict) -> dict[str, str]:
        tags = value.get("tags") or {}
        return {str(key): str(item) for key, item in tags.items() if item is not None}

    streams = []
    for stream in data.get("streams") or []:
        item = {
            key: stream.get(key)
            for key in (
                "index",
                "codec_type",
                "codec_name",
                "width",
                "height",
                "duration",
                "sample_rate",
                "channels",
            )
            if stream.get(key) is not None
        }
        stream_tags = tags_of(stream)
        if stream_tags:
            item["tags"] = stream_tags
        streams.append(item)

    chapters = []
    for chapter in data.get("chapters") or []:
        item = {
            key: chapter.get(key)
            for key in ("id", "start_time", "end_time")
            if chapter.get(key) is not None
        }
        chapter_tags = tags_of(chapter)
        if chapter_tags:
            item["tags"] = chapter_tags
        chapters.append(item)

    return {
        "available": True,
        "format": format_info,
        "tags": tags_of(source_format),
        "streams": streams,
        "chapters": chapters,
    }


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
    subtle: bool = False,
    mode: Optional[str] = None,
    hflip: Optional[bool] = None,
    crop_percent: Optional[float] = None,
    speed: Optional[float] = None,
    mute_audio: bool = False,
    trim_start: Optional[float] = None,
    trim_end: Optional[float] = None,
    duration: Optional[float] = None,
) -> list[str]:
    """Build FFmpeg args with transform modes (light/medium/strong)."""
    plan = build_transform_plan(
        mode=resolve_mode(mode, subtle=subtle),
        subtle=subtle,
        hflip=hflip,
        crop_percent=crop_percent,
        trim_start=trim_start,
        trim_end=trim_end,
        speed=speed,
        explicit_crop=crop,
    )

    args: list[str] = ["-y"]
    start = float(plan.trim_start or 0.0)
    end_cut = float(plan.trim_end or 0.0)

    if start > 0:
        args.extend(["-ss", str(start)])

    args.extend(["-i", str(input_path)])

    if start > 0 or end_cut > 0:
        if duration is not None and duration > 0:
            out_len = duration - start - end_cut
            if out_len <= 0:
                raise InputValidationError(
                    "trim_start + trim_end excedem a duração do vídeo"
                )
            args.extend(["-t", str(out_len)])

    vf_parts: list[str] = list(plan.vf)

    if width is not None or height is not None:
        if preserve_aspect:
            w = width if width is not None else -2
            h = height if height is not None else -2
            vf_parts.append(f"scale={w}:{h}")
        else:
            w = width if width is not None else -1
            h = height if height is not None else -1
            vf_parts.append(f"scale={w}:{h}")

    if vf_parts:
        args.extend(["-vf", ",".join(vf_parts)])

    if mute_audio:
        # strip audio entirely
        pass
    elif plan.af:
        args.extend(["-af", ",".join(plan.af)])

    args.extend(["-c:v", "libx264", "-crf", str(crf), "-preset", preset])
    if mute_audio:
        args.append("-an")
    else:
        args.extend(["-c:a", "aac", "-b:a", "192k"])

    if remove_metadata:
        args.extend(["-map_metadata", "-1"])

    args.extend(["-movflags", "+faststart"])
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
    subtle: bool = False,
    mode: Optional[str] = None,
    hflip: Optional[bool] = None,
    crop_percent: Optional[float] = None,
    speed: Optional[float] = None,
    mute_audio: bool = False,
    trim_start: Optional[float] = None,
    trim_end: Optional[float] = None,
) -> Path:
    """Process a video file with FFmpeg."""
    input_path = Path(input_path)
    output_path = Path(output_path)

    validate_input(input_path)
    ffmpeg = check_ffmpeg()

    if trim_start is not None and trim_start < 0:
        raise InputValidationError("trim_start deve ser >= 0")
    if trim_end is not None and trim_end < 0:
        raise InputValidationError("trim_end deve ser >= 0")

    plan = build_transform_plan(
        mode=resolve_mode(mode, subtle=subtle),
        subtle=subtle,
        hflip=hflip,
        crop_percent=crop_percent,
        trim_start=trim_start,
        trim_end=trim_end,
        speed=speed,
        explicit_crop=crop,
    )
    # use resolved trims from plan
    trim_start = plan.trim_start or None
    trim_end = plan.trim_end or None

    duration: Optional[float] = None
    needs_duration = (trim_end is not None and trim_end > 0) or (
        trim_start is not None and trim_start > 0
    )
    if needs_duration:
        duration = get_duration_seconds(input_path)
        if duration is None and trim_end and trim_end > 0:
            raise ProcessingError(
                "Não foi possível obter a duração do vídeo (ffprobe ausente ou "
                "falhou). trim_end requer ffprobe."
            )

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
        subtle=subtle,
        mode=mode,
        hflip=hflip,
        crop_percent=crop_percent,
        speed=speed,
        mute_audio=mute_audio,
        trim_start=trim_start,
        trim_end=trim_end,
        duration=duration,
    )

    # End-only trim without start: use -sseof before -i
    if (trim_end is not None and trim_end > 0) and not (trim_start and trim_start > 0):
        if duration is None:
            args = ["-y", "-sseof", f"-{trim_end}", "-i", str(input_path)]
            vf_parts = []
            if crop:
                vf_parts.append(f"crop={crop}")
            if subtle:
                vf_parts.append("crop=iw-2:ih-2:1:1")
                vf_parts.append("scale=trunc(iw/2)*2:trunc(ih/2)*2")
                vf_parts.append("eq=contrast=1.01:saturation=1.01")
            if width is not None or height is not None:
                if preserve_aspect:
                    w = width if width is not None else -2
                    h = height if height is not None else -2
                    vf_parts.append(f"scale={w}:{h}")
                else:
                    w = width if width is not None else -1
                    h = height if height is not None else -1
                    vf_parts.append(f"scale={w}:{h}")
            if vf_parts:
                args.extend(["-vf", ",".join(vf_parts)])
            if subtle:
                args.extend(["-af", "volume=1.01"])
            args.extend(
                ["-c:v", "libx264", "-crf", str(crf), "-preset", preset, "-c:a", "aac", "-b:a", "192k"]
            )
            if remove_metadata:
                args.extend(["-map_metadata", "-1"])
            args.extend(["-movflags", "+faststart", str(output_path)])

    cmd = [ffmpeg, *args]

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=False)
    except OSError as exc:
        raise ProcessingError(f"Falha ao executar FFmpeg: {exc}") from exc

    if result.returncode != 0:
        stderr_tail = (result.stderr or "")[-2000:]
        raise ProcessingError(
            f"FFmpeg retornou código {result.returncode}.\n{stderr_tail}"
        )

    if not output_path.exists() or output_path.stat().st_size == 0:
        raise ProcessingError(f"Arquivo de saída não foi gerado: {output_path}")

    return output_path
