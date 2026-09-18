"""Video transformation families using FFmpeg."""

from __future__ import annotations

import json
import random
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional


@dataclass
class TransformSpec:
    name: str
    params: dict[str, Any] = field(default_factory=dict)
    family: str = "video"


class VideoTransforms:
    """Controlled perceptual transforms for video via FFmpeg."""

    def __init__(self, seed: Optional[int] = None, work_dir: Optional[Path] = None):
        self.rng = random.Random(seed)
        self.work_dir = work_dir
        self.ffmpeg = shutil.which("ffmpeg")
        self.ffprobe = shutil.which("ffprobe")
        if not self.ffmpeg:
            raise RuntimeError("ffmpeg not found on PATH")

    def probe(self, path: Path) -> dict[str, Any]:
        cmd = [
            self.ffprobe or "ffprobe",
            "-v", "quiet",
            "-print_format", "json",
            "-show_format",
            "-show_streams",
            str(path),
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, check=False)
        if result.returncode != 0:
            return {}
        return json.loads(result.stdout or "{}")

    def _run_ffmpeg(self, args: list[str], timeout: int = 300) -> None:
        cmd = [self.ffmpeg, "-y", "-hide_banner", "-loglevel", "error", *args]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        if result.returncode != 0:
            raise RuntimeError(f"ffmpeg failed: {result.stderr[-1500:]}")

    def recompress(
        self,
        input_path: Path,
        output_path: Path,
        crf: Optional[int] = None,
        preset: Optional[str] = None,
    ) -> TransformSpec:
        c = crf if crf is not None else self.rng.randint(18, 32)
        p = preset or self.rng.choice(["ultrafast", "veryfast", "fast", "medium"])
        self._run_ffmpeg([
            "-i", str(input_path),
            "-c:v", "libx264", "-crf", str(c), "-preset", p,
            "-c:a", "aac", "-b:a", "128k",
            "-movflags", "+faststart",
            str(output_path),
        ])
        return TransformSpec("recompress", {"crf": c, "preset": p}, "recompression")

    def change_bitrate(
        self,
        input_path: Path,
        output_path: Path,
        video_bitrate: Optional[str] = None,
    ) -> TransformSpec:
        br = video_bitrate or self.rng.choice(["500k", "800k", "1200k", "2000k", "3500k"])
        self._run_ffmpeg([
            "-i", str(input_path),
            "-c:v", "libx264", "-b:v", br, "-maxrate", br, "-bufsize", "2M",
            "-c:a", "aac", "-b:a", "128k",
            "-movflags", "+faststart",
            str(output_path),
        ])
        return TransformSpec("change_bitrate", {"video_bitrate": br}, "recompression")

    def resize(
        self,
        input_path: Path,
        output_path: Path,
        scale: Optional[float] = None,
    ) -> TransformSpec:
        s = scale if scale is not None else self.rng.uniform(0.5, 1.25)
        # scale=iw*s:ih*s with even dimensions
        vf = f"scale=trunc(iw*{s}/2)*2:trunc(ih*{s}/2)*2"
        self._run_ffmpeg([
            "-i", str(input_path),
            "-vf", vf,
            "-c:v", "libx264", "-crf", "23", "-preset", "fast",
            "-c:a", "aac", "-b:a", "128k",
            "-movflags", "+faststart",
            str(output_path),
        ])
        return TransformSpec("resize", {"scale": round(s, 4)}, "resize")

    def change_fps(
        self,
        input_path: Path,
        output_path: Path,
        fps: Optional[float] = None,
    ) -> TransformSpec:
        f = fps if fps is not None else self.rng.choice([15, 20, 24, 25, 30])
        self._run_ffmpeg([
            "-i", str(input_path),
            "-r", str(f),
            "-c:v", "libx264", "-crf", "23", "-preset", "fast",
            "-c:a", "aac", "-b:a", "128k",
            "-movflags", "+faststart",
            str(output_path),
        ])
        return TransformSpec("change_fps", {"fps": f}, "temporal")

    def crop(
        self,
        input_path: Path,
        output_path: Path,
        ratio: Optional[float] = None,
    ) -> TransformSpec:
        r = ratio if ratio is not None else self.rng.uniform(0.85, 0.97)
        # center crop approximation
        vf = f"crop=iw*{r}:ih*{r}"
        self._run_ffmpeg([
            "-i", str(input_path),
            "-vf", vf,
            "-c:v", "libx264", "-crf", "23", "-preset", "fast",
            "-c:a", "aac", "-b:a", "128k",
            "-movflags", "+faststart",
            str(output_path),
        ])
        return TransformSpec("crop", {"ratio": round(r, 4)}, "crop")

    def pad_letterbox(
        self,
        input_path: Path,
        output_path: Path,
        target: str = "1920:1080",
    ) -> TransformSpec:
        # simple pad to target while keeping aspect
        vf = f"scale={target}:force_original_aspect_ratio=decrease,pad={target}:(ow-iw)/2:(oh-ih)/2"
        self._run_ffmpeg([
            "-i", str(input_path),
            "-vf", vf,
            "-c:v", "libx264", "-crf", "23", "-preset", "fast",
            "-c:a", "aac", "-b:a", "128k",
            "-movflags", "+faststart",
            str(output_path),
        ])
        return TransformSpec("pad_letterbox", {"target": target}, "letterbox")

    def trim(
        self,
        input_path: Path,
        output_path: Path,
        start_sec: Optional[float] = None,
        duration_sec: Optional[float] = None,
    ) -> TransformSpec:
        info = self.probe(input_path)
        duration = float(info.get("format", {}).get("duration", 10.0))
        start = start_sec if start_sec is not None else self.rng.uniform(0, max(0.1, duration * 0.15))
        dur = duration_sec if duration_sec is not None else self.rng.uniform(duration * 0.6, duration * 0.95)
        dur = min(dur, duration - start)
        self._run_ffmpeg([
            "-ss", f"{start:.3f}",
            "-i", str(input_path),
            "-t", f"{dur:.3f}",
            "-c:v", "libx264", "-crf", "23", "-preset", "fast",
            "-c:a", "aac", "-b:a", "128k",
            "-movflags", "+faststart",
            str(output_path),
        ])
        return TransformSpec(
            "trim",
            {"start_sec": round(start, 3), "duration_sec": round(dur, 3)},
            "temporal",
        )

    def change_container(
        self,
        input_path: Path,
        output_path: Path,
        container: Optional[str] = None,
    ) -> TransformSpec:
        # re-mux or light re-encode into different container
        c = container or self.rng.choice(["mp4", "mkv", "webm"])
        if not str(output_path).endswith(f".{c}"):
            output_path = output_path.with_suffix(f".{c}")
        if c == "webm":
            self._run_ffmpeg([
                "-i", str(input_path),
                "-c:v", "libvpx-vp9", "-crf", "30", "-b:v", "0",
                "-c:a", "libopus", "-b:a", "96k",
                str(output_path),
            ])
        else:
            self._run_ffmpeg([
                "-i", str(input_path),
                "-c:v", "libx264", "-crf", "23", "-preset", "fast",
                "-c:a", "aac", "-b:a", "128k",
                str(output_path),
            ])
        return TransformSpec("change_container", {"container": c}, "recompression")

    def brightness_contrast(
        self,
        input_path: Path,
        output_path: Path,
        brightness: Optional[float] = None,
        contrast: Optional[float] = None,
    ) -> TransformSpec:
        b = brightness if brightness is not None else self.rng.uniform(-0.15, 0.15)
        c = contrast if contrast is not None else self.rng.uniform(0.85, 1.15)
        # eq filter: brightness, contrast
        vf = f"eq=brightness={b}:contrast={c}"
        self._run_ffmpeg([
            "-i", str(input_path),
            "-vf", vf,
            "-c:v", "libx264", "-crf", "23", "-preset", "fast",
            "-c:a", "copy",
            "-movflags", "+faststart",
            str(output_path),
        ])
        return TransformSpec(
            "brightness_contrast",
            {"brightness": round(b, 4), "contrast": round(c, 4)},
            "color",
        )

    def remove_audio(self, input_path: Path, output_path: Path) -> TransformSpec:
        self._run_ffmpeg([
            "-i", str(input_path),
            "-c:v", "copy",
            "-an",
            str(output_path),
        ])
        return TransformSpec("remove_audio", {}, "audio")

    AVAILABLE = [
        "recompress",
        "change_bitrate",
        "resize",
        "change_fps",
        "crop",
        "pad_letterbox",
        "trim",
        "brightness_contrast",
        "remove_audio",
    ]

    def apply_random(
        self,
        input_path: Path,
        output_path: Path,
        max_transforms: int = 3,
    ) -> list[TransformSpec]:
        """Apply a chain of random transforms, writing intermediate files."""
        n = self.rng.randint(1, max_transforms)
        chosen = self.rng.sample(self.AVAILABLE, min(n, len(self.AVAILABLE)))
        specs: list[TransformSpec] = []

        with tempfile.TemporaryDirectory(prefix="vredteam_") as tmp:
            tmp_path = Path(tmp)
            current = input_path
            for i, name in enumerate(chosen):
                is_last = i == len(chosen) - 1
                next_path = output_path if is_last else tmp_path / f"step_{i}.mp4"
                method = getattr(self, name)
                spec = method(current, next_path)
                specs.append(spec)
                current = next_path
            # ensure final exists
            if current != output_path and current.exists():
                shutil.copy2(current, output_path)
        return specs
