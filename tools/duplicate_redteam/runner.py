"""Core runner for the adversarial duplicate testing laboratory."""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any, Optional

from .detectors.adapter import DetectionPipeline
from .reports.reporter import Reporter
from .transforms.image import ImageTransforms
from .transforms.video import VideoTransforms


def get_git_commit() -> Optional[str]:
    try:
        r = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True, timeout=5,
        )
        if r.returncode == 0:
            return r.stdout.strip()
    except Exception:
        pass
    return None


def media_info(path: Path) -> dict[str, Any]:
    ffprobe = shutil.which("ffprobe")
    if not ffprobe:
        return {}
    cmd = [
        ffprobe, "-v", "quiet", "-print_format", "json",
        "-show_format", "-show_streams", str(path),
    ]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        data = json.loads(r.stdout or "{}")
        info: dict[str, Any] = {}
        fmt = data.get("format", {})
        info["duration"] = float(fmt.get("duration", 0) or 0)
        info["size_bytes"] = int(fmt.get("size", 0) or 0)
        info["format_name"] = fmt.get("format_name")
        for s in data.get("streams", []):
            if s.get("codec_type") == "video" and "width" not in info:
                info["width"] = s.get("width")
                info["height"] = s.get("height")
                info["video_codec"] = s.get("codec_name")
                info["fps"] = s.get("r_frame_rate")
            if s.get("codec_type") == "audio" and "audio_codec" not in info:
                info["audio_codec"] = s.get("codec_name")
                info["sample_rate"] = s.get("sample_rate")
                info["channels"] = s.get("channels")
        return info
    except Exception:
        return {}


def is_image(path: Path) -> bool:
    return path.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tiff", ".gif"}


def is_video(path: Path) -> bool:
    return path.suffix.lower() in {
        ".mp4", ".mkv", ".avi", ".mov", ".webm", ".flv", ".wmv", ".m4v", ".mpeg", ".mpg"
    }


