"""Audio transformation families using FFmpeg."""

from __future__ import annotations

import random
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional


@dataclass
class TransformSpec:
    name: str
    params: dict[str, Any] = field(default_factory=dict)
    family: str = "audio"


class AudioTransforms:
    """Controlled transforms for audio streams (and standalone audio)."""

    def __init__(self, seed: Optional[int] = None):
        self.rng = random.Random(seed)
        self.ffmpeg = shutil.which("ffmpeg")
        if not self.ffmpeg:
            raise RuntimeError("ffmpeg not found on PATH")

    def _run(self, args: list[str], timeout: int = 120) -> None:
        cmd = [self.ffmpeg, "-y", "-hide_banner", "-loglevel", "error", *args]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        if result.returncode != 0:
            raise RuntimeError(f"ffmpeg audio failed: {result.stderr[-1000:]}")

    def reencode(
        self,
        input_path: Path,
        output_path: Path,
        bitrate: Optional[str] = None,
        sample_rate: Optional[int] = None,
    ) -> TransformSpec:
        br = bitrate or self.rng.choice(["64k", "96k", "128k", "192k"])
        sr = sample_rate or self.rng.choice([22050, 44100, 48000])
        self._run([
            "-i", str(input_path),
            "-c:v", "copy",
            "-c:a", "aac", "-b:a", br, "-ar", str(sr),
            str(output_path),
        ])
        return TransformSpec("reencode", {"bitrate": br, "sample_rate": sr}, "audio")

    def change_gain(
        self,
        input_path: Path,
        output_path: Path,
        db: Optional[float] = None,
    ) -> TransformSpec:
        g = db if db is not None else self.rng.uniform(-6.0, 6.0)
        self._run([
            "-i", str(input_path),
            "-c:v", "copy",
            "-af", f"volume={g}dB",
            "-c:a", "aac", "-b:a", "128k",
            str(output_path),
        ])
        return TransformSpec("change_gain", {"db": round(g, 2)}, "audio")

    def lowpass(
        self,
        input_path: Path,
        output_path: Path,
        freq: Optional[int] = None,
    ) -> TransformSpec:
        f = freq or self.rng.choice([8000, 10000, 12000, 14000])
        self._run([
            "-i", str(input_path),
            "-c:v", "copy",
            "-af", f"lowpass=f={f}",
            "-c:a", "aac", "-b:a", "128k",
            str(output_path),
        ])
        return TransformSpec("lowpass", {"freq": f}, "audio")

    def highpass(
        self,
        input_path: Path,
        output_path: Path,
        freq: Optional[int] = None,
    ) -> TransformSpec:
        f = freq or self.rng.choice([80, 120, 200])
        self._run([
            "-i", str(input_path),
            "-c:v", "copy",
            "-af", f"highpass=f={f}",
            "-c:a", "aac", "-b:a", "128k",
            str(output_path),
        ])
        return TransformSpec("highpass", {"freq": f}, "audio")

    def replace_with_silence(
        self,
        input_path: Path,
        output_path: Path,
    ) -> TransformSpec:
        self._run([
            "-i", str(input_path),
            "-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=44100",
            "-c:v", "copy",
            "-c:a", "aac", "-b:a", "64k",
            "-shortest",
            "-map", "0:v:0", "-map", "1:a:0",
            str(output_path),
        ])
        return TransformSpec("replace_with_silence", {}, "audio")

    AVAILABLE = ["reencode", "change_gain", "lowpass", "highpass"]
