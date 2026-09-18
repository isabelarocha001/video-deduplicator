"""
End-to-end media duplicate detection pipeline.

Flow:
  media file
    → extract fingerprints (exact, PDQ-like, SSCD-like, TMK-like, audio)
    → candidate retrieval against Supabase (or in-memory index)
    → score + policy
    → optional persist (disabled in dry_run)

This is the integration point between the red-team lab and the real store.
"""

from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Optional

from .adapter import DetectionPipeline, DetectionResult, DetectorScores, DEFAULT_THRESHOLDS


@dataclass
class FingerprintBundle:
    """All fingerprints extracted from a single media file."""
    path: str
    exact_sha256: str
    pdq_hashes: list[str] = field(default_factory=list)      # hex strings per keyframe
    sscd_embedding: Optional[list[float]] = None
    tmk_fingerprint: Optional[bytes] = None
    tmk_frame_count: int = 0
    audio_fingerprint: Optional[bytes] = None
    audio_duration_ms: Optional[int] = None
    metadata: dict[str, Any] = field(default_factory=dict)
    versions: dict[str, str] = field(default_factory=lambda: {
        "exact": "sha256-v1",
        "pdq": "phash-lab-v1",
        "sscd": "hist+phash-lab-v1",
        "tmk_pdqf": "seq-phash-lab-v1",
        "audio": "spectral-lab-v1",
        "policy": "combined-v1",
    })


@dataclass
class PipelineDecision:
    decision: str  # NEW | DUPLICATE | POSSIBLE_DUPLICATE
    final_score: float
    exact_match: bool
    scores: dict[str, Any]
    candidates: list[dict[str, Any]]
    fingerprints: FingerprintBundle
    policy_version: str
    detector_versions: dict[str, str]
    duration_ms: float
    persisted: bool = False
    dry_run: bool = True

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        # fingerprints path only
        return d


