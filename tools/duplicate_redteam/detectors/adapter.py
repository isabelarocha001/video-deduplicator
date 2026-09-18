"""
Detection pipeline adapter.

Implements simplified but structured versions of:
- Exact cryptographic hash
- PDQ-like perceptual hash (via imagehash.phash on keyframes)
- SSCD-like visual similarity (multi-hash + histogram distance)
- TMK/PDQF-like temporal fingerprint (sequence of frame hashes)
- Audio fingerprint (simple spectral signature)

These are laboratory approximations intended for QA of transform robustness.
They are NOT drop-in replacements for production Meta PDQ / SSCD / TMK.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Optional

import numpy as np
from PIL import Image

try:
    import imagehash
except ImportError as e:
    raise ImportError(
        "imagehash is required. Install with: pip install imagehash pillow numpy"
    ) from e


# ---------------------------------------------------------------------------
# Thresholds (tunable laboratory defaults)
# ---------------------------------------------------------------------------

DEFAULT_THRESHOLDS = {
    "exact_hash": 0.0,          # exact match only
    "pdq": 18,                  # Hamming distance on 64-bit phash (lower = more similar)
    "sscd": 0.55,               # cosine / similarity score (higher = more similar)
    "tmk_pdqf": 0.45,           # temporal sequence similarity
    "audio": 0.50,              # audio fingerprint similarity
}


@dataclass
class DetectorScores:
    exact_hash: dict[str, Any] = field(default_factory=dict)
    pdq: dict[str, Any] = field(default_factory=dict)
    sscd: dict[str, Any] = field(default_factory=dict)
    tmk_pdqf: dict[str, Any] = field(default_factory=dict)
    audio: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class DetectionResult:
    is_duplicate: bool
    policy: str                 # "DUPLICATE" | "NEW"
    scores: DetectorScores
    expected: str = "DUPLICATE"
    result: str = "PASS"        # "PASS" | "FALSE NEGATIVE" | "FALSE POSITIVE"
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "is_duplicate": self.is_duplicate,
            "policy": self.policy,
            "expected": self.expected,
            "result": self.result,
            "scores": self.scores.to_dict(),
            "details": self.details,
        }


class DetectionPipeline:
    """
    Laboratory detection pipeline.

    Call `index_original(path)` once, then `check(variant_path)` for each variant.
    Models / fingerprints of the original are kept in memory for the batch.
    """

    def __init__(
        self,
        thresholds: Optional[dict[str, float]] = None,
        max_frames: int = 16,
        dry_run: bool = True,
    ):
        self.thresholds = {**DEFAULT_THRESHOLDS, **(thresholds or {})}
        self.max_frames = max_frames
        self.dry_run = dry_run  # never writes to any production store

        self._original_path: Optional[Path] = None
        self._original_sha256: Optional[str] = None
        self._original_frames: list[Image.Image] = []
        self._original_phashes: list[Any] = []
        self._original_hist: Optional[np.ndarray] = None
        self._original_audio_fp: Optional[np.ndarray] = None
        self._ffmpeg = shutil.which("ffmpeg")
        self._ffprobe = shutil.which("ffprobe")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def index_original(self, path: Path) -> dict[str, Any]:
        """Compute and store fingerprints of the known original media."""
        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(path)

        self._original_path = path
        self._original_sha256 = self._sha256(path)
        self._original_frames = self._extract_frames(path, self.max_frames)
        self._original_phashes = [imagehash.phash(f) for f in self._original_frames]
        self._original_hist = self._color_histogram(self._original_frames)
        self._original_audio_fp = self._audio_fingerprint(path)

        return {
            "path": str(path),
            "sha256": self._original_sha256,
            "num_frames": len(self._original_frames),
            "has_audio_fp": self._original_audio_fp is not None,
        }

    def check(self, variant_path: Path) -> DetectionResult:
        """Run full pipeline against a variant. Original must be indexed first."""
        if self._original_path is None:
            raise RuntimeError("Call index_original() first")

        variant_path = Path(variant_path)
        scores = DetectorScores()

        # 1. Exact hash
        v_sha = self._sha256(variant_path)
        exact_match = v_sha == self._original_sha256
        scores.exact_hash = {
            "match": exact_match,
            "score": 1.0 if exact_match else 0.0,
            "threshold": self.thresholds["exact_hash"],
            "original_sha256": self._original_sha256,
            "variant_sha256": v_sha,
        }

        # 2. PDQ-like (perceptual hash on keyframes)
        v_frames = self._extract_frames(variant_path, self.max_frames)
        v_phashes = [imagehash.phash(f) for f in v_frames] if v_frames else []
        pdq_dist, pdq_match = self._pdq_score(self._original_phashes, v_phashes)
        scores.pdq = {
            "match": pdq_match,
            "score": pdq_dist,          # Hamming distance (lower better)
            "threshold": self.thresholds["pdq"],
            "num_frames_original": len(self._original_phashes),
            "num_frames_variant": len(v_phashes),
        }

        # 3. SSCD-like (visual similarity)
        v_hist = self._color_histogram(v_frames)
        sscd_sim, sscd_match = self._sscd_score(
            self._original_phashes, v_phashes,
            self._original_hist, v_hist,
        )
        scores.sscd = {
            "match": sscd_match,
            "score": sscd_sim,          # similarity 0-1 (higher better)
            "threshold": self.thresholds["sscd"],
        }

        # 4. TMK/PDQF-like (temporal sequence)
        tmk_sim, tmk_match = self._tmk_score(self._original_phashes, v_phashes)
        scores.tmk_pdqf = {
            "match": tmk_match,
            "score": tmk_sim,
            "threshold": self.thresholds["tmk_pdqf"],
        }

        # 5. Audio
        v_audio = self._audio_fingerprint(variant_path)
        audio_sim, audio_match = self._audio_score(self._original_audio_fp, v_audio)
        scores.audio = {
            "match": audio_match,
            "score": audio_sim,
            "threshold": self.thresholds["audio"],
            "original_has_audio": self._original_audio_fp is not None,
            "variant_has_audio": v_audio is not None,
        }

        # Policy (laboratory):
        # - exact match always wins
        # - any single strong visual signal (PDQ / SSCD / TMK) → DUPLICATE
        # - two or more soft signals → DUPLICATE
        # - strong audio + at least weak visual support → DUPLICATE
        soft_hits = sum([pdq_match, sscd_match, tmk_match, audio_match])
        is_dup = (
            exact_match
            or pdq_match
            or sscd_match
            or tmk_match
            or soft_hits >= 2
            or (audio_match and (scores.pdq.get("score", 99) < 28 or scores.sscd.get("score", 0) > 0.4))
        )

        policy = "DUPLICATE" if is_dup else "NEW"
        expected = "DUPLICATE"
        result = "PASS" if policy == expected else "FALSE NEGATIVE"

        return DetectionResult(
            is_duplicate=is_dup,
            policy=policy,
            scores=scores,
            expected=expected,
            result=result,
            details={
                "variant_path": str(variant_path),
                "thresholds": self.thresholds,
            },
        )

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    @staticmethod
    def _sha256(path: Path) -> str:
        h = hashlib.sha256()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                h.update(chunk)
        return h.hexdigest()

    def _extract_frames(self, path: Path, max_frames: int) -> list[Image.Image]:
        """Extract up to max_frames uniformly spaced frames via FFmpeg."""
        if not self._ffmpeg:
            return []
        frames: list[Image.Image] = []
        with tempfile.TemporaryDirectory(prefix="frames_") as tmp:
            tmp_path = Path(tmp)
            # Determine duration
            duration = self._get_duration(path)
            if duration <= 0:
                # treat as image
                try:
                    img = Image.open(path).convert("RGB")
                    return [img]
                except Exception:
                    return []

            # fps such that we get ~max_frames
            fps = max(0.1, max_frames / max(duration, 0.1))
            pattern = str(tmp_path / "frame_%04d.jpg")
            cmd = [
                self._ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
                "-i", str(path),
                "-vf", f"fps={fps:.4f}",
                "-frames:v", str(max_frames),
                "-q:v", "3",
                pattern,
            ]
            subprocess.run(cmd, capture_output=True, timeout=120)
            for p in sorted(tmp_path.glob("frame_*.jpg")):
                try:
                    frames.append(Image.open(p).convert("RGB"))
                except Exception:
                    continue
        return frames

    def _get_duration(self, path: Path) -> float:
        if not self._ffprobe:
            return 0.0
        cmd = [
            self._ffprobe, "-v", "quiet", "-print_format", "json",
            "-show_format", str(path),
        ]
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            data = json.loads(r.stdout or "{}")
            return float(data.get("format", {}).get("duration", 0))
        except Exception:
            return 0.0

    @staticmethod
    def _color_histogram(frames: list[Image.Image], bins: int = 32) -> np.ndarray:
        if not frames:
            return np.zeros(bins * 3, dtype=np.float64)
        hists = []
        for img in frames:
            arr = np.asarray(img.resize((64, 64)))
            h = []
            for c in range(3):
                hist, _ = np.histogram(arr[:, :, c], bins=bins, range=(0, 256), density=True)
                h.append(hist)
            hists.append(np.concatenate(h))
        return np.mean(hists, axis=0)

    def _pdq_score(
        self, orig: list, variant: list
    ) -> tuple[float, bool]:
        if not orig or not variant:
            return 64.0, False
        # minimum average Hamming distance across best matching pairs
        dists = []
        for oh in orig:
            best = min((oh - vh) for vh in variant)
            dists.append(best)
        avg = float(np.mean(dists)) if dists else 64.0
        match = avg <= self.thresholds["pdq"]
        return avg, match

    def _sscd_score(
        self,
        orig_hashes: list,
        var_hashes: list,
        orig_hist: Optional[np.ndarray],
        var_hist: Optional[np.ndarray],
    ) -> tuple[float, bool]:
        # Combine hash agreement + histogram cosine
        if not orig_hashes or not var_hashes:
            hash_sim = 0.0
        else:
            # fraction of original hashes that find a close match
            close = 0
            for oh in orig_hashes:
                if any((oh - vh) <= self.thresholds["pdq"] for vh in var_hashes):
                    close += 1
            hash_sim = close / len(orig_hashes)

        hist_sim = 0.0
        if orig_hist is not None and var_hist is not None:
            a = orig_hist.ravel().astype(np.float64)
            b = var_hist.ravel().astype(np.float64)
            na, nb = np.linalg.norm(a), np.linalg.norm(b)
            if na > 0 and nb > 0:
                hist_sim = float(np.dot(a, b) / (na * nb))

        # weighted combination
        sim = 0.55 * hash_sim + 0.45 * hist_sim
        match = sim >= self.thresholds["sscd"]
        return sim, match

    def _tmk_score(self, orig: list, variant: list) -> tuple[float, bool]:
        """Simple temporal matching: ordered sequence similarity."""
        if not orig or not variant:
            return 0.0, False
        # Normalize lengths by sampling
        n = min(len(orig), len(variant), 12)
        o_idx = np.linspace(0, len(orig) - 1, n).astype(int)
        v_idx = np.linspace(0, len(variant) - 1, n).astype(int)
        matches = 0
        for i, j in zip(o_idx, v_idx):
            if (orig[i] - variant[j]) <= self.thresholds["pdq"] + 4:
                matches += 1
        sim = matches / n
        match = sim >= self.thresholds["tmk_pdqf"]
        return sim, match

    def _audio_fingerprint(self, path: Path) -> Optional[np.ndarray]:
        """Extract a simple spectral fingerprint via FFmpeg + numpy."""
        if not self._ffmpeg:
            return None
        with tempfile.TemporaryDirectory(prefix="audio_") as tmp:
            wav = Path(tmp) / "a.wav"
            # mono 8kHz for speed
            cmd = [
                self._ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
                "-i", str(path),
                "-ac", "1", "-ar", "8000",
                "-t", "30",          # first 30s
                str(wav),
            ]
            r = subprocess.run(cmd, capture_output=True, timeout=60)
            if r.returncode != 0 or not wav.exists():
                return None
            try:
                # raw PCM read
                import wave
                with wave.open(str(wav), "rb") as w:
                    n = w.getnframes()
                    raw = w.readframes(n)
                    audio = np.frombuffer(raw, dtype=np.int16).astype(np.float32)
                if len(audio) < 1024:
                    return None
                # simple log-energy in bands
                audio = audio / (np.max(np.abs(audio)) + 1e-8)
                # FFT magnitude over windows
                win = 1024
                hop = 512
                feats = []
                for start in range(0, len(audio) - win, hop):
                    chunk = audio[start:start + win]
                    spec = np.abs(np.fft.rfft(chunk * np.hanning(win)))
                    # band energies
                    bands = np.array_split(spec, 16)
                    feats.append([np.log1p(np.mean(b)) for b in bands])
                if not feats:
                    return None
                return np.mean(feats, axis=0)
            except Exception:
                return None

    def _audio_score(
        self,
        orig: Optional[np.ndarray],
        variant: Optional[np.ndarray],
    ) -> tuple[float, bool]:
        if orig is None or variant is None:
            # if both missing audio → neutral; if only one → no match
            if orig is None and variant is None:
                return 0.5, False
            return 0.0, False
        a = orig.ravel().astype(np.float64)
        b = variant.ravel().astype(np.float64)
        # pad/truncate
        n = min(len(a), len(b))
        a, b = a[:n], b[:n]
        na, nb = np.linalg.norm(a), np.linalg.norm(b)
        if na < 1e-9 or nb < 1e-9:
            return 0.0, False
        sim = float(np.dot(a, b) / (na * nb))
        match = sim >= self.thresholds["audio"]
        return sim, match