class RedTeamRunner:
    def __init__(
        self,
        input_path: Path,
        iterations: int = 50,
        seed: Optional[int] = None,
        workers: int = 1,
        results_dir: Optional[Path] = None,
        verbose: bool = True,
        max_transforms: int = 3,
    ):
        self.input_path = Path(input_path)
        self.iterations = iterations
        self.seed = seed if seed is not None else int(time.time()) % 2**31
        self.workers = max(1, workers)
        self.verbose = verbose
        self.max_transforms = max_transforms

        self.results_dir = Path(results_dir) if results_dir else Path("tools/duplicate_redteam/results")
        self.results_dir.mkdir(parents=True, exist_ok=True)

        self.original_id = self.input_path.stem
        self.pipeline = DetectionPipeline(dry_run=True)
        self.reporter = Reporter(self.results_dir, self.original_id)
        self.commit = get_git_commit()

    def run(self) -> dict[str, Any]:
        if not self.input_path.exists():
            raise FileNotFoundError(self.input_path)

        print(f"[redteam] indexing original: {self.input_path}")
        print(f"[redteam] seed={self.seed}  iterations={self.iterations}")
        idx = self.pipeline.index_original(self.input_path)
        print(f"[redteam] indexed: {idx}")

        original_sha = idx["sha256"]
        orig_info = media_info(self.input_path)

        if is_image(self.input_path):
            self._run_image_batch(original_sha, orig_info)
        elif is_video(self.input_path):
            self._run_video_batch(original_sha, orig_info)
        else:
            # try as video first
            self._run_video_batch(original_sha, orig_info)

        self.reporter.print_summary()
        report_path = self.reporter.save_full_report()
        print(f"[redteam] full report saved: {report_path}")
        return self.reporter.summary()

    def _run_image_batch(self, original_sha: str, orig_info: dict) -> None:
        img_tx = ImageTransforms(seed=self.seed)
        original_img = img_tx.load(self.input_path)

        with tempfile.TemporaryDirectory(prefix="img_redteam_") as tmp:
            tmp_path = Path(tmp)
            for i in range(1, self.iterations + 1):
                # deterministic sub-seed per variant
                variant_seed = self.seed + i * 9973
                img_tx.rng.seed(variant_seed)

                variant_img, specs = img_tx.apply_random(
                    original_img.copy(), max_transforms=self.max_transforms
                )
                out_path = tmp_path / f"variant_{i:04d}.jpg"
                img_tx.save(variant_img, out_path, quality=85)

                detection = self.pipeline.check(out_path)
                v_sha = hashlib.sha256(out_path.read_bytes()).hexdigest()

                self.reporter.record_variant(
                    variant_id=i,
                    original_path=self.input_path,
                    variant_path=out_path,
                    transforms=specs,
                    detection=detection,
                    original_sha256=original_sha,
                    variant_sha256=v_sha,
                    media_info=media_info(out_path) or orig_info,
                    seed=variant_seed,
                    commit=self.commit,
                )
                if self.verbose and (i % 10 == 0 or detection.result == "FALSE NEGATIVE"):
                    self.reporter.print_variant(self.reporter.records[-1])

    def _run_video_batch(self, original_sha: str, orig_info: dict) -> None:
        vid_tx = VideoTransforms(seed=self.seed)

        with tempfile.TemporaryDirectory(prefix="vid_redteam_") as tmp:
            tmp_path = Path(tmp)
            for i in range(1, self.iterations + 1):
                variant_seed = self.seed + i * 9973
                vid_tx.rng.seed(variant_seed)

                out_path = tmp_path / f"variant_{i:04d}.mp4"
                try:
                    specs = vid_tx.apply_random(
                        self.input_path, out_path, max_transforms=self.max_transforms
                    )
                except Exception as exc:
                    if self.verbose:
                        print(f"[redteam] variant {i} failed: {exc}")
                    continue

                if not out_path.exists():
                    continue

                detection = self.pipeline.check(out_path)
                v_sha = hashlib.sha256(out_path.read_bytes()).hexdigest()

                self.reporter.record_variant(
                    variant_id=i,
                    original_path=self.input_path,
                    variant_path=out_path,
                    transforms=specs,
                    detection=detection,
                    original_sha256=original_sha,
                    variant_sha256=v_sha,
                    media_info=media_info(out_path),
                    seed=variant_seed,
                    commit=self.commit,
                )
                if self.verbose and (i % 5 == 0 or detection.result == "FALSE NEGATIVE"):
                    self.reporter.print_variant(self.reporter.records[-1])

    def replay_case(self, case_id: int, transforms_params: list[dict]) -> None:
        """Reproduce a specific variant by ID and known transform list."""
        raise NotImplementedError("Use --seed + recorded transform params from JSON")


def run_regression(results_dir: Path) -> dict[str, Any]:
    """
    Re-run all saved false-negative fixtures and report regressions.
    """
    fn_root = Path(results_dir) / "false_negatives"
    if not fn_root.exists():
        print("No false_negatives directory found.")
        return {"total": 0}

    total = 0
    detected = 0
    still_fn = 0
    pipeline = DetectionPipeline(dry_run=True)

    for original_dir in sorted(fn_root.iterdir()):
        if not original_dir.is_dir():
            continue
        # find original path from any json
        jsons = list(original_dir.glob("variant_*.json"))
        if not jsons:
            continue
        with open(jsons[0], encoding="utf-8") as f:
            sample = json.load(f)
        original = Path(sample["original"])
        if not original.exists():
            print(f"[regression] original missing: {original}")
            continue
        pipeline.index_original(original)

        for jpath in jsons:
            with open(jpath, encoding="utf-8") as f:
                rec = json.load(f)
            vpath = original_dir / Path(rec["variant_path"]).name
            if not vpath.exists():
                # try suffix from record
                candidates = list(original_dir.glob(jpath.stem + ".*"))
                candidates = [c for c in candidates if c.suffix != ".json"]
                if not candidates:
                    continue
                vpath = candidates[0]

            total += 1
            det = pipeline.check(vpath)
            if det.policy == "DUPLICATE":
                detected += 1
            else:
                still_fn += 1
                print(f"  REGRESSION still FN: {vpath}")

    print("\nRegression Suite")
    print(f"Total:               {total}")
    print(f"Detected correctly:  {detected}")
    print(f"False negatives:     {still_fn}")
    print(f"Regressions:         {still_fn}")
    return {
        "total": total,
        "detected_correctly": detected,
        "false_negatives": still_fn,
        "regressions": still_fn,
    }