class MediaDuplicatePipeline:
    """
    Full pipeline used both by:
    - production-style processing (dry_run=False + Supabase store)
    - red-team lab (dry_run=True, optional store for candidate lookup)
    """

    def __init__(
        self,
        store: Any = None,          # SupabaseFingerprintStore | None
        thresholds: Optional[dict] = None,
        dry_run: bool = True,
        max_frames: int = 16,
    ):
        self.store = store
        self.dry_run = dry_run
        self.thresholds = {**DEFAULT_THRESHOLDS, **(thresholds or {})}
        # Reuse the lab detector for feature extraction / local scoring
        self._local = DetectionPipeline(
            thresholds=self.thresholds,
            max_frames=max_frames,
            dry_run=True,
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def process(
        self,
        path: Path,
        *,
        media_id: Optional[str] = None,
        persist: Optional[bool] = None,
    ) -> PipelineDecision:
        """
        Extract fingerprints, retrieve candidates, score, decide.

        persist defaults to (not self.dry_run) and requires a Supabase store.
        If media_id is omitted and persist=True, a vd_media row is created automatically.
        """
        t0 = time.perf_counter()
        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(path)

        do_persist = (not self.dry_run) if persist is None else persist
        if do_persist and not self.store:
            raise ValueError("persist=True requires a Supabase store")

        # 1) Extract
        fps = self.extract(path)

        # 2) Exact match short-circuit via store or local
        candidates: list[dict[str, Any]] = []
        exact_match = False
        if self.store:
            hits = self.store.find_by_exact_hash(fps.exact_sha256)
            if hits:
                exact_match = True
                candidates.extend([{**h, "match_type": "exact"} for h in hits])

        # 3) Local index of "original" for lab-style comparison when no store hits
        #    (red-team already indexes original separately; here we support standalone use)
        scores = self._score_against_candidates(fps, candidates)

        # 4) Policy
        decision, final_score = self._policy(exact_match, scores, candidates)

        # 5) Optional persist
        persisted = False
        if do_persist and self.store and not self.dry_run:
            # Ensure media row exists
            if not media_id:
                media_type = "video"
                if path.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp", ".bmp"}:
                    media_type = "image"
                elif path.suffix.lower() in {".mp3", ".wav", ".aac", ".flac"}:
                    media_type = "audio"
                created = self.store.create_media({
                    "storage_path": str(path),
                    "original_name": path.name,
                    "media_type": media_type,
                    "size_bytes": path.stat().st_size,
                    "status": "processing",
                    "metadata": fps.metadata,
                })
                media_id = created["id"] if created and "id" in created else None
            if not media_id:
                raise RuntimeError("Could not resolve media_id for persist")
            self._persist_fingerprints(fps, media_id)
            self.store.insert_duplicate_check({
                "media_id": media_id,
                "candidate_media_id": candidates[0]["media_id"] if candidates else None,
                "pdq_score": scores.get("pdq", {}).get("score"),
                "sscd_score": scores.get("sscd", {}).get("score"),
                "tmk_score": scores.get("tmk_pdqf", {}).get("score"),
                "audio_score": scores.get("audio", {}).get("score"),
                "exact_match": exact_match,
                "final_score": final_score,
                "decision": decision,
                "policy_version": fps.versions.get("policy", "combined-v1"),
                "detector_versions": fps.versions,
                "details": {"candidates": candidates[:5], "path": str(path)},
            })
            status = "duplicate" if decision == "DUPLICATE" else "ready"
            self.store.update_media_status(media_id, status)
            persisted = True

        elapsed = (time.perf_counter() - t0) * 1000
        return PipelineDecision(
            decision=decision,
            final_score=final_score,
            exact_match=exact_match,
            scores=scores,
            candidates=candidates,
            fingerprints=fps,
            policy_version=fps.versions.get("policy", "combined-v1"),
            detector_versions=fps.versions,
            duration_ms=round(elapsed, 1),
            persisted=persisted,
            dry_run=self.dry_run,
        )

    def extract(self, path: Path) -> FingerprintBundle:
        """Compute all fingerprints for a media file (no DB writes)."""
        path = Path(path)
        sha = self._sha256(path)

        # Reuse DetectionPipeline frame / hash machinery
        frames = self._local._extract_frames(path, self._local.max_frames)
        phashes = []
        try:
            import imagehash
            phashes = [str(imagehash.phash(f)) for f in frames]
        except Exception:
            phashes = []

        hist = self._local._color_histogram(frames)
        # SSCD-like: fixed-size vector from histogram (pad/truncate to 512)
        emb = self._hist_to_embedding(hist, dim=512)

        audio_fp = self._local._audio_fingerprint(path)
        audio_bytes = None
        audio_ms = None
        if audio_fp is not None:
            import numpy as np
            audio_bytes = np.asarray(audio_fp, dtype=np.float32).tobytes()
            audio_ms = int(self._local._get_duration(path) * 1000)

        # TMK-like: concatenate phash digests
        tmk = None
        if phashes:
            tmk = b"".join(bytes.fromhex(h) if all(c in "0123456789abcdef" for c in h) else h.encode() for h in phashes)

        meta = {
            "num_frames": len(frames),
            "path": str(path),
            "suffix": path.suffix.lower(),
        }
        try:
            from tools.duplicate_redteam.runner import media_info
            meta.update(media_info(path) or {})
        except Exception:
            pass

        return FingerprintBundle(
            path=str(path),
            exact_sha256=sha,
            pdq_hashes=phashes,
            sscd_embedding=emb,
            tmk_fingerprint=tmk,
            tmk_frame_count=len(phashes),
            audio_fingerprint=audio_bytes,
            audio_duration_ms=audio_ms,
            metadata=meta,
        )

    def compare_to_indexed(
        self,
        variant_path: Path,
        original_path: Path,
    ) -> DetectionResult:
        """
        Lab helper: index original in-memory, check variant.
        Does not touch Supabase writes.
        """
        self._local.index_original(original_path)
        return self._local.check(variant_path)

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

    @staticmethod
    def _hist_to_embedding(hist, dim: int = 512) -> list[float]:
        import numpy as np
        v = np.asarray(hist, dtype=np.float64).ravel()
        if len(v) == 0:
            return [0.0] * dim
        if len(v) < dim:
            v = np.pad(v, (0, dim - len(v)))
        else:
            v = v[:dim]
        n = np.linalg.norm(v)
        if n > 0:
            v = v / n
        return v.astype(float).tolist()

    def _score_against_candidates(
        self,
        fps: FingerprintBundle,
        candidates: list[dict],
    ) -> dict[str, Any]:
        """
        Build score dict compatible with DetectionResult reporting.
        When no DB candidates, scores remain neutral (lab uses compare_to_indexed).
        """
        scores: dict[str, Any] = {
            "exact_hash": {
                "match": any(c.get("match_type") == "exact" for c in candidates),
                "score": 1.0 if any(c.get("match_type") == "exact" for c in candidates) else 0.0,
                "threshold": 0.0,
            },
            "pdq": {"match": False, "score": None, "threshold": self.thresholds["pdq"]},
            "sscd": {"match": False, "score": None, "threshold": self.thresholds["sscd"]},
            "tmk_pdqf": {"match": False, "score": None, "threshold": self.thresholds["tmk_pdqf"]},
            "audio": {"match": False, "score": None, "threshold": self.thresholds["audio"]},
        }
        return scores

    def _policy(
        self,
        exact_match: bool,
        scores: dict[str, Any],
        candidates: list[dict],
    ) -> tuple[str, float]:
        if exact_match:
            return "DUPLICATE", 1.0

        soft = sum(1 for k in ("pdq", "sscd", "tmk_pdqf", "audio") if scores.get(k, {}).get("match"))
        if soft >= 2:
            return "DUPLICATE", 0.85
        if soft == 1:
            return "POSSIBLE_DUPLICATE", 0.55
        if candidates:
            return "POSSIBLE_DUPLICATE", 0.4
        return "NEW", 0.0

    def _persist_fingerprints(
        self,
        fps: FingerprintBundle,
        media_id: str,
    ) -> None:
        assert self.store is not None
        base = {
            "media_id": media_id,
            "metadata": fps.metadata,
        }
        # exact
        self.store.upsert_fingerprint({
            **base,
            "algorithm": "exact",
            "version": fps.versions["exact"],
            "exact_sha256": fps.exact_sha256,
        })
        # pdq (store first keyframe hash as representative; full set in metadata)
        if fps.pdq_hashes:
            import binascii
            try:
                raw = binascii.unhexlify(fps.pdq_hashes[0])
            except Exception:
                raw = fps.pdq_hashes[0].encode()
            self.store.upsert_fingerprint({
                **base,
                "algorithm": "pdq",
                "version": fps.versions["pdq"],
                "pdq_hash": raw,  # supabase-py may need base64; adjust at integration time
                "metadata": {**fps.metadata, "all_pdq": fps.pdq_hashes},
            })
        # sscd
        if fps.sscd_embedding:
            self.store.upsert_fingerprint({
                **base,
                "algorithm": "sscd",
                "version": fps.versions["sscd"],
                "sscd_embedding": fps.sscd_embedding,
            })
        # tmk
        if fps.tmk_fingerprint:
            self.store.upsert_fingerprint({
                **base,
                "algorithm": "tmk_pdqf",
                "version": fps.versions["tmk_pdqf"],
                "tmk_fingerprint": fps.tmk_fingerprint,
                "tmk_frame_count": fps.tmk_frame_count,
            })
        # audio
        if fps.audio_fingerprint:
            self.store.upsert_fingerprint({
                **base,
                "algorithm": "audio",
                "version": fps.versions["audio"],
                "audio_fingerprint": fps.audio_fingerprint,
                "audio_duration_ms": fps.audio_duration_ms,
            })
